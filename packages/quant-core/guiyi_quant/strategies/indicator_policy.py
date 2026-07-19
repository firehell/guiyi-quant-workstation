from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from guiyi_quant.indicators.policy import require_formal_policy
from guiyi_quant.indicators.registry import get_indicator, resolve_indicator_code


SCHEMA_VERSION = "strategy_indicator_policy_v1"
COST_MODEL_VERSION = "cost_model_v1_rate_slippage_size"

JM_V1B_STRATEGY_CODE = "jm_v1b_daily_direction_fast_entry"
JM_V1B_STRATEGY_VERSION = "v1b.0"
JM_V1B_FROZEN_POLICY_ID = "jm_v1b_report14_frozen_v1"

HTDY_STRICT_STRATEGY_CODE = "huotian_dayou_strict"
HTDY_STRICT_STRATEGY_VERSION = "v0.1.0-backtest-candidate"
HTDY_STRICT_INDICATOR = "huotian_dayou_strict_v1"
HTDY_ORIGINAL_CODES = frozenset({"huotian_dayou_original_v0", "huo_tian_da_you"})

STATUS_AVAILABLE = "available"
STATUS_LEGACY_UNAVAILABLE = "legacy_policy_unavailable"

_REQUIRED_FIELDS = (
    "strategy_code",
    "strategy_version",
    "indicator_versions",
    "formal_policy_ids",
    "profile_id",
    "confirmed_only",
    "execution_timing",
    "cost_model_version",
    "research_status",
)


@dataclass(frozen=True)
class StrategyIndicatorPolicySnapshot:
    strategy_code: str
    strategy_version: str
    indicator_versions: tuple[str, ...]
    formal_policy_ids: tuple[str, ...]
    profile_id: str
    confirmed_only: bool
    execution_timing: str
    cost_model_version: str
    research_status: str
    schema_version: str = SCHEMA_VERSION
    frozen_legacy: bool = False
    cost_parameters: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["indicator_versions"] = list(self.indicator_versions)
        payload["formal_policy_ids"] = list(self.formal_policy_ids)
        return payload


def is_frozen_jm_v1b(strategy_code: str | None, strategy_version: str | None) -> bool:
    return strategy_code == JM_V1B_STRATEGY_CODE and strategy_version == JM_V1B_STRATEGY_VERSION


def is_htdy_strict_candidate(strategy_code: str | None, strategy_version: str | None) -> bool:
    return strategy_code == HTDY_STRICT_STRATEGY_CODE and strategy_version == HTDY_STRICT_STRATEGY_VERSION


def build_frozen_jm_v1b_policy_snapshot(
    *,
    profile_id: str,
    execution_timing: str = "next_bar_open",
    cost_parameters: Mapping[str, Any] | None = None,
) -> StrategyIndicatorPolicySnapshot:
    require_formal_policy(JM_V1B_FROZEN_POLICY_ID)
    return StrategyIndicatorPolicySnapshot(
        strategy_code=JM_V1B_STRATEGY_CODE,
        strategy_version=JM_V1B_STRATEGY_VERSION,
        indicator_versions=("ema21", "macd", "atr"),
        formal_policy_ids=(JM_V1B_FROZEN_POLICY_ID, "ema_first_value_legacy_v1", "quantcore_atr_ema_first_tr_v1"),
        profile_id=profile_id,
        confirmed_only=True,
        execution_timing=execution_timing,
        cost_model_version=COST_MODEL_VERSION,
        research_status="frozen_legacy",
        frozen_legacy=True,
        cost_parameters=dict(cost_parameters or {}),
    )


def build_htdy_strict_policy_snapshot(
    *,
    profile_id: str,
    execution_timing: str = "next_bar_open",
    cost_parameters: Mapping[str, Any] | None = None,
    strategy_parameters: Mapping[str, Any] | None = None,
) -> StrategyIndicatorPolicySnapshot:
    params = dict(strategy_parameters or {})
    indicator_versions = _as_str_tuple(params.get("indicator_versions") or [params.get("indicator_version") or HTDY_STRICT_INDICATOR])
    formal_policy_ids = _as_str_tuple(params.get("formal_policy_ids") or [HTDY_STRICT_INDICATOR])
    snapshot = StrategyIndicatorPolicySnapshot(
        strategy_code=HTDY_STRICT_STRATEGY_CODE,
        strategy_version=HTDY_STRICT_STRATEGY_VERSION,
        indicator_versions=indicator_versions,
        formal_policy_ids=formal_policy_ids,
        profile_id=profile_id,
        confirmed_only=bool(params.get("confirmed_only", True)),
        execution_timing=str(params.get("execution_timing") or execution_timing),
        cost_model_version=str(params.get("cost_model_version") or COST_MODEL_VERSION),
        research_status=str(params.get("research_status") or "backtest_candidate"),
        frozen_legacy=False,
        cost_parameters=dict(cost_parameters or {}),
    )
    return require_formal_strategy_indicator_policy(snapshot.to_dict())


