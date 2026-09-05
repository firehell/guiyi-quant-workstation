"""Owned, explicit product facts; no strategy formula computes test expectations."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    FeatureStatus,
    OwnerBoundary,
    ProductBar,
    ProductIdentity,
    StrategyAction,
    StrategyFrame,
    StrategyReplay,
)
from guiyi_quant.newow.product_identity import build_segment_id


@dataclass(frozen=True)
class CaseWindow:
    """Test-only bounds, to be consumed by the later statistics task."""

    since: datetime
    through: datetime


@dataclass(frozen=True)
class ProductCase:
    identity: ProductIdentity
    bars: tuple[ProductBar, ...]
    replay: StrategyReplay
    entry: StrategyAction
    exit: StrategyAction | None
    boundaries: tuple[OwnerBoundary, ...]
    as_of: datetime
    window: CaseWindow


class ProductCases:
    def closed(self, strategy="trend", frequency="1d", entry="100", exit="110"):
        formulas = {
            "trend": ("newow_trend_band_page_v2",),
            "oscillation": (
                "newow_oscillation_hhv_llv10_page_v1",
                "newow_hhv_llv_channel_page_v1",
            ),
            "main_rise": ("newow_main_rise_ma35_ma45_page_v1",),
        }
        identity = ProductIdentity("rb", strategy, frequency, formulas[strategy])
        start = datetime(2026, 1, 5, tzinfo=UTC)
        segment = build_segment_id("rb", "RB2605", start)
        times = (
            (datetime(2026, 1, 5, 2, tzinfo=UTC), datetime(2026, 1, 5, 3, tzinfo=UTC))
            if frequency == "60m"
            else (
                datetime(2026, 1, 5, 7, tzinfo=UTC),
                datetime(2026, 1, 6, 7, tzinfo=UTC),
            )
        )
        bars = tuple(
            ProductBar(
                bar=NewowDailyBar(
                    product="rb",
                    physical_contract="RB2605",
                    segment_id=segment,
                    trading_day=end.date(),
                    bar_end=end,
                    open=Decimal(price),
                    high=Decimal(price) * Decimal("1.1"),
                    low=Decimal(price) * Decimal("0.9"),
                    close=Decimal(price),
                    volume=100,
                    open_interest=200,
                    source_identity=f"owned:{index}",
                    observation_eligible=True,
                    completed=True,
                ),
                frequency=frequency,
            )
            for index, (end, price) in enumerate(zip(times, (entry, exit), strict=True))
        )
        build = self.action(identity, bars[0], "BUILD", entry)
        clear = self.action(
            identity, bars[1], "CLEAR", exit, related_build_id=build.signal_id
        )
        replay = self.replay(identity, bars, (build, clear), ("BUILD", "CLEAR"))
        return ProductCase(
            identity,
            bars,
            replay,
            build,
            clear,
            (),
            datetime(2026, 1, 9, 16, tzinfo=UTC),
            CaseWindow(start, datetime(2026, 1, 9, 16, tzinfo=UTC)),
        )

    def action(self, identity, bar, kind, price, **kwargs):
        return StrategyAction(
            identity=identity,
            physical_contract=bar.bar.physical_contract,
            segment_id=bar.bar.segment_id,
            bar_end=bar.bar.bar_end,
            trading_day=bar.bar.trading_day,
            kind=kind,
            reference_price=Decimal(price),
            anchor_price=Decimal(price),
            source_marker_id=f"owned:{kind}:{bar.bar.bar_end.isoformat()}",
            **kwargs,
        )

    def replay(self, identity, bars, actions, states):
        frames = tuple(
            StrategyFrame(
                bar=bar,
                main_state=state,
                main_values=(("reference", bar.bar.close),),
                actions=tuple(a for a in actions if a.bar_end == bar.bar.bar_end),
                availability=FeatureStatus("ready", "ACTIVE_CODE_VERIFIED"),
            )
            for bar, state in zip(bars, states, strict=True)
        )
        return StrategyReplay(identity, frames, actions, (), ())

    def open(self):
        case = self.closed()
        return replace(
            case,
            exit=None,
            replay=self.replay(
                case.identity,
                case.bars,
                (case.entry,),
                ("BUILD", "HOLD"),
            ),
        )

    def interrupted(self, mark="90"):
        case = self.open()
        value = Decimal(mark)
        last = replace(
            case.bars[-1],
            bar=replace(
                case.bars[-1].bar,
                open=value,
                high=value * Decimal("1.1"),
                low=value * Decimal("0.9"),
                close=value,
            ),
        )
        bars = (case.bars[0], last)
        effective_at = datetime(2026, 1, 7, tzinfo=UTC)
        boundary = OwnerBoundary(
            product="rb",
            old_contract="RB2605",
            new_contract="RB2610",
            old_segment_id=case.entry.segment_id,
            new_segment_id=build_segment_id("rb", "RB2610", effective_at),
            effective_trading_day=date(2026, 1, 7),
            effective_at=effective_at,
            source_identity="owned:authoritative-owner-boundary",
        )
        return replace(
            case,
            bars=bars,
            boundaries=(boundary,),
            replay=self.replay(
                case.identity,
                bars,
                (case.entry,),
                ("BUILD", "HOLD"),
            ),
        )

    def same_bar_rebuild(self):
        case = self.closed(strategy="oscillation")
        rebuild = self.action(case.identity, case.bars[-1], "BUILD", "105", sequence=1)
        return replace(
            case,
            replay=self.replay(
                case.identity,
                case.bars,
                (case.entry, case.exit, rebuild),
                ("BUILD", "BUILD"),
            ),
        )

    def warmup_only_build(self):
        case = self.closed()
        first = replace(
            case.bars[0], bar=replace(case.bars[0].bar, observation_eligible=False)
        )
        entry = replace(case.entry, trade_eligibility="WARMUP_ONLY")
        clear = replace(case.exit, trade_eligibility="NO_ELIGIBLE_ENTRY")
        bars = (first, case.bars[1])
        return replace(
            case,
            bars=bars,
            entry=entry,
            exit=clear,
            replay=self.replay(
                case.identity,
                bars,
                (entry, clear),
                ("BUILD", "CLEAR"),
            ),
        )
