"""Retain historical maintenance evidence without creating a new natural run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo
import subprocess
import fcntl

NAME = "after-market-history.json"
_LIMIT = 2 * 1024 * 1024


def _bytes(path: Path) -> bytes:
    if path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > _LIMIT):
            raise ValueError("AFTER_MARKET_HISTORY_INVALID")
        data = os.read(fd, _LIMIT + 1)
        if len(data) > _LIMIT:
            raise ValueError("AFTER_MARKET_HISTORY_INVALID")
        return data
    finally:
        os.close(fd)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_history(content: bytes, *, commit: str, products: tuple[str, ...], now: datetime) -> dict:
    from app.market_data.after_market import public_after_market_status

    public = public_after_market_status(json.loads(content))
    last = public.get("last_run")
    day = public.get("last_successful_trading_day")
    if (not re.fullmatch(r"[0-9a-f]{40}", commit) or not public
            or public.get("current_run") is not None or not isinstance(last, dict)
            or last.get("status") not in {"passed", "skipped", "failed", "interrupted"}
            or (day is None and last.get("status") not in {"failed", "interrupted"}
                and public.get("last_failure") is None)
            or (day is not None and day > last["trading_day"])
            or tuple(last["products"]) != products or not products
            or now.tzinfo is None):
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    started = datetime.fromisoformat(last["started_at"])
    finished = datetime.fromisoformat(last["finished_at"])
    if not started.tzinfo or not finished.tzinfo or not started <= finished <= now:
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    failure = public.get("last_failure")
    local_day = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    if (date.fromisoformat(last["trading_day"]) > started.astimezone(ZoneInfo("Asia/Shanghai")).date()
            or date.fromisoformat(last["trading_day"]) > local_day
            or (day is not None and date.fromisoformat(day) > local_day)
            or (failure is not None and date.fromisoformat(failure["trading_day"]) > local_day)):
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    return {"schema_version": 1, "source_commit": commit,
            "source_status_sha256": hashlib.sha256(content).hexdigest(),
            "retained_at": now.isoformat(), "status": public, "status_sha256": _digest(public)}


def read_history(path: Path, *, products: tuple[str, ...], now: datetime) -> dict | None:
    if not os.path.lexists(path):
        return None
    value = json.loads(_bytes(path))
    if (not isinstance(value, dict) or set(value) != {"schema_version", "source_commit",
            "source_status_sha256", "retained_at", "status", "status_sha256"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["source_status_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["source_status_sha256"])
            or _digest(value["status"]) != value["status_sha256"]):
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    retained_at = datetime.fromisoformat(value["retained_at"])
    if not retained_at.tzinfo or retained_at > now:
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    checked = make_history(json.dumps(value["status"]).encode(),
                           commit=value["source_commit"], products=products, now=retained_at)
    if checked["status"] != value["status"]:
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    return value


def publish_history(path: Path, value: dict) -> str:
    """Create once using exclusive publication; never overwrite an existing proof."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    content = (json.dumps(value, indent=2) + "\n").encode()
    # One file is the entire proof; no partially committed sidecar pair.
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=".history-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _bytes(path) != content:
                raise ValueError("AFTER_MARKET_HISTORY_CONFLICT") from None
            return "already_retained"
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return "retained"
    finally:
        os.unlink(temporary)


def retain_from_supervised(target_root: Path, *, apply: bool = False) -> str:
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.runtime_status_authority import resolve_market_runtime_status_authority
    from app.market_data.after_market import public_after_market_status

    authority = resolve_market_runtime_status_authority(candidate_root=target_root,
        expected_stopped_status_sha256=os.environ.get("GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256"))
    products = load_operational_products()
    now = datetime.now(UTC)
    if authority.mode == "first_install":
        return "no_previous_success"
    source_root = authority.path.parent.parent
    authority.recheck()
    history = read_history(authority.path.with_name(NAME), products=products, now=now)
    if target_root.resolve(strict=True) == source_root.resolve(strict=True):
        return "same_runtime"
    content = _bytes(authority.path) if os.path.lexists(authority.path) else None
    public = public_after_market_status(json.loads(content)) if content is not None else {}
    if content is not None and (not public or public.get("current_run") is not None):
        raise ValueError("AFTER_MARKET_HISTORY_INVALID")
    day = public.get("last_successful_trading_day")
    retained_day = history["status"]["last_successful_trading_day"] if history else None
    negative = public.get("last_failure") is not None or (public.get("last_run") or {}).get("status") in {"failed", "interrupted"}
    recovered = ((public.get("last_run") or {}).get("status") == "passed"
                 and history is not None
                 and datetime.fromisoformat(public["last_run"]["finished_at"])
                     >= datetime.fromisoformat(history["status"]["last_run"]["finished_at"]))
    if content is not None and (negative or recovered or (day is not None and (retained_day is None or day > retained_day))):
        commit = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
        history = make_history(content, commit=commit, products=products, now=now)
    authority.recheck()
    if content is not None and _bytes(authority.path) != content:
        raise ValueError("AFTER_MARKET_HISTORY_CHANGED")
    if history is None:
        return "no_previous_success"
    target = target_root / ".run" / NAME
    existing = read_history(target, products=products, now=now)
    if existing is not None:
        if any(existing[key] != history[key] for key in history if key != "retained_at"):
            raise ValueError("AFTER_MARKET_HISTORY_CONFLICT")
        return "already_retained"
    return publish_history(target, history) if apply else "ready"


