"""Only a single snapshot may reuse a byte-bound verified ledger replay."""

from pathlib import Path
import sqlite3
import pytest
from guiyi_quant.simnow_execution import account_binding as binding
from guiyi_quant.htdy_account_execution import LocalStore
from test_settings import existing_v2


def fixture(tmp_path, monkeypatch):
    _, value, folder = existing_v2(tmp_path)
    root, account = Path(value["state_root"]), value["account_id"]
    original = LocalStore.inspect
    calls = []

    def inspect(path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(LocalStore, "inspect", inspect)
    return root, account, folder, calls


def test_same_snapshot_replays_once_but_public_default_replays_each_time(
    tmp_path, monkeypatch
):
    root, account, _, calls = fixture(tmp_path, monkeypatch)
    with binding._snapshot_account_proof(root, account):
        first = binding.existing_account(root, account)
        assert binding.existing_account(root, account) is first
    assert len(calls) == 1
    assert binding.existing_account(root, account) == first
    assert len(calls) == 2
    with binding._snapshot_account_proof(root, account):
        assert binding.existing_account(root, account) == first
    assert len(calls) == 3


def test_account_byte_change_cannot_reuse_verified_state(tmp_path, monkeypatch):
    root, account, folder, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)
            with sqlite3.connect(folder / "account.sqlite") as db:
                db.execute("PRAGMA user_version=41")
            binding.existing_account(root, account)
    assert len(calls) == 1


def test_final_byte_change_cannot_escape_snapshot_proof(tmp_path, monkeypatch):
    root, account, folder, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)
            with sqlite3.connect(folder / "account.sqlite") as db:
                db.execute("PRAGMA user_version=42")


def test_other_database_owner_check_is_never_cached(tmp_path, monkeypatch):
    root, account, folder, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)
            with sqlite3.connect(folder / "signals.sqlite") as db:
                db.execute("UPDATE identity SET scope=?", ("[]",))
            binding.existing_account(root, account)
    assert len(calls) == 1


def test_nested_phase_or_different_account_cannot_reuse_scope(tmp_path, monkeypatch):
    root, account, _, calls = fixture(tmp_path, monkeypatch)
    with binding._snapshot_account_proof(root, account):
        binding.existing_account(root, account)
        with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
            with binding._snapshot_account_proof(root, account):
                pass
        with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
            binding.existing_account(root, "b" * 64)
    assert len(calls) == 1


def test_no_public_verified_state_injection_parameter(tmp_path, monkeypatch):
    root, account, _, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(TypeError):
        binding.existing_account(root, account, verified_state=object())


def test_exception_resets_scope_and_cannot_leak_to_next_phase(tmp_path, monkeypatch):
    root, account, _, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)
            raise RuntimeError("isolated-test")
    binding.existing_account(root, account)
    assert len(calls) == 2


def test_copied_context_cannot_reuse_after_scope_exit(tmp_path, monkeypatch):
    from contextvars import copy_context

    root, account, _, calls = fixture(tmp_path, monkeypatch)
    with binding._snapshot_account_proof(root, account):
        binding.existing_account(root, account)
        inherited = copy_context()
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        inherited.run(binding.existing_account, root, account)
    assert len(calls) == 1


def test_concurrent_file_replacement_during_replay_is_rejected(tmp_path, monkeypatch):
    from threading import Thread
    import os

    root, account, folder, _ = fixture(tmp_path, monkeypatch)
    original = LocalStore.inspect

    def inspect(path):
        result = original(path)

        def replace():
            replacement = folder / "replacement.sqlite"
            replacement.write_bytes(Path(path).read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, path)

        worker = Thread(target=replace)
        worker.start()
        worker.join()
        return result

    monkeypatch.setattr(LocalStore, "inspect", inspect)
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)


@pytest.mark.parametrize("alias", ["parent", "symlink", "hardlink"])
def test_alias_or_hardlink_never_reuses_proof(tmp_path, monkeypatch, alias):
    import os

    root, account, folder, _ = fixture(tmp_path, monkeypatch)
    from contextlib import nullcontext

    expected = (
        pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED")
        if alias == "hardlink"
        else nullcontext()
    )
    with expected, binding._snapshot_account_proof(root, account):
        binding.existing_account(root, account)
        alternate = root
        if alias == "parent":
            alternate = root / ".." / root.name
        elif alias == "symlink":
            alternate = tmp_path / "alias-root"
            alternate.symlink_to(root, target_is_directory=True)
        else:
            os.link(folder / "account.sqlite", folder / "extra-link.sqlite")
        with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
            binding.existing_account(alternate, account)


def test_equal_metadata_still_requires_full_sha_equality(tmp_path, monkeypatch):
    from types import SimpleNamespace

    root, account, folder, calls = fixture(tmp_path, monkeypatch)
    path = folder / "account.sqlite"
    before = path.stat()
    real_fstat, real_lstat = binding.os.fstat, Path.lstat

    def normalized(info):
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            return info
        return SimpleNamespace(
            **{
                key: getattr(info, key)
                for key in (
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mode",
                    "st_uid",
                    "st_nlink",
                )
            },
            st_mtime_ns=before.st_mtime_ns,
            st_ctime_ns=before.st_ctime_ns,
        )

    monkeypatch.setattr(binding.os, "fstat", lambda fd: normalized(real_fstat(fd)))
    monkeypatch.setattr(Path, "lstat", lambda self: normalized(real_lstat(self)))
    with pytest.raises(ValueError, match="EXISTING_ACCOUNT_BINDING_REQUIRED"):
        with binding._snapshot_account_proof(root, account):
            binding.existing_account(root, account)
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=43")
            binding.existing_account(root, account)
    assert len(calls) == 1


def test_mac_snapshot_opens_and_closes_one_internal_proof_scope(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from test_trade_switch import m

    root, account, _, calls = fixture(tmp_path, monkeypatch)
    backend = m.MacBackend.__new__(m.MacBackend)
    backend.settings = SimpleNamespace(state_root=root, account_id=account)

    def collect():
        first = binding.existing_account(root, account)
        assert binding.existing_account(root, account) is first
        return {"verified": True}

    backend._snapshot = collect
    assert backend.snapshot() == {"verified": True}
    assert len(calls) == 1
    backend.snapshot()
    assert len(calls) == 2
