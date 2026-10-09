from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from app.market_data.newow.experiments import ExperimentQuery, NewowExperimentService
from app.market_data.newow.product_query import ProductReadWindow
from app.market_data.newow.product_reader import ProductReadSet


NOW = datetime(2026, 10, 9, tzinfo=UTC)


def make_bar(index, contract="RB2701", segment="owner"):
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return ProductBar(
        NewowDailyBar(
            "rb",
            contract,
            segment,
            timestamp.date(),
            timestamp,
            Decimal("100"),
            Decimal("110"),
            Decimal("90"),
            Decimal("100"),
            100,
            100,
            "source",
            True,
            True,
        ),
        ProductFrequency.DAILY,
    )


class Reader:
    def __init__(self, bars):
        self.bars = bars
        self.loads = []

    def resolve_chart_window(self, product, frequency, limit, as_of):
        return ProductReadWindow(date(2026, 1, 1), date(2026, 2, 28))

    def load(self, query, as_of):
        self.loads.append(query)
        window = ProductReadWindow(query.since, query.through)
        return ProductReadSet(
            query.frequency,
            {query.frequency: self.bars},
            (),
            (),
            window,
            window,
            {},
            as_of,
        )


def test_independent_identity_and_read_only_results():
    reader = Reader(tuple(make_bar(i) for i in range(20)))
    result = NewowExperimentService(reader, now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test")
    )
    assert result["page_parity"] is True and result["executable"] is False
    assert result["kind"] == "osc-test"
    assert result["readiness"]["status"] == "READY"
    assert (
        result["segments"][0]["ordinary"]["model_version"]
        != result["segments"][0]["theoretical"]["model_version"]
    )
    assert len(result["input_snapshot_hash"]) == 64
    assert reader.loads[0].strategy.value == "oscillation"


def test_physical_owner_isolation_and_gap_status():
    bars = tuple(make_bar(i) for i in range(12)) + tuple(
        make_bar(i, "RB2705", "owner2") for i in range(12, 24)
    )
    result = NewowExperimentService(Reader(bars), now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test2")
    )
    assert [segment["status"] for segment in result["segments"]] == [
        "ROLLOVER_INTERRUPTED",
        "CURRENT",
    ]
    assert len(result["segments"]) == 2
    for segment in result["segments"]:
        for trade in segment["ordinary"]["trades"]:
            assert trade["physical_contract"] == segment["physical_contract"]
            assert trade["segment_id"] == segment["segment_id"]


@pytest.mark.parametrize(
    "change",
    [dict(product="cu"), dict(bar_end=NOW), dict(bar_end=NOW + timedelta(seconds=1))],
)
def test_identity_and_strict_before_rejected(change):
    bars = list(make_bar(i) for i in range(20))
    bars[-1] = replace(bars[-1], bar=replace(bars[-1].bar, **change))
    with pytest.raises(ValueError):
        NewowExperimentService(Reader(tuple(bars)), now=lambda: NOW).query(
            ExperimentQuery("rb", "1d", "osc-test")
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(kind="trend"),
        dict(frequency="2m"),
        dict(product="RB"),
        dict(chart_limit=True),
        dict(chart_limit=10),
        dict(since=date(2026, 1, 1)),
        dict(as_of=datetime(2026, 1, 1)),
    ],
)
def test_bad_parameters(kwargs):
    with pytest.raises(ValueError):
        ExperimentQuery(
            **(dict(product="rb", frequency="1d", kind="osc-test") | kwargs)
        )


def test_future_asof_and_empty_are_fail_closed():
    with pytest.raises(ValueError):
        NewowExperimentService(Reader(()), now=lambda: NOW).query(
            ExperimentQuery("rb", "1d", "osc-test", NOW + timedelta(days=1))
        )
    with pytest.raises(ValueError):
        NewowExperimentService(Reader(()), now=lambda: NOW).query(
            ExperimentQuery("rb", "1d", "osc-test")
        )


def test_warmup_outputs_no_hidden_markers():
    bars = tuple(
        replace(make_bar(i), bar=replace(make_bar(i).bar, observation_eligible=i >= 12))
        for i in range(20)
    )
    result = NewowExperimentService(Reader(bars), now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test3")
    )
    earliest = bars[12].bar.bar_end.isoformat()
    assert all(bar["bar_end"] >= earliest for bar in result["bars"])
    assert all(marker["bar_end"] >= earliest for marker in result["markers"])


