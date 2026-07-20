from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from app.backtest.htdy_rolling_decision_recheck import (
    BLOCKED_DECISION,
    CURRENT_REJECTION_GATE,
    READY_GATE,
    X504_PACKET_PATH,
    X505_PACKET_PATH,
    X507_PACKET_PATH,
    build_rolling_decision_recheck,
    file_sha256,
    immutable_input_hashes,
    packet_hash,
    verify_packet_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
FOLD_IDS = (
    "walk_forward_a_test",
    "walk_forward_b_test",
    "walk_forward_c_test",
)


def _evidence_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "configs/oos").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "configs/oos/htdy_strict_validation_protocol_v1.json",
        root / "configs/oos/htdy_strict_validation_protocol_v1.json",
    )
    for name in (
        "htdy_oos_validation_x5_04",
        "htdy_rolling_oos_x5_05",
        "htdy_stage5_acceptance_x5_07",
    ):
        shutil.copytree(REPO_ROOT / "data/reports" / name, root / "data/reports" / name)
    return root


def _resign_fold(root: Path, fold_id: str, artifact_name: str) -> None:
    fold_dir = root / "data/reports/htdy_rolling_oos_x5_05/folds" / fold_id
    manifest_path = fold_dir / "fold_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][artifact_name] = file_sha256(fold_dir / artifact_name)
    manifest.pop("fold_hash", None)
    manifest["fold_hash"] = packet_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    packet_path = root / X505_PACKET_PATH
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["fold_artifacts"][fold_id]["sha256"] = manifest["fold_hash"]
    packet.pop("packet_hash", None)
    packet["packet_hash"] = packet_hash(packet)
    packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")

    x507_path = root / X507_PACKET_PATH
    x507 = json.loads(x507_path.read_text(encoding="utf-8"))
    x507["evidence_hashes"]["x505_packet_hash"] = packet["packet_hash"]
    x507["evidence_hashes"]["packet_file_sha256"]["x505"] = file_sha256(packet_path)
    x507.pop("packet_hash", None)
    x507["packet_hash"] = packet_hash(x507)
    x507_path.write_text(json.dumps(x507, sort_keys=True), encoding="utf-8")


def test_current_real_folds_preserve_diagnostic_rejection_and_original_files() -> None:
    before = immutable_input_hashes(REPO_ROOT)

    packet = build_rolling_decision_recheck(
        REPO_ROOT,
        source_commit="d5891c6b1dfd7ad626ad5c47392828939e8dd8c0",
        immutable_hashes_before=before,
        immutable_hashes_after=immutable_input_hashes(REPO_ROOT),
    )

    assert packet["status"] == "completed"
    assert packet["gates"] == [READY_GATE, CURRENT_REJECTION_GATE]
    assert packet["decision"] == "DIAGNOSTIC_CONFIRMS_REJECTION"
    assert packet["x504_hard_reject_preserved"] is True
    assert [fold["fold_id"] for fold in packet["folds"]] == list(FOLD_IDS)
    assert all(fold["audit_status"] == "passed" for fold in packet["folds"])
    assert all(fold["structural_reasons"] == [] for fold in packet["folds"])
    assert all(fold["numeric_reasons"] for fold in packet["folds"])
    assert immutable_input_hashes(REPO_ROOT) == before
    assert verify_packet_hash(packet)


def test_missing_or_tampered_artifact_is_blocked(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)
    artifact = root / "data/reports/htdy_rolling_oos_x5_05/folds/walk_forward_a_test/result.json"
    artifact.write_text("{}", encoding="utf-8")

    packet = build_rolling_decision_recheck(root, source_commit="a" * 40)

    assert packet["status"] == "blocked"
    assert packet["decision"] == BLOCKED_DECISION
    assert "artifact hash" in packet["blocked_reason"]


@pytest.mark.parametrize("drift", ["binding", "config", "cost"])
def test_semantic_drift_is_blocked_even_when_artifacts_are_resigned(
    tmp_path: Path,
    drift: str,
) -> None:
    root = _evidence_copy(tmp_path)
    fold_id = FOLD_IDS[0]
    fold_dir = root / "data/reports/htdy_rolling_oos_x5_05/folds" / fold_id
    if drift == "binding":
        filename = "binding_snapshot.json"
        payload = json.loads((fold_dir / filename).read_text(encoding="utf-8"))
        payload["market_data_file_id"] += 1
    elif drift == "config":
        filename = "config_snapshot.json"
        payload = json.loads((fold_dir / filename).read_text(encoding="utf-8"))
        payload["parameter_hash"] = "f" * 64
    else:
        filename = "cost_timeline.json"
        payload = json.loads((fold_dir / filename).read_text(encoding="utf-8"))
        payload["rows"].pop()
        payload["row_count"] = len(payload["rows"])
        payload["timeline_hash"] = packet_hash(payload["rows"])
    (fold_dir / filename).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _resign_fold(root, fold_id, filename)

    packet = build_rolling_decision_recheck(root, source_commit="b" * 40)

    assert packet["status"] == "blocked"
    assert packet["decision"] == BLOCKED_DECISION
    assert drift in packet["blocked_reason"] or "cost timeline" in packet["blocked_reason"]


def test_x504_hard_reject_and_x507_rejection_cannot_be_flipped(tmp_path: Path) -> None:
    root = _evidence_copy(tmp_path)

    packet = build_rolling_decision_recheck(root, source_commit="c" * 40)

    assert packet["status"] == "completed"
    assert packet["decision"] == "DIAGNOSTIC_CONFIRMS_REJECTION"
    assert packet["x504_hard_reject_preserved"] is True
    assert packet["original_x507"]["research_outcome"] == "REJECTED_RESEARCH_CANDIDATE"


def test_packet_path_constants_are_fixed_to_original_evidence() -> None:
    assert X504_PACKET_PATH.as_posix().startswith("data/reports/htdy_oos_validation_x5_04/")
    assert X505_PACKET_PATH.as_posix().startswith("data/reports/htdy_rolling_oos_x5_05/")
    assert X507_PACKET_PATH.as_posix().startswith("data/reports/htdy_stage5_acceptance_x5_07/")
