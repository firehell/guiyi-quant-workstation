from datetime import date

from app.services.newow_backtest_eod import affected_products, research_key


def test_completed_publication_is_required_and_duplicates_collapse():
    publication = {"dataset": ["contract", "fu", "FU2603", "1m"], "year": 2026, "month": 1}
    retained = {"last_run": {
        "status": "passed", "trading_day": "2026-01-05", "products": ["fu", "rb"],
        "historical_publications": [publication, publication],
    }, "last_successful_trading_day": "2026-01-05"}
    assert affected_products(retained, date(2026, 1, 5), {"fu", "rb"}) == ("fu", "rb")
    assert affected_products(retained, date(2026, 1, 6), {"fu", "rb"}) == ()
    retained["last_run"]["status"] = "failed"
    assert affected_products(retained, date(2026, 1, 5), {"fu", "rb"}) == ()


def test_all_matrix_keys_have_disjoint_trial_identity():
    keys = [research_key("fu", strategy, frequency, trial=trial)
            for strategy in ("trend", "oscillation", "dual_fusion")
            for frequency in ("5m", "15m", "30m", "60m", "1d", "1w")
            for trial in (True, False)]
    assert len(set(keys)) == 36
    assert sum(key.is_trial for key in keys) == 18
    assert research_key("fu", "trend", "5m", trial=True).research_profile_id == "trend_5m_rqalpha_trial_v1"


def test_same_month_superseded_receipt_is_rejected():
    from pathlib import Path
    from types import SimpleNamespace

    from app.market_data.domain import DatasetKey
    from app.services.newow_backtest_eod import _source_is_current

    key = DatasetKey("contract", "fu", "FU2603", "1m")
    part = SimpleNamespace(dataset=key, year=2026, month=1, file_path=Path("part.new.parquet"))
    catalog = SimpleNamespace(product_partitions=lambda _: (part,))
    older = {"dataset": ["contract", "fu", "FU2603", "1m"], "year": 2026, "month": 1,
             "file_name": "part.old.parquet"}
    current = older | {"file_name": "part.new.parquet"}
    assert not _source_is_current(catalog, [older], "fu")
    assert _source_is_current(catalog, [older, current], "fu")


