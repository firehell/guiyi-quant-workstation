import json
from pathlib import Path

import pytest

from lms405_public_casebook import report


def fixture(tmp_path):
    root = Path(__file__).resolve().parents[4]
    book = json.loads((root / 'docs/research/lms405/evidence/two-case-condition-casebook-20261028.json').read_text())
    book['cases'] = book['cases'][:1]
    row = book['cases'][0]
    row['condition_roles'] = {name: 'RESEARCH_VALIDATION' for name in row['condition_meaning']}
    row['condition_roles']['AUTHOR_SHORT_VPLUS_CONFIRMED'] = 'AUTHOR_NECESSARY'
    return book, row


def test_output_keeps_author_conditions_apart_from_research_constraints(tmp_path):
    book, row = fixture(tmp_path)
    row['disclosed_conditions'] = [dict(name='PRIOR_LONG_PROTECTION', value=True,
        observed_at=book['recorded_at'], known_at=book['recorded_at'], source=row['source'],
        time_kind='RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME')]
    path = tmp_path / 'book.json'
    path.write_text(json.dumps(book))
    result = report(path)['cases'][0]
    assert result['condition_roles'] == row['condition_roles']
    assert result['assessment']['status'] == 'INDETERMINATE'
    assert result['assessment']['requested_action'] == 'UNLOCK_SHORT'
    assert result['assessment']['after'] is None
    assert result['condition_facts_supplied'] == 1


def test_partial_or_unknown_condition_role_is_rejected(tmp_path):
    book, row = fixture(tmp_path)
    row['condition_roles']['CASE_APPLIES'] = 'SUFFICIENT_ORIGINAL_PERMISSION'
    path = tmp_path / 'book.json'
    path.write_text(json.dumps(book))
    with pytest.raises(ValueError, match='CONDITION_ROLE_MISMATCH'):
        report(path)


def test_legacy_casebook_output_stays_identical():
    root = Path(__file__).resolve().parents[4] / 'docs/research/lms405/evidence'
    assert report(root / 'two-case-condition-casebook-20261028.json') == json.loads(
        (root / 'two-case-condition-results-20261028.json').read_text())


def test_partial_permission_and_explicit_configuration_counterexample_stay_separate():
    root = Path(__file__).resolve().parents[4] / 'docs/research/lms405/evidence'
    result = report(root / 'recovery-condition-casebook-20261028.json')
    by_id = {c['case_id']: c for c in result['cases']}
    oi = by_id['OI2609_20260605_GRAB_M_SHORT_SCENARIO']
    assert oi['assessment']['routes'][0]['checks']['CONFIG_PERMITS_THIS_M_SCENARIO'] is True
    assert oi['assessment']['status'] == 'INDETERMINATE'
    old_config = by_id['SH2509_20250718_CONTINUOUS_M_CONFIG_COUNTEREXAMPLE']
    assert old_config['assessment']['status'] == 'NOT_PERMITTED'
    assert old_config['assessment']['routes'][0]['checks']['CONFIG_PERMITS_CONTINUOUS_M_IN_THIS_ENVIRONMENT'] is False
    assert result['eligible_golden_signal_samples'] == 0
    assert result['author_signal_success_rate'] is None
    assert all(c['assessment']['after'] is None for c in result['cases'])
    assert all(not c['assessment']['executable'] for c in result['cases'])
    assert result['fill'] is None and result['performance'] is None


def test_related_inertia_concept_is_not_an_author_necessary_gate():
    root = Path(__file__).resolve().parents[4] / 'docs/research/lms405/evidence'
    result = report(root / 'recovery-condition-casebook-20261028.json')['cases'][-1]
    context = 'INERTIA_APPEARS_AFTER_SHORT_TERM'
    assert result['source_context'][context]['relation'] == 'RELATED_CONCEPT_NOT_A_ROUTE_GATE'
    assert context not in result['assessment']['routes'][0]['checks']
    assert context not in result['condition_roles']
    assert set(result['condition_roles'].values()) == {'RESEARCH_VALIDATION'}
