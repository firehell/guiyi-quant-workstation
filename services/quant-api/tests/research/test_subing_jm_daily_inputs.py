"""Fail-closed phase-A provenance and exact physical ownership."""
from copy import deepcopy

import pytest

from app.market_data.subing_jm_daily import verified_days


def report():
    return {'kind': 'PHASE_A_INPUT_AUDIT_NOT_BACKTEST', 'facts_unchanged': True,
        'physical_sources_unchanged_at_end': True,
        'days': [{'day': '2025-01-01', 'contract': 'JM2505', 'status': 'INPUTS_VERIFIED'},
                 {'day': '2025-01-02', 'contract': 'JM2509', 'status': 'EXECUTION_FACTS_MISSING'}]}


def test_only_verified_days_keep_their_physical_owner():
    assert verified_days(report()) == {'2025-01-01': 'JM2505'}


@pytest.mark.parametrize('key', ['kind', 'facts_unchanged', 'physical_sources_unchanged_at_end'])
def test_failed_or_different_audit_cannot_authorize_model_inputs(key):
    raw = deepcopy(report())
    raw[key] = False
    with pytest.raises(ValueError):
        verified_days(raw)


def test_duplicate_day_cannot_hide_conflicting_contract():
    raw = report()
    raw['days'].append({**raw['days'][0], 'contract': 'JM2509'})
    with pytest.raises(ValueError):
        verified_days(raw)
