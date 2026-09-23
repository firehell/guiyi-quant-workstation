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
from uuid import uuid4

from sqlalchemy import create_engine
import uvicorn

from scripts.reference_trading_benchmark import validate_target


def main() -> None:
    database, version = validate_target(dict(os.environ))
    url = os.environ["GUIYI_ISOLATED_MIGRATION_DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    from app.core import env as project_env

    project_env.load_project_env = lambda: None
    from app.api import reference_trading as reference_api
    from app.db.base import Base
    from app.main import app
    from app.reference_trading.health import ForwardReferenceHealth
    from app.reference_trading.query import HistoricalReferenceQuery
    from tests.reference_trading.test_historical_integration import _verify_historical_pipeline
    from tests.reference_trading.test_newow_worker_recovery import (
        _assert_restart_projects_pending_capture_once, _setup,
        test_postgresql_htdy_first_seen_capture_to_persisted_readback,
        test_postgresql_subing_forward_capture_to_persisted_readback,
    )
    import pytest
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)
    schema = "reference_p8_browser_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        with TemporaryDirectory(prefix="guiyi-p8-browser-", dir="/private/tmp") as directory:
            patcher = pytest.MonkeyPatch()
            try:
                _verify_historical_pipeline(scoped, Path(directory), patcher)
                factory, repo, identity, revision, start, observed, reader = _setup(engine=scoped)
                _assert_restart_projects_pending_capture_once(
                    factory, repo, identity, revision, start, observed, reader,
                )
                test_postgresql_subing_forward_capture_to_persisted_readback(scoped, "60m")
                test_postgresql_htdy_first_seen_capture_to_persisted_readback(scoped)
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
                patcher.undo()
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


if __name__ == "__main__":
    main()
