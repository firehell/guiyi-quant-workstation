"""Versioned v3.3.59 price selection, separate from chart channel legends."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from .target_absorb_display import guard_page_price

VERSION = "newow_target_absorb_selection_v3_3_59_v1"
SOURCE_SHA256 = "a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e"
BUFFER = Decimal("1.005")


@dataclass(frozen=True)
class PriceSource:
    value: Decimal
    frequency: str
    bar_end: datetime
    physical_contract: str
    segment_id: str
    calculation_segment_id: str
    source_identity: str
    source_category: str

    def __post_init__(self):
        if (
            not isinstance(self.value, Decimal)
            or not self.value.is_finite()
            or self.value <= 0
            or self.bar_end.utcoffset() is None
        ):
            raise ValueError("NEWOW_PRICE_SOURCE_INVALID")
        if self.frequency not in ("1d", "1w", "1M") or any(
            not isinstance(v, str) or not v
            for v in (
                self.physical_contract,
                self.segment_id,
                self.calculation_segment_id,
                self.source_identity,
                self.source_category,
            )
        ):
            raise ValueError("NEWOW_PRICE_SOURCE_INVALID")

    def wire(self):
        return {
            "raw": format(self.value, "f"),
            "frequency": self.frequency,
            "bar_end": self.bar_end.isoformat(),
            "physical_contract": self.physical_contract,
            "segment_id": self.segment_id,
            "calculation_segment_id": self.calculation_segment_id,
            "source_identity": self.source_identity,
            "source_category": self.source_category,
        }


def select_cross_period_prices(
    *,
    as_of,
    current: PriceSource,
    previous_close: PriceSource | None,
    daily_signal,
    weekly_signal,
    cross_weekly_buy=False,
    period="day",
    target_daily=None,
    target_weekly=None,
    target_monthly=None,
    target=None,
    cost_daily=None,
    cost_weekly=None,
    cost=None,
    high=None,
    weekly_override=None,
    source_family="page_batch",
):
    """Pure public rule with explicit provenance. Never mixes raw source families.

    The futures adapter may supply canonical channels under its own named source
    family; this is not evidence of the private server's batch-price generation.
    Weekly status-card override is a distinct surface from shared selection.
    """
    if period not in ("day", "week", "best_available") or source_family not in (
        "page_batch",
        "canonical_channel",
    ):
        raise ValueError("NEWOW_PRICE_SELECTION_INVALID")

    def validate(fact, frequency=None, category=None):
        if fact is None:
            return
        if (
            not isinstance(fact, PriceSource)
            or fact.bar_end > as_of
            or (fact.physical_contract, fact.segment_id)
            != (current.physical_contract, current.segment_id)
            or frequency
            and fact.frequency != frequency
            or category
            and fact.source_category != category
        ):
            raise ValueError("NEWOW_PRICE_SOURCE_CONFLICT")

    validate(current, category="canonical_completed_close")
    if current.frequency not in ("1d", "1w"):
        raise ValueError("NEWOW_PRICE_SOURCE_CONFLICT")
    for f, freq in (
        (target_daily, "1d"),
        (cost_daily, "1d"),
        (target_weekly, "1w"),
        (cost_weekly, "1w"),
        (target_monthly, "1M"),
        (target, None),
        (cost, None),
        (high, None),
    ):
        validate(f, freq, source_family)
    validate(previous_close, "1d", "canonical_previous_daily_close")
    if (
        previous_close
        and current.frequency == "1d"
        and previous_close.calculation_segment_id != current.calculation_segment_id
    ):
        raise ValueError("NEWOW_PRICE_SOURCE_CONFLICT")
    if previous_close and previous_close.bar_end >= current.bar_end:
        raise ValueError("NEWOW_PRICE_PREVIOUS_CLOSE_NOT_PRIOR")
    if weekly_override:
        if len(weekly_override) != 2:
            raise ValueError("NEWOW_PRICE_SOURCE_CONFLICT")
        for f in weekly_override:
            validate(f, "1w", "canonical_channel")
    sd, sw = daily_signal or "wait", weekly_signal or "wait"
    da = sd not in ("wait", "sell")
    wa = sw not in ("wait", "sell") or cross_weekly_buy
    raw = current.value

    def week_tier():
        return (
            (target_monthly, "target_weekly_breakout_monthly")
            if target_monthly and target_weekly and raw >= target_weekly.value * BUFFER
            else (target_weekly, "target_weekly")
        )

    chosen, branch = None, "target_unavailable"
    if target_daily or target_weekly:
        if da and wa:
            if period == "week" and target_weekly:
                chosen, branch = week_tier()
            elif sd == "buy" and target_daily:
                chosen, branch = (
                    week_tier()
                    if target_weekly and raw >= target_daily.value * BUFFER
                    else (target_daily, "target_daily_buy")
                )
            elif sw == "buy" and target_weekly:
                chosen, branch = week_tier()
            elif period == "day":
                chosen, branch = (
                    (target_daily, "target_daily_hold") if target_daily else week_tier()
                )
            elif target_weekly:
                chosen, branch = week_tier()
            elif target and (not target_daily or target.value > target_daily.value):
                chosen, branch = target, "target_generic_weekly_fallback"
            else:
                chosen, branch = target_daily or target, "target_daily_fallback"
        elif da and target_daily:
            chosen, branch = (
                (target_weekly, "target_daily_breakout_weekly")
                if target_weekly and raw >= target_daily.value * BUFFER
                else (target_daily, "target_daily_positive")
            )
        elif wa and target_weekly:
            chosen, branch = target_weekly, "target_weekly_positive"
        elif target_daily:
            chosen, branch = target_daily, "target_daily_flat"
        elif period != "day":
            chosen, branch = target_weekly, "target_weekly_fallback"
    else:
        chosen, branch = (
            (high, "target_high_fallback")
            if high and high.value > raw
            else (target, "target_generic_fallback")
        )
    # Absorb uses signals alone, not cross_weekly.
    wa_cost = sw not in ("wait", "sell")
    absorb, absorb_branch = None, "absorb_unavailable"
    if da and wa_cost:
        if period == "week" and cost_weekly:
            absorb, absorb_branch = cost_weekly, "absorb_week_view"
        elif sd == "buy" and cost_daily:
            absorb, absorb_branch = cost_daily, "absorb_daily_buy"
        elif sw == "buy" and cost_weekly:
            absorb, absorb_branch = cost_weekly, "absorb_weekly_buy"
        else:
            absorb, absorb_branch = (
                cost_daily or (cost_weekly if period != "day" else None),
                "absorb_daily_first",
            )
    elif da:
        absorb, absorb_branch = (
            cost_daily or (cost_weekly if period != "day" else None),
            "absorb_daily_positive",
        )
    elif wa_cost:
        absorb, absorb_branch = (
            cost_daily or cost_weekly or cost,
            "absorb_weekly_positive",
        )
    else:
        absorb, absorb_branch = (
            (cost_weekly or cost_daily) if period != "day" else cost_daily,
            "absorb_flat",
        )

    def wire(fact, why):
        if fact is None:
            return None
        return {
            **fact.wire(),
            "display_value": format(
                guard_page_price(
                    fact.value, previous_close.value if previous_close else None
                ),
                "f",
            ),
            "branch": why,
        }

    shared = {"target": wire(chosen, branch), "absorb": wire(absorb, absorb_branch)}
    card = (
        shared
        if period != "week" or not weekly_override
        else {
            "target": wire(weekly_override[0], "status_card_weekly_hhv10_override"),
            "absorb": wire(weekly_override[1], "status_card_weekly_llv10_override"),
        }
    )
    return {
        "formula_version": VERSION,
        "source_sha256": SOURCE_SHA256,
        "upgrade_buffer": "1.005",
        "as_of": as_of.isoformat(),
        "period": period,
        "source_family": source_family,
        "daily_signal": daily_signal,
        "weekly_signal": weekly_signal,
        "current_price": current.wire(),
        "previous_close": previous_close.wire() if previous_close else None,
        "guard_status": "verified_previous_close"
        if previous_close
        else "previous_close_unavailable",
        "shared": shared,
        "status_card": card,
        "monthly_target_available": target_monthly is not None,
        "executable": False,
    }
