"""Bounded public-source witnesses; constructed inputs, never market evidence."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.oscillation_channel import (
    OscillationAction,
)
from guiyi_quant.newow.main_rise import calculate_main_rise_series
from guiyi_quant.newow.oscillation_attack import calculate_oscillation_attack
from app.market_data.newow.display_events import (
    breakdown_events,
    project_display_events,
    shared_events,
    cents,
)
from app.market_data.newow.experiments import NewowExperimentService, ExperimentQuery
from .test_experiments import make_bar, Reader, NOW


def sample():
    # _computeAllSignals witness from public v3.4.31 (2026-10-31),
    # detail SHA 76ee34e9...55caebf7: first breakdown indexes 10 and 14.
    bars = [
        replace(
            make_bar(i),
            bar=replace(
                make_bar(i).bar,
                open=Decimal("120"),
                high=Decimal("200"),
                low=Decimal("110"),
                close=Decimal("120"),
            ),
        )
        for i in range(16)
    ]
    overrides = {
        9: ("110", "180", "100", "110"),
        10: ("110", "150", "90", "99.994"),
        11: ("110", "150", "90", "99.993"),
        12: ("210", "220", "120", "210"),
        13: ("90", "100", "80", "90"),
        14: ("70", "80", "60", "79.99"),
        15: ("70", "80", "60", "79.98"),
    }
    for i, values in overrides.items():
        bars[i] = replace(
            bars[i],
            bar=replace(
                bars[i].bar,
                **dict(
                    zip(
                        ("open", "high", "low", "close"),
                        map(Decimal, values),
                        strict=True,
                    )
                ),
            ),
        )
    return tuple(bars)


def identity(strategy="oscillation"):
    return build_product_identity("rb", strategy, ProductFrequency.DAILY)


def test_public_source_breakdown_witness_and_no_trade_mutation():
    bars = sample()
    replay = replay_strategy(identity(), bars)
    before = (replay.frames, replay.actions, replay.hints)
    events = project_display_events(replay)
    breaks = [e for e in events if e["kind"] == "OSC_BREAKDOWN"]
    assert [e["bar_end"] for e in breaks] == [
        bars[i].bar.bar_end.isoformat() for i in (10, 14)
    ]
    assert [e["observed_close"] for e in breaks] == ["99.994", "79.99"]
    assert (replay.frames, replay.actions, replay.hints) == before
    assert len([a for a in replay.actions if a.kind.value == "BUILD"]) == 2
    assert len([a for a in replay.actions if a.kind.value == "CLEAR"]) == 1
    assert breaks[0]["source_build_id"] == replay.actions[0].signal_id
    assert breaks[0]["build_threshold"] == "100"
    assert all(
        e["page_parity"] and not e["executable"] and e["quantity_effect"] == "none"
        for e in events
    )
    assert project_display_events(replay) == events
    assert tuple(
        e for e in events if e["bar_end"] <= bars[10].bar.bar_end.isoformat()
    ) == project_display_events(replay_strategy(identity(), bars[:11]))


def test_rounded_boundary_clear_bar_warmup_and_owner_reset():
    bars = list(sample())
    bars[10] = replace(bars[10], bar=replace(bars[10].bar, close=Decimal("99.9999999")))
    assert not any(
        e["kind"] == "OSC_BREAKDOWN"
        and e["bar_end"] == bars[10].bar.bar_end.isoformat()
        for e in project_display_events(replay_strategy(identity(), tuple(bars)))
    )
    bars = sample()
    hidden = tuple(
        replace(b, bar=replace(b.bar, observation_eligible=i >= 11))
        for i, b in enumerate(bars)
    )
    assert not any(
        e["kind"] == "OSC_BREAKDOWN"
        and e["bar_end"] == bars[11].bar.bar_end.isoformat()
        for e in project_display_events(replay_strategy(identity(), hidden))
    )
    split = tuple(
        replace(
            b,
            bar=replace(b.bar, physical_contract="RB2705", segment_id="new"),
            calculation_segment_id="new",
        )
        if i >= 10
        else b
        for i, b in enumerate(bars)
    )
    assert not any(
        e["kind"] == "OSC_BREAKDOWN"
        for e in project_display_events(replay_strategy(identity(), split))
    )
    assert cents(Decimal("100.005")) == 10001
    assert cents(Decimal("99.9999999")) == 10000


def test_explicit_clear_build_order_and_one_shot():
    bars = sample()[:5]
    def action(kind, price):
        return SimpleNamespace(action=OscillationAction(kind), price=Decimal(price))
    # first Bar builds above close; clear Bar must not warn. Same-Bar genuine
    # reentry resets the latch and uses its own new threshold.
    signals = (
        (action("BUILD", "130"),),
        (),
        (action("CLEAR", "100"),),
        (action("BUILD", "140"), action("CLEAR", "100")),
        (),
    )
    events = breakdown_events(
        bars, signals, "oscillation", "formula", lambda i, s: f"build:{i}:{s}"
    )
    assert [e["bar_end"] for e in events] == [
        bars[0].bar.bar_end.isoformat(),
        bars[3].bar.bar_end.isoformat(),
    ]
    assert events[1]["build_threshold"] == "140"


@pytest.mark.parametrize("kind", ["osc-test", "osc-test2", "osc-test3", "osc-test4"])
def test_experiments_display_uses_chart_state_not_reference_trades(kind):
    bars = sample() + tuple(make_bar(i) for i in range(16, 28))
    service = NewowExperimentService(Reader(bars), now=lambda: NOW)
    full = service.query(ExperimentQuery("rb", "1d", kind, chart_limit=100))
    page = service.query(ExperimentQuery("rb", "1d", kind, chart_limit=11))
    visible = {b["bar_end"] for b in page["bars"]}
    assert page["display_events"] == [
        e for e in full["display_events"] if e["bar_end"] in visible
    ]
    # A second identical read retains all display IDs and all original models.
    assert service.query(ExperimentQuery("rb", "1d", kind, chart_limit=100)) == full
    for e in full["display_events"]:
        if e["kind"] == "OSC_BREAKDOWN":
            assert e["source_strategy"] == kind
            assert any(
                m["marker_id"] == e["source_build_id"] and m["action"] == "BUILD"
                for m in full["markers"]
            )
    assert all(b["calculation_segment_id"] == b["segment_id"] for b in full["bars"])


def test_j_and_badge_reuse_existing_kernels_and_include_tail():
    # Deterministic changing input exercises reduce-J, not just an empty result.
    bars = tuple(
        replace(
            make_bar(i),
            bar=replace(
                make_bar(i).bar,
                open=Decimal(100 + i % 23),
                close=Decimal(100 + i % 23),
                high=Decimal(103 + i % 23),
                low=Decimal(97 + i % 23),
            ),
        )
        for i in range(150)
    )
    raw = tuple(b.bar for b in bars)
    rise = calculate_main_rise_series(raw)
    z = calculate_oscillation_attack(raw)
    expected = [
        b.bar.bar_end.isoformat()
        for b, m, a in zip(bars, rise, z, strict=True)
        if m.reduce_signal is not None and not a["j_warning"]
    ]
    events = shared_events(bars)
    assert (
        expected
        and [e["bar_end"] for e in events if e["kind"] == "MAIN_RISE_J"] == expected
    )
    for end in expected:
        n = next(i + 1 for i, b in enumerate(bars) if b.bar.bar_end.isoformat() == end)
        assert any(
            e["kind"] == "MAIN_RISE_J" and e["bar_end"] == end
            for e in shared_events(bars[:n])
        )
    assert not any(
        e["kind"] == "MAIN_RISE_J"
        for e in project_display_events(replay_strategy(identity("main_rise"), bars))
    )
    assert shared_events(bars[:5]) is not None


def test_experiment_j_collision_keeps_zlgj_source_but_trend_follows_public_skip():
    import random

    rng = random.Random(0)
    close = 100
    bars = []
    for i in range(200):
        close = max(20, close + rng.uniform(-5, 5))
        raw = make_bar(i)
        bars.append(
            replace(
                raw,
                bar=replace(
                    raw.bar,
                    open=Decimal(str(close)),
                    close=Decimal(str(close)),
                    high=Decimal(str(close + rng.uniform(0.1, 5))),
                    low=Decimal(str(close - rng.uniform(0.1, 5))),
                ),
            )
        )
    bars = tuple(bars)
    raw = tuple(b.bar for b in bars)
    main = calculate_main_rise_series(raw)
    attack = calculate_oscillation_attack(raw)
    overlap = [
        b.bar.bar_end.isoformat()
        for b, m, a in zip(bars, main, attack, strict=True)
        if m.reduce_signal and a["j_warning"]
    ]
    assert overlap
    events = shared_events(bars, include_zlgj=True)
    for at in overlap:
        at_events = [
            e
            for e in events
            if e["bar_end"] == at and e["kind"] in ("MAIN_RISE_J", "ZLGJ_J")
        ]
        assert [e["kind"] for e in at_events] == ["ZLGJ_J"]
        assert at_events[0]["source_strategy"] == "oscillation_attack"
    assert not any(
        e["kind"] == "MAIN_RISE_J" and e["bar_end"] in overlap
        for e in shared_events(bars)
    )
