import json
from pathlib import Path

import pytest

from lms_structure_explanations import build_explanations, render_explanations, VERSION
from lms_keybar_approx_replay import build_report

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / 'docs/research/lms405/evidence'
ADMISSION = EVIDENCE / 'keybar-sample-admission-20261028.csv'
INPUT = ROOT / 'output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv'


def test_all_known_structure_attachments_merge_same_event_without_counting_signals():
    result = build_explanations()
    assert result['version'] == VERSION == 'lms-structure-explanation-v1'
    assert result['attachment_count'] == 10
    assert len(result['cases']) == 9
    assert result['type_counts'] == {'TWO_HIGH_ONE_LOW': 5, 'TWO_LOW_ONE_HIGH': 4}
    merged = next(x for x in result['cases'] if x['event_group'] == 'JM2509_JUL18_NIGHT')
    assert [x['sample_id'] for x in merged['sources']] == ['KB16', 'KB17']
    assert {x['source_refs'].split('#')[1] for x in merged['sources']} == {'H12', 'H10'}
    assert result['eligible_author_bar_samples'] == 0
    assert result['executable'] is False and result['author_match_rate'] is None
    assert all(c['local_bar_end'] is None and c['trading_permission'] is None
               and c['selection_formula'] is None and c['completion_formula'] is None
               for c in result['cases'])
    assert json.loads(json.dumps(result)) == result == build_explanations()


def test_source_drift_fails_instead_of_silently_relabeling(tmp_path):
    changed = tmp_path / 'admission.csv'
    changed.write_bytes(ADMISSION.read_bytes().replace(b'KB16', b'KB99'))
    with pytest.raises(ValueError, match='STRUCTURE_SOURCE_HASH_MISMATCH'):
        build_explanations(changed)


def test_author_contexts_and_counterexamples_stay_separate():
    by_sample = {s['sample_id']: c for c in build_explanations()['cases'] for s in c['sources']}
    assert by_sample['KB04']['context'] == 'HOLD_AND_GAP_CONTINUATION'
    assert by_sample['KB10']['context'] == 'PROTECTION_AND_OPTIONAL_M'
    assert by_sample['KB16']['context'] == 'RIGHT_SIDE_SKIPPED_GAP_ALTERNATIVE'
    assert by_sample['KB15']['context'] == 'CROSS_PRODUCT_CONTEXT_AND_M'
    assert '右侧' in by_sample['KB15']['conflicts'] and '左侧' in by_sample['KB15']['conflicts']
    assert '跳过' in by_sample['KB16']['explanation']
    assert '参与' in by_sample['KB16']['boundary']


def test_schematic_and_source_cards_do_not_claim_detected_structure():
    html = render_explanations(build_explanations())
    assert html.count('class="structure-case"') == 9
    assert '仅作阅读示意' in html and '不表达点序' in html
    assert 'H1' in html and 'H2' in html and 'L1' in html and 'L2' in html
    assert 'https://weibo.com/1885745060/PByywfBwO' in html
    assert 'KB16' in html and 'KB17' in html
    assert '自动识别结构数' not in html


def test_new_explanation_report_preserves_old_numeric_replay():
    old = json.loads((EVIDENCE / 'keybar-approx-v1-jm2509-20261029/report.json').read_text())
    result = build_report(INPUT)
    assert result['frames'] == old['frames']
    assert result['next_close_observations'] == old['next_close_observations']
    assert result['local_pattern_counts'] == old['local_pattern_counts']
    assert result['frozen_geometry'] == old['frozen_geometry']
    assert result['structure_explanations'] == build_explanations()
    assert result['report_version'] == 'lms-keybar-report-v2'
    assert result['rule_version'] == old['rule_version'] == 'lms-keybar-approx-v1'
