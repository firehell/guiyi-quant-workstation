from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from app.backtest.htdy_oos_validation import evaluate_hard_reject
from app.backtest.htdy_rolling_oos import (
    BLOCKED_DECISION,
    CONFIRMS_REJECTION,
    FOLD_IDS,
    MODE,
    load_x504_packet,
    proposal_label,
)
from app.backtest.htdy_trusted_report import file_sha256, packet_hash
from app.services.htdy_stage5_acceptance import (
    PIPELINE_READY_GATE,
    REJECTED_OUTCOME,
    decide_stage5_outcome,
)


TASK_ID = "TASK-HTDY-ROLLING-OOS-DECISION-SEMANTICS-R4503"
READY_GATE = "ROLLING_OOS_DECISION_SEMANTICS_READY"
CURRENT_REJECTION_GATE = "CURRENT_HTDY_DIAGNOSTIC_REJECTION_PRESERVED"
PROTOCOL_PATH = Path("configs/oos/htdy_strict_validation_protocol_v1.json")
X504_PACKET_PATH = Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json")
X505_PACKET_PATH = Path(
    "data/reports/htdy_rolling_oos_x5_05/ROLLING_OOS_VALIDATION_RESULT.json"
)
X507_PACKET_PATH = Path(
    "data/reports/htdy_stage5_acceptance_x5_07/STAGE5_ACCEPTANCE_PACKET.json"
)
X505_ARTIFACT_NAMES = {
    "audit.json",
    "binding_snapshot.json",
    "config_snapshot.json",
    "cost_margin_overlays.json",
    "cost_timeline.json",
    "diagnostics.json",
    "result.json",
}


class RollingDecisionEvidenceError(ValueError):
    """Fail-closed error for drifted rolling OOS decision evidence."""


