from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from app.backtest.htdy_trusted_report import file_sha256, packet_hash


SCHEMA_VERSION = "backtest_validation_context_x506b_v1"
X503_PACKET = Path(
    "data/reports/htdy_trusted_backtest_candidate_x5_03/"
    "HTDY_TRUSTED_BACKTEST_CANDIDATE.json"
)
X504_PACKET = Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json")
X505_PACKET = Path(
    "data/reports/htdy_rolling_oos_x5_05/ROLLING_OOS_VALIDATION_RESULT.json"
)
FOLD_IDS = (
    "walk_forward_a_test",
    "walk_forward_b_test",
    "walk_forward_c_test",
)
X503_ARTIFACTS = {
    "candidate_audit": "candidate_trust_audit.json",
    "report14_audit": "report14_trust_audit.json",
    "row_count_hash": "candidate_row_count_hash.json",
}
X505_ARTIFACT_NAMES = {
    "audit.json",
    "binding_snapshot.json",
    "config_snapshot.json",
    "cost_margin_overlays.json",
    "cost_timeline.json",
    "diagnostics.json",
    "result.json",
}


class BacktestValidationEvidenceError(ValueError):
    """Fail-closed error for missing, drifted, or mismatched Stage 5 evidence."""


def verify_context_hash(context: Mapping[str, Any]) -> bool:
    payload = dict(context)
    expected = str(payload.pop("context_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def build_backtest_validation_context(
    repo_root: Path,
    *,
    report_identity: Mapping[str, Any],
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    x503_path = root / X503_PACKET
    x504_path = root / X504_PACKET
    x505_path = root / X505_PACKET
    x503 = _load_packet(x503_path, expected_gate="HTDY_TRUSTED_BACKTEST_CANDIDATE")
    _verify_x503_artifacts(x503_path.parent, x503)
    x504 = _load_packet(x504_path, expected_gate=None)
    _verify_x504_artifacts(x504_path.parent, x504)
    x505 = _load_packet(x505_path, expected_gate=None)
    folds = _load_x505_folds(x505_path.parent, x505)
    _verify_identities(report_identity=report_identity, x503=x503, x504=x504, x505=x505, folds=folds)

    oos_artifact = x504["artifacts"]["window_result"]
    oos_result = _read_json(x504_path.parent / str(oos_artifact["path"]))
    oos_summary = dict(oos_result.get("summary") or {})
    oos_metrics = _selected_metrics(oos_summary)
    hard_reject = deepcopy(x504.get("hard_reject") or {})
    hard_reject_reasons = [
        *list(hard_reject.get("structural_reasons") or []),
        *list(hard_reject.get("numeric_reasons") or []),
    ]
    fold_contexts = [_fold_context(item) for item in folds]
    candidate_identity = deepcopy(x503["candidate_identity"])
    candidate_audit = x503.get("audits") or {}
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_id": int(report_identity["id"]),
        "candidate_status": "oos_hard_rejected",
        "review_skip_status": "SKIPPED_BY_FROZEN_HARD_REJECT",
        "candidate": {
            **candidate_identity,
            "gate": x503["gate"],
            "status": x503.get("status"),
            "candidate_trust_audit": (candidate_audit.get("candidate") or {}).get("audit_status"),
            "report14_trust_audit": (candidate_audit.get("report14") or {}).get("audit_status"),
            "consistency_hash": (x503.get("formal_lineage") or {}).get("consistency_hash"),
        },
        "oos": {
            "window_id": x504.get("window_id"),
            "gate": x504.get("gate"),
            "metrics": oos_metrics,
            "row_counts": deepcopy(x504.get("row_counts") or {}),
            "hard_reject": hard_reject,
        },
        "rolling_oos": {
            "mode": x505.get("mode"),
            "proposal_label": x505.get("proposal_label"),
            "x504_hard_reject_preserved": x505.get("x504_hard_reject_preserved"),
            "folds": fold_contexts,
        },
        "hard_reject_reason": "; ".join(str(reason) for reason in hard_reject_reasons),
        "binding_identity": _binding_identity(x503.get("execution_snapshot") or {}),
        "policy": {
            "protocol_hash": x503.get("protocol_hash"),
            "parameter_hash": x503.get("parameter_hash"),
            "indicator_policy_snapshot": deepcopy(x503.get("policy_snapshot") or {}),
            "cost_model": deepcopy(x503.get("cost_model") or {}),
        },
        "evidence_hashes": {
            "x503_packet_hash": x503.get("packet_hash"),
            "x504_packet_hash": x504.get("packet_hash"),
            "x505_packet_hash": x505.get("packet_hash"),
            "x504_result_hash": x504.get("result_hash"),
            "x504_trust_audit_hash": x504.get("trust_audit_hash"),
            "x505_fold_hashes": {
                item["fold_id"]: item["manifest"]["fold_hash"] for item in folds
            },
        },
        "source_policy": {
            "fixed_evidence_directories_only": True,
            "arbitrary_file_path_accepted": False,
            "original_report_mutated": False,
            "frontend_strategy_recomputed": False,
        },
    }
    packet["context_hash"] = packet_hash(packet)
    return packet


def _load_packet(path: Path, *, expected_gate: str | None) -> dict[str, Any]:
    packet = _read_json(path)
    payload = dict(packet)
    expected_hash = str(payload.pop("packet_hash", ""))
    if not expected_hash or packet_hash(payload) != expected_hash:
        raise BacktestValidationEvidenceError(f"packet hash invalid: {path.name}")
    if expected_gate is not None and packet.get("gate") != expected_gate:
        raise BacktestValidationEvidenceError(f"Gate invalid: {path.name}")
    return packet


def _verify_x503_artifacts(directory: Path, packet: Mapping[str, Any]) -> None:
    artifacts = packet.get("artifacts") or {}
    for key, filename in X503_ARTIFACTS.items():
        expected = str((artifacts.get(key) or {}).get("sha256") or "")
        path = directory / filename
        if not expected or not path.is_file() or file_sha256(path) != expected:
            raise BacktestValidationEvidenceError(f"X5-03 artifact hash invalid: {key}")


def _verify_x504_artifacts(directory: Path, packet: Mapping[str, Any]) -> None:
    if packet.get("gate") not in {"OOS_VALIDATION_EXECUTED", "OOS_HARD_REJECT_TRIGGERED"}:
        raise BacktestValidationEvidenceError("X5-04 Gate invalid")
    for key, artifact in (packet.get("artifacts") or {}).items():
        filename = str((artifact or {}).get("path") or "")
        if not filename or Path(filename).name != filename:
            raise BacktestValidationEvidenceError(f"X5-04 artifact path invalid: {key}")
        path = directory / filename
        if not path.is_file() or file_sha256(path) != artifact.get("sha256"):
            raise BacktestValidationEvidenceError(f"X5-04 artifact hash invalid: {key}")


def _load_x505_folds(directory: Path, packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    if packet.get("proposal_label") not in {
        "PROPOSED_VALIDATED_RESEARCH_CANDIDATE",
        "PROPOSED_REJECTED_RESEARCH_CANDIDATE",
        "DIAGNOSTIC_CONFIRMS_REJECTION",
        "DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS",
    }:
        raise BacktestValidationEvidenceError("X5-05 proposal label invalid")
    summaries = packet.get("folds") or []
    if [item.get("fold_id") for item in summaries] != list(FOLD_IDS):
        raise BacktestValidationEvidenceError("X5-05 fold set or order invalid")
    output: list[dict[str, Any]] = []
    for summary in summaries:
        fold_id = str(summary["fold_id"])
        fold_dir = directory / "folds" / fold_id
        manifest = _read_json(fold_dir / "fold_manifest.json")
        manifest_payload = dict(manifest)
        manifest_hash = str(manifest_payload.pop("fold_hash", ""))
        expected_fold_hash = str(
            ((packet.get("fold_artifacts") or {}).get(fold_id) or {}).get("sha256") or ""
        )
        if not manifest_hash or packet_hash(manifest_payload) != manifest_hash:
            raise BacktestValidationEvidenceError(f"X5-05 manifest hash invalid: {fold_id}")
        if expected_fold_hash != manifest_hash:
            raise BacktestValidationEvidenceError(f"X5-05 top-level fold hash invalid: {fold_id}")
        artifacts = manifest.get("artifacts") or {}
        if set(artifacts) != X505_ARTIFACT_NAMES:
            raise BacktestValidationEvidenceError(f"X5-05 artifact set invalid: {fold_id}")
        payloads: dict[str, dict[str, Any]] = {}
        for filename, expected_hash in artifacts.items():
            if Path(filename).name != filename:
                raise BacktestValidationEvidenceError(f"X5-05 artifact path invalid: {fold_id}")
            path = fold_dir / filename
            if not path.is_file() or file_sha256(path) != expected_hash:
                raise BacktestValidationEvidenceError(f"X5-05 artifact hash invalid: {fold_id}/{filename}")
            payloads[filename] = _read_json(path)
        output.append(
            {
                "fold_id": fold_id,
                "summary": dict(summary),
                "manifest": manifest,
                "payloads": payloads,
            }
        )
    return output


def _verify_identities(
    *,
    report_identity: Mapping[str, Any],
    x503: Mapping[str, Any],
    x504: Mapping[str, Any],
    x505: Mapping[str, Any],
    folds: list[Mapping[str, Any]],
) -> None:
    candidate = x503.get("candidate_identity") or {}
    report = candidate.get("report") or {}
    task = candidate.get("task") or {}
    expected = {
        "id": report.get("id"),
        "report_no": report.get("report_no"),
        "task_id": task.get("id"),
        "task_no": task.get("task_no"),
    }
    if any(report_identity.get(key) != value for key, value in expected.items()):
        raise BacktestValidationEvidenceError("candidate report identity mismatch")
    snapshot = x503.get("execution_snapshot") or {}
    if report_identity.get("profile_id") != snapshot.get("profile_id"):
        raise BacktestValidationEvidenceError("candidate report Profile identity mismatch")
    if report_identity.get("market_data_file_id") != snapshot.get("market_data_file_id"):
        raise BacktestValidationEvidenceError("candidate report file identity mismatch")
    if x504.get("x503_candidate_packet_hash") != x503.get("packet_hash"):
        raise BacktestValidationEvidenceError("X5-04 candidate packet identity mismatch")
    if x505.get("x504_packet_hash") != x504.get("packet_hash"):
        raise BacktestValidationEvidenceError("X5-05 OOS packet identity mismatch")
    if x504.get("candidate_identity") != candidate or x505.get("candidate_identity") != candidate:
        raise BacktestValidationEvidenceError("validation candidate identity mismatch")
    protocol_hashes = {x503.get("protocol_hash"), x504.get("protocol_hash"), x505.get("protocol_hash")}
    parameter_hashes = {x503.get("parameter_hash"), x504.get("parameter_hash"), x505.get("parameter_hash")}
    if len(protocol_hashes) != 1 or None in protocol_hashes:
        raise BacktestValidationEvidenceError("protocol hash drift")
    if len(parameter_hashes) != 1 or None in parameter_hashes:
        raise BacktestValidationEvidenceError("parameter hash drift")
    expected_binding = _binding_identity(snapshot)
    if _binding_identity(x504.get("data_identity") or {}) != expected_binding:
        raise BacktestValidationEvidenceError("X5-04 binding identity drift")
    for fold in folds:
        binding = fold["payloads"]["binding_snapshot.json"]
        if _binding_identity(binding) != expected_binding:
            raise BacktestValidationEvidenceError(f"X5-05 binding identity drift: {fold['fold_id']}")


def _binding_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "profile_id",
            "profile_active_binding_id",
            "market_data_file_id",
            "data_version",
            "file_sha256",
        )
    }


