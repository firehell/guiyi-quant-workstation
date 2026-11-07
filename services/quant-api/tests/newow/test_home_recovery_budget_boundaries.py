"""Real period starts, monotonic occupancy and durable hourly reservations."""
from copy import deepcopy

import pytest

from app.market_data.newow import home_recovery_state as budgets


def case(tmp_path, now=3599, **kwargs):
    store = budgets.WorkStore(tmp_path / 'summary.json')
    state = store.state()
    policy = budgets.RecoveryPolicy(**kwargs)
    job = budgets.reconcile(state, 'rb', {}, 'impl', False, now)
    assert budgets.reserve(state, 'rb', job, now, policy.period_seconds * 2, policy, starts=2)
    return store, state, job, policy


def usage(state, hour):
    return state['budgets'][str(hour)]['products']['rb']


def test_two_children_started_in_distinct_hours_charge_actual_start_and_elapsed(tmp_path):
    store, state, job, policy = case(tmp_path)
    day = budgets.start_compute(state, 'rb', job, 3599, policy)
    store.save(state)
    budgets.end_compute(state, 'rb', job, day, 2)
    week = budgets.start_compute(state, 'rb', job, 3602, policy)
    store.save(state)
    budgets.end_compute(state, 'rb', job, week, 3)
    budgets.settle(state, 'rb', job, 99, starts=2)  # elapsed wall-gap is irrelevant with slots.
    assert usage(state, 0) == {'starts': 1, 'seconds': 1}
    assert usage(state, 1) == {'starts': 1, 'seconds': 4}
    assert state['budgets']['0']['initial'] == 1
    assert state['budgets']['1']['initial'] == 4
    store.save(state)
    assert store.state() == state


def test_forward_clock_jump_uses_each_child_start_not_pair_wall_gap(tmp_path):
    _, state, job, policy = case(tmp_path, now=100)
    first = budgets.start_compute(state, 'rb', job, 100, policy)
    budgets.end_compute(state, 'rb', job, first, 10)
    second = budgets.start_compute(state, 'rb', job, 7205, policy)
    budgets.end_compute(state, 'rb', job, second, 3)
    budgets.settle(state, 'rb', job, 99999, starts=2)
    assert usage(state, 0) == {'starts': 1, 'seconds': 10}
    assert usage(state, 2) == {'starts': 1, 'seconds': 3}
    assert '1' not in state['budgets']


def test_backward_clock_cannot_reopen_earlier_hour_tokens(tmp_path):
    _, state, job, policy = case(tmp_path, now=7205)
    first = budgets.start_compute(state, 'rb', job, 7205, policy)
    budgets.end_compute(state, 'rb', job, first, 4)
    second = budgets.start_compute(state, 'rb', job, 100, policy)
    assert second['at'] == 7209
    budgets.end_compute(state, 'rb', job, second, 5)
    budgets.settle(state, 'rb', job, 9, starts=2)
    assert set(state['budgets']) == {'2'}
    assert usage(state, 2) == {'starts': 2, 'seconds': 9}


def test_future_prepaid_bucket_does_not_fake_clock_advance_for_second_start(tmp_path):
    _, state, job, policy = case(tmp_path, now=3598)
    first = budgets.start_compute(state, 'rb', job, 3598, policy)
    assert usage(state, 1)['seconds'] == 118  # Prepaid capacity, not elapsed time.
    budgets.end_compute(state, 'rb', job, first, 0.2)
    second = budgets.start_compute(state, 'rb', job, 3598.3, policy)
    assert second['hour'] == 0
    budgets.end_compute(state, 'rb', job, second, 1)
    budgets.settle(state, 'rb', job, 1.2, starts=2)
    assert usage(state, 0)['starts'] == 2
    assert usage(state, 0)['seconds'] == pytest.approx(1.2)
    assert usage(state, 1) == {'starts': 0, 'seconds': 0}


def test_started_unended_slot_survives_real_store_restart_without_refund(tmp_path):
    store, state, job, policy = case(tmp_path)
    budgets.start_compute(state, 'rb', job, 3599, policy)
    before = deepcopy(state['budgets'])
    assert usage(state, 0)['seconds'] == 121
    assert usage(state, 1)['seconds'] == 119
    store.save(state)
    loaded = store.state()
    assert loaded['budgets'] == before
    assert len(loaded['items']['rb']['reservation']['slots']) == 1
    # The parent's crash recovery drops reservation metadata without settling;
    # both the started upper bound and pending reservation remain consumed.
    loaded['items']['rb'].pop('reservation')
    assert loaded['budgets'] == before


