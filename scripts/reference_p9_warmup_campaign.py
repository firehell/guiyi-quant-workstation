#!/usr/bin/env python3
"""Bounded P9 source-gap warmup, using the existing contract-warmup command.

Plan is read-only. Apply needs a frozen preflight receipt and stops after any
uncertain unit outcome. The script never chooses a contract or partition.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from time import monotonic

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.closeout_binding import runtime_dependency_settings
from app.market_data.rqdata_adapter import RQDATA_PROVIDER_SETTINGS, runtime_provider_settings


ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-23"
SCHEMA = "20260919_0047"
ARTIFACT_KIND = "reference_p9_warmup_candidate_wave1"
MAX_CANDIDATE_BYTES = 4 * 1024 * 1024
MAX_PREFLIGHT_BYTES = 128 * 1024
ALLOWED_FREQUENCIES = {"1m", "15m", "30m", "60m", "1d"}
PLANNING_CODE_SHA = "943c23b61a18156e0d068726ace843aacb6d4e43"
PROGRESS_LINE = re.compile(
    r"maintenance contract_warmup (?:"
    r"fetched planned=[0-9]+ applied=[0-9]+ failed=[0-9]+ provider_requests=[0-9]+"
    r"|derived planned=[0-9]+ applied=[0-9]+ failed=[0-9]+ blocked=[0-9]+)"
)


class CampaignBlocked(ValueError):
    """Safe public failure code; do not expose provider or database text."""


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _digest(value: object) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _read_pinned(path: Path, expected_sha: str, max_bytes: int) -> dict[str, object]:
    if not path.is_absolute() or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise CampaignBlocked("ARTIFACT_IDENTITY_INVALID")
    try:
        if path.resolve(strict=True) != path:
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
                raise ValueError
            data = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
            if (
                len(data) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or _sha(data) != expected_sha
            ):
                raise ValueError
        value = json.loads(data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise CampaignBlocked("ARTIFACT_IDENTITY_INVALID") from exc
    if not isinstance(value, dict):
        raise CampaignBlocked("ARTIFACT_CONTRACT_INVALID")
    return value


def _write_new(path: Path, value: object) -> None:
    if not path.is_absolute() or not path.parent.resolve(strict=True).is_relative_to(
        Path(tempfile.gettempdir()).resolve()
    ):
        raise CampaignBlocked("OUTPUT_PATH_INVALID")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise CampaignBlocked("OUTPUT_PATH_INVALID") from exc


def _exact_checkout(expected_sha: str) -> None:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"],
        cwd=ROOT, text=True,
    ).strip()
    if commit != expected_sha or len(commit) != 40 or dirty:
        raise CampaignBlocked("CODE_IDENTITY_DRIFT")


def _target_key(target: dict[str, object]) -> tuple[str, str, str, str, int, int]:
    dataset = target.get("dataset")
    year, month = target.get("year"), target.get("month")
    if (
        not isinstance(dataset, list) or len(dataset) != 4
        or any(not isinstance(item, str) for item in dataset)
        or dataset[0] != "contract" or dataset[3] not in ALLOWED_FREQUENCIES
        or type(year) is not int or type(month) is not int
        or year < 2020 or year > 2026 or month < 1 or month > 12
    ):
        raise CampaignBlocked("TARGET_SCOPE_INVALID")
    return (*dataset, year, month)


def _candidate(value: dict[str, object]) -> tuple[list[dict[str, object]], dict[tuple, dict]]:
    matrix = json.loads((
        ROOT / "outputs/reference-p9-source-inventory-20260925/matrix.json"
    ).read_text())
    if (
        value.get("schema_version") != 1 or value.get("artifact_kind") != ARTIFACT_KIND
        or value.get("readonly") is not True or value.get("apply_supported") is not False
        or value.get("database") != "guiyi_quant" or value.get("database_schema") != SCHEMA
        or value.get("through") != DAY
        or value.get("planning_code_sha") != PLANNING_CODE_SHA
        or value.get("source_matrix_sha256") != _sha((
            ROOT / "outputs/reference-p9-source-inventory-20260925/matrix.json"
        ).read_bytes())
        or matrix.get("active_products_sha256") != _sha((
            ROOT / "data/universe/active_products.txt"
        ).read_bytes())
        or matrix.get("operational_products_sha256") != _sha((
            ROOT / "data/universe/operational_products.txt"
        ).read_bytes())
    ):
        raise CampaignBlocked("CANDIDATE_IDENTITY_DRIFT")
    plans, raw_targets, scope = value.get("plans"), value.get("targets"), value.get("scope")
    if not isinstance(plans, list) or len(plans) != 175 or not isinstance(raw_targets, list):
        raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
    if not isinstance(scope, dict) or len(raw_targets) != scope.get("target_partitions"):
        raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
    targets: dict[tuple, dict] = {}
    for target in raw_targets:
        if not isinstance(target, dict):
            raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
        key = _target_key(target)
        if key in targets or type(target.get("missing_bar_count")) is not int:
            raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
        targets[key] = target
    identities: set[str] = set()
    for item in plans:
        if not isinstance(item, dict):
            raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
        stream_id, symbol, contract, frequency = (
            item.get("stream_id"), item.get("symbol"), item.get("contract"),
            item.get("frequency"),
        )
        if (
            not isinstance(stream_id, str) or stream_id in identities
            or not isinstance(symbol, str) or not isinstance(contract, str)
            or frequency not in {"15m", "30m", "60m", "1d"}
            or re.fullmatch(r"[A-Z]{1,4}[0-9]{4}", contract) is None
            or re.fullmatch(r"[0-9a-f]{64}", item.get("baseline_plan_sha256", "")) is None
            or not isinstance(item.get("owner_last"), str)
            or item["owner_last"] > DAY
        ):
            raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
        identities.add(stream_id)
    if (
        len(targets) != 2011 or scope.get("direct_target_partitions") != 526
        or scope.get("derived_target_partitions") != 1485
        or len({(x["symbol"], x["contract"]) for x in plans}) != 64
    ):
        raise CampaignBlocked("CANDIDATE_SCOPE_INVALID")
    priority = {"15m": 0, "30m": 1, "60m": 2, "1d": 3}
    return sorted(plans, key=lambda x: (
        x["symbol"], x["contract"], priority[x["frequency"]], x["stream_id"],
    )), targets


def _binding(expected_database: str) -> tuple[dict[str, str], str, str, str]:
    if any(key.startswith("PG") for key in os.environ):
        raise CampaignBlocked("AMBIENT_PG_CONFIG")
    config_bytes = (
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    ).read_bytes()
    settings = runtime_dependency_settings(config_bytes)
    runtime_provider_settings(settings, required=True)
    url = make_url(normalize_database_url(settings["DATABASE_URL"]))
    if url.get_backend_name() != "postgresql" or url.query:
        raise CampaignBlocked("DATABASE_ENDPOINT_INVALID")
    endpoint_sha = _digest({
        "driver": url.drivername, "host": url.host, "port": url.port,
        "database": url.database, "username": url.username,
    })
    canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    if not canonical.is_absolute() or canonical != canonical.resolve(strict=True):
        raise CampaignBlocked("CANONICAL_ROOT_INVALID")
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]))
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            if session.execute(text("SELECT current_database()")).scalar_one() != expected_database:
                raise CampaignBlocked("DATABASE_IDENTITY_DRIFT")
            if session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != SCHEMA:
                raise CampaignBlocked("SCHEMA_IDENTITY_DRIFT")
            session.rollback()
    finally:
        engine.dispose()
    env = dict(os.environ)
    env["DATABASE_URL"] = normalize_database_url(settings["DATABASE_URL"])
    env["GUIYI_CANONICAL_DATA_ROOT"] = str(canonical)
    # Empty values prevent the repo .env fallback from supplying a different provider.
    env.update({key: settings.get(key, "") for key in RQDATA_PROVIDER_SETTINGS})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'services/quant-api'}:{ROOT / 'packages/quant-core'}"
    return env, endpoint_sha, _sha(str(canonical).encode()), _sha(config_bytes)


def _cli(
    unit: dict[str, object], env: dict[str, str], *, plan_hash: str | None,
    timeout_seconds: int,
) -> dict[str, object]:
    argv = [sys.executable, "-m", "app.guiyi_cli.main", "data", "contract-warmup",
            "--symbol", unit["symbol"], "--contract", unit["contract"],
            "--frequency", unit["frequency"], "--through", unit["owner_last"]]
    if plan_hash is not None:
        argv.extend(("--expected-plan-sha256", plan_hash, "--apply"))
    try:
        result = subprocess.run(
            argv, cwd=ROOT, env=env, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 16 * 1024 * 1024:
            raise CampaignBlocked(
                "UNIT_OUTCOME_UNKNOWN" if plan_hash is not None else "UNIT_PLAN_FAILED"
            )
        lines = result.stdout.splitlines()
        progress_count = 0
        if plan_hash is not None:
            while (
                progress_count < len(lines)
                and PROGRESS_LINE.fullmatch(lines[progress_count]) is not None
            ):
                progress_count += 1
        payload = json.loads("\n".join(lines[progress_count:]))
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        raise CampaignBlocked(
            "UNIT_OUTCOME_UNKNOWN" if plan_hash is not None else "UNIT_PLAN_FAILED"
        ) from exc
    if not isinstance(payload, dict):
        raise CampaignBlocked(
            "UNIT_OUTCOME_UNKNOWN" if plan_hash is not None else "UNIT_PLAN_FAILED"
        )
    return payload


def _validate_plan(
    unit: dict[str, object], plan: dict[str, object], allowed: dict[tuple, dict],
) -> tuple[str, int, int]:
    if (
        plan.get("status") != "planned" or plan.get("readonly") is not True
        or plan.get("provider_requests") != 0
        or plan.get("symbol") != unit["symbol"]
        or plan.get("contract") != unit["contract"]
        or plan.get("frequency") != unit["frequency"]
        or (plan.get("requested_window") or {}).get("through") != unit["owner_last"]
        or re.fullmatch(r"[0-9a-f]{64}", plan.get("plan_sha256", "")) is None
        or not isinstance(plan.get("targets"), list)
    ):
        raise CampaignBlocked("UNIT_PLAN_IDENTITY_DRIFT")
    direct = 0
    seen: set[tuple] = set()
    for target in plan["targets"]:
        if not isinstance(target, dict):
            raise CampaignBlocked("UNIT_TARGET_DRIFT")
        key = _target_key(target)
        baseline = allowed.get(key)
        if key in seen or baseline is None:
            raise CampaignBlocked("UNIT_TARGET_DRIFT")
        seen.add(key)
        try:
            lower = datetime.fromisoformat(baseline["missing_start"])
            upper = datetime.fromisoformat(baseline["missing_end"])
            current_start = datetime.fromisoformat(target["missing_start"])
            current_end = datetime.fromisoformat(target["missing_end"])
            bounded = (
                all(item.tzinfo is not None for item in (
                    lower, upper, current_start, current_end,
                ))
                and lower <= current_start <= current_end <= upper
            )
        except (KeyError, TypeError, ValueError):
            bounded = False
        if (
            key[1] != unit["symbol"] or key[2] != unit["contract"]
            or target.get("expected_bar_count") != baseline.get("expected_bar_count")
            or target.get("expected_start") != baseline.get("expected_start")
            or target.get("expected_end") != baseline.get("expected_end")
            or type(target.get("missing_bar_count")) is not int
            or not 0 < target["missing_bar_count"] <= baseline["missing_bar_count"]
            or not bounded
        ):
            raise CampaignBlocked("UNIT_TARGET_DRIFT")
        direct += key[3] in {"1m", "1d"}
    if plan.get("provider_request_count") != direct:
        raise CampaignBlocked("UNIT_PROVIDER_BUDGET_DRIFT")
    return plan["plan_sha256"], direct, len(seen)


def _preflight(
    units: list[dict[str, object]], allowed: dict[tuple, dict], env: dict[str, str],
    *, code_sha: str, candidate_sha: str, endpoint_sha: str, canonical_sha: str,
    config_sha: str, max_provider_requests: int, max_total_seconds: int,
) -> dict[str, object]:
    baseline = []
    deadline = monotonic() + max_total_seconds
    for unit in units:
        if monotonic() >= deadline:
            raise CampaignBlocked("PREFLIGHT_TIME_BUDGET_EXCEEDED")
        fresh = _cli(unit, env, plan_hash=None, timeout_seconds=min(120, int(deadline - monotonic())))
        plan_hash, _, _ = _validate_plan(unit, fresh, allowed)
        if plan_hash != unit["baseline_plan_sha256"]:
            raise CampaignBlocked("BASELINE_PLAN_DRIFT")
        baseline.append({"stream_id": unit["stream_id"], "plan_sha256": plan_hash})
    payload = {
        "schema_version": 1, "operation": "reference_p9_warmup_wave1",
        "readonly": True, "candidate_sha256": candidate_sha, "code_sha": code_sha,
        "endpoint_sha256": endpoint_sha, "canonical_root_sha256": canonical_sha,
        "project_env_sha256": config_sha,
        "database": "guiyi_quant", "schema": SCHEMA,
        "max_provider_requests": max_provider_requests,
        "max_total_seconds": max_total_seconds,
        "unit_count": len(units), "baseline": baseline,
    }
    return {**payload, "preflight_sha256": _digest(payload)}


def _apply(
    units: list[dict[str, object]], allowed: dict[tuple, dict], env: dict[str, str],
    *, journal_dir: Path, max_provider_requests: int, max_total_seconds: int,
) -> dict[str, object]:
    if not journal_dir.is_absolute() or not journal_dir.parent.resolve(strict=True).is_relative_to(
        Path(tempfile.gettempdir()).resolve()
    ):
        raise CampaignBlocked("JOURNAL_PATH_INVALID")
    try:
        journal_dir.mkdir(mode=0o700, exist_ok=False)
    except OSError as exc:
        raise CampaignBlocked("JOURNAL_PATH_INVALID") from exc
    deadline = monotonic() + max_total_seconds
    provider_used = 0
    completed = 0
    for index, unit in enumerate(units, 1):
        if monotonic() >= deadline:
            raise CampaignBlocked("CAMPAIGN_TIME_BUDGET_EXCEEDED")
        fresh = _cli(unit, env, plan_hash=None, timeout_seconds=min(120, int(deadline - monotonic())))
        plan_hash, proposed_provider, target_count = _validate_plan(unit, fresh, allowed)
        if provider_used + proposed_provider > max_provider_requests:
            raise CampaignBlocked("CAMPAIGN_PROVIDER_BUDGET_EXCEEDED")
        path = journal_dir / f"unit-{index:03d}-{unit['symbol']}-{unit['contract']}-{unit['frequency']}"
        path.mkdir(mode=0o700, exist_ok=False)
        _write_new(path / "attempt.json", {
            "status": "started", "stream_id": unit["stream_id"],
            "plan_sha256": plan_hash, "target_count": target_count,
            "proposed_provider_requests": proposed_provider,
        })
        if target_count:
            result = _cli(
                unit, env, plan_hash=plan_hash,
                timeout_seconds=max(1, min(1800, int(deadline - monotonic()))),
            )
            try:
                _write_new(path / "result.json", {
                    "status": result.get("status"), "applied": result.get("applied"),
                    "blocked": result.get("blocked"), "failed": result.get("failed"),
                    "provider_requests": result.get("provider_requests"),
                    "plan_sha256": plan_hash,
                })
            except CampaignBlocked as exc:
                raise CampaignBlocked("UNIT_OUTCOME_UNKNOWN") from exc
            if (
                result.get("status") != "passed" or result.get("readonly") is not False
                or result.get("plan_sha256") != plan_hash
                or result.get("symbol") != unit["symbol"]
                or result.get("contract") != unit["contract"]
                or result.get("frequency") != unit["frequency"]
                or result.get("blocked") != 0 or result.get("failed") != 0
                or type(result.get("provider_requests")) is not int
                or not 0 <= result["provider_requests"] <= proposed_provider
            ):
                raise CampaignBlocked("UNIT_APPLY_FAILED")
            provider_used += result["provider_requests"]
        try:
            readback = _cli(unit, env, plan_hash=None, timeout_seconds=120)
            _, _, remaining = _validate_plan(unit, readback, allowed)
        except CampaignBlocked as exc:
            raise CampaignBlocked("POST_APPLY_READBACK_FAILED") from exc
        _write_new(path / "readback.json", {
            "status": "passed" if remaining == 0 else "remaining",
            "remaining_targets": remaining, "plan_sha256": readback["plan_sha256"],
        })
        if remaining:
            raise CampaignBlocked("UNIT_READBACK_INCOMPLETE")
        completed += 1
    return {"status": "applied", "completed_units": completed,
            "provider_requests": provider_used, "journal_dir": str(journal_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "apply"), required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-code-sha", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--max-provider-requests", type=int, required=True)
    parser.add_argument("--max-total-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--expected-preflight-sha256")
    parser.add_argument("--journal-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if (
            args.expected_database_name != "guiyi_quant"
            or type(args.max_provider_requests) is not int
            or not 0 < args.max_provider_requests <= 526
            or type(args.max_total_seconds) is not int
            or not 0 < args.max_total_seconds <= 14400
        ):
            raise CampaignBlocked("CAMPAIGN_BUDGET_INVALID")
        if args.phase == "preflight":
            if args.apply or args.output is None or args.preflight or args.journal_dir:
                raise CampaignBlocked("PHASE_ARGUMENT_INVALID")
        elif (
            not args.apply or args.output is not None or args.preflight is None
            or args.journal_dir is None or args.expected_preflight_sha256 is None
        ):
            raise CampaignBlocked("PHASE_ARGUMENT_INVALID")
        _exact_checkout(args.expected_code_sha)
        candidate = _read_pinned(
            args.candidate, args.expected_candidate_sha256, MAX_CANDIDATE_BYTES
        )
        units, allowed = _candidate(candidate)
        env, endpoint_sha, canonical_sha, config_sha = _binding(args.expected_database_name)
        if args.phase == "preflight":
            receipt = _preflight(
                units, allowed, env, code_sha=args.expected_code_sha,
                candidate_sha=args.expected_candidate_sha256,
                endpoint_sha=endpoint_sha, canonical_sha=canonical_sha,
                config_sha=config_sha,
                max_provider_requests=args.max_provider_requests,
                max_total_seconds=args.max_total_seconds,
            )
            _write_new(args.output, receipt)
            print(json.dumps({"status": "preflight_passed", "readonly": True,
                              "preflight_sha256": receipt["preflight_sha256"],
                              "preflight_file_sha256": _sha(args.output.read_bytes()),
                              "output": str(args.output)}, sort_keys=True))
        else:
            receipt = _read_pinned(
                args.preflight, args.expected_preflight_sha256, MAX_PREFLIGHT_BYTES
            )
            if (
                receipt.get("preflight_sha256") != _digest({
                    key: value for key, value in receipt.items() if key != "preflight_sha256"
                })
                or receipt.get("candidate_sha256") != args.expected_candidate_sha256
                or receipt.get("code_sha") != args.expected_code_sha
                or receipt.get("endpoint_sha256") != endpoint_sha
                or receipt.get("canonical_root_sha256") != canonical_sha
                or receipt.get("project_env_sha256") != config_sha
                or receipt.get("max_provider_requests") != args.max_provider_requests
                or receipt.get("max_total_seconds") != args.max_total_seconds
                or receipt.get("unit_count") != len(units)
            ):
                raise CampaignBlocked("PREFLIGHT_IDENTITY_DRIFT")
            result = _apply(
                units, allowed, env, journal_dir=args.journal_dir,
                max_provider_requests=args.max_provider_requests,
                max_total_seconds=args.max_total_seconds,
            )
            print(json.dumps(result, sort_keys=True))
    except CampaignBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "CAMPAIGN_INTERNAL_ERROR"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