def require_formal_strategy_indicator_policy(
    raw: Mapping[str, Any] | StrategyIndicatorPolicySnapshot | None,
) -> StrategyIndicatorPolicySnapshot:
    if raw is None:
        raise ValueError("STRATEGY_INDICATOR_POLICY_REQUIRED: formal strategy missing indicator policy snapshot")
    if isinstance(raw, StrategyIndicatorPolicySnapshot):
        payload = raw.to_dict()
    else:
        payload = dict(raw)

    missing = [field for field in _REQUIRED_FIELDS if field not in payload or payload[field] in (None, "", [], ())]
    if missing:
        raise ValueError(
            "STRATEGY_INDICATOR_POLICY_REQUIRED: missing fields: " + ", ".join(missing)
        )

    if payload.get("schema_version") not in (None, SCHEMA_VERSION):
        raise ValueError(
            f"STRATEGY_INDICATOR_POLICY_INVALID: unsupported schema_version={payload.get('schema_version')!r}"
        )

    indicator_versions = _as_str_tuple(payload["indicator_versions"])
    formal_policy_ids = _as_str_tuple(payload["formal_policy_ids"])
    if not indicator_versions:
        raise ValueError("STRATEGY_INDICATOR_POLICY_REQUIRED: indicator_versions cannot be empty")
    if not formal_policy_ids:
        raise ValueError("STRATEGY_INDICATOR_POLICY_REQUIRED: formal_policy_ids cannot be empty")

    for code in indicator_versions:
        resolved = resolve_indicator_code(code)
        if resolved in HTDY_ORIGINAL_CODES or code in HTDY_ORIGINAL_CODES:
            if payload.get("strategy_code") == HTDY_STRICT_STRATEGY_CODE:
                raise ValueError(
                    "STRATEGY_INDICATOR_POLICY_INVALID: huotian_dayou_strict cannot bind original_v0"
                )
        try:
            get_indicator(code)
        except KeyError as exc:
            raise ValueError(f"STRATEGY_INDICATOR_POLICY_UNKNOWN_INDICATOR: {code}") from exc

    for policy_id in formal_policy_ids:
        try:
            require_formal_policy(policy_id)
        except KeyError as exc:
            raise ValueError(f"STRATEGY_INDICATOR_POLICY_UNKNOWN_POLICY: {policy_id}") from exc

    if payload.get("strategy_code") == HTDY_STRICT_STRATEGY_CODE:
        if HTDY_STRICT_INDICATOR not in indicator_versions:
            raise ValueError(
                "STRATEGY_INDICATOR_POLICY_INVALID: huotian_dayou_strict must include huotian_dayou_strict_v1"
            )
        if HTDY_STRICT_INDICATOR not in formal_policy_ids:
            raise ValueError(
                "STRATEGY_INDICATOR_POLICY_INVALID: huotian_dayou_strict must bind formal_policy_id huotian_dayou_strict_v1"
            )
        forbidden = HTDY_ORIGINAL_CODES.intersection(set(indicator_versions) | set(formal_policy_ids))
        if forbidden:
            raise ValueError(
                "STRATEGY_INDICATOR_POLICY_INVALID: huotian_dayou_strict cannot bind original_v0"
            )

    return StrategyIndicatorPolicySnapshot(
        strategy_code=str(payload["strategy_code"]),
        strategy_version=str(payload["strategy_version"]),
        indicator_versions=indicator_versions,
        formal_policy_ids=formal_policy_ids,
        profile_id=str(payload["profile_id"]),
        confirmed_only=bool(payload["confirmed_only"]),
        execution_timing=str(payload["execution_timing"]),
        cost_model_version=str(payload["cost_model_version"]),
        research_status=str(payload["research_status"]),
        schema_version=SCHEMA_VERSION,
        frozen_legacy=bool(payload.get("frozen_legacy", False)),
        cost_parameters=dict(payload.get("cost_parameters") or {}),
    )


