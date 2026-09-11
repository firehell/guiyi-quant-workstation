from __future__ import annotations

from contextlib import contextmanager
from datetime import date, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.metadata import MetadataSnapshot, MetadataSynchronizer
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


DAY = date(2026, 9, 11)
NEXT = date(2026, 9, 14)


def _snapshot() -> MetadataSnapshot:
    calendars = tuple(
        {
            "exchange_code": "DCE",
            "trade_date": DAY + timedelta(days=offset),
            "is_trading_day": offset in {0, 3},
            "has_night_session": offset in {0, 3},
            "provider": "rqdata",
        }
        for offset in range(4)
    )
    sessions = tuple(
        {
            "exchange_code": "DCE",
            "instrument_symbol": symbol,
            "session_name": f"{symbol}-{row_day.isoformat()}",
            "start_time": time(21),
            "end_time": time(23),
            "effective_from": row_day,
            "effective_to": row_day,
            "crosses_midnight": False,
            "is_active": True,
            "provider": "rqdata",
        }
        for symbol in ("j", "jm")
        for row_day in (DAY, NEXT)
    )
    return MetadataSnapshot(
        exchanges=({"code": "DCE", "name": "DCE"},),
        instruments=(),
        contracts=(),
        calendars=calendars,
        sessions=sessions,
        main_contracts=(("j", DAY, "J2605"), ("jm", DAY, "JM2605")),
        main_contract_starts={"j": DAY, "jm": DAY},
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add_all(
        (
            Instrument(symbol="j", name="J", exchange_code="DCE", is_active=True),
            Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True),
            Contract(contract_code="J2605", instrument_symbol="j", exchange_code="DCE"),
            Contract(
                contract_code="JM2605", instrument_symbol="jm", exchange_code="DCE"
            ),
            TradingCalendar(
                exchange_code="DCE",
                trade_date=DAY,
                is_trading_day=True,
                has_night_session=True,
                provider="rqdata",
            ),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="j",
                session_name="j-2026-09-11",
                start_time=time(21),
                end_time=time(23),
                effective_from=DAY,
                effective_to=DAY,
                crosses_midnight=False,
                is_active=True,
                provider="rqdata",
            ),
            MainContractMap(symbol="j", trade_date=DAY, contract_code="J2605"),
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="j",
                session_name="warm-up",
                start_time=time(9),
                end_time=time(15),
                effective_from=date(2022, 1, 4),
                effective_to=date(2022, 1, 4),
                crosses_midnight=False,
                is_active=True,
                provider="rqdata",
            ),
        )
    )
    session.commit()
    return session


def test_snapshot_codec_is_strict_and_hash_binds_semantic_content() -> None:
    from app.market_data.current_day_metadata_recovery import (
        CurrentDayMetadataRecoveryError,
        decode_current_day_snapshot,
        encode_current_day_snapshot,
    )

    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )
    decoded = decode_current_day_snapshot(
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )

    assert decoded == _snapshot()
    assert encoded["source"] == {
        "method": "RQDataMarketAdapter.fetch_current_day_metadata",
        "arguments": {"products": ["j", "jm"], "trading_day": "2026-09-11"},
    }
    assert encoded["application_calls"]["total"] == 6
    tampered = {**encoded, "products": ["j"]}
    with pytest.raises(CurrentDayMetadataRecoveryError, match="SNAPSHOT_HASH_INVALID"):
        decode_current_day_snapshot(
            tampered,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
        )
    malformed = {**encoded, "unexpected": True}
    with pytest.raises(CurrentDayMetadataRecoveryError, match="SNAPSHOT_INVALID"):
        decode_current_day_snapshot(
            malformed,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
        )


