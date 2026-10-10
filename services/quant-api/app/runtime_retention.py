"""Read-only release worktree retention proof; this module never deletes a tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
from typing import Any

from app.runtime_bindings import SERVICES, _git, read_bindings, verify_release


class RetentionError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _references(value: str, root: Path) -> bool:
    # A conservative prefix match retains descendants and ambiguous shell quoting.
    return str(root) in value


def build_cleanup_plan(roots: tuple[Path, ...], *, backend=None) -> dict[str, Any]:
    """Freeze exact deletion candidates, and fail closed on incomplete host evidence."""
    if not roots or len(set(roots)) != len(roots):
        raise RetentionError("CLEANUP_TARGETS_INVALID")
    for root in roots:
        if not isinstance(root, Path) or not root.is_absolute() or root != root.resolve(strict=True):
            raise RetentionError("CLEANUP_TARGETS_INVALID")
    backend = backend or RetentionBackend()
    identities = {}
    invalid = set()
    for root in roots:
        try:
            identities[str(root)] = backend.candidate_identity(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            invalid.add(str(root))
    try:
        references = backend.references_by_root(roots)
        probe_unknown = False
    except (OSError, ValueError, subprocess.SubprocessError):
        references = {}
        probe_unknown = True
    targets = []
    for root in roots:
        key = str(root)
        reasons = sorted(set(references.get(key, [])))
        unknown = probe_unknown or key in invalid or key not in references
        targets.append({"root": key, "identity": identities.get(key),
            "status": "blocked" if unknown else "retained" if reasons else "eligible",
            "references": reasons, "error_code": "CLEANUP_EVIDENCE_UNAVAILABLE" if unknown else None})
    plan = {"schema_version": 1, "readonly": True, "dry_run": True, "targets": targets,
            "eligible_roots": [row["root"] for row in targets if row["status"] == "eligible"],
            "recovery": "git worktree removal only after an unchanged exact plan readback; never force"}
    plan["plan_sha256"] = _hash(plan)
    return plan


class RetentionBackend:
    def __init__(self, *, home: Path | None = None):
        self.home = Path.home() if home is None else home

    def candidate_identity(self, root: Path) -> dict[str, str]:
        # Release cleanup only accepts a registered detached clean annotated-tag worktree.
        if (root / ".git").is_symlink() or not (root / ".git").is_file():
            raise RetentionError("CLEANUP_MANAGED_WORKTREE_REQUIRED")
        from app.core.env import PROJECT_ROOT
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        authorized_common = _git(PROJECT_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if Path(common).resolve(strict=True) != Path(authorized_common).resolve(strict=True):
            raise RetentionError("CLEANUP_REPOSITORY_IDENTITY_INVALID")
        commit = _git(root, "rev-parse", "HEAD")
        tag = _git(root, "describe", "--exact-match", "--tags", "HEAD")
        verify_release(root, tag, commit)
        listed = _git(root, "worktree", "list", "--porcelain")
        blocks = [dict((line.partition(" ")[0], line.partition(" ")[2]) for line in block.splitlines())
                  for block in listed.split("\n\n") if block]
        matching = [item for item in blocks if item.get("worktree") == str(root)]
        if len(matching) != 1 or matching[0].get("HEAD") != commit or "detached" not in matching[0]:
            raise RetentionError("CLEANUP_WORKTREE_IDENTITY_INVALID")
        return {"root": str(root), "commit": commit, "tag": tag}

    def _command(self, arguments: list[str]) -> str:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=15, check=True)
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise RetentionError("CLEANUP_PROBE_UNAVAILABLE") from None

    def references_by_root(self, roots: tuple[Path, ...]) -> dict[str, list[str]]:
        from app.market_data.closeout_binding import _arguments, _environments, _snapshot
        result: dict[str, list[str]] = {str(root): [] for root in roots}
        registry = read_bindings(home=self.home)
        if registry is not None:
            for service, binding in registry.services.items():
                if binding.root in result:
                    result[binding.root].append(f"binding:{service}")
        directory = self.home / "Library/LaunchAgents"
        labels = set()
        if directory.exists():
            if directory != directory.resolve(strict=True):
                raise RetentionError("CLEANUP_PLIST_DIRECTORY_INVALID")
            for path in directory.glob("com.guiyi.quant-*.plist"):
                content, _ = _snapshot(path)
                try:
                    payload = plistlib.loads(content)
                    label = payload["Label"]
                    if label != path.stem:
                        raise ValueError
                    labels.add(label)
                    environment = payload.get("EnvironmentVariables", {})
                    values = [payload.get("WorkingDirectory", ""), *(environment.get(key, "") for key in ("GUIYI_PROJECT_ROOT", "PYTHONPATH", "VIRTUAL_ENV"))]
                    arguments = payload.get("ProgramArguments", [])
                    if not isinstance(arguments, list) or any(not isinstance(value, str) for value in arguments):
                        raise ValueError
                    values.extend(arguments)
                    if any(not isinstance(value, str) for value in values):
                        raise ValueError
                    for root in roots:
                        if any(_references(value, root) for value in values):
                            result[str(root)].append(f"plist:{label}")
                except (KeyError, TypeError, ValueError, plistlib.InvalidFileException):
                    raise RetentionError("CLEANUP_PLIST_UNAVAILABLE") from None
        # Inventory loaded labels as well as installed plists; stale candidate jobs are pins.
        output = self._command(["/bin/launchctl", "list"])
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) != 3:
                raise RetentionError("CLEANUP_LOADED_INVENTORY_INVALID")
            if parts[2].startswith("com.guiyi.quant-"):
                labels.add(parts[2])
        valid_label = re.compile(r"com\.guiyi\.quant-(?:" + "|".join(re.escape(item) for item in SERVICES) + r")(?:-candidate-[0-9a-f]{32})?")
        from app.market_data.captured_recovery_runtime import _read_launchd_service
        for label in labels:
            if not valid_label.fullmatch(label):
                raise RetentionError("CLEANUP_LOADED_LABEL_UNSUPPORTED")
            observed = _read_launchd_service(label, root=roots[0])
            if observed is None:
                continue
            values = list(_arguments(observed))
            values.extend(environment.get(key, "") for environment in _environments(observed)
                          for key in ("GUIYI_PROJECT_ROOT", "PYTHONPATH", "VIRTUAL_ENV"))
            values.extend(re.findall(r"^\s*working directory = (.*)$", observed, flags=re.M))
            for root in roots:
                if any(_references(value, root) for value in values):
                    result[str(root)].append(f"loaded:{label}")
        # Unmanaged foreground commands may still hold code from a retired release.
        commands = self._command(["/bin/ps", "-ww", "-axo", "pid=,command="])
        for line in commands.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) != 2 or not fields[0].isdigit():
                raise RetentionError("CLEANUP_PROCESS_INVENTORY_INVALID")
            pid = int(fields[0])
            if pid == os.getpid():
                continue
            for root in roots:
                if _references(fields[1], root):
                    result[str(root)].append(f"process:{pid}")
        # A foreground Python process may use relative argv; its cwd is still a pin.
        cwd_inventory = self._command(["/usr/sbin/lsof", "-a", "-d", "cwd", "-F", "pn"])
        cwd_pid: int | None = None
        for line in cwd_inventory.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                cwd_pid = int(line[1:])
            elif line == "fcwd" and cwd_pid is not None:
                continue
            elif line.startswith("n") and cwd_pid is not None:
                for root in roots:
                    if _references(line[1:], root):
                        result[str(root)].append(f"cwd:{cwd_pid}")
            else:
                raise RetentionError("CLEANUP_CWD_INVENTORY_INVALID")
        if read_bindings(home=self.home) != registry:
            raise RetentionError("CLEANUP_REGISTRY_DRIFT")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only exact release cleanup plan")
    parser.add_argument("command", choices=["cleanup-plan"])
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = build_cleanup_plan(tuple(args.roots))
    except (OSError, ValueError):
        print(json.dumps({"status": "blocked", "readonly": True, "error_code": "CLEANUP_TARGETS_INVALID"}))
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 1 if any(item["status"] == "blocked" for item in payload["targets"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