def build_formal_strategy_indicator_policy(
    *,
    strategy_code: str | None,
    strategy_version: str | None,
    profile_id: str,
    execution_timing: str,
    strategy_parameters: Mapping[str, Any] | None = None,
    cost_parameters: Mapping[str, Any] | None = None,
    explicit_snapshot: Mapping[str, Any] | None = None,
) -> StrategyIndicatorPolicySnapshot:
    """Build and validate policy for a formal backtest create path."""

    if is_frozen_jm_v1b(strategy_code, strategy_version):
        return build_frozen_jm_v1b_policy_snapshot(
            profile_id=profile_id,
            execution_timing=execution_timing,
            cost_parameters=cost_parameters,
        )
    if is_htdy_strict_candidate(strategy_code, strategy_version):
        return build_htdy_strict_policy_snapshot(
            profile_id=profile_id,
            execution_timing=execution_timing,
            cost_parameters=cost_parameters,
            strategy_parameters=strategy_parameters,
        )
    if explicit_snapshot is not None:
        payload = dict(explicit_snapshot)
        payload.setdefault("strategy_code", strategy_code)
        payload.setdefault("strategy_version", strategy_version)
        payload.setdefault("profile_id", profile_id)
        payload.setdefault("execution_timing", execution_timing)
        payload.setdefault("cost_model_version", COST_MODEL_VERSION)
        if cost_parameters:
            payload.setdefault("cost_parameters", dict(cost_parameters))
        return require_formal_strategy_indicator_policy(payload)

    params = dict(strategy_parameters or {})
    if any(key in params for key in ("formal_policy_ids", "indicator_versions", "indicator_policy_snapshot")):
        nested = params.get("indicator_policy_snapshot")
        if isinstance(nested, Mapping):
            return build_formal_strategy_indicator_policy(
                strategy_code=strategy_code,
                strategy_version=strategy_version,
                profile_id=profile_id,
                execution_timing=execution_timing,
                strategy_parameters=params,
                cost_parameters=cost_parameters,
                explicit_snapshot=nested,
            )
        payload = {
            "strategy_code": strategy_code,
            "strategy_version": strategy_version,
            "indicator_versions": params.get("indicator_versions"),
            "formal_policy_ids": params.get("formal_policy_ids"),
            "profile_id": params.get("profile_id") or profile_id,
            "confirmed_only": params.get("confirmed_only", True),
            "execution_timing": params.get("execution_timing") or execution_timing,
            "cost_model_version": params.get("cost_model_version") or COST_MODEL_VERSION,
            "research_status": params.get("research_status") or "formal_candidate",
            "cost_parameters": dict(cost_parameters or {}),
        }
        return require_formal_strategy_indicator_policy(payload)

    raise ValueError(
        "STRATEGY_INDICATOR_POLICY_REQUIRED: new formal strategy must declare indicator policy metadata"
    )


def resolve_report_indicator_policy(
    metadata_or_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Read-path resolver; never invents current Registry for legacy reports."""

    if not isinstance(metadata_or_summary, Mapping):
        return {
            "status": STATUS_LEGACY_UNAVAILABLE,
            "snapshot": None,
            "reason": "report metadata missing",
        }

    metadata = metadata_or_summary
    if "report_metadata" in metadata and isinstance(metadata.get("report_metadata"), Mapping):
        metadata = metadata["report_metadata"]  # type: ignore[assignment]

    snapshot = metadata.get("indicator_policy_snapshot")
    if not isinstance(snapshot, Mapping) or not snapshot:
        return {
            "status": STATUS_LEGACY_UNAVAILABLE,
            "snapshot": None,
            "reason": "indicator_policy_snapshot absent; do not infer from current Registry",
        }
    return {
        "status": STATUS_AVAILABLE,
        "snapshot": dict(snapshot),
        "reason": None,
    }


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None and str(item).strip())
    raise ValueError(f"STRATEGY_INDICATOR_POLICY_INVALID: expected list/tuple of strings, got {type(value)!r}")
