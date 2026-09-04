"""Evidence-first types for Niuwa screener observations and own candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from math import isfinite
from typing import Literal, TypeAlias

from .main_rise import MAIN_RISE_PAGE_V1
from .models import CupHandleState, TrendBandState
from .profile import NEWOW_TREND_D1_PAGE_V2, NEWOW_TREND_D1_V1


LEGACY_HOMEPAGE_FILTER_V3282 = "newow_legacy_homepage_filter_v3_2_82"
TREND_BUILD_CANDIDATE_V1 = "newow_trend_build_candidate_v1"
MAINRISE_BUILD_CANDIDATE_V1 = "newow_mainrise_build_candidate_v1"
CUP_HANDLE_CANDIDATE_V1 = "newow_cup_handle_candidate_v1"

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
JsonScalar: TypeAlias = str | int | float | bool | None


class ScreenerStrategyId(StrEnum):
    TREND_BUILD = "trend_build"
    MAINRISE_BUILD = "mainrise_build"
    CUP_HANDLE = "cup_handle"
    DAILY_BUY = "daily_buy"
    WEEKLY_BUY = "weekly_buy"
    OSCILLATION_BUILD = "oscillation_build"


class LegacyFilterId(StrEnum):
    YIJIAN_SAN_DIAO = "yijiansandiao"
    DAILY_BUY = "daily_buy"
    WEEKLY_BUY = "weekly_buy"
    HOT_STRONG = "hot_strong"
    START_CONTROL = "start_control"
    DAILY_ACCUM = "daily_accum"
    WEEKLY_ACCUM = "weekly_accum"
    WAVE_ENTRY = "wave_entry"
    TREND_MASTER = "trend_master"


@dataclass(frozen=True, slots=True)
class ScreenerRowFacts:
    symbol: str
    fields: tuple[tuple[str, JsonScalar], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fields, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2 for item in self.fields
        ):
            raise ValueError("NEWOW_SCREENER_ROW_INVALID")
        names = tuple(name for name, _ in self.fields)
        if (
            not isinstance(self.symbol, str)
            or not _SYMBOL.fullmatch(self.symbol)
            or not self.fields
            or len(names) != len(set(names))
            or any(not isinstance(name, str) or not name for name in names)
            or any(
                value is not None
                and not isinstance(value, (str, int, float, bool))
                for _, value in self.fields
            )
            or any(
                isinstance(value, float) and not isfinite(value)
                for _, value in self.fields
            )
            or not self.has_field("code")
            or self.value("code") != self.symbol
        ):
            raise ValueError("NEWOW_SCREENER_ROW_INVALID")

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> ScreenerRowFacts:
        code = values.get("code")
        if not isinstance(code, str):
            raise ValueError("NEWOW_SCREENER_ROW_INVALID")
        fields: list[tuple[str, JsonScalar]] = []
        for name, value in values.items():
            if not isinstance(name, str) or not (
                value is None or isinstance(value, (str, int, float, bool))
            ):
                raise ValueError("NEWOW_SCREENER_ROW_INVALID")
            fields.append((name, value))
        return cls(code, tuple(fields))

    def has_field(self, name: str) -> bool:
        return any(field_name == name for field_name, _ in self.fields)

    def value(self, name: str) -> JsonScalar:
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class ScreenerProbeObservation:
    strategy_id: ScreenerStrategyId
    captured_at: datetime
    request_identity: str
    response_sha256: str
    product_version: str
    page_asset_sha256: str
    ordered_symbols: tuple[str, ...]
    rows: tuple[ScreenerRowFacts, ...]
    matching_rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.strategy_id, ScreenerStrategyId)
            or not isinstance(self.captured_at, datetime)
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
            or not isinstance(self.request_identity, str)
            or not _HASH.fullmatch(self.request_identity)
            or not isinstance(self.response_sha256, str)
            or not _HASH.fullmatch(self.response_sha256)
            or not isinstance(self.product_version, str)
            or not self.product_version
            or not isinstance(self.page_asset_sha256, str)
            or not _HASH.fullmatch(self.page_asset_sha256)
            or not isinstance(self.ordered_symbols, tuple)
            or not isinstance(self.rows, tuple)
            or any(not isinstance(row, ScreenerRowFacts) for row in self.rows)
            or not isinstance(self.matching_rule_ids, tuple)
            or len(self.ordered_symbols) != len(set(self.ordered_symbols))
            or self.ordered_symbols != tuple(row.symbol for row in self.rows)
            or any(
                not isinstance(rule_id, str) or not rule_id
                for rule_id in self.matching_rule_ids
            )
            or len(self.matching_rule_ids) != len(set(self.matching_rule_ids))
        ):
            raise ValueError("NEWOW_SCREENER_OBSERVATION_INVALID")


@dataclass(frozen=True, slots=True)
class ScreenerObservationComparison:
    intersection: tuple[str, ...]
    only_left: tuple[str, ...]
    only_right: tuple[str, ...]
    jaccard: Decimal
    stable_field_names: tuple[str, ...]
    intersection_order_stable: bool
    response_changed: bool
    page_asset_changed: bool


@dataclass(frozen=True, slots=True)
class PageExactScreenerRule:
    strategy_id: ScreenerStrategyId
    rule_id: str
    evidence_response_sha256: tuple[str, ...]
    page_parity: Literal[True] = True


def _common_fields(observation: ScreenerProbeObservation) -> set[str]:
    if not observation.rows:
        return set()
    common = {name for name, _ in observation.rows[0].fields}
    for row in observation.rows[1:]:
        common.intersection_update(name for name, _ in row.fields)
    return common


def compare_screener_observations(
    left: ScreenerProbeObservation, right: ScreenerProbeObservation
) -> ScreenerObservationComparison:
    if not isinstance(left, ScreenerProbeObservation) or not isinstance(
        right, ScreenerProbeObservation
    ):
        raise ValueError("NEWOW_SCREENER_COMPARISON_INVALID")
    if left.strategy_id is not right.strategy_id:
        raise ValueError("NEWOW_SCREENER_COMPARISON_STRATEGY_MISMATCH")
    left_set, right_set = set(left.ordered_symbols), set(right.ordered_symbols)
    intersection = tuple(
        symbol for symbol in left.ordered_symbols if symbol in right_set
    )
    right_intersection = tuple(
        symbol for symbol in right.ordered_symbols if symbol in left_set
    )
    union_size = len(left_set | right_set)
    jaccard = (
        Decimal(1)
        if union_size == 0
        else (Decimal(len(intersection)) / Decimal(union_size)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
    )
    return ScreenerObservationComparison(
        intersection=intersection,
        only_left=tuple(
            symbol for symbol in left.ordered_symbols if symbol not in right_set
        ),
        only_right=tuple(
            symbol for symbol in right.ordered_symbols if symbol not in left_set
        ),
        jaccard=jaccard,
        stable_field_names=tuple(sorted(_common_fields(left) & _common_fields(right))),
        intersection_order_stable=intersection == right_intersection,
        response_changed=left.response_sha256 != right.response_sha256,
        page_asset_changed=left.page_asset_sha256 != right.page_asset_sha256,
    )


def infer_page_exact_screener_rule(
    observations: tuple[ScreenerProbeObservation, ...],
) -> PageExactScreenerRule:
    """Promote only uniquely identified behavior across independent dates."""

    if len(observations) < 2:
        raise ValueError("NEWOW_SCREENER_EVIDENCE_INSUFFICIENT")
    if any(not isinstance(item, ScreenerProbeObservation) for item in observations):
        raise ValueError("NEWOW_SCREENER_EVIDENCE_INSUFFICIENT")
    first = observations[0]
    if (
        any(item.strategy_id is not first.strategy_id for item in observations)
        or any(item.request_identity != first.request_identity for item in observations)
        or any(item.product_version != first.product_version for item in observations)
        or any(item.page_asset_sha256 != first.page_asset_sha256 for item in observations)
        or len({item.captured_at.date() for item in observations}) != len(observations)
        or len({item.response_sha256 for item in observations}) != len(observations)
    ):
        raise ValueError("NEWOW_SCREENER_EVIDENCE_INSUFFICIENT")
    common_rules = set(first.matching_rule_ids)
    for observation in observations[1:]:
        common_rules.intersection_update(observation.matching_rule_ids)
    if len(common_rules) != 1:
        raise ValueError("NEWOW_SCREENER_EVIDENCE_INSUFFICIENT")
    return PageExactScreenerRule(
        strategy_id=first.strategy_id,
        rule_id=next(iter(common_rules)),
        evidence_response_sha256=tuple(
            item.response_sha256 for item in observations
        ),
    )


@dataclass(frozen=True, slots=True)
class LegacyHomepageStockFacts:
    symbol: str
    signal_daily: Literal["buy", "hold", "sell", "wait"]
    signal_weekly: Literal["buy", "hold", "sell", "wait"]
    trend: Literal["bull", "bear"]
    change_pct: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.symbol, str)
            or not _SYMBOL.fullmatch(self.symbol)
            or self.signal_daily not in {"buy", "hold", "sell", "wait"}
            or self.signal_weekly not in {"buy", "hold", "sell", "wait"}
            or self.trend not in {"bull", "bear"}
            or not isinstance(self.change_pct, Decimal)
            or not self.change_pct.is_finite()
        ):
            raise ValueError("NEWOW_LEGACY_FILTER_FACTS_INVALID")


@dataclass(frozen=True, slots=True)
class LegacyFilterResult:
    rule_id: LegacyFilterId
    matched: bool
    surface: Literal["legacy_homepage"] = "legacy_homepage"
    formula_version: str = LEGACY_HOMEPAGE_FILTER_V3282


def observed_legacy_filter_v3_2_82(
    rule_id: LegacyFilterId, facts: LegacyHomepageStockFacts
) -> LegacyFilterResult:
    if not isinstance(rule_id, LegacyFilterId) or not isinstance(
        facts, LegacyHomepageStockFacts
    ):
        raise ValueError("NEWOW_LEGACY_FILTER_INPUT_INVALID")
    daily_buy = facts.signal_daily == "buy"
    weekly_buy = facts.signal_weekly == "buy"
    bullish = facts.trend == "bull"
    positive = facts.change_pct > 0
    matched = {
        LegacyFilterId.YIJIAN_SAN_DIAO: daily_buy and weekly_buy and bullish,
        LegacyFilterId.DAILY_BUY: daily_buy,
        LegacyFilterId.WEEKLY_BUY: weekly_buy,
        LegacyFilterId.HOT_STRONG: bullish and facts.change_pct > Decimal(2),
        LegacyFilterId.START_CONTROL: bullish and facts.signal_daily == "hold",
        LegacyFilterId.DAILY_ACCUM: daily_buy and positive,
        LegacyFilterId.WEEKLY_ACCUM: weekly_buy and positive,
        LegacyFilterId.WAVE_ENTRY: daily_buy or weekly_buy,
        LegacyFilterId.TREND_MASTER: facts.trend in {"bull", "bear"},
    }[rule_id]
    return LegacyFilterResult(rule_id, matched)


@dataclass(frozen=True, slots=True)
class CandidateTransitionFacts:
    state: TrendBandState
    latest_build_at: datetime | None
    latest_clear_at: datetime | None
    physical_contract: str
    segment_id: str
    formula_version: str

    def __post_init__(self) -> None:
        timestamps = tuple(
            value
            for value in (self.latest_build_at, self.latest_clear_at)
            if value is not None
        )
        if (
            not isinstance(self.state, TrendBandState)
            or any(
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
                for value in timestamps
            )
            or not isinstance(self.physical_contract, str)
            or not self.physical_contract
            or self.physical_contract != self.physical_contract.upper()
            or not isinstance(self.segment_id, str)
            or not self.segment_id
            or not isinstance(self.formula_version, str)
            or not self.formula_version
        ):
            raise ValueError("NEWOW_SCREENER_CANDIDATE_FACTS_INVALID")


@dataclass(frozen=True, slots=True)
class CupCandidateFacts:
    state: CupHandleState
    hard_failures: tuple[str, ...]
    physical_contract: str
    segment_id: str
    formula_version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state, CupHandleState)
            or not isinstance(self.hard_failures, tuple)
            or any(not item for item in self.hard_failures)
            or not isinstance(self.physical_contract, str)
            or not self.physical_contract
            or self.physical_contract != self.physical_contract.upper()
            or not isinstance(self.segment_id, str)
            or not self.segment_id
            or not isinstance(self.formula_version, str)
            or not self.formula_version
        ):
            raise ValueError("NEWOW_SCREENER_CANDIDATE_FACTS_INVALID")


@dataclass(frozen=True, slots=True)
class CleanroomScreenerCandidate:
    identity: str
    matched: bool
    formula_lineage: tuple[str, ...]
    evidence_note: Literal["private_server_logic_unverified"] = (
        "private_server_logic_unverified"
    )
    page_parity: Literal[False] = False


def _recent_build(facts: CandidateTransitionFacts) -> bool:
    return facts.latest_build_at is not None and (
        facts.latest_clear_at is None
        or facts.latest_build_at > facts.latest_clear_at
    )


def evaluate_trend_build_candidate(
    facts: CandidateTransitionFacts,
) -> CleanroomScreenerCandidate:
    if not isinstance(facts, CandidateTransitionFacts):
        raise ValueError("NEWOW_SCREENER_CANDIDATE_FACTS_INVALID")
    if facts.formula_version != NEWOW_TREND_D1_PAGE_V2.trend_band_formula:
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")
    return CleanroomScreenerCandidate(
        TREND_BUILD_CANDIDATE_V1,
        facts.state is TrendBandState.YELLOW and _recent_build(facts),
        (facts.formula_version,),
    )


def evaluate_mainrise_build_candidate(
    facts: CandidateTransitionFacts,
) -> CleanroomScreenerCandidate:
    if not isinstance(facts, CandidateTransitionFacts):
        raise ValueError("NEWOW_SCREENER_CANDIDATE_FACTS_INVALID")
    if facts.formula_version != MAIN_RISE_PAGE_V1.band_formula:
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")
    return CleanroomScreenerCandidate(
        MAINRISE_BUILD_CANDIDATE_V1,
        facts.state is TrendBandState.YELLOW and _recent_build(facts),
        (facts.formula_version,),
    )


def evaluate_cup_handle_candidate(
    facts: CupCandidateFacts,
) -> CleanroomScreenerCandidate:
    if not isinstance(facts, CupCandidateFacts):
        raise ValueError("NEWOW_SCREENER_CANDIDATE_FACTS_INVALID")
    if facts.formula_version != NEWOW_TREND_D1_V1.cup_handle_formula:
        raise ValueError("NEWOW_FORMULA_IDENTITY_MISMATCH")
    return CleanroomScreenerCandidate(
        CUP_HANDLE_CANDIDATE_V1,
        facts.state in {CupHandleState.READY, CupHandleState.BREAKOUT}
        and not facts.hard_failures,
        (facts.formula_version,),
    )
