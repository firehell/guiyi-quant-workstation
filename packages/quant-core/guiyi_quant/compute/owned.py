"""Source-owned indicators keep their existing typed inputs and calculation policies."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType

from ..indicators.htdy_original import INDICATOR_VERSION as HTDY_VERSION, compute_htdy_original
from ..indicators.htdy_strict import BOOLEAN_FIELDS, NUMERIC_FIELDS, compute_strict_fields
from ..indicators.policy import HTDY_ALERT_OBSERVATION_CONSUMER
from ..indicators.range_detector_lux import RANGE_DETECTOR_LUX_VERSION, range_detector_lux_series
from ..indicators.registry import get_indicator
from ..indicators.subing_ths import SUBING_THS_FORMULA_VERSIONS, SubingThs15mKernel
from ..newow.product_auxiliary import calculate_auxiliary_component
from ..newow.subplots import (
    MAIN_FORCE_CONTROL_FORMULA_VERSION,
    UP_DOWN_ENERGY_FORMULA_VERSION,
    ZHAOYAO_MIRROR_FORMULA_VERSION,
    MainForceControlResult,
    UpDownEnergyResult,
    ZhaoyaoMirrorResult,
)
from ..newow.trend_reversal import TREND_REVERSAL_FORMULA_VERSION, TrendReversalResult
from .contracts import FREQUENCIES

SUBING_THS_OBSERVATION_USE = "subing_ths_observation"
SUBING_THS_REFERENCE_USE = "subing_reference"


@dataclass(frozen=True, slots=True)
class OwnedIndicatorDefinition:
    feature_id: str
    formula_version: str
    input_schema_version: str
    output_schema_version: str
    outputs: tuple[str, ...]
    supported_frequencies: frozenset[str]
    allowed_uses: frozenset[str]
    repainting: bool
    calculate: Callable | None
    step: Callable | None = None
    initial_state: Callable | None = None


def _newow_auxiliary(name, formula_version, data_type, *, repainting=False):
    return OwnedIndicatorDefinition(
        feature_id=f"newow.{name}", formula_version=formula_version,
        input_schema_version="newow_product_bars_v1", output_schema_version="newow_auxiliary_v1",
        outputs=tuple(field for field in data_type.__dataclass_fields__ if field != "formula_version"),
        supported_frequencies=FREQUENCIES - {"1m"},
        allowed_uses=frozenset(("web",)), repainting=repainting,
        calculate=partial(calculate_auxiliary_component, component=name),
    )


_HTDY_STRICT = get_indicator("huotian_dayou_strict_v1")


def _subing_ths(frequency: str) -> OwnedIndicatorDefinition:
    kernel = SubingThs15mKernel(frequency=frequency)
    uses = {SUBING_THS_OBSERVATION_USE, SUBING_THS_REFERENCE_USE}
    if frequency == "15m":
        uses.add("research")
    result_version = "v3" if frequency == "15m" else "v1"
    return OwnedIndicatorDefinition(
        feature_id=f"subing_ths_{frequency}",
        formula_version=kernel.formula_version,
        input_schema_version=f"subing_ths_{frequency}_input_v1",
        output_schema_version=f"subing_ths_{frequency}_result_{result_version}",
        outputs=("dif", "dea", "macd", "ema21", "result_codes"),
        supported_frequencies=frozenset({frequency}),
        allowed_uses=frozenset(uses),
        repainting=False,
        calculate=None,
        step=kernel.step,
        initial_state=kernel.initial_state,
    )


_DEFINITIONS = (
    _newow_auxiliary("main_force_control", MAIN_FORCE_CONTROL_FORMULA_VERSION, MainForceControlResult),
    _newow_auxiliary("up_down_energy", UP_DOWN_ENERGY_FORMULA_VERSION, UpDownEnergyResult),
    _newow_auxiliary("trend_reversal", TREND_REVERSAL_FORMULA_VERSION, TrendReversalResult),
    _newow_auxiliary("zhaoyao_mirror", ZHAOYAO_MIRROR_FORMULA_VERSION, ZhaoyaoMirrorResult, repainting=True),
    OwnedIndicatorDefinition(
        "range_detector_lux", RANGE_DETECTOR_LUX_VERSION, "range_detector_ohlc_v1",
        "range_detector_v1", ("points", "ranges"), FREQUENCIES, frozenset(("web",)),
        False, range_detector_lux_series,
    ),
    OwnedIndicatorDefinition(
        "htdy_original", HTDY_VERSION, "htdy_original_ohlcv_v1", "htdy_original_observation_v1",
        ("zk1", "zd1", "zd2", "yellow_candle", "white_candle", "buy_observation", "sell_observation",
         "observation_conflict"),
        FREQUENCIES, frozenset(("web", HTDY_ALERT_OBSERVATION_CONSUMER)), True, compute_htdy_original,
    ),
    OwnedIndicatorDefinition(
        "htdy_strict", _HTDY_STRICT.indicator_version, "htdy_strict_ohlcv_v1", "htdy_strict_research_v1",
        (*NUMERIC_FIELDS, *BOOLEAN_FIELDS), FREQUENCIES, frozenset(("research", "backtest")),
        False, compute_strict_fields,
    ),
    *(_subing_ths(frequency) for frequency in SUBING_THS_FORMULA_VERSIONS),
)

OWNED_DEFINITIONS = MappingProxyType({item.feature_id: item for item in _DEFINITIONS})


def owned_indicator(feature_id: str, *, frequency: str, use: str) -> OwnedIndicatorDefinition:
    definition = OWNED_DEFINITIONS.get(feature_id)
    if definition is None:
        raise ValueError(f"UNSUPPORTED_OWNED_FEATURE: {feature_id}")
    if frequency not in definition.supported_frequencies or use not in definition.allowed_uses:
        raise ValueError(f"FEATURE_USE_NOT_ALLOWED: {feature_id}")
    return definition


def subing_ths_state_step(frequency: str, *, use: str) -> tuple[Callable, Callable]:
    feature = owned_indicator(f"subing_ths_{frequency}", frequency=frequency, use=use)
    if (
        feature.formula_version != SUBING_THS_FORMULA_VERSIONS[frequency]
        or feature.repainting
        or feature.initial_state is None
        or feature.step is None
    ):
        raise ValueError("SUBING_THS_REGISTRATION_MISMATCH")
    return feature.initial_state, feature.step
