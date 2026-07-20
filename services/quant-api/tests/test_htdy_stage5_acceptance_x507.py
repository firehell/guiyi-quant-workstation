from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from app.services.htdy_stage5_acceptance import (
    BLOCKED_GATE,
    PIPELINE_READY_GATE,
    REJECTED_OUTCOME,
    VALIDATED_OUTCOME,
    build_stage5_acceptance,
    decide_stage5_outcome,
    verify_acceptance_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIRS = (
    "htdy_trusted_backtest_candidate_x5_03",
    "htdy_oos_validation_x5_04",
    "htdy_rolling_oos_x5_05",
    "htdy_strategy_review_x5_06b",
)


def _evidence_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    for name in REPORT_DIRS:
        shutil.copytree(REPO_ROOT / "data/reports" / name, reports / name)
    return root


def test_real_rejected_stage5_evidence_closes_pipeline() -> None:
    packet = build_stage5_acceptance(REPO_ROOT, source_commit="a" * 40)

    assert packet["gate"] == PIPELINE_READY_GATE
    assert packet["research_outcome"] == REJECTED_OUTCOME
    assert packet["x504_gate"] == "OOS_HARD_REJECT_TRIGGERED"
    assert packet["x505_label"] == "DIAGNOSTIC_CONFIRMS_REJECTION"
    assert packet["x506_gate"] == "STRATEGY_REVIEW_CLOSED_LOOP_READY"
    assert packet["report14_regression"]["status"] == "passed"
    assert packet["report14_regression"]["consistency_hash"] == (
        "2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a"
    )
    assert verify_acceptance_packet(packet)


def test_validated_decision_requires_all_positive_labels() -> None:
    gate, outcome = decide_stage5_outcome(
        x504_gate="OOS_VALIDATION_EXECUTED",
        x505_label="PROPOSED_VALIDATED_RESEARCH_CANDIDATE",
        x506_gate="STRATEGY_REVIEW_CLOSED_LOOP_READY",
    )
    assert gate == PIPELINE_READY_GATE
    assert outcome == VALIDATED_OUTCOME


def test_rolling_blocked_has_priority_over_x504_hard_reject() -> None:
    gate, outcome = decide_stage5_outcome(
        x504_gate="OOS_HARD_REJECT_TRIGGERED",
        x505_label="STRATEGY_VALIDATION_BLOCKED",
        x506_gate="STRATEGY_REVIEW_CLOSED_LOOP_READY",
    )

    assert gate == BLOCKED_GATE
    assert outcome is None


@pytest.mark.parametrize(
    ("x504_gate", "x505_label"),
    [
        ("OOS_HARD_REJECT_TRIGGERED", "DIAGNOSTIC_CONFIRMS_REJECTION"),
        ("OOS_VALIDATION_EXECUTED", "PROPOSED_REJECTED_RESEARCH_CANDIDATE"),
        ("OOS_HARD_REJECT_TRIGGERED", "DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS"),
    ],
)
def test_rejection_and_diagnostic_labels_remain_rejected(
    x504_gate: str,
    x505_label: str,
) -> None:
    gate, outcome = decide_stage5_outcome(
        x504_gate=x504_gate,
        x505_label=x505_label,
        x506_gate="STRATEGY_REVIEW_CLOSED_LOOP_READY",
    )
    assert gate == PIPELINE_READY_GATE
    assert outcome == REJECTED_OUTCOME


def test_missing_evidence_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    (root / "data/reports/htdy_strategy_review_x5_06b/STRATEGY_REVIEW_CLOSED_LOOP_READY.json").unlink()

    packet = build_stage5_acceptance(root, source_commit="b" * 40)

    assert packet["gate"] == BLOCKED_GATE
    assert packet["research_outcome"] is None
    assert "missing" in packet["blocked_reason"].lower()
    assert verify_acceptance_packet(packet)


def test_tampered_hash_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    path = root / "data/reports/htdy_oos_validation_x5_04/oos_fixed_result.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"]["trade_count"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    packet = build_stage5_acceptance(root, source_commit="c" * 40)

    assert packet["gate"] == BLOCKED_GATE
    assert packet["research_outcome"] is None
    assert "hash" in packet["blocked_reason"].lower()


def test_review_gate_not_ready_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    path = root / "data/reports/htdy_strategy_review_x5_06b/STRATEGY_REVIEW_CLOSED_LOOP_READY.json"
    packet = json.loads(path.read_text(encoding="utf-8"))
    packet["gate"] = "STRATEGY_REVIEW_CLOSED_LOOP_BLOCKED"
    packet_without_hash = deepcopy(packet)
    packet_without_hash.pop("packet_hash")
    from app.backtest.htdy_trusted_report import packet_hash

    packet["packet_hash"] = packet_hash(packet_without_hash)
    path.write_text(json.dumps(packet), encoding="utf-8")

    result = build_stage5_acceptance(root, source_commit="d" * 40)

    assert result["gate"] == BLOCKED_GATE
    assert result["research_outcome"] is None
    assert "x5-06b" in result["blocked_reason"].lower()


def test_packet_hash_detects_acceptance_tampering() -> None:
    packet = build_stage5_acceptance(REPO_ROOT, source_commit="e" * 40)
    assert verify_acceptance_packet(packet)
    packet["research_outcome"] = VALIDATED_OUTCOME
    assert not verify_acceptance_packet(packet)
