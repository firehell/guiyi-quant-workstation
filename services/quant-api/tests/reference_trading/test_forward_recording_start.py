"""Future activation starts park reads without changing the durable activation."""
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.forward_inputs import capture_newow_canonical
from guiyi_quant.newow.product_contracts import ProductFrequency
from tests.reference_trading.test_newow_worker_recovery import _setup


@pytest.mark.parametrize('frequency', ('1d', '1w'))
def test_canonical_capture_rejects_future_start_without_reading(frequency):
    _, _, identity, revision, start, _, _ = _setup(frequency=frequency)
    class NoRead:
        def load(self, *_):
            pytest.fail('future activation must not read market input')
    with pytest.raises(ValueError, match='^FORWARD_INPUT_TIME_INVALID$'):
        capture_newow_canonical(NoRead(), identity, revision_id=revision, generation=1,
            after=None, recording_start=start, now=start - timedelta(microseconds=1),
            capability_ready=lambda _: True)


@pytest.mark.parametrize('strategy', ('trend', 'oscillation', 'main_rise'))
@pytest.mark.parametrize('frequency', ('1d', '1w', '60m'))
def test_composed_reader_parks_before_activation_without_source_or_capture(strategy, frequency):
    _, repo, identity, _, start, _, _ = _setup(strategy=strategy, frequency=frequency)
    before = repo.forward_source_context(identity.stream_id)
    def forbidden(*_args, **_kwargs):
        pytest.fail('future activation must not read input or capture')
    repo.capture_forward = forbidden
    class NoRead:
        load = forbidden
        observation_snapshot = forbidden
        newow_completed_observation_snapshot = forbidden
    worker = build_forward_reference_worker(repository=repo, market_read=NoRead(),
        newow_reader=forbidden, owner_segments=forbidden, expected_endpoints=forbidden,
        newow_capability_ready=forbidden, canonical_read_guard=forbidden,
        now=lambda: start - timedelta(microseconds=1), enabled=True)
    assert worker._read_input(identity.stream_id, 'scan', None) is None
    worker.source_observed_at = start - timedelta(microseconds=1)
    assert worker._read_input(identity.stream_id, 'live_event', start) is None
    assert repo.forward_source_context(identity.stream_id) == before
    assert repo.read_pending_capture(identity.stream_id) is None


@pytest.mark.parametrize('frequency', ('1d', '1w'))
@pytest.mark.parametrize('offset', (0, 1))
def test_at_start_and_after_start_preserve_canonical_read_boundary(frequency, offset):
    _, repo, identity, _, start, _, _ = _setup(frequency=frequency)
    observed = start + timedelta(microseconds=offset)
    calls = []
    class Reader:
        def load(self, query, as_of):
            calls.append((query, as_of))
            return SimpleNamespace(frequency=ProductFrequency(frequency), as_of=as_of,
                replay_bars=(), data_interruptions_by_frequency={})
    worker = build_forward_reference_worker(repository=repo, market_read=None,
        newow_reader=Reader(), owner_segments=None, expected_endpoints=None,
        newow_capability_ready=lambda _: True, canonical_read_guard=nullcontext,
        now=lambda: observed, enabled=True)
    assert worker._read_input(identity.stream_id, 'scan', None) is None
    assert len(calls) == 1
    assert calls[0][1] == observed
    assert calls[0][0].since == start.date()
    assert repo.forward_source_context(identity.stream_id)[3] == start


def test_fusion_parks_old_observed_wake_even_when_wall_clock_is_after_start():
    from dataclasses import replace
    _, repo, identity, _, start, _, _ = _setup()
    context = repo.forward_source_context(identity.stream_id)
    fusion = replace(identity, strategy_code='newow_dual_fusion')
    class ContextOnly:
        def forward_source_context(self, _):
            return (fusion, *context[1:])
    calls = []
    def sources(identity, **kwargs):
        calls.append((identity, kwargs))
        return None
    worker = build_forward_reference_worker(repository=ContextOnly(), market_read=None,
        newow_reader=None, owner_segments=None, expected_endpoints=None,
        newow_capability_ready=None, fusion_sources=sources,
        now=lambda: start + timedelta(days=1), enabled=True)
    worker.source_observed_at = start - timedelta(microseconds=1)
    assert worker._read_input(fusion.stream_id, 'live_event', start) is None
    assert calls == []
    worker.source_observed_at = start
    assert worker._read_input(fusion.stream_id, 'live_event', start) is None
    assert len(calls) == 1
    assert calls[0][1]['now'] == start
    assert calls[0][1]['after'] == start - timedelta(microseconds=1)
