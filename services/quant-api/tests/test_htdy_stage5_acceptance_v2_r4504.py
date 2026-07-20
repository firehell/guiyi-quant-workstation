from __future__ import annotations

from copy import deepcopy
import importlib
import json
from pathlib import Path
import shutil

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.backtest.htdy_trusted_report import file_sha256, packet_hash
from app.services.htdy_stage5_acceptance_v2 import (
    BLOCKED_GATE,
    CHECK_NAMES,
    CLOSEOUT_GATE,
    PIPELINE_READY_GATE,
    REJECTED_OUTCOME,
    R4501_PATH,
    R4502_PATH,
    R4503_PATH,
    STRATEGY_SOURCE_PATHS,
    X503_PATH,
    X506_PATH,
    X507_PATH,
    build_stage5_acceptance_v2,
    collect_immutable_input_hashes,
    collect_strategy_source_invariance,
    verify_acceptance_v2_packet,
    write_evidence_once,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIRS = (
    "htdy_trusted_backtest_candidate_x5_03",
    "htdy_oos_validation_x5_04",
    "htdy_rolling_oos_x5_05",
    "htdy_strategy_review_x5_06b",
    "htdy_stage5_acceptance_x5_07",
    "htdy_stage45_closeout_r45",
)


def _evidence_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    for name in REPORT_DIRS:
        shutil.copytree(REPO_ROOT / "data/reports" / name, reports / name)
    protocol = root / "configs/oos/htdy_strict_validation_protocol_v1.json"
    protocol.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / protocol.relative_to(root), protocol)
    for relative in STRATEGY_SOURCE_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return root


def _packet(root: Path, relative: Path) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _resign(root: Path, relative: Path, mutate) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    value.pop("packet_hash", None)
    value["packet_hash"] = packet_hash(value)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _db_snapshot(root: Path) -> dict:
    return deepcopy(_packet(root, R4502_PATH)["invariance"]["db_after"])


def _binding_snapshot(root: Path) -> dict:
    return deepcopy(_packet(root, X503_PATH)["execution_snapshot"])


def _strategy_proof(root: Path) -> dict:
    commit = _packet(root, X503_PATH)["source_commit"]
    files = {
        relative.as_posix(): {
            "baseline_sha256": file_sha256(root / relative),
            "current_sha256": file_sha256(root / relative),
        }
        for relative in STRATEGY_SOURCE_PATHS
    }
    return {"baseline_commit": commit, "unchanged": True, "files": files}


def _build(
    root: Path,
    *,
    db_before: dict | None = None,
    db_after: dict | None = None,
    binding_before: dict | None = None,
    binding_after: dict | None = None,
    immutable_before: dict[str, str] | None = None,
    immutable_after: dict[str, str] | None = None,
    strategy_proof: dict | None = None,
) -> dict:
    db = db_before if db_before is not None else _db_snapshot(root)
    binding = binding_before if binding_before is not None else _binding_snapshot(root)
    immutable = collect_immutable_input_hashes(root)
    return build_stage5_acceptance_v2(
        root,
        source_commit="a" * 40,
        db_before=db,
        db_after=db_after if db_after is not None else deepcopy(db),
        binding_before=binding,
        binding_after=binding_after if binding_after is not None else deepcopy(binding),
        immutable_hashes_before=(
            immutable_before if immutable_before is not None else immutable
        ),
        immutable_hashes_after=(
            immutable_after if immutable_after is not None else deepcopy(immutable)
        ),
        strategy_source_invariance=(
            strategy_proof if strategy_proof is not None else _strategy_proof(root)
        ),
    )


def test_current_real_evidence_closes_stage5_v2() -> None:
    x503 = _packet(REPO_ROOT, X503_PATH)
    strategy_proof = collect_strategy_source_invariance(
        REPO_ROOT,
        baseline_commit=x503["source_commit"],
    )

    result = _build(REPO_ROOT, strategy_proof=strategy_proof)

    assert result["status"] == "completed"
    assert result["pipeline_gate"] == PIPELINE_READY_GATE
    assert result["research_outcome"] == REJECTED_OUTCOME
    assert result["closeout_gate"] == CLOSEOUT_GATE
    assert result["markers"] == [PIPELINE_READY_GATE, REJECTED_OUTCOME, CLOSEOUT_GATE]
    assert set(result["checks"]) == set(CHECK_NAMES)
    assert all(check["status"] == "passed" for check in result["checks"].values())
    assert result["candidate_identity"]["report"]["id"] == 15
    assert result["database_invariance"]["unchanged"] is True
    assert result["strategy_source_invariance"]["unchanged"] is True
    assert verify_acceptance_v2_packet(result)


