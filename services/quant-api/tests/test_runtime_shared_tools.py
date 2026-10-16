from pathlib import Path
import os

import pytest

from app.private_settings import PrivateSettingsError, load_private_readonly_settings
from app.runtime_identity import file_snapshot


@pytest.mark.parametrize('defect', ['symlink', 'hardlink', 'permissions', 'directory', 'oversize'])
def test_private_settings_reject_unsafe_files_without_disclosing_contents(tmp_path, defect):
    path = tmp_path / 'private.env'
    path.write_bytes(b'DATABASE_URL=fixture-secret')
    path.chmod(0o600)
    if defect == 'symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(path)
        path = alias
    elif defect == 'hardlink':
        os.link(path, tmp_path / 'alias')
    elif defect == 'permissions':
        path.chmod(0o644)
    elif defect == 'directory':
        path.unlink()
        path.mkdir()
    elif defect == 'oversize':
        path.write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(PrivateSettingsError, match='^PROJECT_ENV_UNSAFE$') as error:
        load_private_readonly_settings(path)
    assert 'fixture-secret' not in str(error.value)


def test_public_settings_and_recovery_adapter_keep_same_identity_and_error(tmp_path):
    from scripts.newow_weekly_recovery import RecoveryError
    from scripts.newow_weekly_recovery import load_private_readonly_settings as legacy

    path = tmp_path / 'private.env'
    path.write_text(f'DATABASE_URL=sqlite:///fixture\nGUIYI_CANONICAL_DATA_ROOT={tmp_path}\n')
    path.chmod(0o600)
    assert load_private_readonly_settings(path) == legacy(path)
    path.write_text('DATABASE_URL=fixture\nDATABASE_URL=duplicate\n')
    with pytest.raises(PrivateSettingsError, match='^PROJECT_ENV_UNSAFE$'):
        load_private_readonly_settings(path)
    with pytest.raises(RecoveryError, match='^PROJECT_ENV_UNSAFE$'):
        legacy(path)


def test_safe_snapshot_preserves_exact_bytes_stamp_and_ancestor_checks(tmp_path):
    root = tmp_path.resolve()
    path = root / 'source'
    path.write_bytes(b'exact bytes')
    path.chmod(0o600)
    content, stamp = file_snapshot(path)
    assert content == b'exact bytes'
    assert stamp[2] == len(content)
    assert file_snapshot(path) == (content, stamp)
    alias = root / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        file_snapshot(alias / 'source')


@pytest.mark.parametrize('dependency', ['runtime_identity.py', 'private_settings.py'])
def test_shared_runtime_dependencies_participate_in_input_and_launcher_fingerprints(monkeypatch, dependency):
    from app import runtime_bindings

    files = {
        'services/quant-api/app/db/model.py': 'db',
        'services/quant-api/app/market_data/live_market.py': 'live',
        'packages/quant-core/formula.py': 'formula',
        'services/quant-api/app/reference_trading/model.py': 'reference',
        f'services/quant-api/app/{dependency}': 'old',
    }
    monkeypatch.setattr(runtime_bindings, '_tracked', lambda root: files.copy())
    before = runtime_bindings.contract_fingerprints(Path('/unused'))
    files[f'services/quant-api/app/{dependency}'] = 'new'
    after = runtime_bindings.contract_fingerprints(Path('/unused'))
    assert {key for key in before if before[key] != after[key]} == {'input', 'launcher'}


