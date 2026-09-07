from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime
import io
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.guiyi_cli.main import main


def test_readiness_reports_every_product_even_when_one_input_fails():
    from app.alerts.readiness import subing_readiness

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AlertRule(rule_code="subing_ths_alert_15m_v1", enabled=True,
                              scope_product_frequencies={"jm": ["15m"], "rb": ["15m"]}))
        session.commit()

        class Reader:
            def contract_input_readiness(self, symbol, *, trading_day, as_of):
                if symbol == "jm":
                    return {"symbol": symbol, "status": "blocked", "error_codes": ["HISTORICAL_PREFIX_MISSING"]}
                return {"symbol": symbol, "status": "ready", "error_codes": []}

        result = subing_readiness(session, market_read=Reader(), products=("jm", "rb"),
                                 trading_day=date(2026, 9, 7), as_of=datetime(2026, 9, 7, 7, tzinfo=UTC))
        assert result["status"] == "blocked"
        assert result["ready_count"] == 1
        assert len(result["products"]) == 2
        assert result["products"][1]["scope_enabled"] is True
        assert session.query(AlertEvent).count() == 0
        assert not session.new and not session.dirty


def test_readiness_cli_is_readonly_and_never_builds_runtime_or_downloader():
    def forbidden(*args, **kwargs):
        raise AssertionError("mutation-capable factory invoked")

    out, err = io.StringIO(), io.StringIO()
    code = main(["runtime", "subing-readiness", "--trading-day", "2026-09-07", "--as-of", "2026-09-07T07:00:00Z"],
                session_factory=lambda: nullcontext(object()),
                subing_readiness_builder=lambda session, **kw: {"status": "blocked", "readonly": True, "products": []},
                manager_factory=forbidden, live_service_factory=forbidden, alert_runtime_factory=forbidden,
                stdout=out, stderr=err)
    assert code == 1
    assert json.loads(out.getvalue())["readonly"] is True
    assert err.getvalue() == ""


def test_readiness_bad_time_fails_before_connection():
    def forbidden():
        raise AssertionError("connection before validation")

    out, err = io.StringIO(), io.StringIO()
    code = main(["runtime", "subing-readiness", "--trading-day", "2026-09-07", "--as-of", "2026-09-07T07:00:00"],
                session_factory=forbidden, stdout=out, stderr=err)
    assert code == 2
    assert json.loads(err.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"
