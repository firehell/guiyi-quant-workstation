from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from app.backtest.htdy_rolling_decision_recheck import (
    CURRENT_REJECTION_GATE,
    READY_GATE as R4503_READY_GATE,
    build_rolling_decision_recheck,
    immutable_input_hashes as rolling_input_hashes,
)
from app.backtest.htdy_sample_end_audit import (
    BASELINE_PATH,
    NUMERIC_GATE,
    STRUCTURAL_GATE,
    X504_RESULT_PATH,
    build_closeout_packet,
    immutable_file_hashes as sample_end_input_hashes,
    load_verified_packet,
)
from app.backtest.htdy_trusted_report import (
    file_sha256,
    load_protocol_context,
    packet_hash,
)
from app.services.htdy_stage5_acceptance import (
    BLOCKED_GATE,
    PIPELINE_READY_GATE,
    REJECTED_OUTCOME,
    build_stage5_acceptance,
    verify_acceptance_packet,
)


SCHEMA_VERSION = "htdy_stage5_acceptance_r45_v2_v1"
TASK_ID = "TASK-HTDY-STAGE5-ACCEPTANCE-V2-R4504"
CLOSEOUT_GATE = "STAGE5_CLOSEOUT_V2_READY"
X503_PATH = Path(
    "data/reports/htdy_trusted_backtest_candidate_x5_03/"
    "HTDY_TRUSTED_BACKTEST_CANDIDATE.json"
)
X504_PATH = Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json")
X505_PATH = Path(
    "data/reports/htdy_rolling_oos_x5_05/ROLLING_OOS_VALIDATION_RESULT.json"
)
X506_PATH = Path(
    "data/reports/htdy_strategy_review_x5_06b/"
    "STRATEGY_REVIEW_CLOSED_LOOP_READY.json"
)
X507_PATH = Path(
    "data/reports/htdy_stage5_acceptance_x5_07/STAGE5_ACCEPTANCE_PACKET.json"
)
R4501_PATH = Path("data/reports/htdy_stage45_closeout_r45/R45_01_ACCEPTANCE.json")
R4502_PATH = Path(
    "data/reports/htdy_stage45_closeout_r45/sample_end_audit/SAMPLE_END_AUDIT.json"
)
R4503_PATH = Path(
    "data/reports/htdy_stage45_closeout_r45/rolling_decision_recheck/"
    "ROLLING_DECISION_RECHECK.json"
)
R4501_COMPLETION_PATH = Path(
    "data/reports/htdy_stage45_closeout_r45/data_completion_r4501b/DATA_COMPLETION.json"
)
R4501_REVALIDATED_PATH = Path(
    "data/reports/htdy_stage45_closeout_r45/data_equivalence_revalidated_r4501b/"
    "DATA_EQUIVALENCE_REVALIDATED.json"
)
R4501_FAILURE_PATH = Path(
    "data/reports/htdy_stage45_closeout_r45/data_equivalence/DATA_EQUIVALENCE.json"
)
EXPECTED_ORDERED_BAR_HASH = "c32df4e6b52e9efa0c71c6851d04cc9e0abd2a39f204776729b9a35037f6eba0"
EXPECTED_CANDIDATE_AUDIT_HASH = "dee6c73e0972de51ae314956c038962f1c45cbfb1162322628fee3b728c07a1d"
EXPECTED_REPORT14_AUDIT_HASH = "2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a"
STRATEGY_SOURCE_PATHS = (
    Path("configs/oos/htdy_strict_validation_protocol_v1.json"),
    Path("packages/quant-core/guiyi_quant/strategies/indicator_policy.py"),
    Path("packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/__init__.py"),
    Path("packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/config_schema.py"),
    Path("packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/default_params.json"),
    Path("packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/vnpy_strategy.py"),
)
IMMUTABLE_REPORT_DIRS = (
    Path("data/reports/htdy_trusted_backtest_candidate_x5_03"),
    Path("data/reports/htdy_oos_validation_x5_04"),
    Path("data/reports/htdy_rolling_oos_x5_05"),
    Path("data/reports/htdy_strategy_review_x5_06b"),
    Path("data/reports/htdy_stage5_acceptance_x5_07"),
    Path("data/reports/htdy_stage45_closeout_r45"),
)
CHECK_NAMES = (
    "candidate_report14_dual_audit",
    "report14_invariance",
    "report15_identity",
    "protocol_parameter_hash",
    "binding_identity",
    "frozen_data_window_equivalence",
    "sample_end_accounting_liquidation",
    "ordinary_fill_timing",
    "numeric_hard_reject_preserved",
    "rolling_structural_audits",
    "rolling_numeric_rejection",
    "review_exact_bars_browser_smoke",
    "original_packets_immutable",
    "canonical_db_readonly_no_change",
    "strategy_parameters_unchanged",
)