@pytest.mark.parametrize(
    "relative",
    [X503_PATH, X506_PATH, X507_PATH, R4501_PATH, R4502_PATH, R4503_PATH],
)
def test_missing_prerequisite_is_blocked(tmp_path: Path, relative: Path) -> None:
    root = _evidence_copy(tmp_path)
    immutable = collect_immutable_input_hashes(root)
    db = _db_snapshot(root)
    binding = _binding_snapshot(root)
    strategy = _strategy_proof(root)
    (root / relative).unlink()

    result = _build(
        root,
        db_before=db,
        db_after=deepcopy(db),
        binding_before=binding,
        binding_after=deepcopy(binding),
        immutable_before=immutable,
        immutable_after=immutable,
        strategy_proof=strategy,
    )

    assert result["status"] == "blocked"
    assert result["pipeline_gate"] == BLOCKED_GATE
    assert result["research_outcome"] is None
    assert result["closeout_gate"] is None
    assert result["markers"] == [BLOCKED_GATE]
    assert verify_acceptance_v2_packet(result)


@pytest.mark.parametrize("drift", ["candidate", "review", "r4501", "r4502", "r4503"])
def test_resigned_semantic_drift_is_blocked(tmp_path: Path, drift: str) -> None:
    root = _evidence_copy(tmp_path)
    if drift == "candidate":
        _resign(
            root,
            X503_PATH,
            lambda value: value["audits"]["candidate"].update(audit_status="failed"),
        )
    elif drift == "review":
        _resign(
            root,
            X506_PATH,
            lambda value: value["browser_smoke"].update(status="failed"),
        )
    elif drift == "r4501":
        _resign(
            root,
            R4501_PATH,
            lambda value: value.update(gate="STRATEGY_VALIDATION_BLOCKED"),
        )
    elif drift == "r4502":
        _resign(
            root,
            R4502_PATH,
            lambda value: value["structural_audit"].update(ordinary_events_strict_after=False),
        )
    else:
        _resign(
            root,
            R4503_PATH,
            lambda value: value.update(decision="PROPOSED_VALIDATED_RESEARCH_CANDIDATE"),
        )

    result = _build(root)

    assert result["status"] == "blocked"
    assert result["markers"] == [BLOCKED_GATE]


def test_database_or_binding_drift_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    db_after = _db_snapshot(root)
    db_after["candidate"]["trade_count"] += 1
    binding_after = _binding_snapshot(root)
    binding_after["market_data_file_id"] += 1

    db_result = _build(root, db_after=db_after)
    binding_result = _build(root, binding_after=binding_after)

    assert db_result["markers"] == [BLOCKED_GATE]
    assert binding_result["markers"] == [BLOCKED_GATE]


def test_strategy_or_immutable_input_drift_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    strategy = _strategy_proof(root)
    strategy["unchanged"] = False
    strategy["files"][next(iter(strategy["files"]))]["current_sha256"] = "f" * 64
    immutable = collect_immutable_input_hashes(root)
    changed = deepcopy(immutable)
    changed[next(iter(changed))] = "e" * 64

    strategy_result = _build(root, strategy_proof=strategy)
    immutable_result = _build(
        root,
        immutable_before=immutable,
        immutable_after=changed,
    )

    assert strategy_result["markers"] == [BLOCKED_GATE]
    assert immutable_result["markers"] == [BLOCKED_GATE]


def test_write_once_is_idempotent_and_refuses_different_packet(tmp_path: Path) -> None:
    packet = _build(REPO_ROOT, strategy_proof=_strategy_proof(REPO_ROOT))
    output = tmp_path / "acceptance"

    write_evidence_once(output, packet)
    write_evidence_once(output, packet)
    changed = deepcopy(packet)
    changed["source_commit"] = "b" * 40
    changed.pop("packet_hash")
    changed["packet_hash"] = packet_hash(changed)

    with pytest.raises(ValueError, match="refusing overwrite"):
        write_evidence_once(output, changed)
    assert json.loads((output / "STAGE5_ACCEPTANCE_V2.json").read_text()) == packet


def test_cli_has_fixed_output_and_no_argument_override() -> None:
    module = importlib.import_module("scripts.htdy_stage5_acceptance_v2")

    assert module.OUTPUT_DIR == (
        REPO_ROOT / "data/reports/htdy_stage5_acceptance_r45_v2"
    )
    assert not hasattr(module, "build_parser")


def test_cli_converts_database_connection_error_to_blocked_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("scripts.htdy_stage5_acceptance_v2")

    def unavailable_database() -> tuple[dict, dict]:
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path / "blocked")
    monkeypatch.setattr(module, "_database_state", unavailable_database)

    assert module.main() == 1
    packet = json.loads(
        (tmp_path / "blocked/STAGE5_ACCEPTANCE_V2.json").read_text(encoding="utf-8")
    )
    assert packet["markers"] == [BLOCKED_GATE]
    assert "database unavailable" in packet["blocked_reason"]
