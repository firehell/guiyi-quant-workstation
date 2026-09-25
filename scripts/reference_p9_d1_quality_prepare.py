#!/usr/bin/env python3
"""Prepare P9 SuBing D1 quality replacements outside production Canonical."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, DatasetKey, DatasetKind
from app.market_data.subing_d1_quality_candidates import (
    CandidatePreparationError,
    build_candidate_manifest,
    build_recovery_source_proof_index,
    prepare_replacement_candidate,
)
from app.market_data.subing_d1_quality_plan import build_p9_quality_plan
from app.models import MarketDataset, MarketPartition
from scripts.newow_weekly_recovery import load_private_readonly_settings


def _load_json(path: Path) -> tuple[dict, str]:
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
        raise CandidatePreparationError("P9_EVIDENCE_PATH_INVALID")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise CandidatePreparationError("P9_EVIDENCE_INVALID")
    return value, sha256(raw).hexdigest()


def _write_exclusive(path: Path, value: dict) -> None:
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise CandidatePreparationError("P9_OUTPUT_CONFLICT")
        return
    with path.open("xb") as output:
        output.write(content)


def _source_attempt_path_valid(project_root: Path, attempt: Path, attempt_id: str) -> bool:
    if re.fullmatch(r"p9-d1-source-20260925-[0-9]{3}", attempt_id) is None:
        return False
    expected = project_root / "outputs/reference-p9-d1-source-20260925" / attempt_id
    return (
        attempt.is_absolute() and attempt == expected
        and attempt.resolve(strict=True) == attempt and not attempt.is_symlink()
        and attempt.is_dir()
    )


def _validate_output_paths(
    project_root: Path,
    candidate_root: Path,
    output_root: Path,
    active_root: Path,
    plan_sha256: str,
) -> None:
    expected_output = project_root / "outputs/reference-p9-d1-quality-20260925"
    expected_candidate = (
        project_root / "data/canonical-candidates" / plan_sha256 / "attempt-001"
    )
    if (
        project_root.resolve(strict=True) != project_root
        or output_root != expected_output
        or output_root.resolve(strict=False) != output_root
    ):
        raise CandidatePreparationError("P9_OUTPUT_PATH_INVALID")
    if (
        candidate_root != expected_candidate
        or candidate_root.resolve(strict=False) != candidate_root
        or active_root == candidate_root
        or active_root in candidate_root.parents
        or candidate_root in active_root.parents
    ):
        raise CandidatePreparationError("P9_CANDIDATE_ROOT_INVALID")


def prepare(args: argparse.Namespace) -> dict[str, object]:
    inventory, inventory_sha = _load_json(args.quality_inventory)
    source, source_sha = _load_json(args.source_summary)
    candidate, candidate_sha = _load_json(args.source_candidate)
    plan = build_p9_quality_plan(inventory, source, inventory_sha, source_sha)
    if (
        plan["target_partition_count"] != 460
        or plan["product_count"] != 11
        or sum(len(item["affected_dates"]) for item in plan["targets"]) != 3113
        or candidate_sha != source["candidate_file_sha256"]
        or candidate.get("plan_sha256") != source["candidate_plan_sha256"]
        or not _source_attempt_path_valid(
            PROJECT_ROOT, args.source_attempt, source["attempt_id"],
        )
        or sha256((args.source_attempt / "journal.jsonl").read_bytes()).hexdigest()
        != source["journal_sha256"]
        or sha256((args.source_attempt / "source-only-result.json").read_bytes()).hexdigest()
        != source["result_sha256"]
    ):
        raise CandidatePreparationError("P9_SOURCE_BINDING_INVALID")
    proofs = build_recovery_source_proof_index(candidate, attempt=args.source_attempt)
    if (
        len(proofs) != 3113
        or any(proof.classification != "NONPOSITIVE_CLOSE_SOURCE_FACT" for proof in proofs.values())
    ):
        raise CandidatePreparationError("P9_SOURCE_PROOF_INVALID")

    settings, _identity = load_private_readonly_settings(args.project_env)
    active_root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"]).resolve(strict=True)
    _validate_output_paths(
        PROJECT_ROOT,
        args.candidate_root,
        args.output_root,
        active_root,
        plan["plan_sha256"],
    )
    expected_output = args.output_root
    expected_candidate = args.candidate_root
    expected_output.mkdir(parents=True, exist_ok=True)
    expected_candidate.parent.mkdir(parents=True, exist_ok=True)
    expected_candidate.mkdir(exist_ok=True)
    _write_exclusive(expected_output / "plan.json", plan)

    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    prepared = []
    try:
        with Session(engine) as session:
            with readonly_transaction(session):
                if (
                    session.scalar(text("SELECT current_database()")) != "guiyi_quant"
                    or session.scalar(text("SELECT version_num FROM alembic_version"))
                    != "20260919_0047"
                ):
                    raise CandidatePreparationError("P9_DATABASE_IDENTITY_DRIFT")
                catalog = MarketCatalog(session, active_root)
                partition_cache = {}
                for target in plan["targets"]:
                    symbol, contract = target["symbol"], target["contract"]
                    identity = (symbol, contract)
                    if identity not in partition_cache:
                        key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
                        partition_cache[identity] = {
                            (part.year, part.month): part
                            for part in catalog.all_partitions(key)
                        }
                    year, month = (int(value) for value in target["month"].split("-"))
                    partition = partition_cache[identity].get((year, month))
                    if partition is None:
                        raise CandidatePreparationError("P9_OLD_PARTITION_MISSING")
                    partition_id = session.scalar(
                        select(MarketPartition.id)
                        .join(MarketDataset, MarketPartition.dataset_id == MarketDataset.id)
                        .where(
                            MarketDataset.kind == "contract",
                            MarketDataset.symbol == symbol,
                            MarketDataset.series_or_contract == contract,
                            MarketDataset.frequency == "1d",
                            MarketPartition.year == year,
                            MarketPartition.month == month,
                        )
                    )
                    if partition_id != target["partition_id"]:
                        raise CandidatePreparationError("P9_OLD_PARTITION_ID_DRIFT")
                    prepared.append(dict(prepare_replacement_candidate(
                        target=target,
                        partition=partition,
                        active_root=active_root,
                        candidate_root=expected_candidate,
                        proofs=proofs,
                    ).manifest))
    finally:
        engine.dispose()

    manifest = build_candidate_manifest(
        plan=plan,
        candidate_root=expected_candidate.relative_to(PROJECT_ROOT).as_posix(),
        candidates=prepared,
        recovery_evidence={
            "source_candidate_plan_sha256": source["candidate_plan_sha256"],
            "source_journal_sha256": source["journal_sha256"],
            "source_result_sha256": source["result_sha256"],
        },
    )
    if manifest["state"] != "ALL_CANDIDATES_FROZEN":
        raise CandidatePreparationError("P9_CANDIDATES_INCOMPLETE")
    _write_exclusive(expected_output / "manifest.json", manifest)
    return {
        "status": "isolated_candidates_frozen",
        "plan_sha256": plan["plan_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "candidate_count": manifest["frozen_candidate_count"],
        "provider_requests": 0,
        "production_writes": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-env", type=Path, required=True)
    parser.add_argument("--quality-inventory", type=Path, required=True)
    parser.add_argument("--source-summary", type=Path, required=True)
    parser.add_argument("--source-candidate", type=Path, required=True)
    parser.add_argument("--source-attempt", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    try:
        value = prepare(parser.parse_args(argv))
    except (CandidatePreparationError, ValueError, OSError, json.JSONDecodeError) as error:
        code = str(error) if isinstance(error, CandidatePreparationError) else "P9_PREPARE_FAILED"
        print(json.dumps({"status": "blocked", "reason": code}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "P9_PREPARE_FAILED"}))
        return 1
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