class Stage5AcceptanceV2Error(ValueError):
    """Fail-closed error for incomplete or drifted R45 Stage 5 evidence."""


def verify_acceptance_v2_packet(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def collect_immutable_input_hashes(repo_root: Path) -> dict[str, str]:
    root = repo_root.expanduser().resolve()
    paths = {root / relative for relative in STRATEGY_SOURCE_PATHS}
    for relative_dir in IMMUTABLE_REPORT_DIRS:
        directory = root / relative_dir
        if not directory.is_dir():
            raise Stage5AcceptanceV2Error(
                f"immutable evidence directory is missing: {relative_dir.name}"
            )
        paths.update(path for path in directory.rglob("*") if path.is_file())
    hashes: dict[str, str] = {}
    for path in sorted(paths):
        if not path.is_file():
            raise Stage5AcceptanceV2Error(f"immutable input is missing: {path.name}")
        hashes[path.relative_to(root).as_posix()] = file_sha256(path)
    return hashes


def collect_strategy_source_invariance(
    repo_root: Path,
    *,
    baseline_commit: str,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    files: dict[str, dict[str, str]] = {}
    for relative in STRATEGY_SOURCE_PATHS:
        current_path = root / relative
        if not current_path.is_file():
            raise Stage5AcceptanceV2Error(f"frozen strategy input is missing: {relative.name}")
        completed = subprocess.run(
            ["git", "show", f"{baseline_commit}:{relative.as_posix()}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        files[relative.as_posix()] = {
            "baseline_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "current_sha256": file_sha256(current_path),
        }
    unchanged = all(
        item["baseline_sha256"] == item["current_sha256"] for item in files.values()
    )
    return {
        "baseline_commit": baseline_commit,
        "unchanged": unchanged,
        "files": files,
    }


def build_stage5_acceptance_v2(
    repo_root: Path,
    *,
    source_commit: str,
    db_before: Mapping[str, Any],
    db_after: Mapping[str, Any],
    binding_before: Mapping[str, Any],
    binding_after: Mapping[str, Any],
    immutable_hashes_before: Mapping[str, str],
    immutable_hashes_after: Mapping[str, str],
    strategy_source_invariance: Mapping[str, Any],
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    checks: dict[str, dict[str, Any]] = {}
    immutable_after = dict(immutable_hashes_after)
    strategy_proof = deepcopy(dict(strategy_source_invariance))
    try:
        actual_hashes = collect_immutable_input_hashes(root)
        if dict(immutable_hashes_before) != immutable_after or immutable_after != actual_hashes:
            raise Stage5AcceptanceV2Error("immutable original evidence changed during V2 acceptance")

        x503 = _load_packet(root / X503_PATH, "X5-03")
        x504 = _load_packet(root / X504_PATH, "X5-04")
        x505 = _load_packet(root / X505_PATH, "X5-05")
        x506 = _load_packet(root / X506_PATH, "X5-06B")
        x507 = _load_packet(root / X507_PATH, "X5-07")
        r4501 = _load_packet(root / R4501_PATH, "R45-01")
        r4502 = _load_packet(root / R4502_PATH, "R45-02")
        r4503 = _load_packet(root / R4503_PATH, "R45-03")

        rebuilt_x507 = build_stage5_acceptance(
            root,
            source_commit=str(x507.get("source_commit") or ""),
        )
        if not verify_acceptance_packet(x507) or rebuilt_x507 != x507:
            raise Stage5AcceptanceV2Error("X5-07 exact acceptance recheck failed")
        if (
            x507.get("gate") != PIPELINE_READY_GATE
            or x507.get("research_outcome") != REJECTED_OUTCOME
        ):
            raise Stage5AcceptanceV2Error("X5-07 rejected terminal outcome drifted")

        _validate_r4501(root, r4501)
        checks["frozen_data_window_equivalence"] = _passed(
            ordered_bar_hash=r4501.get("ordered_bar_hash"),
            row_count=19381,
        )

        if dict(db_before) != dict(db_after):
            raise Stage5AcceptanceV2Error("canonical database snapshot changed during acceptance")
        frozen_db = dict((r4502.get("invariance") or {}).get("db_after") or {})
        if dict(db_after) != frozen_db:
            raise Stage5AcceptanceV2Error("canonical database facts drifted from R45-02")

        baseline = load_verified_packet(root / BASELINE_PATH)
        x504_result = _read_json(root / X504_RESULT_PATH)
        r4502_inputs = sample_end_input_hashes(root)
        rebuilt_r4502 = build_closeout_packet(
            result=x504_result,
            x504_packet=x504,
            baseline_packet=baseline,
            r4501_acceptance=r4501,
            immutable_hashes_before=r4502_inputs,
            immutable_hashes_after=r4502_inputs,
            db_before=db_before,
            db_after=db_after,
            source_commit=str(r4502.get("source_commit") or ""),
        )
        if rebuilt_r4502 != r4502:
            raise Stage5AcceptanceV2Error("R45-02 exact accounting audit recheck failed")

        structural = dict(r4502.get("structural_audit") or {})
        classification = dict(r4502.get("classification") or {})
        if (
            r4502.get("structural_gate") != STRUCTURAL_GATE
            or classification.get("is_accounting_liquidation") is not True
            or classification.get("excluded_from_standard_next_bar_fill_check") is not True
            or classification.get("reason") != "sample_end_forced_exit"
            or structural.get("blocked_reasons") != []
        ):
            raise Stage5AcceptanceV2Error("sample-end accounting liquidation audit drifted")
        checks["sample_end_accounting_liquidation"] = _passed(
            event_identity=classification.get("event_identity"),
            trade_identity=classification.get("trade_identity"),
        )
        if (
            structural.get("ordinary_events_strict_after") is not True
            or structural.get("ordinary_trades_strict_after") is not True
        ):
            raise Stage5AcceptanceV2Error("ordinary next-bar fill timing is not strict")
        checks["ordinary_fill_timing"] = _passed(
            ordinary_events_strict_after=True,
            ordinary_trades_strict_after=True,
        )
        numeric = dict(r4502.get("numeric_hard_reject") or {})
        if (
            r4502.get("numeric_gate") != NUMERIC_GATE
            or numeric.get("preserved") is not True
            or numeric.get("research_outcome_remains") != REJECTED_OUTCOME
            or not numeric.get("reasons")
        ):
            raise Stage5AcceptanceV2Error("numeric hard reject was not preserved")
        checks["numeric_hard_reject_preserved"] = _passed(
            max_consecutive_losses=numeric.get("max_consecutive_losses"),
            profit_factor=numeric.get("profit_factor"),
            reasons=numeric.get("reasons"),
        )

        rolling_hashes = rolling_input_hashes(root)
        rebuilt_r4503 = build_rolling_decision_recheck(
            root,
            source_commit=str(r4503.get("source_commit") or ""),
            immutable_hashes_before=rolling_hashes,
            immutable_hashes_after=rolling_hashes,
        )
        if rebuilt_r4503 != r4503:
            raise Stage5AcceptanceV2Error("R45-03 exact decision recheck failed")
        folds = list(r4503.get("folds") or [])
        if (
            len(folds) != 3
            or any(
                fold.get("status") != "completed"
                or fold.get("audit_status") != "passed"
                or fold.get("structural_reasons") != []
                for fold in folds
            )
        ):
            raise Stage5AcceptanceV2Error("rolling structural audits are not all passed")
        checks["rolling_structural_audits"] = _passed(
            folds=[fold.get("fold_id") for fold in folds]
        )
        if (
            r4503.get("gates") != [R4503_READY_GATE, CURRENT_REJECTION_GATE]
            or r4503.get("decision") != "DIAGNOSTIC_CONFIRMS_REJECTION"
            or any(not fold.get("numeric_reasons") for fold in folds)
        ):
            raise Stage5AcceptanceV2Error("rolling numeric rejection is not preserved")
        checks["rolling_numeric_rejection"] = _passed(
            decision=r4503.get("decision"),
            numeric_reasons={
                str(fold.get("fold_id")): fold.get("numeric_reasons") for fold in folds
            },
        )

        audits = dict(x503.get("audits") or {})
        candidate_audit = dict(audits.get("candidate") or {})
        report14_audit = dict(audits.get("report14") or {})
        db_candidate = dict(db_after.get("candidate") or {})
        db_report14 = dict(db_after.get("report14") or {})
        if (
            candidate_audit.get("audit_status") != "passed"
            or report14_audit.get("audit_status") != "passed"
            or db_candidate.get("audit_status") != "passed"
            or db_report14.get("audit_status") != "passed"
            or db_candidate.get("consistency_hash") != EXPECTED_CANDIDATE_AUDIT_HASH
            or db_report14.get("consistency_hash") != EXPECTED_REPORT14_AUDIT_HASH
        ):
            raise Stage5AcceptanceV2Error("candidate/report14 dual trust audit failed")
        checks["candidate_report14_dual_audit"] = _passed(
            candidate_consistency_hash=db_candidate.get("consistency_hash"),
            report14_consistency_hash=db_report14.get("consistency_hash"),
        )
        if (
            (x506.get("report_invariance") or {}).get("report14") is not True
            or (x507.get("report14_regression") or {}).get("invariance_after_review") is not True
            or db_report14 != (frozen_db.get("report14") or {})
        ):
            raise Stage5AcceptanceV2Error("report14 invariance failed")
        checks["report14_invariance"] = _passed(
            consistency_hash=db_report14.get("consistency_hash")
        )

        candidate_identity = deepcopy(dict(x503.get("candidate_identity") or {}))
        _validate_report15_identity(
            candidate_identity,
            x504=x504,
            x505=x505,
            x506=x506,
            x507=x507,
            db_candidate=db_candidate,
        )
        checks["report15_identity"] = _passed(candidate_identity=candidate_identity)

        protocol_context = load_protocol_context(root)
        protocol_hash = str(protocol_context["protocol_hash"])
        parameter_hash = str(protocol_context["parameter_hash"])
        for name, packet in (("X5-03", x503), ("X5-04", x504), ("X5-05", x505), ("X5-07", x507)):
            if packet.get("protocol_hash") != protocol_hash or packet.get("parameter_hash") != parameter_hash:
                raise Stage5AcceptanceV2Error(f"{name} protocol/parameter hash drift")
        checks["protocol_parameter_hash"] = _passed(
            protocol_hash=protocol_hash,
            parameter_hash=parameter_hash,
        )

        binding_identity = _validate_binding_identity(
            binding_before,
            binding_after,
            x503=x503,
            x504=x504,
            x507=x507,
        )
        checks["binding_identity"] = _passed(binding_identity=binding_identity)

        _validate_review(x506)
        checks["review_exact_bars_browser_smoke"] = _passed(
            exact_bars_hash=(x506.get("exact_bars") or {}).get("bars_hash"),
            screenshot_sha256=(x506.get("browser_smoke") or {}).get("screenshot_sha256"),
            console_error_count=(x506.get("browser_smoke") or {}).get("console_error_count"),
        )

        checks["original_packets_immutable"] = _passed(file_count=len(actual_hashes))
        checks["canonical_db_readonly_no_change"] = _passed(
            transaction=db_after.get("transaction"),
            candidate_facts_hash=db_candidate.get("facts_hash"),
            report14_facts_hash=db_report14.get("facts_hash"),
        )

        _validate_strategy_source(strategy_proof, x503)
        checks["strategy_parameters_unchanged"] = _passed(
            baseline_commit=strategy_proof.get("baseline_commit"),
            file_count=len(strategy_proof.get("files") or {}),
            parameter_hash=parameter_hash,
        )
        if set(checks) != set(CHECK_NAMES):
            raise Stage5AcceptanceV2Error("V2 hard-check coverage is incomplete")

        packet: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "status": "completed",
            "pipeline_gate": PIPELINE_READY_GATE,
            "research_outcome": REJECTED_OUTCOME,
            "closeout_gate": CLOSEOUT_GATE,
            "markers": [PIPELINE_READY_GATE, REJECTED_OUTCOME, CLOSEOUT_GATE],
            "source_commit": source_commit,
            "prerequisite_packets": _packet_identities(
                root,
                {
                    "x503": (X503_PATH, x503),
                    "x504": (X504_PATH, x504),
                    "x505": (X505_PATH, x505),
                    "x506b": (X506_PATH, x506),
                    "x507": (X507_PATH, x507),
                    "r4501": (R4501_PATH, r4501),
                    "r4502": (R4502_PATH, r4502),
                    "r4503": (R4503_PATH, r4503),
                },
            ),
            "checks": checks,
            "candidate_identity": candidate_identity,
            "binding_identity": binding_identity,
            "protocol_hash": protocol_hash,
            "parameter_hash": parameter_hash,
            "database_invariance": {
                "unchanged": True,
                "transaction": db_after.get("transaction"),
                "before": deepcopy(dict(db_before)),
                "after": deepcopy(dict(db_after)),
                "matches_r4502": True,
            },
            "strategy_source_invariance": strategy_proof,
            "immutable_input_sha256": actual_hashes,
            "boundaries": _boundaries(),
            "blocked_reason": None,
        }
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        packet = _blocked_packet(
            source_commit=source_commit,
            reason=_sanitize_reason(exc),
            checks=checks,
            immutable_hashes=immutable_after,
            strategy_source_invariance=strategy_proof,
        )
    packet["packet_hash"] = packet_hash(packet)
    return packet


def render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# HTDY Stage 5 Acceptance V2 (R45-04)",
        "",
        f"- Status: `{packet.get('status')}`",
        f"- Pipeline Gate: `{packet.get('pipeline_gate')}`",
        f"- Research Outcome: `{packet.get('research_outcome') or 'N/A'}`",
        f"- Closeout Gate: `{packet.get('closeout_gate') or 'N/A'}`",
        f"- Packet hash: `{packet.get('packet_hash')}`",
        "",
        "## Hard Gates",
        "",
    ]
    for name in CHECK_NAMES:
        status = ((packet.get("checks") or {}).get(name) or {}).get("status", "not_run")
        lines.append(f"- `{name}`: `{status}`")
    if packet.get("blocked_reason"):
        lines.extend(["", f"Blocked reason: `{packet.get('blocked_reason')}`"])
    lines.extend(
        [
            "",
            "This is a read-only acceptance closeout. It does not authorize strategy changes,",
            "database writes, reruns, live notification, or trading execution.",
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence_once(output_dir: Path, packet: Mapping[str, Any]) -> None:
    output = output_dir.expanduser().resolve()
    json_path = output / "STAGE5_ACCEPTANCE_V2.json"
    markdown_path = output / "STAGE5_ACCEPTANCE_V2.md"
    payload = deepcopy(dict(packet))
    markdown = render_markdown(payload)
    if output.exists() and any(output.iterdir()):
        if json_path.is_file() and markdown_path.is_file():
            existing = json.loads(json_path.read_text(encoding="utf-8"))
            if existing == payload and markdown_path.read_text(encoding="utf-8") == markdown:
                return
        raise Stage5AcceptanceV2Error("V2 evidence directory is non-empty; refusing overwrite")
    output.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(markdown, encoding="utf-8")


def build_blocked_packet(*, source_commit: str, reason: str) -> dict[str, Any]:
    packet = _blocked_packet(
        source_commit=source_commit,
        reason=reason,
        checks={},
        immutable_hashes={},
        strategy_source_invariance={},
    )
    packet["packet_hash"] = packet_hash(packet)
    return packet


def _validate_r4501(root: Path, pointer: Mapping[str, Any]) -> None:
    baseline = load_verified_packet(root / BASELINE_PATH)
    completion = _load_packet(root / R4501_COMPLETION_PATH, "R45-01 completion")
    revalidated = _load_packet(root / R4501_REVALIDATED_PATH, "R45-01 revalidated")
    failure = _load_packet(root / R4501_FAILURE_PATH, "R45-01 original failure")
    comparison = dict(revalidated.get("comparison") or {})
    if (
        pointer.get("gate") != "HTDY_FROZEN_DATA_WINDOW_EQUIVALENT"
        or pointer.get("baseline_packet_hash") != baseline.get("packet_hash")
        or pointer.get("completion_packet_hash") != completion.get("packet_hash")
        or pointer.get("revalidated_packet_hash") != revalidated.get("packet_hash")
        or pointer.get("original_failure_packet_hash") != failure.get("packet_hash")
        or pointer.get("ordered_bar_hash") != EXPECTED_ORDERED_BAR_HASH
        or completion.get("base_row_count") != 19366
        or completion.get("completion_row_count") != 15
        or revalidated.get("difference_count") != 0
        or revalidated.get("composite_row_count") != 19381
        or revalidated.get("execution_row_count") != 19381
        or revalidated.get("composite_ordered_bar_hash") != EXPECTED_ORDERED_BAR_HASH
        or revalidated.get("execution_ordered_bar_hash") != EXPECTED_ORDERED_BAR_HASH
        or comparison.get("difference_count") != 0
        or comparison.get("old_row_count") != 19381
        or comparison.get("new_row_count") != 19381
        or comparison.get("old_ordered_bar_hash") != EXPECTED_ORDERED_BAR_HASH
        or comparison.get("new_ordered_bar_hash") != EXPECTED_ORDERED_BAR_HASH
    ):
        raise Stage5AcceptanceV2Error("R45-01 frozen data equivalence chain drifted")
    if not _verify_packet_hash(comparison):
        raise Stage5AcceptanceV2Error("R45-01 nested comparison hash invalid")


def _validate_report15_identity(
    candidate_identity: Mapping[str, Any],
    *,
    x504: Mapping[str, Any],
    x505: Mapping[str, Any],
    x506: Mapping[str, Any],
    x507: Mapping[str, Any],
    db_candidate: Mapping[str, Any],
) -> None:
    report = dict(candidate_identity.get("report") or {})
    task = dict(candidate_identity.get("task") or {})
    if (
        report.get("id") != 15
        or task.get("id") != 23
        or x504.get("candidate_identity") != candidate_identity
        or x505.get("candidate_identity") != candidate_identity
        or x507.get("candidate_identity") != candidate_identity
        or x506.get("report_id") != 15
        or db_candidate.get("report_id") != 15
        or db_candidate.get("task_id") != 23
        or db_candidate.get("report_no") != report.get("report_no")
        or db_candidate.get("task_no") != task.get("task_no")
        or db_candidate.get("trade_count") != 1255
        or db_candidate.get("order_count") != 2510
    ):
        raise Stage5AcceptanceV2Error("report15/task23 identity drifted")


def _validate_binding_identity(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    x503: Mapping[str, Any],
    x504: Mapping[str, Any],
    x507: Mapping[str, Any],
) -> dict[str, Any]:
    if dict(before) != dict(after):
        raise Stage5AcceptanceV2Error("active binding changed during acceptance")
    current = dict(after)
    if current.get("binding_status") != "active":
        raise Stage5AcceptanceV2Error("active binding status is not active")
    x503_binding = dict(x503.get("execution_snapshot") or {})
    x504_binding = dict(x504.get("data_identity") or {})
    x507_binding = dict(x507.get("binding_identity") or {})
    keys = (
        "profile_id",
        "profile_active_binding_id",
        "market_data_file_id",
        "data_version",
        "file_sha256",
        "quality_status",
        "quality_policy",
        "data_role",
    )
    for expected in (x503_binding, x504_binding, x507_binding):
        for key in keys:
            if key in expected and current.get(key) != expected.get(key):
                raise Stage5AcceptanceV2Error(f"binding identity drifted: {key}")
    return {key: current.get(key) for key in keys if key in current}


def _validate_review(x506: Mapping[str, Any]) -> None:
    exact = dict(x506.get("exact_bars") or {})
    browser = dict(x506.get("browser_smoke") or {})
    timing = dict(x506.get("timing") or {})
    invariance = dict(x506.get("report_invariance") or {})
    required_browser = (
        "backtest_round_trip",
        "exact_bars_rendered",
        "market_chart_round_trip",
        "review_deep_link",
        "review_saved_and_reread",
        "trade_markers_rendered",
        "validation_context_api",
    )
    if (
        x506.get("gate") != "STRATEGY_REVIEW_CLOSED_LOOP_READY"
        or exact.get("status") != "passed"
        or not exact.get("bars_hash")
        or exact.get("row_count") != 7
        or browser.get("status") != "passed"
        or browser.get("console_error_count") != 0
        or any(browser.get(key) is not True for key in required_browser)
        or timing.get("status") != "passed"
        or timing.get("strictly_after") is not True
        or any(invariance.get(key) is not True for key in ("candidate", "report14", "selected_trade"))
    ):
        raise Stage5AcceptanceV2Error("Review exact-bars/browser smoke evidence failed")


def _validate_strategy_source(proof: Mapping[str, Any], x503: Mapping[str, Any]) -> None:
    expected_paths = {path.as_posix() for path in STRATEGY_SOURCE_PATHS}
    files = dict(proof.get("files") or {})
    strategy = dict(x503.get("strategy_identity") or {})
    if (
        proof.get("baseline_commit") != x503.get("source_commit")
        or proof.get("unchanged") is not True
        or set(files) != expected_paths
        or any(
            not item.get("baseline_sha256")
            or item.get("baseline_sha256") != item.get("current_sha256")
            for item in files.values()
        )
        or strategy.get("strategy_code") != "huotian_dayou_strict"
        or strategy.get("strategy_version") != "v0.1.0-backtest-candidate"
        or strategy.get("candidate_policy") != "strict_v1_15m_formal_candidate_v0"
    ):
        raise Stage5AcceptanceV2Error("frozen strategy source or identity changed")


def _packet_identities(
    root: Path,
    packets: Mapping[str, tuple[Path, Mapping[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "relative_path": relative.as_posix(),
            "file_sha256": file_sha256(root / relative),
            "packet_hash": packet.get("packet_hash"),
        }
        for name, (relative, packet) in packets.items()
    }


def _load_packet(path: Path, name: str) -> dict[str, Any]:
    value = _read_json(path)
    if not _verify_packet_hash(value):
        raise Stage5AcceptanceV2Error(f"{name} packet hash invalid")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Stage5AcceptanceV2Error(f"required evidence is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5AcceptanceV2Error(f"evidence is not an object: {path.name}")
    return value


def _verify_packet_hash(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def _passed(**evidence: Any) -> dict[str, Any]:
    return {"status": "passed", "evidence": evidence}


def _boundaries() -> dict[str, bool]:
    return {
        "canonical_database_write": False,
        "original_packet_or_artifact_overwritten": False,
        "strategy_or_parameter_changed": False,
        "strategy_or_oos_rerun": False,
        "profile_binding_write": False,
        "parquet_write": False,
        "rqdata_call": False,
        "notification_sent": False,
        "trading_execution": False,
    }


def _blocked_packet(
    *,
    source_commit: str,
    reason: str,
    checks: Mapping[str, Any],
    immutable_hashes: Mapping[str, str],
    strategy_source_invariance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "blocked",
        "pipeline_gate": BLOCKED_GATE,
        "research_outcome": None,
        "closeout_gate": None,
        "markers": [BLOCKED_GATE],
        "source_commit": source_commit,
        "prerequisite_packets": {},
        "checks": deepcopy(dict(checks)),
        "candidate_identity": {},
        "binding_identity": {},
        "protocol_hash": None,
        "parameter_hash": None,
        "database_invariance": {},
        "strategy_source_invariance": deepcopy(dict(strategy_source_invariance)),
        "immutable_input_sha256": dict(immutable_hashes),
        "boundaries": _boundaries(),
        "blocked_reason": reason,
    }


def _sanitize_reason(exc: BaseException) -> str:
    text = str(exc).replace("\\", "/")
    safe = [Path(part).name if "/" in part else part for part in text.split()]
    return " ".join(safe)[:500] or exc.__class__.__name__


__all__ = [
    "BLOCKED_GATE",
    "CHECK_NAMES",
    "CLOSEOUT_GATE",
    "PIPELINE_READY_GATE",
    "R4501_PATH",
    "R4502_PATH",
    "R4503_PATH",
    "REJECTED_OUTCOME",
    "STRATEGY_SOURCE_PATHS",
    "Stage5AcceptanceV2Error",
    "X503_PATH",
    "X506_PATH",
    "X507_PATH",
    "build_blocked_packet",
    "build_stage5_acceptance_v2",
    "collect_immutable_input_hashes",
    "collect_strategy_source_invariance",
    "render_markdown",
    "verify_acceptance_v2_packet",
    "write_evidence_once",
]
