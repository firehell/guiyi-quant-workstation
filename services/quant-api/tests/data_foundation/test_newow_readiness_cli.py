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
    assert statements[0] == "PRAGMA query_only = ON"
    assert "private backend detail" not in output.getvalue()


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
