#!/usr/bin/env python3
"""Serve disposable persisted P8 fixtures through the real FastAPI routes.

Only the dedicated loopback test DB is accepted. The project .env loader is
disabled before importing the application; no provider or Runtime starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
import uvicorn

from scripts.reference_trading_benchmark import validate_target


def main() -> None:
    database, version = validate_target(dict(os.environ))
    url = os.environ["GUIYI_ISOLATED_MIGRATION_DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    os.environ["REDIS_URL"] = "redis://127.0.0.1:56380/0"
    from app.core import env as project_env

    project_env.load_project_env = lambda: None
    from app.api import reference_trading as reference_api
    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app
    from app.reference_trading.health import ForwardReferenceHealth
    from app.reference_trading.query import HistoricalReferenceQuery
    from app.models import TradingCalendar, TradingSession
    from app.alerts.models import AlertEvent, AlertRule
    from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE
    from tests.reference_trading.test_historical_integration import _verify_historical_pipeline
    from tests.reference_trading.test_newow_worker_recovery import (
        _assert_restart_projects_pending_capture_once, _setup,
        test_postgresql_htdy_first_seen_capture_to_persisted_readback,
        test_postgresql_subing_forward_capture_to_persisted_readback,
    )
    import pytest
    from sqlalchemy import select
    from sqlalchemy.orm import Session, sessionmaker

    engine = create_engine(url)
    schema = "reference_p8_browser_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        with TemporaryDirectory(prefix="guiyi-p8-browser-", dir="/private/tmp") as directory:
            os.environ["GUIYI_CANONICAL_DATA_ROOT"] = directory
            def isolated_db():
                with Session(scoped) as session:
                    yield session
            app.dependency_overrides[get_db] = isolated_db
            patcher = pytest.MonkeyPatch()
            try:
                _verify_historical_pipeline(scoped, Path(directory), patcher)
                # The pipeline test disables legacy replay while checking the
                # persisted adapter. Browser readback must use the real kernel.
                patcher.undo()
                # The integration test deliberately shifts this first Session to
                # 08:59 for revision rejection. Restore its original fixture fact
                # before serving ordinary Market pages over the same Canonical.
                with Session(scoped) as session:
                    first_session = session.scalar(select(TradingSession).where(
                        TradingSession.instrument_symbol == "rb",
                        TradingSession.effective_from == date(2026, 1, 5),
                    ))
                    assert first_session is not None and first_session.start_time == time(8, 59)
                    first_session.start_time = time(9)
                    # Legacy SuBing validates the complete one-year Calendar
                    # horizon even when the requested display window is shorter.
                    first_calendar = date(2025, 3, 27)
                    session.add_all(
                        TradingCalendar(
                            exchange_code="SHFE", trade_date=first_calendar + timedelta(days=offset),
                            is_trading_day=(first_calendar + timedelta(days=offset)).weekday() < 5,
                            provider="rqdata",
                        )
                        for offset in range((date(2026, 1, 5) - first_calendar).days)
                    )
                    session.add_all(
                        TradingSession(
                            exchange_code="SHFE", instrument_symbol="rb", session_name="day",
                            start_time=time(9), end_time=time(13),
                            effective_from=first_calendar + timedelta(days=offset),
                            effective_to=first_calendar + timedelta(days=offset),
                            is_active=True, provider="rqdata",
                        )
                        for offset in range((date(2026, 1, 5) - first_calendar).days)
                        if (first_calendar + timedelta(days=offset)).weekday() < 5
                    )
                    rule = AlertRule(
                        rule_code=SUBING_THS_ALERT_RULE_CODE,
                        enabled=False,
                        scope_product_frequencies={},
                    )
                    session.add(rule)
                    session.flush()
                    bar_end = datetime(2026, 3, 27, 5, tzinfo=UTC)
                    session.add(AlertEvent(
                        rule_id=rule.id, symbol="rb", contract="RB2701",
                        trading_day=date(2026, 3, 27), frequency="15m",
                        bar_end=bar_end, result_codes=["buy"],
                        detected_at=bar_end,
                    ))
                    session.commit()
                factory, repo, identity, revision, start, observed, reader = _setup(engine=scoped)
                _assert_restart_projects_pending_capture_once(
                    factory, repo, identity, revision, start, observed, reader,
                )
                test_postgresql_subing_forward_capture_to_persisted_readback(scoped, "60m")
                test_postgresql_htdy_first_seen_capture_to_persisted_readback(scoped)
                from app.api.market_subing_reference import _build_service
                from app.market_data.subing_reference import SubingReferenceQuery
                with Session(scoped) as session:
                    _build_service(session, lambda: None).query(SubingReferenceQuery(
                        "rb", date(2026, 1, 5), date(2026, 3, 27), frequency="15m",
                    ))
                factory = sessionmaker(scoped, expire_on_commit=False)
                reference_api._query = HistoricalReferenceQuery(factory)
                reference_api._health = ForwardReferenceHealth(factory)
                historical = reference_api._query.streams(
                    strategy="newow-oscillation", product="rb", frequency="1d",
                    mode="historical_replay",
                )
                forward = reference_api._query.streams(
                    strategy="newow-trend", product="rb", frequency="1d",
                    mode="forward_observation",
                )
                assert len(historical) == 1 and len(forward) == 1
                print("P8_BROWSER_READY=" + json.dumps({
                    "database": database, "postgresql_version": version,
                    "schema": schema, "historical_stream": historical[0]["stream_id"],
                    "forward_stream": forward[0]["stream_id"],
                    "port": 18081,
                }, sort_keys=True), flush=True)
                uvicorn.run(app, host="127.0.0.1", port=18081, log_level="warning")
            finally:
                app.dependency_overrides.pop(get_db, None)
                patcher.undo()
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


if __name__ == "__main__":
    main()
