import pytest


def ownership(tmp_path, **kwargs):
    from app.runtime_handover import RunOwnership
    return RunOwnership('alert', runtime_dir=tmp_path, generation=1,
                        verify=lambda: None, **kwargs)


def test_only_one_owner_can_write(tmp_path):
    from app.runtime_handover import HandoverError
    first, second = ownership(tmp_path), ownership(tmp_path)
    with first.acquired():
        first.assert_owned()
        with pytest.raises(HandoverError, match='RUNTIME_OWNER_BUSY'):
            with second.acquired():
                pass
    with second.acquired():
        second.assert_owned()


def test_assert_rechecks_generation_before_effect(tmp_path):
    from app.runtime_handover import HandoverError
    current = [True]
    def verify():
        if not current[0]:
            raise HandoverError('RUNTIME_GENERATION_CHANGED')
    from app.runtime_handover import RunOwnership
    owner = RunOwnership('alert', runtime_dir=tmp_path, generation=1, verify=verify)
    with owner.acquired():
        current[0] = False
        with pytest.raises(HandoverError, match='RUNTIME_GENERATION_CHANGED'):
            owner.assert_owned()


def test_drain_can_be_cancelled_without_changing_generation(tmp_path):
    from app.runtime_handover import request_drain, cancel_drain
    owner = ownership(tmp_path)
    with owner.acquired():
        assert not owner.should_drain()
        request = request_drain('alert', generation=1, runtime_dir=tmp_path)
        assert owner.should_drain()
        cancel_drain('alert', request_id=request, runtime_dir=tmp_path)
        assert not owner.should_drain()


def test_symlink_lock_never_accepted(tmp_path):
    from app.runtime_handover import HandoverError
    target = tmp_path / 'user-file'
    target.write_text('unchanged')
    (tmp_path / 'alert.owner.lock').symlink_to(target)
    with pytest.raises(HandoverError):
        with ownership(tmp_path).acquired():
            pass
    assert target.read_text() == 'unchanged'


def test_control_corruption_does_not_resume_owner(tmp_path):
    from app.runtime_handover import HandoverError
    with pytest.raises(HandoverError, match='RUNTIME_CONTROL_INVALID'):
        with ownership(tmp_path).acquired() as owner:
            (tmp_path / 'alert.handover.json').write_text('{}')
            (tmp_path / 'alert.handover.json').chmod(0o600)
            owner.should_drain()


def test_readonly_status_does_not_create_runtime_directory(tmp_path):
    from app.runtime_handover import read_service_state
    directory = tmp_path / 'missing'
    assert read_service_state('alert', runtime_dir=directory) is None
    assert not directory.exists()


def test_invalid_service_cannot_escape_runtime_root(tmp_path):
    from app.runtime_handover import HandoverError, read_service_state
    with pytest.raises(HandoverError):
        read_service_state('../outside', runtime_dir=tmp_path)


def _transport_process(directory, sending, finished):
    from app.runtime_handover import RunOwnership
    with RunOwnership('alert', runtime_dir=directory, generation=1, verify=lambda: None).acquired() as owner:
        sending.set()
        finished.wait(10)
        owner.assert_owned()
        assert owner.should_drain()


def test_cross_process_drain_cannot_release_inflight_transport(tmp_path):
    import multiprocessing
    from app.runtime_handover import request_drain, owner_lock_available, read_service_state
    context = multiprocessing.get_context('spawn')
    sending, finished = context.Event(), context.Event()
    process = context.Process(target=_transport_process, args=(tmp_path, sending, finished))
    process.start()
    try:
        assert sending.wait(5)
        request_drain('alert', generation=1, runtime_dir=tmp_path)
        assert not owner_lock_available('alert', runtime_dir=tmp_path)
        assert read_service_state('alert', runtime_dir=tmp_path)['phase'] == 'active'
        finished.set()
        process.join(5)
        assert process.exitcode == 0
        assert owner_lock_available('alert', runtime_dir=tmp_path)
        assert read_service_state('alert', runtime_dir=tmp_path)['phase'] == 'parked'
    finally:
        finished.set()
        process.join(10)


def test_same_root_old_generation_cannot_reanimate(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import runtime_bindings, runtime_handover
    from app.core.env import PROJECT_ROOT
    binding = SimpleNamespace(enabled=True, generation=2, root=str(PROJECT_ROOT), commit='a'*40, tag='v1.2.3')
    monkeypatch.setattr(runtime_bindings, 'resolve_service_binding', lambda service: binding)
    monkeypatch.setenv('GUIYI_RUNTIME_COMMIT', 'a'*40)
    monkeypatch.setenv('GUIYI_RUNTIME_TAG', 'v1.2.3')
    monkeypatch.setenv('GUIYI_RUNTIME_GENERATION', '1')
    owner = runtime_handover.RunOwnership('alert', runtime_dir=tmp_path)
    with pytest.raises(runtime_handover.HandoverError, match='GENERATION_CHANGED'):
        with owner.acquired():
            pytest.fail('old generation acquired side effect rights')


def test_failed_cycle_clears_previous_ready_proof(tmp_path):
    from app.runtime_handover import RunOwnership, read_service_state
    with RunOwnership('live', runtime_dir=tmp_path, generation=1, verify=lambda: None).acquired() as owner:
        owner.mark_ready({'input_read_frontier': '110-0'})
        assert read_service_state('live', runtime_dir=tmp_path)['ready'] is True
        owner.mark_not_ready()
        assert read_service_state('live', runtime_dir=tmp_path).get('ready') is not True
