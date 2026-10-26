"""Deterministic completed-bar display events, independent of notification history."""
from dataclasses import replace
from types import SimpleNamespace

from tests.newow.test_caution_v3402 import bars
from app.market_data.newow.home_cards import project_caution_events, project_row_hints


def replay(source):
    return SimpleNamespace(identity=SimpleNamespace(frequency=SimpleNamespace(value='1d')),
        frames=tuple(SimpleNamespace(bar=SimpleNamespace(bar=b, calculation_segment_id='calc')) for b in source))


def test_fixed_anchor_survives_new_high_and_decline_with_separate_peak():
    source = bars([100]*20+[110,120,119,114])
    first = project_caution_events(replay(source[:21]))[-1]
    moved = project_caution_events(replay(source[:22]))[-1]
    waiting = project_caution_events(replay(source[:23]))[-1]
    assert moved['bar_end'] == waiting['bar_end'] == first['bar_end'] == source[20].bar_end.isoformat()
    assert moved['peak_bar_end'] == source[21].bar_end.isoformat()
    assert moved['event_id'] == first['event_id'] == waiting['event_id']
    assert moved['display_state'] == 'tentative' and moved['age_bars'] == 1
    assert moved['first_visible_at'] == source[20].bar_end.isoformat()
    confirmed = project_caution_events(replay(source))[-1]
    assert confirmed['event_id'] == first['event_id']
    assert confirmed['display_state'] == 'confirmed'
    assert confirmed['confirmed_at'] == source[23].bar_end.isoformat()
    assert not confirmed['tentative']
    assert confirmed == project_caution_events(replay(tuple(source)))[-1]


def test_expiry_is_fixed_to_first_event_not_refreshed_by_new_high():
    source = bars([100]*20+list(range(110,123)))
    assert project_caution_events(replay(source[:31]))[-1]['age_bars'] == 10
    assert not project_caution_events(replay(source[:32]))
    assert not project_caution_events(replay(source[:33]))


def test_home_and_detail_share_identity_but_have_distinct_visibility_windows():
    source = bars([100]*20+[110,120,130])
    for count in [21,22,23]:
        r = replay(source[:count])
        hints = project_row_hints(r,r.frames[-1],True)
        caution = [h for h in hints['items'] if h['kind']=='caution']
        detail = project_caution_events(r)[-1]
        assert hints['display_policy_version'] == detail['display_policy_version']
        if count < 23:
            assert caution[0]['event_id'] == detail['event_id']
            assert caution[0]['event_bar_end'] == detail['bar_end']
        else:
            assert not caution


def test_no_inherited_anchor_from_warmup_or_other_owner():
    source = bars([100]*20+[110,120,130])
    source = tuple(replace(b,observation_eligible=i>=21) for i,b in enumerate(source))
    r = replay(source)
    event = project_caution_events(r)[-1]
    assert event['first_visible_at'] == source[21].bar_end.isoformat()
    assert event['bar_end'] == source[21].bar_end.isoformat()
    other = replay(tuple(replace(b,physical_contract='OTHER',segment_id='OTHER') for b in source))
    assert project_caution_events(other)[-1]['event_id'] != event['event_id']


def test_confirmation_does_not_claim_it_was_known_at_peak():
    source = bars([100]*20+[110,120,119,114])
    e = project_caution_events(replay(source))[-1]
    assert e['confirmed_at'] > e['first_visible_at']
    assert e['visibility_basis'] == 'completed_bar'
    assert e['page_parity'] is False and e['executable'] is False


def test_new_leg_gets_new_identity_and_uses_no_wall_clock():
    source=bars([100]*20+[110,120,114]+[100]*11+[106,120])
    prior=project_caution_events(replay(source[:22]))[-1]
    after=project_caution_events(replay(source))[-1]
    assert after['bar_end'] == source[34].bar_end.isoformat()
    assert after['event_id'] != prior['event_id']


def test_display_schema_rejects_missing_or_contradictory_state():
    import pytest
    from pydantic import ValidationError
    from app.schemas.market_newow_product import CautionDisplayEventOut
    event=project_caution_events(replay(bars([100]*20+[110,120])))[-1]
    assert CautionDisplayEventOut.model_validate(event).display_state == 'tentative'
    for patch in [{'display_state':'confirmed'}, {'age_bars':11,'home_visible':False}, {'first_visible_at':event['as_of']}]:
        with pytest.raises(ValidationError):
            CautionDisplayEventOut.model_validate({**event,**patch})
    with pytest.raises(ValidationError):
        CautionDisplayEventOut.model_validate({k:v for k,v in event.items() if k!='first_visible_at'})


def test_historical_confirmation_before_warmup_is_not_first_visible_before_warmup():
    source=bars([100,110,104]+[104]*17)
    event=project_caution_events(replay(source))[-1]
    assert event['confirmed_at'] == source[2].bar_end.isoformat()
    assert event['first_visible_at'] == source[19].bar_end.isoformat()


def test_display_rejects_duplicate_or_reverse_time_and_isolates_frequency():
    import pytest
    source=bars([100]*20+[110,120])
    for bad in [source+(source[-1],),tuple(reversed(source))]:
        with pytest.raises(ValueError,match='NON_MONOTONIC'):
            project_caution_events(replay(bad))
    daily=project_caution_events(replay(source))[-1]
    # Product replay uses normalized legacy bars; the wire identity carries the actual frequency.
    hourly=replay(source)
    hourly.identity.frequency.value='60m'
    assert project_caution_events(hourly)[-1]['event_id'] != daily['event_id']


def test_first_seen_matches_incremental_public_fresh_condition():
    import random
    from guiyi_quant.newow.subplots import calculate_zhaoyao_mirror, mirror_peak_structure
    rng=random.Random(71)
    values=[100]*20
    for _ in range(80):
        values.append(values[-1]+rng.choice([-8,-4,0,3,6,10]))
    source=bars(values)
    expected_first=None
    prior_confirmed=0
    for count in range(20,len(source)+1):
        prefix=source[:count]
        mirror=calculate_zhaoyao_mirror(prefix)
        if len(mirror.confirmed_peak_events)!=prior_confirmed:
            expected_first=None
        prior_confirmed=len(mirror.confirmed_peak_events)
        if mirror.last_bar_fresh_peak and expected_first is None:
            expected_first=count-1
        assert mirror_peak_structure(prefix)[4] == expected_first
