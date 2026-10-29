"""Market-only source revalidation, safe while a Reference row lock is held."""

from contextlib import contextmanager
from hashlib import sha256
import json
from app.db.readonly import readonly_transaction
from app.market_data.domain import SeriesPageQuery, SeriesKind, BarFrequency
from app.market_data.live_market import _bar_from_payload
from app.reference_trading.forward_inputs import _bar_wire
from app.reference_trading.htdy_activation import htdy_identity
from app.reference_trading.inbox import _verified_input
from app.reference_trading.inbox_recovery import require
from app.reference_trading.models import ReferenceInboxInput


@contextmanager
def open_market_recovery_facts():
    from contextlib import closing
    from app.db.session import SessionLocal
    from app.market_data.composition import (
        build_market_read_service,
        build_market_data_service,
    )
    from app.redis_connections import get_redis_connection
    from app.reference_trading.forward_authority import ForwardMarketAuthority

    with (
        closing(get_redis_connection()) as redis,
        SessionLocal() as db,
        readonly_transaction(db, timeout_seconds=30),
    ):
        yield (
            build_market_read_service(db, redis=redis),
            ForwardMarketAuthority(build_market_data_service(db)).owner_segments,
        )


class HtdyRecoverySource:
    def __init__(self, session_factory, market_facts=open_market_recovery_facts):
        self.factory = session_factory
        self.market_facts = market_facts

    def __call__(self, plan):
        identity = htdy_identity("al")
        require(
            plan.capture.stream_id == identity.stream_id,
            "REFERENCE_ROLLBACK_SCOPE_INVALID",
        )
        with self.factory() as db, readonly_transaction(db, timeout_seconds=20):
            event = _verified_input(db.get(ReferenceInboxInput, plan.input_id))
        require(
            event.channel == "live:bar:al:60m" and event.notification_eligible,
            "REFERENCE_ROLLBACK_ORIGINAL_INVALID",
        )
        require(
            sha256(event.to_json().encode()).hexdigest()
            == plan.capture.source_proof["journal_envelope_sha256"],
            "REFERENCE_ROLLBACK_ORIGINAL_DRIFT",
        )
        bar = _bar_from_payload(json.dumps(event.data, allow_nan=False))
        require(
            bar.bar_end == plan.capture.bar_end and bar.bar_end < event.confirmed_at,
            "REFERENCE_ROLLBACK_ORIGINAL_DRIFT",
        )
        with self.market_facts() as (market, owner_segments):
            query = SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT, "AL", BarFrequency("60m"), limit=32
            )
            window = market.bars_until(
                query, trading_day=event.trading_day, end=bar.bar_end, limit=32
            )
            require(
                len(window.bars) == 32
                and window.bars[-1] == bar
                and window.contract == event.data["contract"]
                and window.cutoff == bar.bar_end
                and list(window.bar_contracts)
                == plan.capture.input_payload["bar_contracts"],
                "REFERENCE_ROLLBACK_WINDOW_DRIFT",
            )
            market.validate_alert_window(window, context_bars=32)
            market.assert_window_current(window)
            actual = sha256(
                json.dumps(
                    [_bar_wire(b) for b in window.bars],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            proof = plan.capture.source_proof
            require(
                actual == proof["window_sha256"]
                and owner_segments(
                    identity, window.contract, event.trading_day, bar.bar_end
                )
                == (proof["owner_segment_id"], proof["calculation_segment_id"]),
                "REFERENCE_ROLLBACK_WINDOW_DRIFT",
            )
