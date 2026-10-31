import json
from decimal import Decimal
from pathlib import Path

import pytest

from lms_keybar_approx_replay import build_report, write_report, render_html

ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT / 'output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv'


def test_frozen_replay_is_repeatable_and_not_author_accuracy():
    result = build_report(INPUT)
    assert result == build_report(INPUT)
    assert result['bar_count'] == len(result['frames']) == 138
    assert result['rule_version'] == 'lms-keybar-approx-v1'
    assert result['executable'] is False
    assert result['author_match_rate'] is result['fill'] is result['performance'] is None
    assert result['eligible_author_samples'] == 0
    assert {x['category'] for x in result['author_comparison']} == {
        'EXPLAINABLE', 'DIFFERENCE', 'UNALIGNABLE'}
    row = next(x for x in result['frames'] if x['bar_end'] == '2025-07-22T09:10:00+08:00')
    assert row['ibar'] is True and Decimal(row['body']) == Decimal('3')
    obs = next(x for x in result['next_close_observations'] if x['signal_bar_end'] == row['bar_end'])
    assert obs['observed_at'] == '2025-07-22T09:15:00+08:00'
    assert obs['close_below_low'] is True
    assert all('close_below_low' not in f for f in result['frames'])
    assert result['frozen_geometry']['provisional_peak_comparison']['local_minus_image'] == '0.500000000000000000'
    for obs in result['next_close_observations']:
        assert obs['observed_at'] > obs['signal_bar_end']
    assert json.loads(json.dumps(result)) == result


def test_tampered_input_fails_without_output(tmp_path):
    source = tmp_path / 'changed.csv'
    source.write_bytes(INPUT.read_bytes().replace(b'934.000', b'935.000', 1))
    target = tmp_path / 'report'
    with pytest.raises(ValueError, match='FROZEN_INPUT_HASH_MISMATCH'):
        write_report(source, target)
    assert not target.exists()


def test_existing_output_is_never_modified(tmp_path):
    target = tmp_path / 'existing'
    target.mkdir()
    marker = target / 'index.html'
    marker.write_text('KEEP')
    with pytest.raises(FileExistsError):
        write_report(INPUT, target)
    assert marker.read_text() == 'KEEP'
    assert list(target.iterdir()) == [marker]


def test_html_exposes_boundaries_and_separate_later_observations():
    report = build_report(INPUT)
    html = render_html(report, '<svg aria-label="test"/>')
    assert 'lms-keybar-approx-v1' in html
    assert '暂定视觉对应' in html and '无法对齐' in html
    assert '下一根' in html and '不是交易许可' in html
    assert '1034.5' in html and '1035' in html
    assert '准确率' in html and 'null' in html
    assert '<svg' in html and 'frames.csv' in html and 'observations.csv' in html


def test_rendered_svg_is_valid_and_has_no_trailing_whitespace():
    pytest.importorskip('matplotlib', reason='render smoke uses documented system Python')
    import xml.etree.ElementTree as ET
    from lms_keybar_approx_replay import render_chart
    svg = render_chart(build_report(INPUT))
    assert ET.fromstring(svg).tag == '{http://www.w3.org/2000/svg}svg'
    assert all(line == line.rstrip() for line in svg.splitlines())