@pytest.mark.parametrize('dependency', ['capability_contracts.py', 'capability_contracts.json', 'product_release.py'])
def test_shared_capability_source_participates_in_input_identity(monkeypatch, dependency):
    from app import runtime_bindings

    files = {
        'services/quant-api/app/db/model.py': 'db',
        'services/quant-api/app/market_data/live_market.py': 'live',
        'services/quant-api/app/market_data/rqdata_adapter.py': 'input',
        'packages/quant-core/formula.py': 'formula',
        'services/quant-api/app/reference_trading/model.py': 'reference',
        'services/quant-api/app/runtime_bindings.py': 'launcher',
        f'services/quant-api/app/market_data/newow/{dependency}': 'old',
    }
    monkeypatch.setattr(runtime_bindings, '_tracked', lambda root: files.copy())
    before = runtime_bindings.contract_fingerprints(Path('/unused'))
    files[f'services/quant-api/app/market_data/newow/{dependency}'] = 'new'
    after = runtime_bindings.contract_fingerprints(Path('/unused'))
    assert {key for key in before if before[key] != after[key]} == {'input'}


@pytest.mark.parametrize('dependency', ['composition.py', 'capability_contracts.py', 'capability_contracts.json'])
def test_daily_execution_hash_covers_newow_shared_composition_and_contract(tmp_path, dependency):
    from scripts import newow_weekly_recovery as recovery

    for relative in recovery._D1_EXECUTION_CODE_PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'original fixture')
    before = recovery._current_execution_code_sha256(recovery_frequency='1d', project_root=tmp_path)
    (tmp_path / 'services/quant-api/app/market_data/newow' / dependency).write_bytes(b'changed fixture')
    after = recovery._current_execution_code_sha256(recovery_frequency='1d', project_root=tmp_path)
    assert after != before


def test_weekly_daily_hourly_execution_identity_covers_public_dependencies():
    from scripts import newow_weekly_recovery as recovery

    for paths in (recovery._EXECUTION_CODE_PATHS, recovery._D1_EXECUTION_CODE_PATHS,
                  recovery._HOURLY_EXECUTION_CODE_PATHS):
        assert 'services/quant-api/app/private_settings.py' in paths
        assert 'services/quant-api/app/runtime_identity.py' in paths


def test_fault_recovery_retains_after_market_status_snapshot_size_policy(tmp_path):
    from app.runtime_fault_recovery_host import FaultRecoveryHost

    path = tmp_path.resolve() / 'after-market-status.json'
    content = b'x' * (1024 * 1024 + 1)
    path.write_bytes(content)
    assert FaultRecoveryHost().bytes(path) == content
    ordinary = path.with_name('ordinary.json')
    ordinary.write_bytes(content)
    with pytest.raises(ValueError):
        FaultRecoveryHost().bytes(ordinary)


@pytest.mark.parametrize('frequency', ['1w', '1d', '60m'])
@pytest.mark.parametrize('dependency', ['runtime_identity.py', 'private_settings.py'])
def test_execution_hash_changes_when_shared_dependency_changes(tmp_path, frequency, dependency):
    from scripts import newow_weekly_recovery as recovery

    paths = {'1w': recovery._EXECUTION_CODE_PATHS, '1d': recovery._D1_EXECUTION_CODE_PATHS,
             '60m': recovery._HOURLY_EXECUTION_CODE_PATHS}[frequency]
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'original fixture')
    before = recovery._current_execution_code_sha256(recovery_frequency=frequency, project_root=tmp_path)
    (tmp_path / 'services/quant-api/app' / dependency).write_bytes(b'changed fixture')
    after = recovery._current_execution_code_sha256(recovery_frequency=frequency, project_root=tmp_path)
    assert after != before


def test_shared_atomic_json_keeps_existing_evidence_and_symlinks(tmp_path):
    from scripts.evidence_files import atomic_json

    target = tmp_path / 'receipt.json'
    atomic_json(target, {'status': 'complete'})
    original = target.read_bytes()
    with pytest.raises(FileExistsError, match='^EVIDENCE_FILE_EXISTS$'):
        atomic_json(target, {'status': 'replacement'})
    assert target.read_bytes() == original
    alias = tmp_path / 'alias.json'
    alias.symlink_to(target)
    with pytest.raises(FileExistsError, match='^EVIDENCE_FILE_EXISTS$'):
        atomic_json(alias, {}, exclusive=False)
    assert target.read_bytes() == original
    assert not list(tmp_path.glob('.*'))