def verify_packet_hash(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def immutable_input_hashes(repo_root: Path) -> dict[str, str]:
    root = repo_root.expanduser().resolve()
    paths = [root / PROTOCOL_PATH, root / X504_PACKET_PATH, root / X507_PACKET_PATH]
    x504 = _read_json(root / X504_PACKET_PATH)
    for artifact in (x504.get("artifacts") or {}).values():
        filename = str((artifact or {}).get("path") or "")
        if not filename or Path(filename).name != filename:
            raise RollingDecisionEvidenceError("X5-04 artifact path is invalid")
        paths.append((root / X504_PACKET_PATH).parent / filename)
    x505_dir = (root / X505_PACKET_PATH).parent
    if not x505_dir.is_dir():
        raise RollingDecisionEvidenceError("X5-05 evidence directory is missing")
    paths.extend(path for path in x505_dir.rglob("*") if path.is_file())
    hashes: dict[str, str] = {}
    for path in sorted(set(paths)):
        if not path.is_file():
            raise RollingDecisionEvidenceError(f"immutable input is missing: {path.name}")
        hashes[path.relative_to(root).as_posix()] = file_sha256(path)
    return hashes


def build_rolling_decision_recheck(
    repo_root: Path,
    *,
    source_commit: str,
    immutable_hashes_before: Mapping[str, str] | None = None,
    immutable_hashes_after: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    before = dict(immutable_hashes_before or immutable_input_hashes(root))
    try:
        evidence = _load_evidence(root)
        after = dict(immutable_hashes_after or immutable_input_hashes(root))
        if before != after:
            raise RollingDecisionEvidenceError("immutable original evidence changed during recheck")
        decision = proposal_label(
            x504_gate=str(evidence["x504"].get("gate")),
            folds=evidence["folds"],
        )
        if decision == BLOCKED_DECISION:
            raise RollingDecisionEvidenceError("rolling decision is structurally blocked")
        if decision != CONFIRMS_REJECTION:
            raise RollingDecisionEvidenceError(
                "current real folds no longer confirm the frozen X5-04 rejection"
            )
        x507_gate, x507_outcome = decide_stage5_outcome(
            x504_gate=str(evidence["x504"].get("gate")),
            x505_label=decision,
            x506_gate="STRATEGY_REVIEW_CLOSED_LOOP_READY",
        )
        if x507_gate != PIPELINE_READY_GATE or x507_outcome != REJECTED_OUTCOME:
            raise RollingDecisionEvidenceError("X5-07 decision recheck did not preserve rejection")
        packet: dict[str, Any] = {
            "schema_version": "htdy_rolling_decision_recheck_r4503_v1",
            "task_id": TASK_ID,
            "status": "completed",
            "gates": [READY_GATE, CURRENT_REJECTION_GATE],
            "decision": decision,
            "source_commit": source_commit,
            "x504_hard_reject_preserved": True,
            "original_x504": _packet_identity(evidence["x504"], root / X504_PACKET_PATH),
            "original_x505": _packet_identity(evidence["x505"], root / X505_PACKET_PATH),
            "original_x507": {
                **_packet_identity(evidence["x507"], root / X507_PACKET_PATH),
                "gate": evidence["x507"].get("gate"),
                "research_outcome": evidence["x507"].get("research_outcome"),
            },
            "folds": deepcopy(evidence["folds"]),
            "x507_decision_recheck": {
                "gate": x507_gate,
                "research_outcome": x507_outcome,
                "rolling_blocked_precedence": "verified_by_unit_test",
            },
            "immutable_input_sha256": after,
            "boundaries": {
                "original_x5_packet_overwritten": False,
                "strategy_rerun": False,
                "canonical_database_write": False,
                "profile_binding_write": False,
                "parquet_write": False,
                "strategy_or_parameter_changed": False,
                "x504_hard_reject_flipped": False,
            },
            "blocked_reason": None,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        packet = _blocked_packet(source_commit=source_commit, reason=_sanitize_reason(exc))
    packet["packet_hash"] = packet_hash(packet)
    return packet


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# HTDY R45-03 Rolling OOS Decision Recheck",
        "",
        f"- Status: `{packet.get('status')}`",
        f"- Decision: `{packet.get('decision')}`",
    ]
    for gate in packet.get("gates") or []:
        lines.append(f"- Gate: `{gate}`")
    if packet.get("blocked_reason"):
        lines.append(f"- Blocked reason: `{packet.get('blocked_reason')}`")
    lines.extend(
        [
            "",
            "Original X5-04/X5-05/X5-07 evidence is read-only and hash-bound.",
            "Structural failure is blocked; only numeric failure after structural pass is rejected.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_evidence(root: Path) -> dict[str, Any]:
    protocol_path = root / PROTOCOL_PATH
    protocol = _read_json(protocol_path)
    protocol_hash = file_sha256(protocol_path)
    x504 = load_x504_packet(root)
    x505_path = root / X505_PACKET_PATH
    x505 = _load_packet(x505_path, "X5-05")
    x507 = _load_packet(root / X507_PACKET_PATH, "X5-07")
    if x504.get("gate") != "OOS_HARD_REJECT_TRIGGERED":
        raise RollingDecisionEvidenceError("X5-04 hard reject is not preserved")
    if x505.get("x504_packet_hash") != x504.get("packet_hash"):
        raise RollingDecisionEvidenceError("X5-05 X5-04 packet hash drift")
    if x505.get("protocol_hash") != protocol_hash or x504.get("protocol_hash") != protocol_hash:
        raise RollingDecisionEvidenceError("protocol hash drift")
    parameter_hash = protocol.get("parameter_hash")
    if x505.get("parameter_hash") != parameter_hash or x504.get("parameter_hash") != parameter_hash:
        raise RollingDecisionEvidenceError("parameter hash drift")
    if x505.get("candidate_identity") != x504.get("candidate_identity"):
        raise RollingDecisionEvidenceError("candidate identity drift")
    if x507.get("gate") != PIPELINE_READY_GATE or x507.get("research_outcome") != REJECTED_OUTCOME:
        raise RollingDecisionEvidenceError("original X5-07 rejection is not intact")
    x507_hashes = x507.get("evidence_hashes") or {}
    if x507_hashes.get("x504_packet_hash") != x504.get("packet_hash"):
        raise RollingDecisionEvidenceError("X5-07 X5-04 identity drift")
    if x507_hashes.get("x505_packet_hash") != x505.get("packet_hash"):
        raise RollingDecisionEvidenceError("X5-07 X5-05 identity drift")
    summaries = list(x505.get("folds") or [])
    if [summary.get("fold_id") for summary in summaries] != list(FOLD_IDS):
        raise RollingDecisionEvidenceError("required fold set or order is invalid")
    folds = [
        _load_fold(
            x505_path.parent,
            summary=summary,
            x505=x505,
            x504=x504,
            protocol=protocol,
        )
        for summary in summaries
    ]
    return {"protocol": protocol, "x504": x504, "x505": x505, "x507": x507, "folds": folds}


def _load_fold(
    x505_dir: Path,
    *,
    summary: Mapping[str, Any],
    x505: Mapping[str, Any],
    x504: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    fold_id = str(summary.get("fold_id") or "")
    fold_dir = x505_dir / "folds" / fold_id
    manifest = _read_json(fold_dir / "fold_manifest.json")
    manifest_payload = dict(manifest)
    manifest_hash = str(manifest_payload.pop("fold_hash", ""))
    expected_fold_hash = str(
        ((x505.get("fold_artifacts") or {}).get(fold_id) or {}).get("sha256") or ""
    )
    if not manifest_hash or packet_hash(manifest_payload) != manifest_hash:
        raise RollingDecisionEvidenceError(f"manifest hash invalid: {fold_id}")
    if expected_fold_hash != manifest_hash:
        raise RollingDecisionEvidenceError(f"top-level fold hash invalid: {fold_id}")
    artifacts = dict(manifest.get("artifacts") or {})
    if set(artifacts) != X505_ARTIFACT_NAMES:
        raise RollingDecisionEvidenceError(f"artifact set invalid: {fold_id}")
    payloads: dict[str, dict[str, Any]] = {}
    for filename, expected_hash in artifacts.items():
        if Path(filename).name != filename:
            raise RollingDecisionEvidenceError(f"artifact path invalid: {fold_id}")
        path = fold_dir / filename
        if not path.is_file() or file_sha256(path) != expected_hash:
            raise RollingDecisionEvidenceError(f"artifact hash invalid: {fold_id}/{filename}")
        payloads[filename] = _read_json(path)
    _validate_fold_payloads(
        fold_id,
        summary=summary,
        manifest=manifest,
        payloads=payloads,
        x505=x505,
        x504=x504,
        protocol=protocol,
    )
    return {
        "fold_id": fold_id,
        "status": summary.get("status"),
        "audit_status": summary.get("audit_status"),
        "trade_count": summary.get("trade_count"),
        "total_return_pct": summary.get("total_return_pct"),
        "numeric_reasons": list(summary.get("numeric_reasons") or []),
        "structural_reasons": list(summary.get("structural_reasons") or []),
        "fold_hash": manifest_hash,
        "artifact_sha256": artifacts,
    }


def _validate_fold_payloads(
    fold_id: str,
    *,
    summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
    payloads: Mapping[str, Mapping[str, Any]],
    x505: Mapping[str, Any],
    x504: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    audit = payloads["audit.json"]
    config = payloads["config_snapshot.json"]
    binding = payloads["binding_snapshot.json"]
    cost = payloads["cost_timeline.json"]
    result = payloads["result.json"]
    decision_fields = (
        "fold_id",
        "status",
        "audit_status",
        "trade_count",
        "total_return_pct",
        "numeric_reasons",
        "structural_reasons",
    )
    if any(summary.get(key) != manifest.get(key) for key in decision_fields):
        raise RollingDecisionEvidenceError(f"fold summary/manifest drift: {fold_id}")
    if result.get("status") != "executed" or result.get("fold_id") != fold_id:
        raise RollingDecisionEvidenceError(f"fold execution status invalid: {fold_id}")
    if summary.get("status") != "completed":
        raise RollingDecisionEvidenceError(f"fold execution exception or failure: {fold_id}")
    if audit.get("audit_status") != summary.get("audit_status"):
        raise RollingDecisionEvidenceError(f"fold audit status drift: {fold_id}")
    if audit.get("structural_reasons") != summary.get("structural_reasons"):
        raise RollingDecisionEvidenceError(f"fold structural reasons drift: {fold_id}")
    if audit.get("numeric_reasons") != summary.get("numeric_reasons"):
        raise RollingDecisionEvidenceError(f"fold numeric reasons drift: {fold_id}")
    if summary.get("audit_status") != "passed" or summary.get("structural_reasons"):
        raise RollingDecisionEvidenceError(f"fold structural audit blocked: {fold_id}")
    if config.get("fold_id") != fold_id or config.get("mode") != MODE:
        raise RollingDecisionEvidenceError(f"config fold identity drift: {fold_id}")
    if config.get("protocol_hash") != x505.get("protocol_hash"):
        raise RollingDecisionEvidenceError(f"config protocol drift: {fold_id}")
    if config.get("parameter_hash") != x505.get("parameter_hash"):
        raise RollingDecisionEvidenceError(f"config parameter drift: {fold_id}")
    if config.get("confirmed_only") is not True or config.get("execution_timing") != "next_bar_open":
        raise RollingDecisionEvidenceError(f"config execution policy drift: {fold_id}")
    expected_binding = dict(x504.get("data_identity") or {})
    for key in (
        "profile_id",
        "profile_active_binding_id",
        "market_data_file_id",
        "data_version",
        "file_sha256",
        "quality_status",
        "quality_policy",
    ):
        if binding.get(key) != expected_binding.get(key):
            raise RollingDecisionEvidenceError(f"binding drift: {fold_id}/{key}")
    if binding.get("binding_status") != "active":
        raise RollingDecisionEvidenceError(f"binding status drift: {fold_id}")
    if binding.get("snapshot_hash") != x504.get("execution_snapshot_hash"):
        raise RollingDecisionEvidenceError(f"binding snapshot hash drift: {fold_id}")
    if result.get("protocol_hash") != x505.get("protocol_hash"):
        raise RollingDecisionEvidenceError(f"result protocol drift: {fold_id}")
    if result.get("parameter_hash") != x505.get("parameter_hash"):
        raise RollingDecisionEvidenceError(f"result parameter drift: {fold_id}")
    if result.get("execution_snapshot_hash") != x504.get("execution_snapshot_hash"):
        raise RollingDecisionEvidenceError(f"result binding hash drift: {fold_id}")
    data = dict(result.get("data") or {})
    trading_days = list(data.get("trading_days") or [])
    cost_rows = list(cost.get("rows") or [])
    cost_days = [str(row.get("trading_day")) for row in cost_rows]
    if (
        cost.get("row_count") != len(cost_rows)
        or set(cost_days) != set(trading_days)
        or len(cost_days) != len(set(cost_days))
        or cost.get("timeline_hash") != packet_hash(cost_rows)
    ):
        raise RollingDecisionEvidenceError(f"cost timeline incomplete: {fold_id}")
    recomputed_numeric = evaluate_hard_reject(
        result.get("summary") or {},
        protocol["hard_reject_criteria"]["oos_fixed_any_of"],
    )
    if recomputed_numeric != summary.get("numeric_reasons"):
        raise RollingDecisionEvidenceError(f"numeric reasons drift: {fold_id}")


def _load_packet(path: Path, name: str) -> dict[str, Any]:
    value = _read_json(path)
    if not verify_packet_hash(value):
        raise RollingDecisionEvidenceError(f"{name} packet hash invalid")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RollingDecisionEvidenceError(f"evidence is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RollingDecisionEvidenceError(f"evidence is not an object: {path.name}")
    return value


def _packet_identity(packet: Mapping[str, Any], path: Path) -> dict[str, Any]:
    return {
        "relative_path": path.as_posix().split("data/reports/", 1)[-1],
        "file_sha256": file_sha256(path),
        "packet_hash": packet.get("packet_hash"),
        "proposal_label": packet.get("proposal_label"),
    }


def _blocked_packet(*, source_commit: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "htdy_rolling_decision_recheck_r4503_v1",
        "task_id": TASK_ID,
        "status": "blocked",
        "gates": [],
        "decision": BLOCKED_DECISION,
        "source_commit": source_commit,
        "x504_hard_reject_preserved": True,
        "blocked_reason": reason,
        "boundaries": {
            "original_x5_packet_overwritten": False,
            "strategy_rerun": False,
            "canonical_database_write": False,
            "profile_binding_write": False,
            "parquet_write": False,
            "strategy_or_parameter_changed": False,
            "x504_hard_reject_flipped": False,
        },
    }


def _sanitize_reason(exc: BaseException) -> str:
    text = str(exc).replace("\\", "/")
    safe = [Path(part).name if "/" in part else part for part in text.split()]
    return " ".join(safe)[:500] or exc.__class__.__name__


__all__ = [
    "BLOCKED_DECISION",
    "CURRENT_REJECTION_GATE",
    "READY_GATE",
    "RollingDecisionEvidenceError",
    "X504_PACKET_PATH",
    "X505_PACKET_PATH",
    "X507_PACKET_PATH",
    "build_rolling_decision_recheck",
    "file_sha256",
    "immutable_input_hashes",
    "packet_hash",
    "render_markdown",
    "verify_packet_hash",
]
