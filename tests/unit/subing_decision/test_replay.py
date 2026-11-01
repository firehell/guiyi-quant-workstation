import json
from pathlib import Path

import pytest

from scripts.research.subing_decision import render, replay


def test_render_preserves_literal_untrusted_text_without_script_injection():
    text = '</script><script>window.pwned=true</script>'
    page = render({'rows': [], 'source_note': text})
    assert text not in page
    embedded = page.split('<script type="application/json" id="data">', 1)[1].split('</script>', 1)[0]
    assert json.loads(embedded)['source_note'] == text
    assert 'textContent=' in page
    assert '__DATA__' not in page


@pytest.mark.parametrize('packet', [None, {}, {'kind': 'BACKTEST'},
    dict(kind='REAL_FILL', contract='JM2609', run_id='x', source_note='test', events=[{}]),
    dict(kind='ENGINEERING_SCENARIO', contract='JM2609', run_id='x', source_note='', events=[{}]),
    dict(kind='ENGINEERING_SCENARIO', contract='JM2609', run_id='x', source_note='test', events=[]),
])
def test_replay_rejects_missing_source_and_false_result_categories(packet):
    with pytest.raises(ValueError):
        replay(packet)


def test_explicit_lifecycle_preserves_pending_and_per_layer_positions():
    packet = json.loads(Path('tests/fixtures/subing_decision/lifecycle.json').read_text())
    result = replay(packet)
    rows = result['rows']
    assert rows[0]['after']['quantity'] == 0
    assert rows[0]['after']['pending']['kind'] == 'OPEN'
    assert rows[1]['after']['quantity'] == 1
    assert rows[7]['after']['quantity'] == 3
    assert len(rows[8]['after']['pending']['layer_ids']) == 2
    assert rows[9]['after']['quantity'] == 1
    assert rows[13]['after']['pending']['reasons'] == ['ADD_PROTECTION']
    assert rows[16]['actions'][0]['kind'] == 'REJECT'
    assert 'DAY_END_NO_OPEN' in rows[16]['actions'][0]['reasons']
    assert rows[-2]['after']['quantity'] == 1
    assert rows[-2]['after']['cooldown'] == 0
    assert rows[-1]['after']['quantity'] == 0
    assert rows[-1]['after']['cooldown'] == 10
    assert 'performance' not in result


def test_replay_duplicate_does_not_display_old_position_as_current():
    packet = json.loads(Path('tests/fixtures/subing_decision/lifecycle.json').read_text())
    packet['events'].append(packet['events'][0])
    rows = replay(packet)['rows']
    assert rows[-1]['actions'] == [{'kind': 'DUPLICATE_IGNORED'}]
    assert rows[-1]['before'] == rows[-1]['after'] == rows[-2]['after']