def test_real_reader_completed_snapshot(product_cases):
    reader, query, fake = product_cases.paged_reader(
        prefix_bars=24, page_size=20, frequency="1d"
    )
    result = NewowExperimentService(reader, now=lambda: fake.as_of).query(
        ExperimentQuery("rb", "1d", "osc-test4", fake.as_of, query.since, query.through)
    )
    assert result["as_of"] == fake.as_of.isoformat()
    assert all(
        datetime.fromisoformat(bar["bar_end"]) < fake.as_of for bar in result["bars"]
    )
    assert result["segments"]


@pytest.mark.parametrize(
    "parameters",
    [
        [
            ("product", "rb"),
            ("frequency", "1d"),
            ("kind", "osc-test"),
            ("kind", "osc-test2"),
        ],
        dict(product="rb", frequency="1d", kind="osc-test", unknown="1"),
        dict(
            product="rb", frequency="1d", kind="osc-test", as_of="2030-01-01T00:00:00Z"
        ),
        dict(
            product="rb", frequency="1d", kind="osc-test", as_of="2026-01-01T00:00:00"
        ),
        dict(product="rb", frequency="1d", kind="trend"),
    ],
)
def test_route_rejects_parameters_before_market_access(parameters):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db

    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/market/newow/experiments", params=parameters)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_route_read_only_projection(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db
    from app.api import market_newow

    reader = Reader(tuple(make_bar(i) for i in range(20)))
    monkeypatch.setattr(
        market_newow, "build_market_data_service", lambda session: object()
    )
    monkeypatch.setattr(
        market_newow, "build_database_coverage_source", lambda session: object()
    )
    monkeypatch.setattr(market_newow, "load_active_products", lambda: {"rb"})
    monkeypatch.setattr(
        market_newow, "NewowProductReader", lambda *args, **kwargs: reader
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/experiments",
                params=dict(
                    product="rb",
                    frequency="1d",
                    kind="osc-test4",
                    as_of=NOW.isoformat(),
                ),
            )
        assert response.status_code == 200, response.text
        assert response.json()["kind"] == "osc-test4"
        assert response.json()["executable"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("event_kind", ["gap", "rollover"])
def test_tail_break_never_creates_terminal_realization(event_kind):
    from guiyi_quant.newow.product_contracts import DataInterruption, OwnerBoundary

    bars = tuple(make_bar(i) for i in range(11))
    effective = bars[-1].bar.bar_end + timedelta(seconds=1)
    reader = Reader(bars)
    original = reader.load

    def load(query, as_of):
        read = original(query, as_of)
        if event_kind == "gap":
            event = DataInterruption(
                "rb",
                ProductFrequency.DAILY,
                "RB2701",
                "owner",
                effective.date(),
                effective,
                "proof",
            )
            return replace(
                read, data_interruptions_by_frequency={ProductFrequency.DAILY: (event,)}
            )
        event = OwnerBoundary(
            "rb",
            "RB2701",
            "RB2705",
            "owner",
            "next",
            effective.date(),
            effective,
            "proof",
        )
        return replace(read, boundaries=(event,))

    reader.load = load
    result = NewowExperimentService(reader, now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test4")
    )
    segment = result["segments"][-1]
    assert segment["status"] == (
        "DATA_CONFLICT" if event_kind == "gap" else "ROLLOVER_INTERRUPTED"
    )
    assert result["window"]["terminal_eligible"] is False
    assert not any(trade["force_close"] for trade in segment["ordinary"]["trades"])
    assert Decimal(segment["ordinary"]["summary"]["cum_return_percentage_points"]) == 0


def test_all_history_uses_authoritative_performance_window():
    from app.market_data.newow.product_reader import ResolvedPerformanceWindow

    reader = Reader(tuple(make_bar(i) for i in range(20)))
    calls = []

    def resolve(*args):
        calls.append(args)
        return ResolvedPerformanceWindow(
            date(2026, 1, 1), date(2026, 1, 20), date(2026, 1, 20), NOW, True
        )

    reader.resolve_performance_window = resolve
    result = NewowExperimentService(reader, now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test", all_history=True)
    )
    assert calls[0][2:4] == (None, None)
    assert result["window"]["all_history"] is True
    assert reader.loads[0].performance_since == date(2026, 1, 1)


def test_current_segment_warmup_is_not_hidden_by_old_ready_segment():
    bars = tuple(make_bar(i) for i in range(12)) + tuple(
        make_bar(i, "RB2705", "owner2") for i in range(12, 17)
    )
    result = NewowExperimentService(Reader(bars), now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test")
    )
    assert result["segments"][0]["readiness"]["status"] == "READY"
    assert result["segments"][-1]["readiness"]["status"] == "WARMUP"
    assert result["readiness"]["status"] == "WARMUP"


def test_explicit_window_keeps_warmup_but_bounds_reference_dates():
    reader = Reader(tuple(make_bar(i) for i in range(25)))
    result = NewowExperimentService(reader, now=lambda: NOW).query(
        ExperimentQuery(
            "rb", "1d", "osc-test2", since=date(2026, 1, 12), through=date(2026, 1, 20)
        )
    )
    assert result["bars"][0]["trading_day"] == "2026-01-12"
    assert result["bars"][-1]["trading_day"] == "2026-01-20"
    assert result["bars"][0]["channel_high"] is not None
    ordinary = result["segments"][0]["ordinary"]
    assert all(
        "2026-01-12" <= timestamp[:10] <= "2026-01-20"
        for timestamp in ordinary["dates"]
    )
    assert all(
        "2026-01-12" <= trade["exit_bar_end"][:10] <= "2026-01-20"
        for trade in ordinary["trades"]
    )


def test_reference_chart_limit_does_not_clip_statistics_window():
    reader = Reader(tuple(make_bar(i) for i in range(25)))
    result = NewowExperimentService(reader, now=lambda: NOW).query(
        ExperimentQuery("rb", "1d", "osc-test", chart_limit=11)
    )
    assert len(result["bars"]) == 11
    assert all(
        marker["bar_end"] in {bar["bar_end"] for bar in result["bars"]}
        for marker in result["markers"]
    )
    assert len(result["segments"][0]["ordinary"]["dates"]) > len(result["bars"])


def test_cancelled_service_does_not_emit_partial_projection():
    reader = Reader(tuple(make_bar(i) for i in range(25)))
    with pytest.raises(ValueError, match="NEWOW_REQUEST_CANCELLED"):
        NewowExperimentService(reader, now=lambda: NOW, cancelled=lambda: True).query(
            ExperimentQuery("rb", "1d", "osc-test")
        )


@pytest.mark.parametrize("function", ["markers", "ordinary", "ideal"])
def test_long_segment_replay_checks_cancellation(function):
    from guiyi_quant.newow.oscillation_experiments import (
        calculate_experiment_series,
        run_experiment_reference,
        run_base_oscillation_ideal,
        ExperimentKind,
    )

    bars = tuple(make_bar(i).bar for i in range(600))
    calls = []

    def check():
        calls.append(True)
        if len(calls) == 2:
            raise ValueError("NEWOW_REQUEST_CANCELLED")

    with pytest.raises(ValueError, match="NEWOW_REQUEST_CANCELLED"):
        if function == "markers":
            calculate_experiment_series(
                bars, ExperimentKind.TEST1, check_cancelled=check
            )
        elif function == "ordinary":
            run_experiment_reference(bars, ExperimentKind.TEST1, check_cancelled=check)
        else:
            run_base_oscillation_ideal(bars, check_cancelled=check)
    assert len(calls) == 2


def test_window_preserves_entry_before_since_and_selects_exit():
    values = [(105, 110, 102, 105)] * 9 + [
        (103, 108, 100, 104),
        (103, 109, 101, 105),
        (110, 115, 103, 112),
    ]
    bars = tuple(
        replace(
            make_bar(i),
            bar=replace(
                make_bar(i).bar,
                open=Decimal(o),
                high=Decimal(h),
                low=Decimal(low),
                close=Decimal(c),
            ),
        )
        for i, (o, h, low, c) in enumerate(values)
    )
    service = NewowExperimentService(Reader(bars), now=lambda: NOW)
    full = service.query(
        ExperimentQuery(
            "rb", "1d", "osc-test", since=date(2026, 1, 1), through=date(2026, 1, 12)
        )
    )
    short = service.query(
        ExperimentQuery(
            "rb", "1d", "osc-test", since=date(2026, 1, 11), through=date(2026, 1, 12)
        )
    )
    full_ordinary, short_ordinary = (
        full["segments"][0]["ordinary"],
        short["segments"][0]["ordinary"],
    )
    assert (
        short_ordinary["summary"]["trade_count"]
        == full_ordinary["summary"]["trade_count"]
        == 1
    )
    assert Decimal(short_ordinary["summary"]["cum_return_percentage_points"]) == 15
    trade = short_ordinary["trades"][0]
    assert trade["entry_bar_end"][:10] == "2026-01-10"
    assert Decimal(trade["entry_reference_price"]) == 100
    assert trade["exit_bar_end"][:10] == "2026-01-12"
    assert Decimal(short_ordinary["equity"][0]) == 0
    assert (
        short["segments"][0]["theoretical"]["trades"][0]["entry_bar_end"][:10]
        == "2026-01-10"
    )