def test_plan_discloses_exact_equal_and_insert_facts_and_blocks_value_changes() -> None:
    from app.market_data.current_day_metadata_recovery import (
        CurrentDayMetadataRecoveryError,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    session = _session()
    catalog = MarketCatalog(session, Path("."))
    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )

    plan = plan_current_day_metadata(
        catalog,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )

    assert plan["status"] == "planned"
    assert plan["readonly"] is True
    assert plan["counts"] == {
        "calendar_equal": 1,
        "calendar_insert": 3,
        "session_equal": 1,
        "session_insert": 3,
        "main_contract_equal": 1,
        "main_contract_insert": 1,
    }
    assert {item["kind"] for item in plan["facts"]} == {
        "calendar",
        "session",
        "main_contract",
    }
    row = session.scalar(
        select(TradingCalendar).where(TradingCalendar.trade_date == DAY)
    )
    row.has_night_session = False
    session.commit()
    with pytest.raises(CurrentDayMetadataRecoveryError, match="CALENDAR_CONFLICT"):
        plan_current_day_metadata(
            catalog,
            encoded,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
        )
    session.close()


def test_apply_replans_under_maintenance_lease_and_preserves_other_facts() -> None:
    from app.market_data.current_day_metadata_recovery import (
        apply_current_day_metadata,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    session = _session()
    catalog = MarketCatalog(session, Path("."))
    synchronizer = MetadataSynchronizer(SimpleNamespace(), catalog)
    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )
    plan = plan_current_day_metadata(
        catalog,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )
    events: list[str] = []

    class Lease:
        def release(self):
            events.append("released")

    result = apply_current_day_metadata(
        synchronizer,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        expected_plan_sha256=plan["plan_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
        acquire_maintenance_lock=lambda: events.append("locked") or Lease(),
        verify_identity=lambda: events.append("verified"),
    )

    assert events == ["locked", "verified", "released"]
    assert result == {
        "schema_version": 1,
        "command": "data.current-day-metadata-recovery",
        "status": "applied",
        "readonly": False,
        "trading_day": "2026-09-11",
        "product_count": 2,
        "snapshot_sha256": encoded["snapshot_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "calendar_writes": 3,
        "session_writes": 3,
        "main_contract_writes": 1,
        "provider_requests": 0,
    }
    assert (
        session.scalar(
            select(TradingSession).where(TradingSession.session_name == "warm-up")
        )
        is not None
    )
    assert (
        session.scalar(
            select(MainContractMap).where(
                MainContractMap.symbol == "jm", MainContractMap.trade_date == DAY
            )
        ).contract_code
        == "JM2605"
    )
    session.close()


def test_apply_blocks_plan_or_identity_drift_before_writer() -> None:
    from app.market_data.current_day_metadata_recovery import (
        CurrentDayMetadataRecoveryError,
        apply_current_day_metadata,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    session = _session()
    catalog = MarketCatalog(session, Path("."))
    synchronizer = MetadataSynchronizer(SimpleNamespace(), catalog)
    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )
    plan = plan_current_day_metadata(
        catalog,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )
    writes = []
    synchronizer.apply_current_day_snapshot = lambda *_args, **_kwargs: writes.append(
        True
    )

    with pytest.raises(CurrentDayMetadataRecoveryError, match="RUNTIME_IDENTITY_DRIFT"):
        apply_current_day_metadata(
            synchronizer,
            encoded,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            expected_plan_sha256=plan["plan_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
            acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None),
            verify_identity=lambda: (_ for _ in ()).throw(ValueError("drift")),
        )
    assert writes == []

    with pytest.raises(CurrentDayMetadataRecoveryError, match="MAINTENANCE_LOCKED"):
        apply_current_day_metadata(
            synchronizer,
            encoded,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            expected_plan_sha256=plan["plan_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
            acquire_maintenance_lock=lambda: None,
            verify_identity=lambda: pytest.fail("identity follows the lease"),
        )
    assert writes == []
    session.close()


def test_apply_blocks_catalog_plan_drift_under_lock_before_writer() -> None:
    from app.market_data.current_day_metadata_recovery import (
        CurrentDayMetadataRecoveryError,
        apply_current_day_metadata,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    session = _session()
    catalog = MarketCatalog(session, Path("."))
    synchronizer = MetadataSynchronizer(SimpleNamespace(), catalog)
    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )
    plan = plan_current_day_metadata(
        catalog,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )
    session.add(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2026, 9, 12),
            is_trading_day=False,
            has_night_session=False,
            provider="rqdata",
        )
    )
    session.commit()
    writes = []
    synchronizer.apply_current_day_snapshot = lambda *_args, **_kwargs: writes.append(
        True
    )

    with pytest.raises(CurrentDayMetadataRecoveryError, match="PLAN_DRIFT"):
        apply_current_day_metadata(
            synchronizer,
            encoded,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            expected_plan_sha256=plan["plan_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
            acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None),
            verify_identity=lambda: None,
        )
    assert writes == []
    session.close()


def test_apply_reports_unknown_commit_and_does_not_retry() -> None:
    from app.market_data.current_day_metadata_recovery import (
        CurrentDayMetadataRecoveryError,
        apply_current_day_metadata,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    session = _session()
    catalog = MarketCatalog(session, Path("."))
    synchronizer = MetadataSynchronizer(SimpleNamespace(), catalog)
    encoded = encode_current_day_snapshot(
        _snapshot(), products=("j", "jm"), trading_day=DAY
    )
    plan = plan_current_day_metadata(
        catalog,
        encoded,
        expected_snapshot_sha256=encoded["snapshot_sha256"],
        products=("j", "jm"),
        trading_day=DAY,
    )
    calls = []
    original_commit = session.commit

    def unknown_commit():
        calls.append("commit")
        raise OSError("outcome deliberately unknown")

    session.commit = unknown_commit
    with pytest.raises(CurrentDayMetadataRecoveryError, match="COMMIT_OUTCOME_UNKNOWN"):
        apply_current_day_metadata(
            synchronizer,
            encoded,
            expected_snapshot_sha256=encoded["snapshot_sha256"],
            expected_plan_sha256=plan["plan_sha256"],
            products=("j", "jm"),
            trading_day=DAY,
            acquire_maintenance_lock=lambda: SimpleNamespace(
                release=lambda: calls.append("release")
            ),
            verify_identity=lambda: None,
        )
    assert calls == ["commit", "release"]
    session.commit = original_commit
    assert (
        session.scalar(
            select(MainContractMap).where(
                MainContractMap.symbol == "jm", MainContractMap.trade_date == DAY
            )
        )
        is None
    )
    session.close()


def test_capture_runner_calls_shared_adapter_once_without_opening_a_session() -> None:
    from app.guiyi_cli.current_day_metadata_recovery import (
        run_current_day_metadata_recovery,
    )

    calls = []
    adapter = SimpleNamespace(
        fetch_current_day_metadata=lambda products, trading_day: (
            calls.append((products, trading_day)) or _snapshot()
        )
    )
    runtime = SimpleNamespace(
        products=("j", "jm"),
        adapter=adapter,
        synchronizer=MetadataSynchronizer(adapter, SimpleNamespace()),
        verify_identity=lambda: calls.append("verified"),
    )

    @contextmanager
    def context(root, commit, status_sha256, *, phase):
        calls.append((root, commit, status_sha256, phase))
        yield runtime

    args = SimpleNamespace(
        phase="capture",
        runtime_root="/runtime",
        runtime_commit="a" * 40,
        expected_status_sha256="b" * 64,
        trading_day=DAY,
        apply=True,
        snapshot=None,
        expected_snapshot_sha256=None,
        expected_plan_sha256=None,
    )

    result = run_current_day_metadata_recovery(args, runtime_context_factory=context)

    assert calls == [
        (Path("/runtime"), "a" * 40, "b" * 64, "capture"),
        "verified",
        (("j", "jm"), DAY),
    ]
    assert result["status"] == "captured"
    assert result["application_calls"]["total"] == 6
