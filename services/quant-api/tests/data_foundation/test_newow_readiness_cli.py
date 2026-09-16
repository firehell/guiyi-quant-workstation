"""CLI read-only composition, validation before connection and rollback."""

import io
import json

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.guiyi_cli.main import main


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--symbol", "rb", "--universe", "active"],
        ["--symbol", "rb", "--apply"],
        ["--symbol", "rb", "--max-work", "0"],
        ["--symbol", "rb", "--timeout-seconds", "0"],
    ],
)
def test_invalid_readiness_intent_never_opens_session(extra):
    def forbidden():
        raise AssertionError("invalid intent opened session")

    output = io.StringIO()
    code = main(
        ["data", "newow-readiness", "--as-of", "2026-09-04T08:00:00Z", *extra],
        session_factory=forbidden,
        stdout=output,
        stderr=output,
    )
    assert code == 2
    assert json.loads(output.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


@pytest.mark.parametrize("fails", [False, True])
def test_readiness_has_one_readonly_transaction_and_always_rolls_back(fails):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    statements = []
    rolled_back = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _c, _cur, stmt, *_rest: statements.append(stmt),
    )
    event.listen(engine, "rollback", lambda _conn: rolled_back.append(True))

    def forbidden(_session):
        raise AssertionError("maintenance/provider composed")

    def run(session, *, request):
        assert request.products == ("rb",)
        assert request.as_of.isoformat() == "2026-09-04T08:00:00+00:00"
        assert session.scalar(text("PRAGMA query_only")) == 1
        if fails:
            raise RuntimeError("private backend detail")
        return {"status": "audited", "readonly": True, "complete": True}

    output = io.StringIO()
    code = main(
        [
            "data",
            "newow-readiness",
            "--symbol",
            "rb",
            "--as-of",
            "2026-09-04T08:00:00Z",
        ],
        session_factory=lambda: Session(engine),
        manager_factory=forbidden,
        newow_readiness_builder=run,
        stdout=output,
        stderr=output,
    )
    assert code == (1 if fails else 0)
    assert len(rolled_back) == 1
    assert statements[:2] == ["PRAGMA query_only", "PRAGMA query_only = ON"]
    assert "private backend detail" not in output.getvalue()


def test_weekly_operational_readiness_builds_one_readonly_60_product_scope(monkeypatch):
    from app.guiyi_cli import data_commands
    from guiyi_quant.newow.product_contracts import ProductFrequency

    products = tuple(
        f"{chr(97 + index // 26)}{chr(97 + index % 26)}" for index in range(60)
    )
    monkeypatch.setattr(data_commands, "load_operational_products", lambda: products)
    engine = create_engine("sqlite+pysqlite:///:memory:")

    def run(session, *, request):
        assert session.scalar(text("PRAGMA query_only")) == 1
        assert request.products == products
        assert request.frequencies == (ProductFrequency.WEEKLY,)
        return {"status": "audited", "readonly": True, "complete": True}

    output = io.StringIO()
    code = main(
        [
            "data",
            "newow-readiness",
            "--universe",
            "operational",
            "--frequency",
            "1w",
            "--as-of",
            "2026-09-04T08:00:00Z",
        ],
        session_factory=lambda: Session(engine),
        newow_readiness_builder=run,
        stdout=output,
        stderr=output,
    )

    assert code == 0


def test_compact_readiness_keeps_gate_identities_and_counts_without_full_rows():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    def run(_session, *, request):
        assert request.frequencies[0].value == "1w"
        return {
            "schema_version": 1,
            "command": "data.newow-readiness",
            "readonly": True,
            "status": "incomplete",
            "complete": False,
            "as_of": request.as_of.isoformat(),
            "release_stage": "daily",
            "matrix": True,
            "frequency_scope": ["1w"],
            "product_count": 1,
            "main_case_count": 3,
            "main_ready_count": 1,
            "budget_exhausted": False,
            "work_used": 12,
            "enumerations": [
                {"status": "ENUMERATED"},
                {"status": "UNKNOWN", "reason": "HISTORICAL_SESSION_FACT_MISSING"},
            ],
            "dependencies": [
                {"status": "DATA_READY"},
                {"status": "DATA_UNAVAILABLE", "reason": "REPLAY_PREFIX_MISSING"},
            ],
            "repair_targets": [
                {
                    "symbol": "rb",
                    "contract": "RB2701",
                    "frequency": "1w",
                    "through": "2026-09-04",
                    "status": "PROPOSED",
                    "expected_bar_count": 22,
                    "provider_request_count": 2,
                    "plan_sha256": "a" * 64,
                    "target_windows": [{"large": "discard"}],
                    "scope_diagnostics": [{"large": "discard"}],
                    "consumers": [{"large": "discard"}],
                }
            ],
            "metadata_proposals": [
                {
                    "symbol": "ag",
                    "contract": "AG2302",
                    "frequency": "1w",
                    "through": "2023-01-11",
                    "status": "UNKNOWN",
                    "reason": "HISTORICAL_SESSION_FACT_MISSING",
                    "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
                    "error": {"private": "discard"},
                }
            ],
            "cases": [{"symbol": "rb", "strategy": "trend", "frequency": "1w"}],
            "provider_requests": 0,
            "writes": 0,
        }

    output = io.StringIO()
    code = main(
        [
            "data",
            "newow-readiness",
            "--symbol",
            "rb",
            "--frequency",
            "1w",
            "--matrix",
            "--compact",
            "--as-of",
            "2026-09-04T08:00:00Z",
        ],
        session_factory=lambda: Session(engine),
        newow_readiness_builder=run,
        stdout=output,
        stderr=output,
    )

    assert code == 1
    payload = json.loads(output.getvalue())
    assert payload["schema_version"] == "newow_readiness_compact_v1"
    assert payload["enumeration_counts"] == {
        "ENUMERATED": 1,
        "UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1,
    }
    assert payload["dependency_counts"] == {
        "DATA_READY": 1,
        "DATA_UNAVAILABLE:REPLAY_PREFIX_MISSING": 1,
    }
    assert payload["repair_counts"] == {"PROPOSED": 1}
    assert payload["metadata_counts"] == {
        "UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1
    }
    assert payload["repair_targets"] == [
        {
            "symbol": "rb",
            "contract": "RB2701",
            "frequency": "1w",
            "through": "2026-09-04",
            "status": "PROPOSED",
            "reason": None,
            "expected_bar_count": 22,
            "provider_request_count": 2,
            "plan_sha256": "a" * 64,
        }
    ]
    assert payload["metadata_proposals"][0] == {
        "symbol": "ag",
        "contract": "AG2302",
        "frequency": "1w",
        "through": "2023-01-11",
        "status": "UNKNOWN",
        "reason": "HISTORICAL_SESSION_FACT_MISSING",
        "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
    }
    assert payload["cases"] == [
        {"symbol": "rb", "strategy": "trend", "frequency": "1w"}
    ]
    assert "dependencies" not in payload
    assert "enumerations" not in payload


