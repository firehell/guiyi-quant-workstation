"""A proven no-write append rejection does not wait a full route rotation."""
from tests.reference_trading.test_historical_refresh import setup, END, route
from guiyi_quant.newow.product_identity import InputQualityPolicy


def test_append_rejection_rebuilds_same_route_in_one_quantum(tmp_path):
    runner, planner, service = setup(tmp_path, [
        ('blocked', 'REBUILD_REQUIRED', False), ('completed', None, False),
    ], routes=(route('trend'), route('oscillation')))
    runner.tick(now=END, batch_limit=1)
    assert [call[0] for call in service.calls] == ['advance', 'rebuild']
    assert service.calls[0][1].streams[0] == service.calls[1][1].streams[0]
    assert not runner.state.read()['routes']
    assert len(planner.requests) == 2


def test_yield_after_append_rejection_keeps_known_pending_boundary(tmp_path):
    runner, _planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END, cancelled=lambda: bool(service.calls), batch_limit=1)
    assert len(service.calls) == 1
    pending = runner.state.read()['routes'][route().identity.stream_id]
    assert pending['status'] == 'pending' and pending['rebuild_required'] is True


def test_same_quantum_rebuild_source_drift_never_mutates(tmp_path):
    runner, planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    original = service.advance
    def change_source(plan, expected):
        result = original(plan, expected)
        planner.source = 'changed-source'
        return result
    service.advance = change_source
    runner.tick(now=END, batch_limit=1)
    assert len(service.calls) == 1
    assert runner.state.read()['routes'][route().identity.stream_id]['reason'] == 'SOURCE_CHANGED'


def test_rebuild_required_with_effects_never_converts(tmp_path):
    runner, _planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    original = service.advance
    def unexpected_effect(plan, expected):
        result = original(plan, expected)
        result.streams[0].completed_bars = 1
        return result
    service.advance = unexpected_effect
    runner.tick(now=END, batch_limit=1)
    row = runner.state.read()['routes'][route().identity.stream_id]
    assert row['status'] == 'blocked' and row['reason'] == 'REFRESH_READBACK_REQUIRED'
    assert len(service.calls) == 1


def test_committed_callback_prevents_rebuild_even_if_report_claims_zero(tmp_path):
    from contextlib import contextmanager
    runner, planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    @contextmanager
    def components(*, after_batch, **_kwargs):
        original = service.advance
        def advance(plan, expected):
            after_batch('committed', {})
            return original(plan, expected)
        service.advance = advance
        yield planner, service
    runner._components = components
    runner.tick(now=END, batch_limit=1)
    assert len(service.calls) == 1
    assert runner.state.read()['routes'][route().identity.stream_id]['status'] == 'blocked'


def test_progress_redacts_raw_failure_and_snapshot_is_detached(tmp_path):
    from app.reference_trading.historical_refresh import RefreshThread
    runner, _planner, _service = setup(tmp_path, [('failed', 'secret=unsafe', False)])
    runner.tick(now=END)
    thread = RefreshThread(runner)
    snapshot = thread.diagnostic_snapshot()
    assert snapshot['reason'] == 'REFRESH_FAILED_READBACK_REQUIRED'
    snapshot['reason'] = 'changed'
    assert runner.last_progress['reason'] == 'REFRESH_FAILED_READBACK_REQUIRED'


def test_fusion_proof_upgrade_waits_for_both_current_semantic_bases(tmp_path):
    from dataclasses import replace
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    from app.reference_trading.historical_refresh import RefreshRoute
    from datetime import date
    fusion = RefreshRoute(build_fusion_stream_identity('rb', '1d', input_quality_policy=InputQualityPolicy.DAILY_V2), date(2023, 1, 1), END,
                          'INPUT_PROOF_UPGRADE_REQUIRED')
    trend = replace(route('trend', END), reason='INPUT_PROOF_UPGRADE_REQUIRED')
    oscillator = route('oscillation', END)
    runner, planner, service = setup(tmp_path, [], routes=(fusion, trend, oscillator))
    ids = sorted(item.identity.stream_id for item in (fusion, trend, oscillator))
    state = runner.state.read()
    state['cursor'] = ids[ids.index(fusion.identity.stream_id) - 1]
    runner.state.write(state)
    # Restrict the turn to fusion: an unchanged endpoint on old base proof cannot authorize it.
    runner._execute = lambda *args: (_ for _ in ()).throw(AssertionError('fusion must wait'))
    runner.tick(now=END, cancelled=lambda: runner.last_progress.get('reason') == 'BASE_DEPENDENCIES_PENDING')
    assert runner.last_progress['reason'] == 'BASE_DEPENDENCIES_PENDING'
    assert not service.calls


def test_fusion_proof_upgrade_at_same_endpoint_uses_native_rebuild(tmp_path):
    from datetime import date
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    from app.reference_trading.historical_refresh import RefreshRoute
    fusion = RefreshRoute(build_fusion_stream_identity('rb', '1d', input_quality_policy=InputQualityPolicy.DAILY_V2), date(2023, 1, 1), END,
                          'INPUT_PROOF_UPGRADE_REQUIRED')
    runner, planner, service = setup(tmp_path, [('completed', None, False)],
        routes=(fusion, route('trend', END), route('oscillation', END)))
    ids = sorted(item.identity.stream_id for item in (fusion, route('trend', END), route('oscillation', END)))
    state = runner.state.read()
    state['cursor'] = ids[ids.index(fusion.identity.stream_id) - 1]
    runner.state.write(state)
    runner.tick(now=END)
    assert [call[0] for call in service.calls] == ['rebuild']
    assert planner.requests[0].streams[0].identity == fusion.identity
