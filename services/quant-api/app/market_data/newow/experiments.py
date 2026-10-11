"""Independent, read-only page experiment projection; never a Runtime strategy."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo
from hashlib import sha256
from decimal import Decimal
from itertools import groupby
import re

from guiyi_quant.newow.oscillation_experiments import (
    ExperimentKind,
    calculate_experiment_series,
    run_experiment_reference,
    run_base_oscillation_ideal,
)
from guiyi_quant.newow.product_contracts import (
    ProductFrequency,
    ProductStrategy,
    lifecycle_input_sha256,
)
from guiyi_quant.newow.product_adapters import (
    build_product_identity,
    label_calculation_segments,
)
from guiyi_quant.newow.product_identity import utc_timestamp, input_policy_version
from guiyi_quant.newow.page_performance import filter_page_by_date
from .product_query import NewowProductQuery, ProductReadWindow
from .product_reader import NewowProductReader, NewowProductReadError


def _window_reference(result, bars, window, frequency):
    """Reuse the public exit-date filter without changing experiment identity."""
    if result is None:
        return None
    days = {bar.bar_end.isoformat(): bar.trading_day.isoformat() for bar in bars}
    mapped = dict(
        period=frequency.value,
        dates=result["dates"],
        equity=result["equity"],
        trading_days=[days[stamp] for stamp in result["dates"]],
        summary=dict(
            cumReturn=result["summary"]["cum_return_percentage_points"],
            accuracy=result["summary"]["accuracy_pct"],
            maxDrawdown=result["summary"]["max_drawdown_percentage_points"],
            tradeCount=result["summary"]["trade_count"],
        ),
        trades=[
            dict(
                sellDate=trade["exit_bar_end"],
                pct=trade["return_percentage_points"],
                original=trade,
            )
            for trade in result["trades"]
        ],
    )
    filtered = filter_page_by_date(
        mapped, window.since.isoformat(), window.through.isoformat()
    )
    return dict(
        result,
        dates=filtered["dates"],
        equity=filtered["equity"],
        trades=[trade["original"] for trade in filtered["trades"]],
        summary=dict(
            cum_return_percentage_points=filtered["summary"]["cumReturn"],
            accuracy_pct=str(filtered["summary"]["accuracy"]),
            max_drawdown_percentage_points=filtered["summary"]["maxDrawdown"],
            trade_count=filtered["summary"]["tradeCount"],
        ),
    )


@dataclass(frozen=True)
class ExperimentQuery:
    product: str
    frequency: ProductFrequency
    kind: ExperimentKind
    as_of: datetime | None = None
    since: date | None = None
    through: date | None = None
    chart_limit: int = 500
    all_history: bool = False

    def __post_init__(self):
        if (
            not isinstance(self.product, str)
            or re.fullmatch("[a-z]+", self.product) is None
        ):
            raise ValueError("NEWOW_INVALID_PRODUCT")
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(self, "kind", ExperimentKind(self.kind))
        if type(self.chart_limit) is not int or not 11 <= self.chart_limit <= 2000:
            raise ValueError("NEWOW_INVALID_CHART_LIMIT")
        if type(self.all_history) is not bool or (
            self.all_history and self.since is not None
        ):
            raise ValueError("NEWOW_INVALID_RANGE")
        if (self.since is None) != (self.through is None):
            raise ValueError("NEWOW_INVALID_RANGE")
        if self.since is not None:
            ProductReadWindow(self.since, self.through)
        if self.as_of is not None:
            object.__setattr__(self, "as_of", utc_timestamp(self.as_of))


class NewowExperimentService:
    def __init__(self, reader: NewowProductReader, *, now=None, cancelled=None):
        self.reader = reader
        self.cancelled = cancelled
        self.now = now or (lambda: datetime.now(UTC))

    def _check_cancelled(self):
        if self.cancelled is not None and self.cancelled():
            raise NewowProductReadError("NEWOW_REQUEST_CANCELLED")

    def query(self, query: ExperimentQuery) -> dict:
        as_of = utc_timestamp(query.as_of or self.now())
        if as_of > utc_timestamp(self.now()):
            raise NewowProductReadError("NEWOW_INVALID_AS_OF")
        resolved = (
            self.reader.resolve_performance_window(
                query.product, query.frequency, None, None, as_of
            )
            if query.all_history
            else None
        )
        window = (
            ProductReadWindow(resolved.requested_since, resolved.actual_through)
            if resolved is not None
            else ProductReadWindow(query.since, query.through)
            if query.since is not None
            else self.reader.resolve_chart_window(
                query.product, query.frequency, query.chart_limit, as_of
            )
        )
        read = self.reader.load(
            NewowProductQuery(
                query.product,
                ProductStrategy.OSCILLATION,
                query.frequency,
                window.since,
                window.through,
                window.since,
                window.through,
                as_of,
            ),
            as_of,
        )
        if read.as_of != as_of or read.frequency != query.frequency:
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
        if resolved is not None and query.frequency is ProductFrequency.WEEKLY:
            completed_weeks = tuple(
                item.bar
                for item in read.replay_bars
                if item.bar.observation_eligible
                and item.bar.bar_end <= resolved.cutoff
                and item.bar.trading_day <= resolved.requested_through
            )
            if not completed_weeks:
                raise NewowProductReadError("NEWOW_COMPLETE_PERIOD_MISSING")
            resolved = replace(
                resolved,
                complete=completed_weeks[-1].trading_day == resolved.actual_through,
            )
        # Reuse the reader's calculation segment; quality gaps and owner changes
        # cannot be bridged by a local identity resolver.
        product_identity = build_product_identity(
            query.product,
            ProductStrategy.OSCILLATION,
            query.frequency,
            input_quality_policy=read.input_quality_policy,
        )
        labeled = label_calculation_segments(
            product_identity, read.replay_bars, read.data_interruptions
        )
        groups = [
            (key, tuple(values))
            for key, values in groupby(
                labeled,
                lambda b: (
                    b.bar.physical_contract,
                    b.calculation_segment_id,
                ),
            )
        ]
        event_cutoff = min(
            as_of, datetime.combine(window.through, time.max, ZoneInfo("Asia/Shanghai"))
        )
        last = max(
            (
                item.bar.bar_end
                for item in labeled
                if item.bar.observation_eligible
                and window.since <= item.bar.trading_day <= window.through
            ),
            default=None,
        )
        tail_gap = last is not None and any(
            last <= gap.effective_at <= event_cutoff for gap in read.data_interruptions
        )
        tail_rollover = last is not None and any(
            last <= boundary.effective_at <= event_cutoff
            for boundary in read.boundaries
        )
        terminal_blocked = (
            last is None
            or tail_gap
            or tail_rollover
            or (resolved is not None and not resolved.complete)
        )
        segments, chart, markers = [], [], []
        seen, previous = set(), None
        for index, (identity, wrapped) in enumerate(groups):
            if self.cancelled is not None and self.cancelled():
                raise NewowProductReadError("NEWOW_REQUEST_CANCELLED")
            if identity in seen:
                raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
            seen.add(identity)
            values = tuple(wrapped)
            bars = tuple(
                replace(b.bar, segment_id=identity[1])
                for b in values
                if b.bar.trading_day <= window.through
            )
            if not bars:
                continue
            values = tuple(b for b in values if b.bar.trading_day <= window.through)
            for wrapped_bar, bar in zip(values, bars, strict=True):
                if (
                    wrapped_bar.frequency != query.frequency
                    or bar.product != query.product
                    or bar.bar_end >= as_of
                    or not bar.completed
                ):
                    raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
                if bar.observation_eligible:
                    if previous is not None and bar.bar_end <= previous:
                        raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
                    previous = bar.bar_end
            # Preserve original owner eligibility and all prefix transactions;
            # page range filtering selects exits after the full calculation.
            steps = calculate_experiment_series(
                bars, query.kind, check_cancelled=self._check_cancelled
            )
            eligible = tuple(b for b in bars if b.observation_eligible)
            if not any(
                window.since <= bar.trading_day <= window.through for bar in eligible
            ):
                continue
            for bar, step in zip(bars, steps, strict=True):
                if (
                    not bar.observation_eligible
                    or not window.since <= bar.trading_day <= window.through
                ):
                    continue
                chart.append(
                    dict(
                        bar_end=bar.bar_end.isoformat(),
                        trading_day=bar.trading_day.isoformat(),
                        physical_contract=bar.physical_contract,
                        segment_id=bar.segment_id,
                        open=str(bar.open),
                        high=str(bar.high),
                        low=str(bar.low),
                        close=str(bar.close),
                        channel_high=str(step.channel.upper) if step.channel else None,
                        channel_low=str(step.channel.lower) if step.channel else None,
                    )
                )
                for signal_index, signal in enumerate(step.signals):
                    marker_id = sha256(
                        f"{query.kind}:{query.frequency}:{bar.segment_id}:{bar.bar_end.isoformat()}:{signal_index}:{signal.action}".encode()
                    ).hexdigest()
                    markers.append(
                        dict(
                            marker_id=marker_id,
                            bar_end=bar.bar_end.isoformat(),
                            physical_contract=bar.physical_contract,
                            segment_id=bar.segment_id,
                            action=signal.action.value,
                            reference_price=str(signal.price),
                            score=signal.score,
                            break_label=signal.break_label,
                            stop_loss=signal.stop_loss,
                            confirm_exit=signal.confirm_exit,
                        )
                    )
            segment_ready = steps[-1].channel is not None and len(bars) >= 11
            segments.append(
                dict(
                    readiness=dict(
                        status="READY" if segment_ready else "WARMUP",
                        reason_code=None
                        if segment_ready
                        else "NEWOW_EXPERIMENT_WARMUP",
                    ),
                    segment_id=identity[1],
                    physical_contract=identity[0],
                    status=(
                        (
                            "DATA_CONFLICT"
                            if tail_gap
                            else "ROLLOVER_INTERRUPTED"
                            if tail_rollover
                            else "CURRENT"
                        )
                        if index == len(groups) - 1
                        else "ROLLOVER_INTERRUPTED"
                        if groups[index + 1][0][0] != identity[0]
                        else "DATA_CONFLICT"
                    ),
                    statistics_window=dict(
                        since=next(
                            bar.bar_end.isoformat()
                            for bar in eligible
                            if window.since <= bar.trading_day <= window.through
                        ),
                        through=eligible[-1].bar_end.isoformat(),
                    ),
                    latest_state=dict(
                        holding=steps[-1].state.holding,
                        entry_reference_price=str(steps[-1].state.entry_price)
                        if steps[-1].state.entry_price is not None
                        else None,
                        stop_reference_price=str(
                            steps[-1].state.entry_price
                            * (
                                Decimal("0.88")
                                if query.kind is ExperimentKind.TEST4
                                else Decimal("0.93")
                            )
                        )
                        if steps[-1].state.entry_price is not None
                        else None,
                        locked_target=str(steps[-1].state.target_price)
                        if steps[-1].state.target_price is not None
                        else None,
                        confirm_reference=str(steps[-1].state.sell_reference)
                        if steps[-1].state.sell_reference is not None
                        else None,
                    ),
                    ordinary=_window_reference(
                        run_experiment_reference(
                            bars,
                            query.kind,
                            terminal_eligible=index == len(groups) - 1
                            and not terminal_blocked,
                            check_cancelled=self._check_cancelled,
                        ),
                        bars,
                        window,
                        query.frequency,
                    ),
                    theoretical=_window_reference(
                        run_base_oscillation_ideal(
                            bars, check_cancelled=self._check_cancelled
                        ),
                        bars,
                        window,
                        query.frequency,
                    ),
                )
            )
        if not chart:
            raise NewowProductReadError("NEWOW_DATA_UNAVAILABLE")
        ready = segments[-1]["readiness"]["status"] == "READY"
        return dict(
            schema_version="newow_experiment_detail_v1",
            product=query.product,
            frequency=query.frequency.value,
            kind=query.kind.value,
            as_of=as_of.isoformat(),
            formula_version=query.kind.formula_version,
            page_parity=True,
            executable=False,
            input_policy_version=input_policy_version(
                query.frequency.value, read.input_quality_policy
            ),
            input_snapshot_hash=lifecycle_input_sha256(labeled),
            profile_id="guiyi_newow_experiment_completed_physical_v1",
            window=dict(
                since=window.since.isoformat(),
                through=window.through.isoformat(),
                all_history=query.all_history,
                terminal_eligible=not terminal_blocked,
            ),
            readiness=dict(
                status="READY" if ready else "WARMUP",
                reason_code=None if ready else "NEWOW_EXPERIMENT_WARMUP",
            ),
            bars=chart[-query.chart_limit :],
            markers=[
                marker
                for marker in markers
                if marker["bar_end"]
                in {bar["bar_end"] for bar in chart[-query.chart_limit :]}
            ],
            segments=segments,
        )
