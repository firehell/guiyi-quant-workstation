"""Source-owned indicators keep their existing typed inputs and calculation policies."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime
from functools import partial
from types import MappingProxyType

from .. import subing_recent_structure
from ..indicators import subing_conditions, subing_macd, subing_price, subing_range, subing_trend, subing_volume
from ..indicators.htdy_original import INDICATOR_VERSION as HTDY_VERSION, compute_htdy_original
from ..indicators.htdy_strict import BOOLEAN_FIELDS, NUMERIC_FIELDS, compute_strict_fields
from ..indicators.policy import HTDY_ALERT_OBSERVATION_CONSUMER
from ..indicators.range_detector_lux import RANGE_DETECTOR_LUX_VERSION, range_detector_lux_series
from ..indicators.registry import get_indicator
from ..indicators.subing_ths import SUBING_THS_FORMULA_VERSIONS, SubingThs15mKernel
from ..newow.cup_handle import CupReadyWitness
from ..newow.profile import NEWOW_TREND_D1_V1
from ..newow.product_auxiliary import AuxiliaryLayer, calculate_auxiliary_component
from ..newow.product_contracts import ProductBar, ProductIdentity
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
SUBING_PAPER_FACTOR_USE = "subing_paper_factor"


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
    optional_outputs: tuple[str, ...] = ()


def _newow_display_calculator(name: str) -> Callable:
    def calculate(
        identity: ProductIdentity, bars: tuple[ProductBar, ...], *, as_of: datetime | None = None,
    ) -> AuxiliaryLayer[object]:
        return calculate_auxiliary_component(identity, bars, name, as_of=as_of)

    return calculate


def _newow_auxiliary(name, formula_version, data_type, *, repainting=False):
    return OwnedIndicatorDefinition(
        feature_id=f"newow.{name}", formula_version=formula_version,
        input_schema_version="newow_product_bars_v1", output_schema_version="newow_auxiliary_v1",
        outputs=tuple(field for field in data_type.__dataclass_fields__ if field != "formula_version"),
        supported_frequencies=FREQUENCIES - {"1m"},
        allowed_uses=frozenset(("web",)), repainting=repainting,
        calculate=_newow_display_calculator(name),
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


def _subing_paper_factor(
    name, version, outputs, *, optional_outputs=(), frequencies=("30m",), calculate=None, step=None, initial_state=None,
) -> OwnedIndicatorDefinition:
    return OwnedIndicatorDefinition(
        feature_id=f"subing_paper.{name}", formula_version=version,
        input_schema_version=f"subing_paper_{name}_input_v1",
        output_schema_version=f"subing_paper_{name}_result_v1",
        outputs=outputs, supported_frequencies=frozenset(frequencies),
        allowed_uses=frozenset((SUBING_PAPER_FACTOR_USE,)), repainting=False,
        calculate=calculate, step=step, initial_state=initial_state, optional_outputs=optional_outputs,
    )


def _paper_trend_state(contract: str, frequency: str):
    return subing_trend.initial_state(contract, frequency)


def _require_paper_m30(frequency: str) -> None:
    if frequency != "30m":
        raise ValueError("SUBING_PAPER_FACTOR_FREQUENCY_UNSUPPORTED")


def _paper_m30_state(initializer, contract: str, frequency: str):
    _require_paper_m30(frequency)
    return initializer(contract, frequency)


def _paper_pullback_state(contract: str, frequency: str, *, side: str = "LONG"):
    _require_paper_m30(frequency)
    if side not in ("LONG", "SHORT"):
        raise ValueError("PRICE_SIDE_INVALID")
    return subing_price.PullbackState(contract, side=side)


def _paper_structure_state(contract: str, frequency: str):
    _require_paper_m30(frequency)
    return subing_recent_structure.State(contract)


_SUBING_PAPER_FACTORS = (
    _subing_paper_factor(
        "trend", subing_trend.VERSION, tuple(field.name for field in fields(subing_trend.TrendPoint)),
        frequencies=("1d", "30m", "60m"), step=subing_trend.step, initial_state=_paper_trend_state,
    ),
    _subing_paper_factor(
        "macd", subing_macd.VERSION, tuple(field.name for field in fields(subing_macd.CrossPoint)),
        step=subing_macd.step, initial_state=partial(_paper_m30_state, subing_macd.initial_state),
    ),
    _subing_paper_factor(
        "volume", subing_volume.VERSION, tuple(field.name for field in fields(subing_volume.VolumeObservation)),
        step=subing_volume.observe, initial_state=partial(_paper_m30_state, subing_volume.initial_state),
    ),
    _subing_paper_factor(
        "price", subing_price.VERSION, tuple(field.name for field in fields(subing_price.PricePoint)),
        calculate=subing_price.price_point,
    ),
    _subing_paper_factor(
        "pullback", subing_price.VERSION,
        ("touch", "hold", "breakout", "breakout_source", "breakout_high", "invalidated", "replaced",
         "armed_at", "armed_high", "lower", "upper", "reason", "qualified_hold", "background_at",
         "background_close", "from_above", "trend_direction", "background_reset"),
        optional_outputs=("next_background_at", "next_background_close"),
        step=subing_price.observe, initial_state=_paper_pullback_state,
    ),
    _subing_paper_factor(
        "range", subing_range.VERSION, tuple(field.name for field in fields(subing_range.Point)),
        step=subing_range.step, initial_state=partial(_paper_m30_state, subing_range.initial_state),
    ),
    _subing_paper_factor(
        "structure", subing_recent_structure.VERSION,
        ("phase", "reason"),
        optional_outputs=("lower", "upper", "boundary_at", "break_side", "count", "structure_direction", "pivot_confirmed_now"),
        step=subing_recent_structure.step, initial_state=_paper_structure_state,
    ),
    _subing_paper_factor(
        "exit_facts", subing_conditions.VERSION, ("previous_low", "below_previous_low", "below_ema", "high_death"),
        calculate=subing_conditions.exit_facts,
    ),
)


_DEFINITIONS = (
    _newow_auxiliary("main_force_control", MAIN_FORCE_CONTROL_FORMULA_VERSION, MainForceControlResult),
    _newow_auxiliary("up_down_energy", UP_DOWN_ENERGY_FORMULA_VERSION, UpDownEnergyResult),
    _newow_auxiliary("trend_reversal", TREND_REVERSAL_FORMULA_VERSION, TrendReversalResult),
    _newow_auxiliary("zhaoyao_mirror", ZHAOYAO_MIRROR_FORMULA_VERSION, ZhaoyaoMirrorResult, repainting=True),
    OwnedIndicatorDefinition(
        "newow.cup_handle", NEWOW_TREND_D1_V1.cup_handle_formula,
        "newow_product_bars_v1", "newow_cup_handle_witnesses_v1",
        tuple(field.name for field in fields(CupReadyWitness)),
        # The display envelope retains NOT_APPLICABLE for inactive strategy/period pairs.
        FREQUENCIES - {"1m"}, frozenset(("web",)),
        False, _newow_display_calculator("cup_handle"),
    ),
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
    *_SUBING_PAPER_FACTORS,
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


def subing_paper_factors(frequency: str) -> tuple[OwnedIndicatorDefinition, ...]:
    """Return only the factors used by the existing Paper model at this frequency."""
    factors = tuple(item for item in _SUBING_PAPER_FACTORS if frequency in item.supported_frequencies)
    if not factors:
        raise ValueError("SUBING_PAPER_FACTOR_FREQUENCY_UNSUPPORTED")
    return factors
