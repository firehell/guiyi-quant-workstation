"""Read-only composition for a bounded SimNow host, never registered as Runtime."""

from contextlib import contextmanager
from datetime import timedelta, date, datetime
from dataclasses import dataclass, replace
from sqlalchemy import select, text
from app.db.session import SessionLocal
from app.models import Contract
from app.market_data.composition import (
    build_market_data_service,
    build_market_read_service,
)
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import resolved_session_windows_for_trading_day
from app.market_data.domain import SeriesPageQuery, SeriesKind, BarFrequency
from app.redis_connections import get_redis_connection
from app.alerts.runtime import _parse_live_bar_trigger
from app.alerts.evaluators import HtdyOriginalEvaluator
from app.htdy_execution import signal_from_window
from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.htdy_account_execution.codec import digest


@dataclass(frozen=True)
class Authority:
    product: str
    owner: str
    contract: str
    exchange: str
    trading_day: date
    session: a.Session
    source_id: str
    contiguous_session_end: datetime | None = None


class MarketBridge:
    def __init__(self, product):
        if product.lower() not in load_operational_products():
            raise ValueError("PRODUCT_NOT_OPERATIONAL")
        self.product = product.upper()
        self.redis = get_redis_connection()
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe("live:bar:" + product.lower() + ":60m")
        self.identity = SeriesPageQuery(
            SeriesKind.ACTUAL_DOMINANT, product.lower(), BarFrequency.H1, limit=32
        )
        self.started = None

    @contextmanager
    def reader(self):
        with SessionLocal() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            yield db, build_market_read_service(db, redis=self.redis)

    def activate(self, now):
        # Startup queue is never an execution signal.
        while self.pubsub.get_message(timeout=0) is not None:
            pass
        self.started = now

    def authority(self, day, now, contract=None):
        with self.reader() as (db, reader):
            owner = (
                build_market_data_service(db)
                .dominant_segment_for_day(self.product.lower(), day)
                .contract
            )
            actual = contract or owner
            row = db.scalar(
                select(Contract).where(
                    Contract.contract_code == actual,
                    Contract.instrument_symbol == self.product.lower(),
                    Contract.provider == "rqdata",
                )
            )
            if row is None:
                raise ValueError("AUTHORITATIVE_CONTRACT_MISSING")
            windows = resolved_session_windows_for_trading_day(
                db,
                exchange=row.exchange_code,
                symbol=self.product.lower(),
                trading_day=day,
            )
            groups = {
                flag: tuple(w for w in windows if w.is_night == flag)
                for flag in (True, False)
            }
            options = [v for v in groups.values() if v]
            if not options:
                raise ValueError("AUTHORITATIVE_SESSION_MISSING")
            active = [
                group
                for group in options
                if min(w.window.start for w in group)
                <= now
                < max(w.window.end for w in group)
            ]
            group = (
                active[0]
                if len(active) == 1
                else min(
                    options,
                    key=lambda g: abs(
                        (max(w.window.end for w in g) - now).total_seconds()
                    ),
                )
            )
            current = tuple(
                w.window for w in group if w.window.start <= now < w.window.end
            )
            tradable = bool(current)
            contiguous_end = max((w.end for w in current), default=None)
            if contiguous_end is not None:
                # Adjacent/overlapping windows are one uninterrupted trading span.
                for window in sorted((w.window for w in group), key=lambda w: w.start):
                    if window.start <= contiguous_end and window.end > contiguous_end:
                        contiguous_end = window.end
            close = max(w.window.end for w in group)
            source = "authority:" + digest(
                (
                    day.isoformat(),
                    owner,
                    actual,
                    tuple(
                        (w.name, w.window.start, w.window.end, w.is_night)
                        for w in windows
                    ),
                )
            )
            return Authority(
                self.product,
                owner,
                actual,
                row.exchange_code,
                day,
                a.Session(
                    actual,
                    now,
                    min(now + timedelta(seconds=15), contiguous_end)
                    if contiguous_end is not None
                    else now + timedelta(seconds=15),
                    source,
                    close,
                    tradable,
                    tradable,
                ),
                source,
                contiguous_end,
            )

    def canonical_for_native(self, native, exchange, instruments):
        rows = [
            r
            for r in instruments
            if r["InstrumentID"] == native and r["ExchangeID"] == exchange
        ]
        if len(rows) != 1 or rows[0]["ProductID"].upper() != self.product:
            raise ValueError("NATIVE_POSITION_OUTSIDE_CONTROLLED_SCOPE")
        row = rows[0]
        candidate = (
            self.product + f"{row['DeliveryYear'] % 100:02}{row['DeliveryMonth']:02}"
        )
        with self.reader() as (db, _):
            contract = db.scalar(
                select(Contract).where(
                    Contract.contract_code == candidate,
                    Contract.instrument_symbol == self.product.lower(),
                    Contract.exchange_code == exchange,
                    Contract.provider == "rqdata",
                )
            )
            if contract is None:
                raise ValueError("NATIVE_POSITION_CATALOG_IDENTITY_MISSING")
            return contract.contract_code

    def poll(self, now, after):
        if self.started is None:
            raise ValueError("NATURAL_SOURCE_NOT_ACTIVATED")
        message = self.pubsub.get_message(timeout=0)
        if message is None:
            return None
        if message["type"] != "message":
            return None
        trigger = _parse_live_bar_trigger(message["channel"], message["data"])
        if (
            trigger is None
            or trigger.symbol != self.product.lower()
            or trigger.frequency != BarFrequency.H1
        ):
            raise ValueError("NATURAL_TRIGGER_INVALID")
        return self.signal_from_trigger(trigger, now, after)

    def signal_from_trigger(self, trigger, observed_at, after):
        """Apply the single-product first-seen proof to an already captured trigger."""
        if self.started is None:
            raise ValueError("NATURAL_SOURCE_NOT_ACTIVATED")
        if (
            trigger.symbol != self.product.lower()
            or trigger.frequency != BarFrequency.H1
        ):
            raise ValueError("NATURAL_TRIGGER_INVALID")
        if trigger.bar.bar_end <= max(after, self.started):
            return None
        if trigger.bar.bar_end >= observed_at:
            raise ValueError("NATURAL_BAR_NOT_COMPLETED")
        with self.reader() as (_, reader):
            snapshot = reader.observation_snapshot(self.identity, after, observed_at)
            if (
                snapshot.source != "realtime"
                or not snapshot.bars
                or snapshot.bars[-1] != trigger.bar
            ):
                raise ValueError("LATEST_NATURAL_OBSERVATION_UNPROVEN")
            window = reader.bars_until(
                self.identity,
                trading_day=trigger.bar.trading_day,
                end=trigger.bar.bar_end,
                limit=32,
            )
            return signal_from_window(
                reader,
                window,
                source_id="simnow-natural:"
                + digest((trigger.symbol, trigger.bar.bar_end, snapshot.contract)),
                observed_at=observed_at,
            )

    def recovery(self, state, now):
        p = next(p for p in state.products if p.product == self.product)
        with self.reader() as (_, reader):
            snapshot = reader.observation_snapshot(self.identity, None, now)
            if snapshot.source != "realtime" or not snapshot.bars:
                return ()
            end = snapshot.bars[-1].bar_end
            floor = p.last_bar or state.activated_at
            window = None
            for bound in (64, 128, 256, 512, 1024, 2000):
                candidate = reader.bars_until(
                    self.identity,
                    trading_day=snapshot.trading_day,
                    end=end,
                    limit=bound,
                )
                if len(candidate.bars) >= 32 and candidate.bars[31].bar_end <= floor:
                    window = candidate
                    break
                if len(candidate.bars) < bound:
                    return ()
            if window is None:
                return ()
            reader.validate_alert_window(window, context_bars=len(window.bars))
            held = next(
                (v.quantity for v in state.positions if v.product == self.product), 0
            )
            direction = p.desired if p.signal_id else held
            for index, bar in enumerate(window.bars):
                if bar.bar_end <= floor:
                    continue
                current = replace(
                    window,
                    bars=window.bars[index - 31 : index + 1],
                    bar_contracts=window.bar_contracts[index - 31 : index + 1],
                    cutoff=bar.bar_end,
                    trading_day=bar.trading_day,
                    contract=window.bar_contracts[index],
                )
                types = HtdyOriginalEvaluator().evaluate(current).observation_types
                if types == ("buy",):
                    direction = 1
                elif types == ("sell",):
                    direction = -1
            return (
                h.RecoveryInput(
                    self.product,
                    window.contract,
                    direction,
                    end,
                    "simnow-recovery:" + digest((window.cutoff, window.bar_contracts)),
                ),
            )

    def close(self):
        self.pubsub.close()
        self.redis.close()