def test_unused_period_refund_does_not_refund_completed_or_duplicate_settlement(tmp_path):
    _, state, job, policy = case(tmp_path, now=100)
    first = budgets.start_compute(state, 'rb', job, 100, policy)
    budgets.end_compute(state, 'rb', job, first, 10)
    budgets.end_compute(state, 'rb', job, first, 0)  # Duplicate end is idempotent.
    budgets.settle(state, 'rb', job, 9999, starts=1)
    assert usage(state, 0) == {'starts': 1, 'seconds': 10}
    before = deepcopy(state)
    budgets.settle(state, 'rb', job, 0, starts=0)
    assert state == before


def test_target_hour_start_cap_denies_before_executor_and_finish_keeps_budget_wait(tmp_path):
    _, state, job, policy = case(tmp_path)
    first = budgets.start_compute(state, 'rb', job, 3599, policy)
    budgets.end_compute(state, 'rb', job, first, 2)
    usage(state, 1)['starts'] = policy.product_starts
    second = budgets.start_compute(state, 'rb', job, 3602, policy)
    assert second is None
    assert len(job['reservation']['slots']) == 1
    budgets.settle(state, 'rb', job, 3, starts=1)
    budgets.finish(job, {'category': 'budget', 'code': 'HOME_RECOVERY_BUDGET_WAIT'}, 3602, policy)
    assert job['status'] == 'retry_wait'
    assert job['next_at'] == 7200
    assert usage(state, 0) == {'starts': 1, 'seconds': 1}
    assert usage(state, 1) == {'starts': 6, 'seconds': 1}


def test_cross_hour_cpu_cap_is_reserved_before_start_even_if_process_crashes(tmp_path):
    _, state, job, policy = case(tmp_path)
    state['budgets']['1'] = {'initial': 350, 'retry': 0, 'products': {'rb': {'starts': 0, 'seconds': 350}}}
    # Only 10 seconds remain next hour; a 120-second child cannot be launched
    # one second before the boundary on the assumption it will finish early.
    assert budgets.start_compute(state, 'rb', job, 3599, policy) is None
    budgets.settle(state, 'rb', job, 0, starts=0)
    assert usage(state, 0) == {'starts': 0, 'seconds': 0}
    assert usage(state, 1)['seconds'] == 350


def test_slots_are_bounded_to_two_and_schema_rejects_corrupt_reservation(tmp_path):
    from app.market_data.newow.home_projection import ProjectionError

    store, state, job, policy = case(tmp_path, now=100)
    for now in (100, 110):
        slot = budgets.start_compute(state, 'rb', job, now, policy)
        budgets.end_compute(state, 'rb', job, slot, 1)
    with pytest.raises(ProjectionError):
        budgets.start_compute(state, 'rb', job, 120, policy)
    store.save(state)
    assert len(store.state()['items']['rb']['reservation']['slots']) == 2
    job['reservation']['slots'].append(deepcopy(job['reservation']['slots'][0]))
    store.save(state)
    with pytest.raises(ProjectionError):
        store.state()


def test_late_child_shutdown_charges_real_monotonic_overrun_instead_of_clamping(tmp_path):
    store, state, job, policy = case(tmp_path, now=3599)
    first = budgets.start_compute(state, 'rb', job, 3599, policy)
    budgets.end_compute(state, 'rb', job, first, 125)
    budgets.settle(state, 'rb', job, 125, starts=1)
    assert usage(state, 0) == {'starts': 1, 'seconds': 1}
    assert usage(state, 1) == {'starts': 0, 'seconds': 124}
    store.save(state)
    assert store.state() == state


def test_per_hour_initial_and_retry_pools_remain_separate_for_actual_child_starts(tmp_path):
    _, state, job, policy = case(tmp_path, now=100)
    first = budgets.start_compute(state, 'rb', job, 100, policy)
    budgets.end_compute(state, 'rb', job, first, 10)
    budgets.settle(state, 'rb', job, 10, starts=1)
    latest = budgets.reconcile(state, 'rb', {'1d': 'new'}, 'impl', False, 200)
    assert budgets.reserve(state, 'rb', latest, 200, 120, policy, starts=1)
    retry = budgets.start_compute(state, 'rb', latest, 200, policy)
    assert retry['pool'] == 'retry'
    budgets.end_compute(state, 'rb', latest, retry, 5)
    budgets.settle(state, 'rb', latest, 5, starts=1)
    assert state['budgets']['0']['initial'] == 10
    assert state['budgets']['0']['retry'] == 5
    assert usage(state, 0) == {'starts': 2, 'seconds': 15}
