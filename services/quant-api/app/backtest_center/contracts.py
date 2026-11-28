from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2

from app.strategy_center.catalog import CATALOG

from .errors import BacktestError as BacktestError
from .plus_costs import RESEARCH_PROFILE

TREND = NEWOW_TREND_D1_PAGE_V2
EXECUTION_POLICY = "single_physical_long_next_same_session_1m_v1"
DELAY_PARAMETER = "execution_delay_minutes"


Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Policy = Annotated[str, Field(max_length=96, pattern=r"^[A-Za-z0-9_-]+$")]
Frequency = Literal["5m", "15m", "30m", "60m", "1d", "1w"]
Status = Literal["QUEUED", "RUNNING", "CANCELING", "SUCCEEDED", "FAILED", "CANCELED"]


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    strategy_id: Policy = "newow_trend"
    formula_version: Policy | None = None
    profile_id: Policy | None = None
    product: str = Field(pattern=r"^[a-zA-Z]{1,8}$")
    contract: str = Field(pattern=r"^[a-zA-Z]{1,8}[0-9]{3,4}$")
    warmup_start: date
    start: date
    end: date
    signal_frequency: Frequency = "5m"
    execution_frequency: Literal["1m"] = "1m"
    initial_capital: Decimal = Field(default=Decimal("100000"), ge=1, le=1_000_000_000, decimal_places=2)
    commission_multiplier: Decimal = Field(default=Decimal("1"), ge=0, le=10, decimal_places=4)
    slippage_ticks: int = Field(default=0, ge=0, le=20, strict=True)
    parameters: dict[Policy, Decimal] = Field(default_factory=dict, max_length=8)
    sample_type: Literal["historical", "experiment", "train", "oos"] = "historical"
    benchmark: Literal["cash"] = "cash"
    contract_selection: Literal["physical", "dominant"] = "physical"
    rollover_policy: Literal["interrupt"] = "interrupt"

    @model_validator(mode="after")
    def resolve(self):
        if self.strategy_id not in CATALOG:
            raise ValueError("STRATEGY_NOT_FOUND")
        product, contract = self.product.lower(), self.contract.upper()
        if contract.rstrip("0123456789").lower() != product:
            raise ValueError("PHYSICAL_CONTRACT_PRODUCT_MISMATCH")
        if not date(2000, 1, 1) <= self.warmup_start < self.start <= self.end:
            raise ValueError("BACKTEST_WINDOW_INVALID")
        if (self.end - self.warmup_start).days > 730:
            raise ValueError("BACKTEST_WINDOW_TOO_LARGE")
        object.__setattr__(self, "product", product)
        object.__setattr__(self, "contract", contract)
        for field in ("initial_capital", "commission_multiplier"):
            value = format(getattr(self, field), "f")
            if "." in value:
                value = value.rstrip("0").rstrip(".")
            object.__setattr__(self, field, Decimal(value))
        if DELAY_PARAMETER in self.parameters:
            delay = self.parameters[DELAY_PARAMETER]
            if delay != delay.to_integral_value() or not 0 <= delay <= 3:
                raise ValueError("BACKTEST_EXECUTION_DELAY_OUT_OF_RANGE")
            parameters = {name: value for name, value in self.parameters.items() if name != DELAY_PARAMETER}
            if delay:
                parameters[DELAY_PARAMETER] = Decimal(int(delay))
            object.__setattr__(self, "parameters", parameters)
        if self.strategy_id == "newow_trend":
            object.__setattr__(self, "formula_version", self.formula_version or TREND.trend_band_formula)
            object.__setattr__(self, "profile_id", self.profile_id or TREND.profile_id)
        return self


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: Key
    config: RunConfig


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: Key


class TemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    config: RunConfig


REASONS = {
    "newow_oscillation": "OSCILLATION_SAME_BAR_POLICY_UNVERIFIED",
    "newow_main_rise": "MAIN_RISE_REDUCTION_POLICY_UNVERIFIED",
    "newow_dual_fusion": "FUSION_INPUT_AND_EXECUTION_POLICY_UNVERIFIED",
    "htdy_60m": "HTDY_LOOKBACK_REPAINTS",
    "subing_portfolio_16": "SUBING_DOMAIN_REPLAY_AND_PAPER",
}


def eligibility() -> list[dict]:
    items = []
    for strategy in CATALOG.values():
        key = strategy.strategy_id
        trend = key == "newow_trend"
        items.append({
            "strategy_id": key, "label": strategy.name,
            "status": "TRIAL" if trend else "UNAVAILABLE",
            "reason": "PLUS_INPUT_AND_EXECUTION_COVERAGE_REQUIRED" if trend else REASONS[key],
            "formula_version": TREND.trend_band_formula if trend else None,
            "profile_id": TREND.profile_id if trend else None,
            "research_profile_id": RESEARCH_PROFILE if trend else None,
            "product": "fu" if trend else None, "signal_frequency": "5m" if trend else None,
            "execution_frequency": "1m" if trend else None, "dependencies": strategy.dependencies,
            "research_parameters": {DELAY_PARAMETER: {"default": 0, "min": 0, "max": 3}} if trend else {},
            "links": {"history": "/research/subing-decision?mode=history", "paper": "/research/subing-decision"}
            if key == "subing_portfolio_16" else {},
        })
    return items


def admission_code(config: RunConfig) -> str | None:
    if config.strategy_id != "newow_trend":
        return REASONS[config.strategy_id]
    if config.contract_selection == "dominant":
        return "POINT_IN_TIME_RANK1_EVIDENCE_MISSING"
    if config.formula_version != TREND.trend_band_formula or config.profile_id != TREND.profile_id:
        return "STRATEGY_FORMULA_OR_PROFILE_UNVERIFIED"
    if config.product != "fu" or config.signal_frequency != "5m":
        return "STRATEGY_COMBINATION_UNVERIFIED"
    if any(name != DELAY_PARAMETER for name in config.parameters):
        return "STRATEGY_PARAMETERS_UNSUPPORTED"
    return None
