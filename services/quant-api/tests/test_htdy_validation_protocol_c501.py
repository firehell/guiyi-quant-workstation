"""C5-01 HTDY validation protocol config / schema / hash regressions.

Read-only checks. Does not run formal backtest, OOS, or write DB / report14.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from guiyi_quant.strategies.huotian_dayou_strict.config_schema import (  # noqa: E402
    CANDIDATE_POLICY,
    FILL_POLICY,
    INDICATOR_VERSION,
    STRATEGY_CODE,
    STRATEGY_VERSION,
)

CONFIG_PATH = REPO_ROOT / "configs/oos/htdy_strict_validation_protocol_v1.json"
SCHEMA_PATH = REPO_ROOT / "configs/oos/schemas/htdy_validation_protocol_v1.schema.json"
HASH_EVIDENCE_PATH = (
    REPO_ROOT / "data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json"
)
PARAMS_PATH = (
    REPO_ROOT
    / "packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/default_params.json"
)
JM_OOS_PATH = REPO_ROOT / "configs/oos/jm_v1b_report14_frozen.json"
PROTOCOL_MD = REPO_ROOT / "docs/strategy_specs/htdy/VALIDATION_PROTOCOL_V1.md"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parameter_hash(params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_protocol_artifacts_exist() -> None:
    assert CONFIG_PATH.is_file()
    assert SCHEMA_PATH.is_file()
    assert HASH_EVIDENCE_PATH.is_file()
    assert PROTOCOL_MD.is_file()


def test_config_passes_json_schema() -> None:
    cfg = _load_json(CONFIG_PATH)
    schema = _load_json(SCHEMA_PATH)
    jsonschema.validate(cfg, schema)


def test_identity_matches_strict_config_constants() -> None:
    cfg = _load_json(CONFIG_PATH)
    strategy = cfg["frozen_strategy"]
    assert strategy["strategy_code"] == STRATEGY_CODE
    assert strategy["strategy_version"] == STRATEGY_VERSION
    assert strategy["indicator_version"] == INDICATOR_VERSION
    assert strategy["candidate_policy"] == CANDIDATE_POLICY
    assert strategy["fill_policy"] == FILL_POLICY
    assert strategy["entry_interval"] == "15m"
    assert strategy["period"] == "15m"
    assert strategy["product"] == "JM"
    assert strategy["contract"] == "jm.MAIN"
    assert strategy["contract_role"] == "dominant_main_continuous"
    assert strategy["actual_contract_in_scope"] is False

    snap = cfg["indicator_policy_snapshot"]
    assert INDICATOR_VERSION in snap["indicator_versions"]
    assert INDICATOR_VERSION in snap["formal_policy_ids"]
    assert snap["confirmed_only"] is True


def test_parameter_hash_matches_default_params() -> None:
    cfg = _load_json(CONFIG_PATH)
    params = _load_json(PARAMS_PATH)
    assert cfg["parameter_hash"] == _parameter_hash(params)
    assert cfg["parameter_hash"] == "84d80219d2a27d115dfdd36fe7bdf0ea41530e2fc9f2a188ec48bf9db37c2eb8"


def test_freeze_status_is_prepared_not_final_frozen() -> None:
    cfg = _load_json(CONFIG_PATH)
    assert cfg["freeze_status"] == "protocol_prepared_not_final_frozen"
    assert cfg["cursor_gate"] == "CURSOR_VALIDATION_PROTOCOL_PREPARED"
    assert cfg["persist_to_db"] is False
    assert cfg["baseline_report_id"] is None
    assert cfg["report14_policy"] == "do_not_touch"
    assert cfg["live_signal_wecom_in_scope"] is False
    assert "FINAL_FROZEN" not in cfg["freeze_status"]
    assert cfg["freeze_status"] != "frozen"


def test_hard_reject_and_e5_05_branch_present() -> None:
    cfg = _load_json(CONFIG_PATH)
    hard = cfg["hard_reject_criteria"]
    assert "trust_audit_not_passed" in hard["structural_any_of"]
    assert "report14_touched" in hard["structural_any_of"]
    oos = hard["oos_fixed_any_of"]
    assert oos["window_id"] == "oos_fixed"
    assert oos["max_drawdown_pct_gt"] == 0.15
    assert oos["max_consecutive_losses_gte"] == 8
    assert oos["trade_count_lt"] == 5
    assert oos["profit_factor_lt"] == 0.5
    assert oos["total_return_pct_lte"] == -0.2
    assert hard["on_trigger_gate"] == "OOS_HARD_REJECT_TRIGGERED"
    assert hard["forbid_param_retune_to_mask_failure"] is True

    branch = cfg["e5_05_branch"]["on_oos_hard_reject"]
    assert branch["skip_x5_05_rolling_by_default"] is True
    assert "diagnostic_only_x5_05" in branch["allowed_followups"]
    assert "flip_oos_hard_reject" in branch["forbidden"]
    assert "PROPOSED_REJECTED_RESEARCH_CANDIDATE" in branch["allowed_labels"]
    assert "DIAGNOSTIC_CONFIRMS_REJECTION" in branch["allowed_labels"]
    assert "DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS" in branch["allowed_labels"]


def test_windows_include_in_sample_oos_and_walk_forward() -> None:
    cfg = _load_json(CONFIG_PATH)
    ids = {w["id"] for w in cfg["windows"]}
    assert ids == {
        "in_sample_baseline",
        "oos_fixed",
        "walk_forward_a_test",
        "walk_forward_b_test",
        "walk_forward_c_test",
    }


def test_config_sha256_evidence_matches_file_bytes() -> None:
    raw = CONFIG_PATH.read_bytes()
    expected = hashlib.sha256(raw).hexdigest()
    evidence = _load_json(HASH_EVIDENCE_PATH)
    assert evidence["config_path"] == "configs/oos/htdy_strict_validation_protocol_v1.json"
    assert evidence["config_sha256"] == expected
    assert evidence["config_size_bytes"] == len(raw)
    assert evidence["config_hash_method"] == "sha256(utf8_file_bytes)"
    assert evidence["parameter_hash"] == _load_json(CONFIG_PATH)["parameter_hash"]
    assert evidence["freeze_status"] == "protocol_prepared_not_final_frozen"
    assert evidence["cursor_gate"] == "CURSOR_VALIDATION_PROTOCOL_PREPARED"
    assert evidence["report14_untouched"] is True


def test_jm_report14_oos_frozen_untouched() -> None:
    assert JM_OOS_PATH.is_file()
    jm = _load_json(JM_OOS_PATH)
    assert jm["baseline_report_id"] == 14
    assert jm["frozen_strategy"]["strategy_code"] == "jm_v1b_daily_direction_fast_entry"
    # HTDY protocol must not claim report14 as baseline.
    htdy = _load_json(CONFIG_PATH)
    assert htdy["baseline_report_id"] is None
    assert htdy["report14_policy"] == "do_not_touch"
