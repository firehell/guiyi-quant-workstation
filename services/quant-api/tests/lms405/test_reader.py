"""Synthetic adapter failure checks; never reported as real data evidence."""

import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


def test_transaction_exit_failure_cannot_report_readable(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "lms405_reader", root / "scripts/research/lms405_replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app.db import session, readonly
    from app.market_data import composition

    @contextmanager
    def fake_session():
        yield object()

    @contextmanager
    def fail_exit(*args, **kwargs):
        yield
        raise readonly.ReadOnlyTransactionError()

    bar = SimpleNamespace(
        bar_end=datetime(2026, 9, 21, tzinfo=UTC),
        open=Decimal(1),
        high=Decimal(2),
        low=Decimal(1),
        close=Decimal(2),
    )
    result = SimpleNamespace(
        bars=(bar,), coverage=(bar.bar_end, bar.bar_end), request_identity={}
    )
    market = SimpleNamespace(
        query_contract_trading_days=lambda query: result,
        catalog=SimpleNamespace(
            contract_fact=lambda *args: SimpleNamespace(listed_date=date(2026, 1, 1))
        ),
    )
    monkeypatch.setattr(session, "SessionLocal", fake_session)
    monkeypatch.setattr(readonly, "readonly_transaction", fail_exit)
    monkeypatch.setattr(composition, "build_market_data_service", lambda _: market)
    env = tmp_path / "empty.env"
    env.write_text("")
    output = tmp_path / "result"
    monkeypatch.setattr(
        sys, "argv", ["lms405", "--env-file", str(env), "--output", str(output)]
    )
    module.main()
    report = json.loads((output / "report.json").read_text())
    assert all(
        row["status"] == "BLOCKED"
        and row["bar_count"] == 0
        and row["prefix_status"] == "BLOCKED"
        for row in report["results"]
    )
    assert "<polyline" not in (output / "comparison.html").read_text()
