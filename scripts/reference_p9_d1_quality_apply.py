#!/usr/bin/env python3
"""Publish the frozen 460-partition P9 D1 quality batch with exact readback."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.subing_d1_quality_apply import (
    QualityCandidateApplyError,
    apply_frozen_candidates,
    preflight_frozen_candidates,
)
from scripts.newow_weekly_recovery import load_private_readonly_settings
from scripts.subing_d1_quality_apply import ReceiptJournal


ROOT = Path(__file__).resolve().parents[1]
PLAN_SHA = "4cba25557a0d0b967ec2b39e77e79d986e292f512923365bf24a8cc399625310"
MANIFEST_SHA = "20d1a38d1205aabbf94f634b3a921fe016f5cfda0322e4ec4640a50e21c59781"
PLAN_FILE_SHA = "64a9046a64569f8ebe519d47d54a23da7f347c196c7d5eb651cade23e11641d8"
MANIFEST_FILE_SHA = "24444926c899d33a08f7da0240fd4104a33e75174d37326c57d2fe50d7dbf680"
BACKUP_FILE_SHA = "eed6fd47794c892e17b33707ea57205ef61e652705aa3586e1eccba267b0fc29"
TARGET_COUNT = 460


def _validate_paths(
    root: Path, plan: Path, manifest: Path, candidate: Path,
    backup: Path, plan_sha: str,
) -> None:
    expected_output = root / "outputs/reference-p9-d1-quality-20260925"
    expected_candidate = root / "data/canonical-candidates" / plan_sha / "attempt-001"
    paths = (plan, manifest, candidate, backup)
    expected = (
        expected_output / "plan.json", expected_output / "manifest.json",
        expected_candidate, expected_output / "preapply-pointer-backup-20260925.json",
    )
    if any(
        path != fixed or path.is_symlink() or path.resolve(strict=True) != path
        for path, fixed in zip(paths, expected, strict=True)
    ):
        raise QualityCandidateApplyError("P9_PATH_INVALID")


def _read_exact(path: Path, expected_sha: str) -> dict:
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha:
        raise QualityCandidateApplyError("P9_ARTIFACT_HASH_MISMATCH")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise QualityCandidateApplyError("P9_ARTIFACT_INVALID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "apply"), required=True)
    parser.add_argument("--expected-code-sha", required=True)
    parser.add_argument("--expected-backup-sha", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if (args.phase == "apply") != args.apply or (args.apply and args.receipt is None):
        raise QualityCandidateApplyError("P9_PHASE_INVALID")
    if args.expected_backup_sha != BACKUP_FILE_SHA:
        raise QualityCandidateApplyError("P9_BACKUP_IDENTITY_INVALID")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if head != args.expected_code_sha or dirty:
        raise QualityCandidateApplyError("P9_CODE_IDENTITY_INVALID")

    output = ROOT / "outputs/reference-p9-d1-quality-20260925"
    plan_path = output / "plan.json"
    manifest_path = output / "manifest.json"
    backup_path = output / "preapply-pointer-backup-20260925.json"
    candidate_root = ROOT / "data/canonical-candidates" / PLAN_SHA / "attempt-001"
    _validate_paths(ROOT, plan_path, manifest_path, candidate_root, backup_path, PLAN_SHA)
    plan = _read_exact(plan_path, PLAN_FILE_SHA)
    manifest = _read_exact(manifest_path, MANIFEST_FILE_SHA)
    backup = _read_exact(backup_path, BACKUP_FILE_SHA)
    if (
        plan.get("plan_sha256") != PLAN_SHA
        or manifest.get("manifest_sha256") != MANIFEST_SHA
        or manifest.get("candidate_root") != candidate_root.relative_to(ROOT).as_posix()
        or plan.get("target_partition_count") != TARGET_COUNT
        or manifest.get("frozen_candidate_count") != TARGET_COUNT
        or backup.get("plan_sha256") != PLAN_SHA
        or backup.get("manifest_sha256") != MANIFEST_SHA
        or backup.get("target_count") != TARGET_COUNT
        or len(backup.get("rows", [])) != TARGET_COUNT
    ):
        raise QualityCandidateApplyError("P9_BATCH_IDENTITY_INVALID")
    if args.apply and (
        args.receipt != output / "apply-journal-20260925.jsonl"
        or args.receipt.is_symlink()
    ):
        raise QualityCandidateApplyError("P9_RECEIPT_PATH_INVALID")

    env = Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    settings, _ = load_private_readonly_settings(env)
    active_root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    journal = None
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            if (
                session.scalar(text("SELECT current_database()")) != "guiyi_quant"
                or session.scalar(text("SELECT version_num FROM alembic_version"))
                != "20260919_0047"
            ):
                raise QualityCandidateApplyError("P9_DATABASE_IDENTITY_DRIFT")
            session.rollback()
        with Session(engine) as session:
            preflight = preflight_frozen_candidates(
                session=session, active_root=active_root,
                candidate_root=candidate_root, plan=plan, manifest=manifest,
                expected_plan_sha256=PLAN_SHA,
                expected_manifest_sha256=MANIFEST_SHA,
            )
        if not args.apply:
            print(json.dumps({**preflight, "readonly": True, "code_sha": head}, sort_keys=True))
            return 0
        if preflight["status"] != "ready" or preflight["old_count"] != TARGET_COUNT:
            raise QualityCandidateApplyError("P9_PREFLIGHT_NOT_READY")
        assert args.receipt is not None
        journal = ReceiptJournal.reserve(args.receipt, {
            "status": "started", "at": datetime.now(UTC).isoformat(),
            "code_sha": head, "plan_sha256": PLAN_SHA,
            "manifest_sha256": MANIFEST_SHA,
            "backup_file_sha256": BACKUP_FILE_SHA,
            "target_count": TARGET_COUNT,
        })
        with Session(engine) as session:
            result = apply_frozen_candidates(
                session=session, active_root=active_root,
                candidate_root=candidate_root, plan=plan, manifest=manifest,
                expected_plan_sha256=PLAN_SHA,
                expected_manifest_sha256=MANIFEST_SHA,
            )
        journal.append({**result, "status": result["status"], "at": datetime.now(UTC).isoformat()})
        print(json.dumps({**result, "readonly": False, "code_sha": head}, sort_keys=True))
        return 0
    except Exception as exc:
        if journal is not None:
            code = str(exc) if isinstance(exc, QualityCandidateApplyError) else "P9_APPLY_INTERNAL_ERROR"
            journal.append({"status": "failed", "error_code": code, "at": datetime.now(UTC).isoformat()})
        raise
    finally:
        if journal is not None:
            journal.close()
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualityCandidateApplyError as exc:
        print(json.dumps({"status": "blocked", "code": str(exc)}, sort_keys=True))
        raise SystemExit(2) from None
    except Exception:
        print(json.dumps({"status": "blocked", "code": "P9_APPLY_INTERNAL_ERROR"}, sort_keys=True))
        raise SystemExit(2) from None
