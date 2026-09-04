"""Diagnostic tokens and page-only ranking isolated from trusted OOS results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import floor, log1p
from types import MappingProxyType
from typing import Literal

from .diagnostic_facts import DiagnosticFacts
from .models import CupHandleState, TrendBandState
from .oscillation_channel import OSCILLATION_FORMULA_VERSION
from .price_channel import PageSignalState
from .profile import NEWOW_TREND_D1_PAGE_V2
from .research_backtest import ResearchStrategy
from .research_walk_forward import WalkForwardValidationResult
from .subplots import MainForceStatus


DIAGNOSTIC_RULES_CLEANROOM_V1 = "newow_diagnostic_rules_cleanroom_v1"
AI_SIX_COMBO_PAGE_V3250 = "newow_ai_six_combo_page_v3_2_50"
AI_WEEK_DAY_16_MATRIX_PAGE_V1 = "newow_ai_week_day_16_matrix_page_v1"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    RISK = "risk"


class PageAiPeriod(StrEnum):
    WEEK = "week"
    DAY = "day"
    SIXTY_MINUTE = "60min"


class PageAiStrategy(StrEnum):
    OSCILLATION = "oscillation"
    TREND = "trend"


@dataclass(frozen=True, slots=True)
class DiagnosticToken:
    code: str
    severity: DiagnosticSeverity
    fact_keys: tuple[str, ...]
    formula_identities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageAiCombination:
    period: PageAiPeriod
    strategy: PageAiStrategy
    cumulative_return_pct: Decimal
    max_drawdown_pct: Decimal
    accuracy_pct: Decimal
    trade_count: int
    formula_version: str

    def __post_init__(self) -> None:
        values = (
            self.cumulative_return_pct,
            self.max_drawdown_pct,
            self.accuracy_pct,
        )
        if (
            not isinstance(self.period, PageAiPeriod)
            or not isinstance(self.strategy, PageAiStrategy)
            or any(not isinstance(value, Decimal) or not value.is_finite() for value in values)
            or self.max_drawdown_pct < 0
            or not Decimal(0) <= self.accuracy_pct <= Decimal(100)
            or type(self.trade_count) is not int
            or self.trade_count < 0
            or not self.formula_version
        ):
            raise ValueError("NEWOW_PAGE_AI_COMBINATION_INVALID")


@dataclass(frozen=True, slots=True)
class PageAiScoredCombination:
    combination: PageAiCombination
    score: Decimal
    input_order: int


@dataclass(frozen=True, slots=True)
class PageAiRanking:
    ranked: tuple[PageAiScoredCombination, ...]
    discarded_trade_count: int
    trustworthy_for_research: Literal[False] = False
    formula_version: str = AI_SIX_COMBO_PAGE_V3250


@dataclass(frozen=True, slots=True)
class OosCandidateAssessment:
    strategy: ResearchStrategy
    signal_formula_versions: tuple[str, ...]
    fold_count: int
    closed_trade_count: int
    compounded_net_return_pct: Decimal
    trustworthy_for_research: Literal[True] = True


_PAGE_AI_MATRIX = MappingProxyType(
    {
        (weekly, daily): (
            f"NEWOW_DIAG_AI_MATRIX_{weekly.value.upper()}_{daily.value.upper()}"
        )
        for weekly in PageSignalState
        for daily in PageSignalState
    }
)


def _token(
    code: str,
    severity: DiagnosticSeverity,
    fact_keys: tuple[str, ...],
    identities: tuple[str, ...],
) -> DiagnosticToken:
    return DiagnosticToken(code, severity, fact_keys, identities)


def diagnostic_tokens(facts: DiagnosticFacts) -> tuple[DiagnosticToken, ...]:
    if not isinstance(facts, DiagnosticFacts):
        raise ValueError("NEWOW_DIAGNOSTIC_FACTS_INVALID")
    identity = (DIAGNOSTIC_RULES_CLEANROOM_V1, *facts.formula_versions)
    tokens: list[DiagnosticToken] = []

    trend_severity = (
        DiagnosticSeverity.INFO
        if facts.trend_state is TrendBandState.YELLOW
        else DiagnosticSeverity.RISK
        if facts.trend_state is TrendBandState.BLUE
        else DiagnosticSeverity.WARNING
    )
    tokens.append(
        _token(
            f"NEWOW_DIAG_TREND_{facts.trend_state.value}",
            trend_severity,
            ("trend_state", "trend_duration_bars"),
            identity,
        )
    )

    if facts.target_price is not None:
        tokens.append(
            _token(
                "NEWOW_DIAG_CHANNEL_TARGET",
                DiagnosticSeverity.INFO,
                ("target_price", "target_distance_pct"),
                identity,
            )
        )
    if facts.absorb_price is not None:
        tokens.append(
            _token(
                "NEWOW_DIAG_CHANNEL_ABSORB",
                DiagnosticSeverity.INFO,
                ("absorb_price", "absorb_distance_pct"),
                identity,
            )
        )
    if facts.ema20 is not None:
        tokens.append(
            _token(
                f"NEWOW_DIAG_OPERATOR_LINE_{facts.close_vs_ema20.upper()}",
                DiagnosticSeverity.INFO,
                ("ema20", "close_vs_ema20"),
                identity,
            )
        )
    if facts.main_force_status is not None:
        force_risk = facts.main_force_status in {
            MainForceStatus.DISTRIBUTION,
            MainForceStatus.HIGH_CONTROL_DISTRIBUTION,
        }
        tokens.append(
            _token(
                f"NEWOW_DIAG_MAIN_FORCE_{facts.main_force_status.name}",
                DiagnosticSeverity.RISK if force_risk else DiagnosticSeverity.INFO,
                ("main_force_status",),
                identity,
            )
        )
    if facts.main_rise_active is not None:
        tokens.append(
            _token(
                "NEWOW_DIAG_MAIN_RISE_ACTIVE"
                if facts.main_rise_active
                else "NEWOW_DIAG_MAIN_RISE_INACTIVE",
                DiagnosticSeverity.INFO if facts.main_rise_active else DiagnosticSeverity.WARNING,
                ("main_rise_active",),
                identity,
            )
        )
    if facts.cup_state is not None:
        tokens.append(
            _token(
                f"NEWOW_DIAG_CUP_{facts.cup_state.value}",
                DiagnosticSeverity.INFO
                if facts.cup_state in {CupHandleState.READY, CupHandleState.BREAKOUT}
                else DiagnosticSeverity.WARNING,
                ("cup_state",),
                identity,
            )
        )
    if facts.trend_state is TrendBandState.BLUE and facts.oscillation_holding:
        tokens.append(
            _token(
                "NEWOW_DIAG_RISK_TREND_OSCILLATION_CONFLICT",
                DiagnosticSeverity.RISK,
                ("trend_state", "oscillation_holding"),
                identity,
            )
        )
    if facts.weekly_signal is not None and facts.daily_signal is not None:
        code = _PAGE_AI_MATRIX[(facts.weekly_signal, facts.daily_signal)]
        tokens.append(
            _token(
                code,
                DiagnosticSeverity.INFO,
                ("weekly_signal", "daily_signal"),
                (AI_WEEK_DAY_16_MATRIX_PAGE_V1,),
            )
        )
    if any(
        value is None
        for value in (
            facts.ema20,
            facts.target_price,
            facts.absorb_price,
            facts.oscillation_holding,
            facts.main_force_status,
            facts.main_rise_active,
        )
    ):
        tokens.append(
            _token(
                "NEWOW_DIAG_DATA_INSUFFICIENT",
                DiagnosticSeverity.WARNING,
                ("formula_versions",),
                identity,
            )
        )
    return tuple(tokens)


def _expected_formula(strategy: PageAiStrategy) -> str:
    if strategy is PageAiStrategy.OSCILLATION:
        return OSCILLATION_FORMULA_VERSION
    return NEWOW_TREND_D1_PAGE_V2.trend_band_formula


def _normalized(values: tuple[float, ...]) -> tuple[float, ...]:
    low, high = min(values), max(values)
    if high == low:
        return tuple(0.0 for _ in values)
    return tuple((value - low) / (high - low) for value in values)


def _browser_round4(value: float) -> Decimal:
    rounded = floor(value * 10_000 + 0.5) / 10_000
    return Decimal(str(rounded)).quantize(Decimal("0.0001"))


def rank_page_ai_combinations(
    combinations: tuple[PageAiCombination, ...], *, require_six: bool = True
) -> PageAiRanking:
    if not combinations:
        raise ValueError("NEWOW_PAGE_AI_COMBINATIONS_EMPTY")
    expected_keys = {
        (period, strategy) for period in PageAiPeriod for strategy in PageAiStrategy
    }
    actual_keys = {(item.period, item.strategy) for item in combinations}
    if len(actual_keys) != len(combinations) or (
        require_six and actual_keys != expected_keys
    ):
        raise ValueError("NEWOW_PAGE_AI_COMBINATION_SET_INVALID")
    if any(item.formula_version != _expected_formula(item.strategy) for item in combinations):
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")

    retained = tuple(
        (index, item)
        for index, item in enumerate(combinations)
        if item.trade_count >= 3
    )
    if not retained:
        raise ValueError("NEWOW_PAGE_AI_NO_ELIGIBLE_COMBINATION")
    returns = _normalized(tuple(float(item.cumulative_return_pct) for _, item in retained))
    calmars = _normalized(
        tuple(
            log1p(
                max(
                    0.0,
                    float(item.cumulative_return_pct / item.max_drawdown_pct)
                    if item.max_drawdown_pct > 0
                    else 999.0
                    if item.cumulative_return_pct > 0
                    else 0.0,
                )
            )
            for _, item in retained
        )
    )
    accuracies = _normalized(tuple(float(item.accuracy_pct) for _, item in retained))

    scored: list[PageAiScoredCombination] = []
    for offset, (input_order, item) in enumerate(retained):
        raw = (
            0.40 * returns[offset]
            + 0.35 * calmars[offset]
            + 0.25 * accuracies[offset]
        )
        penalty = 1.0 if item.trade_count >= 10 else 0.85
        scored.append(
            PageAiScoredCombination(
                combination=item,
                score=_browser_round4(raw * penalty),
                input_order=input_order,
            )
        )
    ranked = tuple(
        sorted(
            scored,
            key=lambda item: (
                -item.score,
                -item.combination.trade_count,
                item.input_order,
            ),
        )
    )
    return PageAiRanking(
        ranked=ranked,
        discarded_trade_count=len(combinations) - len(retained),
    )


def assess_oos_candidate(
    result: WalkForwardValidationResult | PageAiRanking,
) -> OosCandidateAssessment:
    if isinstance(result, PageAiRanking):
        raise ValueError("NEWOW_PAGE_OPTIMIZER_UNTRUSTED_RESULT")
    if not isinstance(result, WalkForwardValidationResult):
        raise ValueError("NEWOW_OOS_RESULT_INVALID")
    return OosCandidateAssessment(
        strategy=result.strategy,
        signal_formula_versions=result.signal_formula_versions,
        fold_count=len(result.folds),
        closed_trade_count=result.closed_trade_count,
        compounded_net_return_pct=result.compounded_net_return_pct,
    )