def test_matrix_freezes_all_six_frequencies_from_bounded_canonical(tmp_path, monkeypatch):
    from collections import defaultdict
    from dataclasses import replace
    from datetime import UTC, datetime, time, timedelta
    from decimal import Decimal
    from hashlib import sha256
    import json
    import os
    from pathlib import Path

    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.db.readonly import readonly_transaction
    from app.market_data.aggregation import SessionWindow, aggregate_from_1m
    from app.market_data.catalog import MarketCatalog
    from app.market_data.domain import CanonicalBar, DatasetKey
    from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
    from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
    from app.services.newow_backtest_job import BacktestJobError, _json, _launch, _seal, freeze_research
    from guiyi_quant.newow.decision_adapter import DECISION_FREQUENCIES, V2Strategy

    first, through = date(2026, 1, 5), date(2026, 3, 27)
    calendar_days = tuple(first + timedelta(days=index) for index in range((through - first).days + 4))
    days = tuple(day for day in calendar_days if day <= through and day.weekday() < 5)
    def start_of(day):
        return datetime.combine(day, time(1), UTC)

    isolated_market = os.getenv("GUIYI_P4_EOD_TEST_MARKET_DSN")
    if isolated_market:
        from app.services.newow_backtest_eod import _isolated_market_url
        _isolated_market_url(isolated_market)
    work = create_engine(isolated_market or "sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(work)
    root = tmp_path / "canonical"
    root.mkdir()
    minute_count = 70
    price = Decimal("2500")
    oi = Decimal("12")
    sessions = tuple(SessionWindow(start_of(day), start_of(day) + timedelta(minutes=minute_count)) for day in days)
    minutes = tuple(CanonicalBar(window.start + timedelta(minutes=index), day, price, price, price, price,
                                 Decimal("1"), Decimal("2500"), oi)
                    for day, window in zip(days, sessions, strict=True) for index in range(1, minute_count + 1))
    daily = tuple(replace(bar, volume=Decimal(minute_count), turnover=price * minute_count)
                  for bar in minutes[minute_count - 1::minute_count])
    weekly = tuple(replace(bar, volume=Decimal(minute_count * 5), turnover=price * minute_count * 5)
                   for bar in daily if bar.trading_day.weekday() == 4)
    datasets = {"1m": minutes, "1d": daily, "1w": weekly}
    datasets.update({frequency: aggregate_from_1m(minutes, target_frequency=frequency, sessions=sessions)
                     for frequency in ("5m", "15m", "30m", "60m")})
    with Session(work) as session:
        session.add(Exchange(code="SHFE", name="SHFE"))
        session.add(Instrument(symbol="fu", name="FU", exchange_code="SHFE", is_active=True))
        session.flush()
        session.add(Contract(contract_code="FU2605", instrument_symbol="fu", exchange_code="SHFE",
                             listed_date=first, expired_date=date(2026, 5, 20), provider="rqdata"))
        session.add_all(TradingSession(exchange_code="SHFE", instrument_symbol="fu", session_name="day",
                                      start_time=time(9), end_time=time(10, 10), effective_from=day,
                                      effective_to=day, is_active=True) for day in days)
        session.add_all(TradingCalendar(exchange_code="SHFE", trade_date=day, is_trading_day=day.weekday() < 5)
                        for day in calendar_days)
        session.flush()
        catalog, storage = MarketCatalog(session, root), CanonicalMonthlyStore(root)
        catalog.upsert_main_contracts(tuple(("fu", day, "FU2605") for day in days))
        for frequency, bars in datasets.items():
            parts = defaultdict(list)
            for bar in bars:
                parts[(bar.trading_day.year, bar.trading_day.month)].append(bar)
            for (year, month), part in parts.items():
                catalog.register_partition(storage.publish(PublishRequest(
                    DatasetKey("contract", "fu", "FU2605", frequency), year, month,
                    tuple(part), tuple(bar.bar_end for bar in part),
                )))
        session.commit()
    early_week = date(2026, 1, 23)
    facts = tmp_path / "dated.json"
    facts.write_text(json.dumps({
        "instrument": {"order_book_id": "FU2605", "contract_multiplier": 10, "tick_size": "1"},
        "parameters": [{
            "date": str(day), "commission_type": "by_volume", "open_commission": "2",
            "close_commission": "3", "close_commission_today": "4", "long_margin_ratio": "0.1",
            "short_margin_ratio": "0.2",
        } for day in (early_week, through)],
        "daily": [{"date": str(day), "prev_settlement": "2500", "settlement": "2500",
                   "limit_down": "2300", "limit_up": "2700"} for day in (early_week, through)],
    }))
    digest = sha256(facts.read_bytes()).hexdigest()
    def freeze(strategy, frequency, day=through):
        with Session(work) as session, readonly_transaction(session):
            return freeze_research(
                session, root, product="fu", strategy=strategy, frequency=frequency,
                since=day, through=day, facts_path=facts, facts_digest=digest, witnesses={},
            )

    engine = os.getenv("GUIYI_P4_MATRIX_ENGINE")
    for frequency in DECISION_FREQUENCIES:
        for strategy in V2Strategy:
            packet, manifest = freeze(strategy, frequency)
            assert packet["frequency"] == frequency.value and packet["strategy"] == strategy.value
            assert manifest["warmup_count"] >= 10 and manifest["execution_bar_count"] == minute_count
            assert manifest["rank1"]["code"] == "RANK1_AS_KNOWN_UNPROVEN"
            assert packet["completed"][-1]["candidate_open_at"] is None
            if frequency.value == "60m":
                assert manifest["signal_bar_count"] == 2
                assert packet["completed"][-2]["candidate_open_at"] == start_of(through) + timedelta(minutes=61)
            if engine and not isolated_market:
                data = _json(packet)
                fingerprint = sha256(data).hexdigest()
                artifact = _seal(tmp_path, data, fingerprint)
                if frequency.value in ("1d", "1w"):
                    with pytest.raises(BacktestJobError, match="BACKTEST_EXECUTION_POLICY_UNAVAILABLE"):
                        _launch(Path(engine), artifact, fingerprint, "a" * 64)
                else:
                    result = _launch(Path(engine), artifact, fingerprint, "a" * 64)
                    assert result["summary"]["cutoff_trading_day"] == through.isoformat()
                    assert result["summary"]["money_policy"] == "cny_8_half_even_v1"

    from guiyi_quant.newow.product_contracts import ProductFrequency

    with pytest.raises(BacktestJobError, match="BACKTEST_WARMUP_INSUFFICIENT"):
        freeze(V2Strategy.DUAL_FUSION, ProductFrequency.WEEKLY, early_week)

    def submit_receipt():
        from app.main import app
        from app.market_data.after_market import _atomic_write_status
        from app.services.newow_backtest_eod import reconcile_publications
        from fastapi.testclient import TestClient

        assert engine
        sealed = tmp_path / "sealed"
        sealed.mkdir()
        for name, value in {
            "GUIYI_NEWOW_EOD_MARKET_DSN": isolated_market,
            "GUIYI_NEWOW_EOD_CANONICAL_ROOT": str(root),
            "GUIYI_NEWOW_EOD_INPUT_DIR": str(sealed),
            "GUIYI_NEWOW_EOD_ENGINE": engine,
            "GUIYI_NEWOW_BACKTEST_WRITE_DSN": os.environ["GUIYI_P3_TEST_WRITE_DSN"],
            "GUIYI_NEWOW_BACKTEST_READ_DSN": os.environ["GUIYI_P3_TEST_READ_DSN"],
        }.items():
            monkeypatch.setenv(name, value)
        config = tmp_path / "research.json"
        config.write_text(json.dumps([{"product": "fu", "trial": True, "since": str(through),
                                       "facts": str(facts), "facts_sha256": digest}]))
        with Session(work) as session, readonly_transaction(session):
            parts = MarketCatalog(session, root).product_partitions("fu")
            publication = [
                {"dataset": [part.dataset.kind.value, "fu", part.dataset.series_or_contract, part.dataset.frequency.value],
                 "year": part.year, "month": part.month, "file_name": part.file_path.name,
                 "provenance": {"version": 1, "input_source": "historical_provider", "input_sha256": "b" * 64}}
                for part in parts if part.month == through.month
            ]
        authority = tmp_path / "after-market-status.json"
        _atomic_write_status(authority, {
            "schema_version": 4, "last_successful_trading_day": str(through),
            "last_run": {"status": "passed", "attempts": 1, "error_code": None, "trading_day": str(through),
                         "started_at": f"{through}T18:05:00+08:00", "finished_at": f"{through}T18:09:00+08:00",
                         "products": ["fu"], "historical_publications": publication},
        })
        report, = reconcile_publications(authority, config)
        assert report["series"] == report["computed"] == 18, report
        assert report["failed"] == []
        print(f"after-market isolated: {report['computed']} series, {report['work_seconds']}s, {len(report['failed'])} failures")
        assert reconcile_publications(authority, config) == []
        with TestClient(app) as client:
            for frequency in ("5m", "15m", "30m", "60m", "1d", "1w"):
                key = research_key("fu", "trend", frequency, trial=True)
                result = client.get("/api/v1/newow/backtests/latest", params={
                    "product": key.product, "strategy": key.strategy, "frequency": key.frequency,
                    "research_profile_id": key.research_profile_id,
                })
                assert result.status_code == 200, result.text
                row = result.json()["result"]
                assert row["qualification"] == "TRIAL"
                assert row["as_of_trading_day"] == str(through) and row["finished_at"]
                assert (row["summary"].get("result_kind") == "reference_only") == (frequency in ("1d", "1w"))
                uri = f"/api/v1/newow/backtests/{row['run_id']}/equity"
                page = client.get(uri)
                assert page.status_code == 200 and page.json()["run_id"] == row["run_id"]
                assert bool(page.json()["items"]) == (frequency not in ("1d", "1w"))
        assert reconcile_publications(authority, config) == []

    if isolated_market:
        submit_receipt()

    original, _ = freeze(V2Strategy.TREND, ProductFrequency.FIVE_MINUTE)
    revised = list(minutes)
    revised[-1] = replace(revised[-1], high=price + 1, close=price + 1)
    with Session(work) as session:
        catalog = MarketCatalog(session, root)
        for frequency, bars in (("1m", tuple(revised)), ("5m", aggregate_from_1m(
            tuple(revised), target_frequency="5m", sessions=sessions,
        ))):
            month = tuple(bar for bar in bars if bar.trading_day.month == through.month)
            catalog.register_partition(storage.publish(PublishRequest(
                DatasetKey("contract", "fu", "FU2605", frequency), through.year, through.month,
                month, tuple(bar.bar_end for bar in month),
            )))
        session.commit()
    revised_packet, _ = freeze(V2Strategy.TREND, ProductFrequency.FIVE_MINUTE)
    assert revised_packet["market_revision"] != original["market_revision"]
    assert revised_packet["completed"][-1]["bar"]["close"] != original["completed"][-1]["bar"]["close"]
    work.dispose()
