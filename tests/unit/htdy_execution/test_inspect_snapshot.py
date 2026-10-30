import sqlite3
from guiyi_quant.htdy_account_execution.store import LocalStore
from test_account_execution import initial


def test_full_replay_does_not_hold_original_reader_lock(tmp_path, monkeypatch):
    path = tmp_path / "account.sqlite"
    store = LocalStore(path, initial())
    store.close()
    verify = LocalStore._verify

    def checked(view):
        actual = view._conn.execute("PRAGMA database_list").fetchone()[2]
        assert actual != str(path)
        with sqlite3.connect(path, timeout=0.1) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE projection SET payload=payload WHERE id=1")
        return verify(view)

    monkeypatch.setattr(LocalStore, "_verify", checked)
    assert LocalStore.inspect(path) == initial()


def test_snapshot_timeout_is_fixed_code_and_private_copy_removed(tmp_path, monkeypatch):
    import pytest
    import guiyi_quant.htdy_account_execution.store as module

    path = tmp_path / "account.sqlite"
    store = LocalStore(path, initial())
    store.close()
    before = path.read_bytes()
    times = iter([0, 4])
    monkeypatch.setattr(module, "monotonic", lambda: next(times))
    with pytest.raises(module.StoreError, match="^READ_ONLY_SNAPSHOT_BUSY$"):
        LocalStore.inspect(path)
    assert path.read_bytes() == before


def test_private_snapshot_rejects_wal_and_symlink(tmp_path):
    import pytest
    from guiyi_quant.htdy_account_execution.store import StoreError

    path = tmp_path / "account.sqlite"
    store = LocalStore(path, initial())
    store.close()
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(path)
    with pytest.raises(StoreError, match="PRIVATE_LOCAL_STORE_REQUIRED"):
        LocalStore.inspect(alias)
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        with pytest.raises(StoreError, match="READ_ONLY_JOURNAL_MODE_UNSUPPORTED"):
            LocalStore.inspect(path)


def test_original_inode_replacement_during_copy_is_rejected(tmp_path, monkeypatch):
    import pytest
    import guiyi_quant.htdy_account_execution.store as module

    path = tmp_path / "account.sqlite"
    store = LocalStore(path, initial())
    store.close()
    replacement = tmp_path / "replacement.sqlite"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)

    def changed():
        if replacement.exists():
            replacement.replace(path)
        return 0

    monkeypatch.setattr(module, "monotonic", changed)
    # Replacement happens after the original inode was frozen, before backup.
    with pytest.raises(module.StoreError, match="PRIVATE_LOCAL_STORE_REQUIRED"):
        LocalStore.inspect(path)