def _selected_metrics(summary: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "trade_count",
        "total_return_pct",
        "max_drawdown_pct",
        "max_consecutive_losses",
        "profit_factor",
        "win_rate",
        "total_commission",
        "total_slippage",
    )
    return {key: summary.get(key) for key in keys}


def _fold_context(item: Mapping[str, Any]) -> dict[str, Any]:
    payloads = item["payloads"]
    result = payloads["result.json"]
    summary = result.get("summary") or {}
    overlays = payloads["cost_margin_overlays.json"].get("scenarios") or []
    returns = [float(row.get("adjusted_total_return_pct") or 0.0) for row in overlays]
    return {
        "fold_id": item["fold_id"],
        "status": item["summary"].get("status"),
        "audit_status": item["summary"].get("audit_status"),
        "metrics": _selected_metrics(summary),
        "trade_count": item["summary"].get("trade_count"),
        "total_return_pct": item["summary"].get("total_return_pct"),
        "numeric_reasons": deepcopy(item["summary"].get("numeric_reasons") or []),
        "structural_reasons": deepcopy(item["summary"].get("structural_reasons") or []),
        "overlay_scenario_count": len(overlays),
        "cost_sensitivity": {
            "min_adjusted_total_return_pct": min(returns) if returns else None,
            "max_adjusted_total_return_pct": max(returns) if returns else None,
            "margin_infeasible_scenario_count": sum(
                1 for row in overlays if not bool(row.get("margin_feasible"))
            ),
        },
        "diagnostics": deepcopy(payloads["diagnostics.json"]),
        "fold_hash": item["manifest"].get("fold_hash"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BacktestValidationEvidenceError(f"evidence file missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BacktestValidationEvidenceError(f"invalid evidence JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise BacktestValidationEvidenceError(f"evidence JSON must be an object: {path.name}")
    return value


__all__ = [
    "BacktestValidationEvidenceError",
    "SCHEMA_VERSION",
    "build_backtest_validation_context",
    "verify_context_hash",
]