def _guard_fd(authority) -> int:
    path = authority.path.parent / "live-recovery-guards/after-market.lock"
    if path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError
    directory = path.parent.stat()
    if directory.st_uid != os.getuid() or directory.st_mode & 0o022:
        raise ValueError
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o022):
        os.close(fd)
        raise ValueError
    return fd


def verify_install_guard(target_root: Path) -> None:
    from app.market_data.runtime_status_authority import resolve_market_runtime_status_authority
    authority = resolve_market_runtime_status_authority(candidate_root=target_root,
        expected_stopped_status_sha256=os.environ.get("GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256"))
    marker = os.environ.get("GUIYI_MARKET_INSTALL_GUARD_FD", "")
    if marker == "first_install" and authority.mode == "first_install":
        return
    if not marker.isdecimal() or int(marker) < 3:
        raise ValueError
    inherited = int(marker)
    expected = _guard_fd(authority)
    try:
        actual_info, expected_info = os.fstat(inherited), os.fstat(expected)
        if (actual_info.st_dev, actual_info.st_ino) != (expected_info.st_dev, expected_info.st_ino):
            raise ValueError
        fcntl.flock(inherited, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A separate open description MUST be excluded by the inherited lock.
        try:
            fcntl.flock(expected, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise ValueError
        authority.recheck()
    finally:
        os.close(expected)


def install_with_history_guard(target_root: Path) -> int:
    """Hold the old writer's kernel lock through the entire existing installer."""
    from app.market_data.runtime_status_authority import resolve_market_runtime_status_authority
    authority = resolve_market_runtime_status_authority(candidate_root=target_root,
        expected_stopped_status_sha256=os.environ.get("GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256"))
    fd = None
    try:
        if authority.mode != "first_install":
            fd = _guard_fd(authority)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            authority.recheck()
        environment = {**os.environ, "GUIYI_MARKET_INSTALL_GUARD_FD": str(fd) if fd is not None else "first_install"}
        return subprocess.run(["/bin/bash", str(target_root / "scripts/ops/macos/install-local-services.sh"),
                              "--confirm-market-runtime"], env=environment,
                              pass_fds=(fd,) if fd is not None else (), check=False).returncode
    finally:
        if fd is not None:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--from-supervised", action="store_true")
    parser.add_argument("--source-status", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--verify-install-guard", action="store_true")
    args = parser.parse_args()
    try:
        if args.install:
            return install_with_history_guard(args.target_root.resolve(strict=True))
        if args.verify_install_guard:
            verify_install_guard(args.target_root.resolve(strict=True))
            return 0
        if args.from_supervised:
            if any((args.source_status, args.source_commit, args.expected_source_sha256)):
                raise ValueError
            result = retain_from_supervised(args.target_root.resolve(strict=True), apply=args.apply)
        else:
            from app.market_data.operational_universe import load_operational_products
            if not args.source_status or not args.source_commit or not args.expected_source_sha256:
                raise ValueError
            if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
                raise ValueError
            content = _bytes(args.source_status.absolute())
            if hashlib.sha256(content).hexdigest() != args.expected_source_sha256:
                raise ValueError
            subprocess.run(["git", "-C", str(args.target_root), "cat-file", "-e",
                            args.source_commit + "^{commit}"], check=True, capture_output=True)
            now = datetime.now(UTC)
            value = make_history(content, commit=args.source_commit, products=load_operational_products(), now=now)
            target = args.target_root.resolve(strict=True) / ".run" / NAME
            existing = read_history(target, products=load_operational_products(), now=now)
            if existing is not None:
                if any(existing[key] != value[key] for key in value if key != "retained_at"):
                    raise ValueError
                result = "already_retained"
            else:
                result = publish_history(target, value) if args.apply else "ready"
        print(json.dumps({"command": "runtime.retain-after-market-history", "status": result,
                          "readonly": not args.apply}))
        return 0
    except Exception:
        print(json.dumps({"command": "runtime.retain-after-market-history", "status": "blocked",
                          "error_code": "AFTER_MARKET_HISTORY_INVALID", "readonly": not args.apply}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
