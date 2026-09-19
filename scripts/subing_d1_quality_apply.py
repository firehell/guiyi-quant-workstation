#!/usr/bin/env python3
"""Apply one approved, hash-bound SuBing D1 quality candidate batch."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, BinaryIO

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = PROJECT_ROOT / "services/quant-api"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.db.url import normalize_database_url  # noqa: E402
from app.market_data.subing_d1_quality_apply import (  # noqa: E402
    QualityCandidateApplyError,
    apply_frozen_candidates,
    preflight_frozen_candidates,
)
from scripts.newow_weekly_recovery import load_private_readonly_settings  # noqa: E402


AUTHORIZED_PLAN_SHA256 = "5d5475b0709ea4f6c6464491938e38c4d0867d30d42a6f8366004594a282561c"
AUTHORIZED_MANIFEST_SHA256 = "2a15f7aa0fe896804c2ee2b0b19dd5658407cf05eb6e9e96a4fad9e7245371ba"
AUTHORIZED_TARGET_COUNT = 156


class ReceiptJournal:
    """Durable attempt record reserved and fsynced before production mutation."""

    def __init__(self, path: Path, stream: BinaryIO) -> None:
        self.path = path
        self._stream = stream

    @classmethod
    def reserve(cls, path: Path, first: dict[str, Any]) -> ReceiptJournal:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError as exc:
            raise QualityCandidateApplyError("APPLY_RECEIPT_EXISTS") from exc
        except OSError as exc:
            raise QualityCandidateApplyError("APPLY_RECEIPT_RESERVE_FAILED") from exc
        stream = os.fdopen(fd, "wb", buffering=0)
        journal = cls(path, stream)
        try:
            journal.append(first)
            directory_fd = os.open(
                path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            stream.close()
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
        return journal

    def append(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode() + b"\n"
        try:
            self._stream.write(payload)
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except OSError as exc:
            raise QualityCandidateApplyError("APPLY_RECEIPT_APPEND_FAILED") from exc

    def close(self) -> None:
        self._stream.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-env", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and args.receipt is None:
        raise QualityCandidateApplyError("APPLY_RECEIPT_REQUIRED")

    plan = _read_json(args.plan)
    manifest = _read_json(args.manifest)
    if (
        args.expected_plan_sha256 != AUTHORIZED_PLAN_SHA256
        or args.expected_manifest_sha256 != AUTHORIZED_MANIFEST_SHA256
        or plan.get("target_partition_count") != AUTHORIZED_TARGET_COUNT
        or manifest.get("target_partition_count") != AUTHORIZED_TARGET_COUNT
    ):
        raise QualityCandidateApplyError("AUTHORIZED_BATCH_IDENTITY_MISMATCH")
    settings, _identity = load_private_readonly_settings(args.project_env)
    active_root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        journal = None
        if args.apply:
            assert args.receipt is not None
            journal = ReceiptJournal.reserve(args.receipt, {
                "schema": "subing-d1-quality-production-apply-journal-v1",
                "status": "prepared",
                "prepared_at": datetime.now(UTC).isoformat(),
                "plan_sha256": args.expected_plan_sha256,
                "manifest_sha256": args.expected_manifest_sha256,
                "target_count": AUTHORIZED_TARGET_COUNT,
                "provider_requests": 0,
            })
        try:
            with Session(engine) as session:
                operation = apply_frozen_candidates if args.apply else preflight_frozen_candidates
                result = operation(
                    session=session,
                    active_root=active_root,
                    candidate_root=args.candidate_root,
                    plan=plan,
                    manifest=manifest,
                    expected_plan_sha256=args.expected_plan_sha256,
                    expected_manifest_sha256=args.expected_manifest_sha256,
                )
        except QualityCandidateApplyError as exc:
            if journal is not None:
                journal.append({
                    "status": "failed",
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "error_code": str(exc),
                })
            raise
        finally:
            if journal is not None and sys.exc_info()[0] is not None:
                journal.close()
    finally:
        engine.dispose()

    receipt = {
        "schema": "subing-d1-quality-production-apply-receipt-v1",
        "status": result["status"],
        "applied_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "plan_sha256": args.expected_plan_sha256,
        "manifest_sha256": args.expected_manifest_sha256,
        "target_count": result["target_count"],
        "old_count": result.get("old_count", 0),
        "applied_count": result.get("applied_count", 0),
        "noop_count": result.get("noop_count", 0),
        "provider_requests": 0,
    }
    if args.apply:
        assert journal is not None
        try:
            journal.append(receipt)
        finally:
            journal.close()
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualityCandidateApplyError("APPLY_INPUT_INVALID")
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualityCandidateApplyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