def test_real_composition_missing_metadata_never_constructs_provider_writer_or_redis(
    monkeypatch, tmp_path
):
    from app.db.base import Base
    from app.market_data import (
        composition,
        historical_data_manager,
        metadata,
        rqdata_adapter,
    )
    from app.market_data.newow import readiness_composition
    from app.market_data.newow.readiness import ReadinessRequest
    from datetime import UTC, datetime

    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("forbidden mutation capability constructed")

    monkeypatch.setattr(rqdata_adapter, "RQDataMarketAdapter", forbidden)
    monkeypatch.setattr(metadata, "MetadataSynchronizer", forbidden)
    monkeypatch.setattr(historical_data_manager, "HistoricalDataManager", forbidden)
    monkeypatch.setattr(composition, "get_redis_connection", forbidden)
    monkeypatch.setattr(composition, "canonical_root", lambda: tmp_path / "canonical")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(text("PRAGMA query_only = ON"))
        report = readiness_composition.build_newow_readiness(
            session,
            request=ReadinessRequest(
                ("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC), max_work=100
            ),
        )
        assert report["complete"] is False
        assert report["dependencies"] == []
        assert report["writes"] == report["provider_requests"] == 0
        assert calls == []
        assert list(tmp_path.iterdir()) == []
        session.rollback()


def test_shared_readonly_transaction_rejects_writes_and_rolls_back():
    from app.db import readonly
    from sqlalchemy.exc import OperationalError

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as session:
        with pytest.raises(OperationalError):
            with readonly.readonly_transaction(session, timeout_seconds=1):
                session.execute(text("CREATE TABLE forbidden (id integer)"))
        assert not session.in_transaction()
        assert (
            session.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE name='forbidden'")
            )
            == 0
        )


@pytest.mark.parametrize("original", [0, 1])
@pytest.mark.parametrize("fails", [False, True])
def test_sqlite_guard_restores_original_connection_state_before_reuse(original, fails):
    from app.db.readonly import readonly_transaction

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        connection.exec_driver_sql(f"PRAGMA query_only = {original}")
    with Session(engine) as session:
        try:
            with readonly_transaction(session):
                assert session.scalar(text("PRAGMA query_only")) == 1
                if fails:
                    raise RuntimeError("fixture stop")
        except RuntimeError:
            assert fails
    with Session(engine) as next_session:
        assert next_session.scalar(text("PRAGMA query_only")) == original
        if original == 0:
            next_session.execute(text("CREATE TABLE ordinary (id integer)"))
            assert next_session.scalar(text("SELECT count(*) FROM ordinary")) == 0


def test_sqlite_restore_failure_discards_connection_instead_of_leaking_state():
    from app.db.readonly import readonly_transaction, ReadOnlyTransactionError

    engine = create_engine("sqlite+pysqlite:///:memory:")
    invalidations = []
    event.listen(engine.pool, "invalidate", lambda *_args: invalidations.append(True))

    def fail_restore(_conn, _cursor, statement, *_rest):
        if statement == "PRAGMA query_only = OFF":
            raise RuntimeError("fixture restoration error")

    event.listen(engine, "before_cursor_execute", fail_restore)
    with Session(engine) as session:
        with pytest.raises(ReadOnlyTransactionError):
            with readonly_transaction(session):
                assert session.scalar(text("PRAGMA query_only")) == 1
    assert invalidations == [True]
    event.remove(engine, "before_cursor_execute", fail_restore)
    with Session(engine) as other:
        assert other.scalar(text("PRAGMA query_only")) == 0
        other.execute(text("CREATE TABLE usable (id integer)"))
