#!/usr/bin/env python3
"""Freeze SuBing D1 replacement candidates outside active Canonical."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, DatasetKey, DatasetKind
from app.market_data.subing_d1_quality_candidates import (
    CandidatePreparationError,
    build_candidate_manifest,
    build_source_proof_index,
    prepare_replacement_candidate,
    verify_plan_input_files,
)
from app.market_data.subing_d1_quality_plan import validate_apply_binding
from app.models import MarketDataset, MarketPartition
from scripts.newow_weekly_recovery import load_private_readonly_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-env", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--evidence-refresh", type=Path, required=True)
    parser.add_argument("--source-complete", type=Path, required=True)
    parser.add_argument("--raw-evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    plan = _read_json(args.plan)
    validate_apply_binding(plan, args.expected_plan_sha256)
    verify_plan_input_files(plan, {
        "d1-17-source-diagnosis.json": args.diagnosis,
        "d1-17-source-evidence-refresh.json": args.evidence_refresh,
        "d1-17-source-verification-complete.json": args.source_complete,
    })
    expected_root = (
        PROJECT_ROOT / "data/canonical-candidates" / str(plan["plan_sha256"])
        / "raw-verified-v2"
    ).resolve()
    supplied_root = args.candidate_root.absolute()
    if supplied_root != expected_root or ".." in args.candidate_root.parts:
        raise CandidatePreparationError("CANDIDATE_ROOT_INVALID")
    supplied_root.mkdir(parents=True, exist_ok=True)
    if supplied_root.is_symlink():
        raise CandidatePreparationError("CANDIDATE_ROOT_INVALID")

    expected_output = (
        PROJECT_ROOT
        / "outputs/subing-four-period-readiness-20260918"
        / "d1-quality-segmentation-raw-verified-candidate-manifest.json"
    ).resolve()
    if args.output.absolute() != expected_output:
        raise CandidatePreparationError("CANDIDATE_MANIFEST_PATH_INVALID")

    refresh = _read_json(args.evidence_refresh)
    _read_json(args.source_complete)
    raw_evidence_root = args.raw_evidence_root.resolve(strict=True)
    proofs = build_source_proof_index(
        refresh, raw_evidence_root=raw_evidence_root
    )
    settings, _identity = load_private_readonly_settings(args.project_env)
    active_root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"]).resolve()
    if active_root == supplied_root or active_root in supplied_root.parents or supplied_root in active_root.parents:
        raise CandidatePreparationError("CANDIDATE_ROOT_INVALID")

    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    candidates: list[dict[str, Any]] = []
    try:
        with Session(engine) as session:
            with readonly_transaction(session):
                catalog = MarketCatalog(session, active_root)
                for target in plan["targets"]:
                    if target["operation"] != "REPLACE_EXISTING_PARTITION":
                        continue
                    year, month = (int(value) for value in target["month"].split("-"))
                    key = DatasetKey(
                        DatasetKind.CONTRACT,
                        target["symbol"],
                        target["contract"],
                        BarFrequency.D1,
                    )
                    partition = next(
                        (
                            item for item in catalog.all_partitions(key)
                            if item.year == year and item.month == month
                        ),
                        None,
                    )
                    if partition is None:
                        raise CandidatePreparationError("OLD_PARTITION_MISSING")
                    partition_id = session.scalar(
                        select(MarketPartition.id)
                        .join(MarketDataset, MarketPartition.dataset_id == MarketDataset.id)
                        .where(
                            MarketDataset.kind == key.kind.value,
                            MarketDataset.symbol == key.symbol,
                            MarketDataset.series_or_contract == key.series_or_contract,
                            MarketDataset.frequency == key.frequency.value,
                            MarketPartition.year == year,
                            MarketPartition.month == month,
                        )
                    )
                    if partition_id != target["partition_id"]:
                        raise CandidatePreparationError("OLD_PARTITION_ID_DRIFT")
                    try:
                        prepared = prepare_replacement_candidate(
                            target=target,
                            partition=partition,
                            active_root=active_root,
                            candidate_root=supplied_root,
                            proofs=proofs,
                        )
                    except CandidatePreparationError as exc:
                        if str(exc) == "SOURCE_PROOF_MISSING":
                            continue
                        raise
                    candidates.append(dict(prepared.manifest))
    finally:
        engine.dispose()

    relative_root = supplied_root.relative_to(PROJECT_ROOT).as_posix()
    manifest = build_candidate_manifest(
        plan=plan,
        candidate_root=relative_root,
        candidates=candidates,
    )
    _write_json_idempotent(expected_output, manifest)
    print(json.dumps({
        "state": manifest["state"],
        "parent_plan_sha256": manifest["parent_plan_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "frozen_candidate_count": manifest["frozen_candidate_count"],
        "blocked_target_count": manifest["blocked_target_count"],
        "provider_requests": 0,
        "production_writes": 0,
    }, ensure_ascii=False))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise CandidatePreparationError("CANDIDATE_INPUT_INVALID")
    return value


def _write_json_idempotent(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise CandidatePreparationError("CANDIDATE_MANIFEST_CONFLICT")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CandidatePreparationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
