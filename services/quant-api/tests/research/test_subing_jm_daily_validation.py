"""Validation guards must detect leakage and cannot relabel viewed history as OOS."""
from dataclasses import replace
from datetime import timedelta

import pytest

from guiyi_quant.subing_jm_daily import DailyModel, digest
from scripts.research.subing_jm_daily_validation import (
    exposure_status, validate_account, validate_daily, validate_fills,
)
from tests.research.test_subing_jm_daily_stress import event, events, T


def test_known_history_can_never_become_unseen_by_splitting():
    assert exposure_status('2026-10-19') == 'EXPOSED_HISTORY'
    assert exposure_status('2026-10-22') == 'EXPOSED_HISTORY'
    assert exposure_status('2026-10-23') == 'FUTURE_ELIGIBLE_NOT_VALIDATED'


def test_account_prefix_restore_and_duplicate_checks_cover_live_position():
    result = validate_account(events())
    assert result['prefix_checks'] > 0 and result['restart_checks'] > 0
    assert {'PENDING_OPEN', 'POSITION_OPEN', 'PENDING_CLOSE', 'FLAT_AFTER_CLOSE'} <= set(result['states_checked'])
    assert result['final_hash'] == digest(result['result'])
    assert result['result']['summary']['closed_trades'] == 1


def test_account_validator_rejects_different_frozen_result():
    with pytest.raises(ValueError, match='FROZEN_RESULT'):
        validate_account(events(), expected={'summary': {}})


def test_empty_account_is_not_a_validation_pass():
    with pytest.raises(ValueError, match='EMPTY_ACCOUNT'):
        validate_account(())


def test_prefix_validator_detects_a_model_which_uses_future_batch_length():
    class LeakyModel(DailyModel):
        def __init__(self, size):
            super().__init__()
            self.batch_size = size

        def result(self):
            result = super().result()
            result['future_batch_size'] = self.batch_size
            return result

    with pytest.raises(ValueError, match='PREFIX'):
        validate_account(events(), factory=LeakyModel)


def test_fill_validator_checks_raw_bar_price_and_strict_time():
    result = validate_account(events())['result']
    assert validate_fills(events(), result) == 2
    result['fills'][0]['price'] = '1001'
    with pytest.raises(ValueError, match='FILL'):
        validate_fills(events(), result)


def test_fill_validator_rejects_fabricated_same_time_execution():
    result = validate_account(events())['result']
    result['fills'][0]['decision_at'] = result['fills'][0]['fill_at']
    with pytest.raises(ValueError, match='FILL'):
        validate_fills(events(), result)


def test_daily_future_perturbation_includes_warmup_boundaries():
    bars = [event('1d', T+timedelta(days=i), str(1000+i)).bar for i in range(50)]
    result = validate_daily(bars)
    assert result['prefix_checks'] > 0 and result['future_perturbation_checks'] > 0
    assert result['bars'] == 50


def test_daily_validator_detects_future_looking_signal_function():
    from guiyi_quant.subing_jm_daily import daily_frames

    def leaking(bars):
        frames = daily_frames(bars)
        return tuple(replace(e, ema=frames[-1].ema, cross=0) for e in frames)

    bars = [event('1d', T+timedelta(days=i), str(1000+i)).bar for i in range(50)]
    with pytest.raises(ValueError, match='DAILY_PREFIX'):
        validate_daily(bars, compute=leaking)
