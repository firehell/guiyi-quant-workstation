from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from guiyi_quant.newow.subplots import calculate_zhaoyao_mirror, mirror_care
from guiyi_quant.newow.composite_decision_v2 import compute_cdv2
from app.market_data.newow.home_cards import project_row_hints
from tests.newow.test_oscillation_channel import golden_bars


def bars(values):
    b = golden_bars()[0]
    return tuple(
        replace(
            b,
            bar_end=b.bar_end + timedelta(days=i),
            trading_day=b.trading_day + timedelta(days=i),
            open=Decimal(v),
            high=Decimal(v) + 1,
            low=Decimal(v) - 1,
            close=Decimal(v),
        )
        for i, v in enumerate(values)
    )


def test_candidate_movement_confirmation_and_restart():
    source = bars([100] * 20 + [110, 120, 119, 114])
    fresh = calculate_zhaoyao_mirror(source[:21])
    moved = calculate_zhaoyao_mirror(source[:22])
    assert fresh.last_bar_fresh_peak and fresh.candidate_peak_index == 20
    assert moved.last_bar_fresh_peak and moved.candidate_peak_index == 21
    waiting = calculate_zhaoyao_mirror(source[:23])
    assert not waiting.last_bar_fresh_peak and waiting.candidate_peak_index == 21
    confirmed = calculate_zhaoyao_mirror(source)
    assert confirmed.candidate_peak_index is None
    assert confirmed.confirmed_peak_events == ((21, 23),)
    assert confirmed.confirmation_index[21] == 23
    for n in range(20, len(source) + 1):
        a = calculate_zhaoyao_mirror(source[:n])
        assert a == calculate_zhaoyao_mirror(tuple(source[:n]))
        assert a.caution[-1] == 0
        assert all(c < n for _, c in a.confirmed_peak_events)


def test_fresh_home_event_does_not_enable_care():
    source = bars([100] * 79 + [110])
    frames = tuple(
        SimpleNamespace(bar=SimpleNamespace(bar=b, calculation_segment_id="calc"))
        for b in source
    )
    replay = SimpleNamespace(
        identity=SimpleNamespace(frequency=SimpleNamespace(value="1d")), frames=frames
    )
    hint = project_row_hints(replay, frames[-1], True)["items"][0]
    assert hint["event_day"] == source[-1].trading_day and hint["tentative"]
    assert not mirror_care(calculate_zhaoyao_mirror(source).caution)


def test_old_peak_just_confirmed_does_not_light_home():
    source = bars([100] * 70 + [120] + [116] * 8 + [110])
    frames = tuple(
        SimpleNamespace(bar=SimpleNamespace(bar=b, calculation_segment_id="calc"))
        for b in source
    )
    replay = SimpleNamespace(
        identity=SimpleNamespace(frequency=SimpleNamespace(value="1d")), frames=frames
    )
    assert not [
        x
        for x in project_row_hints(replay, frames[-1], True)["items"]
        if x["kind"] == "caution"
    ]


def test_care_boundary_and_explanation_only():
    assert mirror_care([50] + [0] * 65)
    assert not mirror_care([50] + [0] * 66)
    trend = dict(week="hold", day="hold", m60="hold")
    osc = dict(week="wait", day=None, m60="hold")
    before = compute_cdv2(trend, osc)
    after = compute_cdv2(trend, osc, care=True)
    assert (before["total"], after["total"]) == (82, 79)
    assert (before["reference_exposure_cap"], after["reference_exposure_cap"]) == (
        60,
        50,
    )
    assert before["action_code"] == after["action_code"] and not after["executable"]


def test_chart_events_share_prefix_and_do_not_change_strategy_markers():
    from app.market_data.newow.home_cards import project_caution_events

    source = bars([100] * 20 + [110, 120, 119, 114])

    def replay(count):
        return SimpleNamespace(
            frames=tuple(
                SimpleNamespace(
                    bar=SimpleNamespace(bar=b, calculation_segment_id="calc")
                )
                for b in source[:count]
            )
        )

    before = project_caution_events(replay(21))
    moved = project_caution_events(replay(22))
    assert (
        before[-1]["bar_end"] == source[20].bar_end.isoformat()
        and before[-1]["tentative"]
    )
    assert (
        moved[-1]["bar_end"] == source[21].bar_end.isoformat()
        and moved[-1]["tentative"]
    )
    confirmed = project_caution_events(replay(24))
    assert confirmed[-1]["confirmed_at"] == source[23].bar_end.isoformat()
    assert not confirmed[-1]["tentative"] and not confirmed[-1]["executable"]
    assert confirmed == project_caution_events(replay(24))


def test_nearby_peak_is_absorbed_without_forcing_fresh_event():
    value = calculate_zhaoyao_mirror(bars([100] * 20 + [120, 114, 120]))
    assert value.caution[-1] == 0
    assert not value.last_bar_fresh_peak
    assert sum(value.caution[20:]) == 50


def test_overlapping_foreign_warmup_peaks_are_not_observation_events():
    from app.market_data.newow.home_cards import project_caution_events
    source=bars([100]*20+[110,120,119,114])
    frames=[]
    for contract,eligible in [('RB2605',True),('RB2610',False)]:
        for b in source:
            frames.append(SimpleNamespace(bar=SimpleNamespace(bar=replace(b,physical_contract=contract,segment_id=contract,observation_eligible=eligible),calculation_segment_id=contract+'-calc')))
    events=project_caution_events(SimpleNamespace(frames=tuple(frames)))
    assert events
    assert all(e['physical_contract']=='RB2605' for e in events)
