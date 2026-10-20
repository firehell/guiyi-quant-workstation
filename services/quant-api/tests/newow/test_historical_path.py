from guiyi_quant.newow.historical_path import build_historical_path


def trade(b, s, bp=100, sp=120, force=False):
    return dict(buyDate=b, sellDate=s, buyPrice=bp, sellPrice=sp, forceClose=force)


def test_forceclose_has_no_sell_and_eta_preserves_original_clamp():
    days = [f"2026-01-{i:02}" for i in range(1, 31)]
    trades = [
        trade(days[0], days[5]),
        trade(days[6], days[11]),
        trade(days[19], days[-1], force=True),
    ]
    result = build_historical_path(
        trades=trades,
        kline_dates=days,
        daily_dates=days,
        period="1d",
        today=days[-1],
        current="110",
        target="120",
        cost="100",
        weekly_signals=[],
    )
    assert result["status"] == "ready"
    assert len(result["buys"]) == 2 and len(result["sells"]) == 1
    eta = result["eta"]
    assert eta["base"] == 5 and eta["remain"] == 2.5 and eta["elapsed"] == 10
    assert eta["overdue"] and eta["date"] == days[-1] and eta["date_limited"]


def test_insufficient_samples_are_explicit():
    r = build_historical_path(
        trades=[],
        kline_dates=[],
        daily_dates=[],
        period="1d",
        today="2026-01-30",
        current="110",
        target="120",
        cost="100",
        weekly_signals=[],
    )
    assert r["status"] == "unavailable" and r["reason"] == "TRADE_SAMPLES_MISSING"


def test_recent_window_keeps_whole_trade_and_flat_week_background():
    days = [f"2026-01-{i:02}" for i in range(1, 31)]
    r = build_historical_path(
        trades=[trade(days[0], days[11]), trade(days[19], days[24])],
        kline_dates=days,
        daily_dates=days,
        period="1d",
        today=days[-1],
        current="110",
        target="120",
        cost="100",
        weekly_signals=[
            dict(date=days[10], type="buy"),
            dict(date=days[20], type="sell"),
        ],
    )
    assert r["buys"][0]["date"] == days[0]
    assert r["background"][0]["state"] == "flat"
    assert [x["state"] for x in r["background"]] == ["flat", "hold", "flat"]


def test_weekly_eta_uses_calendar_weeks_not_daily_index():
    r = build_historical_path(
        trades=[
            trade("2026-01-01", "2026-01-08"),
            trade("2026-01-09", "2026-01-16"),
            trade("2026-01-17", "2026-01-30", force=True),
        ],
        kline_dates=["2026-01-01", "2026-01-30"],
        daily_dates=[],
        period="1w",
        today="2026-01-30",
        current="110",
        target="120",
        cost="100",
        weekly_signals=[],
    )
    assert r["eta"]["base"] == 1 and r["eta"]["remain"] == 0.5
    assert r["eta"]["date"] == "2026-02-03" and not r["eta"]["date_limited"]


def test_explicit_path_strategy_query_is_bounded_and_cache_distinct():
    import pytest
    from app.market_data.newow.product_service import ProductServiceQuery

    for strategy in [
        "trend",
        "oscillation",
        "main_rise",
        "fusion",
        "osc-test",
        "osc-test2",
        "osc-test3",
        "osc-test4",
    ]:
        assert (
            ProductServiceQuery(
                "rb",
                "trend",
                "1d",
                section="explanation",
                decision_v2=True,
                path_strategy=strategy,
            ).path_strategy
            == strategy
        )
    with pytest.raises(ValueError):
        ProductServiceQuery("rb", "trend", "1d", path_strategy="fusion")
    with pytest.raises(ValueError):
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="explanation",
            decision_v2=True,
            path_strategy="private",
        )


def test_adapter_experiment_uses_its_projection_and_shanghai_trade_dates(monkeypatch):
    from types import SimpleNamespace as S
    from tests.newow.test_caution_v3402 import bars
    from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus
    from app.market_data.newow.historical_path import project_historical_path
    import guiyi_quant.newow.oscillation_experiments as experiments
    import app.market_data.newow.historical_path as adapter

    source = bars([100] * 30)
    frames = tuple(
        S(
            bar=S(bar=b, calculation_segment_id="calc"),
            availability=S(status=FeatureRuntimeStatus.READY),
            actions=(),
        )
        for b in source
    )
    replay = S(frames=frames, identity=S(strategy=S(value="oscillation")))
    captured = {}

    def projected(values, kind):
        captured["kind"] = kind.value
        return {
            "trades": [
                dict(
                    entry_bar_end="2026-01-01T17:00:00+00:00",
                    exit_bar_end="2026-01-03T17:00:00+00:00",
                    entry_reference_price="100",
                    exit_reference_price="120",
                    force_close=False,
                )
            ]
        }

    def build(**kw):
        captured.update(kw)
        return dict(background=[])

    monkeypatch.setattr(experiments, "run_experiment_reference", projected)
    monkeypatch.setattr(adapter, "build_historical_path", build)
    p = dict(raw="110")
    prices = dict(
        current_price=p,
        status_card=dict(target=dict(raw="120"), absorb=dict(raw="100")),
    )
    project_historical_path(
        replay=replay,
        daily=None,
        weekly=None,
        cutoff=source[-1].bar_end,
        prices=prices,
        frequency="1d",
        strategy="osc-test4",
    )
    assert captured["kind"] == "osc-test4"
    assert captured["trades"][0]["buyDate"].startswith("2026-01-02T01:00:00")
    assert captured["trades"][0]["sellDate"].startswith("2026-01-04T01:00:00")


def test_fusion_adapter_uses_eligible_osc_then_trend_actions(monkeypatch):
    from types import SimpleNamespace as S
    from tests.newow.test_caution_v3402 import bars
    from guiyi_quant.newow.product_contracts import (
        FeatureRuntimeStatus,
        TradeEligibility,
    )
    from app.market_data.newow.historical_path import project_historical_path
    import app.market_data.newow.historical_path as adapter

    source = bars([100] * 30)
    captured = {}

    def replay(strategy, eligibility):
        def action(b):
            return S(
                kind=S(value="BUILD"),
                bar_end=b.bar_end,
                reference_price=b.low,
                trade_eligibility=eligibility,
            )

        frames = tuple(
            S(
                bar=S(bar=b, calculation_segment_id="calc"),
                availability=S(status=FeatureRuntimeStatus.READY),
                actions=(action(b),) if i == 20 else (),
            )
            for i, b in enumerate(source)
        )
        return S(frames=frames, identity=S(strategy=S(value=strategy)))

    def compute(segments, strategy, **kwargs):
        captured["actions"] = segments[0].actions
        captured["strategy"] = strategy
        return {"ordinary": {"trades": []}}

    monkeypatch.setattr(adapter, "compute_page_performance", compute)
    p = dict(raw="110")
    prices = dict(
        current_price=p,
        status_card=dict(target=dict(raw="120"), absorb=dict(raw="100")),
    )
    project_historical_path(
        replay=replay("trend", TradeEligibility.INITIAL_CLEAR_NO_ENTRY),
        fusion_peer=replay("oscillation", TradeEligibility.INITIAL_CLEAR_NO_ENTRY),
        daily=None,
        weekly=None,
        cutoff=source[-1].bar_end,
        prices=prices,
        frequency="1d",
        strategy="fusion",
    )
    assert captured["strategy"] == "fusion" and len(captured["actions"]) == 1
