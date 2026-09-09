from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pyarrow.parquet as pq
import pytest

from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CANONICAL_COLUMNS, CanonicalMonthlyStore, PublishRequest, StorageError


def _bar(minute: int) -> CanonicalBar:
    value = Decimal("100")
    return CanonicalBar(datetime(2025, 1, 2, 1, minute, tzinfo=UTC), date(2025, 1, 2), value, value, value, value, 1, 10, 20)


def _request(bars: tuple[CanonicalBar, ...], *, expected: tuple[datetime, ...] | None = None) -> PublishRequest:
    return PublishRequest(DatasetKey("continuous", "jm", "MAIN", "1m"), 2025, 1, bars, expected or tuple(bar.bar_end for bar in bars))


def test_publish_writes_only_one_validated_month_parquet(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish(_request((_bar(1), _bar(2))))

    assert result.parquet_path.parent.relative_to(tmp_path).as_posix() == "kind=continuous/symbol=jm/series=MAIN/frequency=1m/year=2025/month=01"
    assert result.row_count == 2
    assert pq.read_schema(result.parquet_path).names == list(CANONICAL_COLUMNS)
    assert store.read_catalog_partition(_partition(result)) == (_bar(1), _bar(2))
    assert not tuple(tmp_path.rglob("manifest.json"))
    assert not tuple(tmp_path.rglob("*.bak"))


def test_publish_rejects_invalid_or_incomplete_month(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    with pytest.raises(StorageError, match="BAR_END_NOT_STRICTLY_INCREASING"):
        store.publish(_request((_bar(1), _bar(1))))
    with pytest.raises(StorageError, match="TARGET_WINDOW_INCOMPLETE"):
        store.publish(_request((_bar(1),), expected=(_bar(1).bar_end, _bar(2).bar_end)))


def test_publish_rejects_naive_expected_bar_end(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)

    with pytest.raises(StorageError, match="EXPECTED_BAR_END_INVALID"):
        store.publish(_request((_bar(1),), expected=(datetime(2025, 1, 2, 1, 1),)))

    with pytest.raises(StorageError, match="EXPECTED_BAR_END_INVALID"):
        store.publish(_request((_bar(1),), expected=(cast(datetime, "invalid"),)))


def _partition(result):
    from app.market_data.catalog import CatalogPartition
    return CatalogPartition(result.dataset, result.year, result.month, result.coverage_start, result.coverage_end, result.parquet_path, result.row_count)


def test_publication_preserves_previous_bytes_and_catalog_pointer(tmp_path):
    import hashlib
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    old_bytes = old.parquet_path.read_bytes()
    new = store.publish(_request((_bar(1), _bar(2))))
    assert old.parquet_path != new.parquet_path
    assert old.parquet_path.read_bytes() == old_bytes
    assert new.parquet_path.name == f"part.{hashlib.sha256(new.parquet_path.read_bytes()).hexdigest()}.parquet"
    assert store.read_catalog_partition(_partition(old)) == (_bar(1),)
    assert store.read_catalog_partition(_partition(new)) == (_bar(1), _bar(2))
    assert store.publish(_request((_bar(1),))).parquet_path == old.parquet_path


def test_catalog_rejects_tampered_hash_and_symlink(tmp_path):
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish(_request((_bar(1),)))
    result.parquet_path.write_bytes(b"corruption")
    with pytest.raises(StorageError):
        store.read_catalog_partition(_partition(result))
    result.parquet_path.unlink()
    other = tmp_path / "other.parquet"
    other.write_bytes(b"corruption")
    result.parquet_path.symlink_to(other)
    with pytest.raises(StorageError):
        store.read_catalog_partition(_partition(result))


def test_explicit_legacy_shadow_publish(tmp_path):
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish_legacy_shadow(_request((_bar(1),)))
    assert result.parquet_path.name == "part.parquet"
    assert store.read_month(result.dataset, 2025, 1) == (_bar(1),)
    assert store.read_catalog_partition(_partition(result)) == (_bar(1),)


def test_candidate_install_failure_preserves_old_partition(tmp_path, monkeypatch):
    import os
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    old_bytes = old.parquet_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected install failure")
    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(StorageError, match="ATOMIC_PUBLISH_FAILED"):
        store.publish(_request((_bar(1), _bar(2))))
    assert old.parquet_path.read_bytes() == old_bytes
    assert store.read_catalog_partition(_partition(old)) == (_bar(1),)
    assert not list(tmp_path.rglob("*.tmp"))


def test_existing_content_address_is_never_overwritten(tmp_path):
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    old.parquet_path.write_bytes(b"damaged")
    with pytest.raises(StorageError, match="IMMUTABLE_PARTITION_CONFLICT"):
        store.publish(_request((_bar(1),)))
    assert old.parquet_path.read_bytes() == b"damaged"


def test_parent_symlink_rejected_on_read_and_publish(tmp_path):
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    directory = old.parquet_path.parent
    relocated = directory.with_name("relocated")
    directory.rename(relocated)
    directory.symlink_to(relocated, target_is_directory=True)
    with pytest.raises(StorageError):
        store.read_catalog_partition(_partition(old))
    with pytest.raises(StorageError):
        store.publish(_request((_bar(1), _bar(2))))


def test_catalog_uri_preserves_symlink_and_rejects_traversal(tmp_path):
    from app.market_data.catalog import CatalogError, MarketCatalog
    catalog = object.__new__(MarketCatalog)
    catalog.canonical_root = tmp_path
    (tmp_path / "target").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "target", target_is_directory=True)
    assert catalog._resolve_uri("alias/part.parquet") == tmp_path / "alias/part.parquet"
    with pytest.raises(CatalogError):
        catalog._resolve_uri("target/../target/part.parquet")


def test_catalog_rejects_wrong_directory_and_row_count(tmp_path):
    from dataclasses import replace
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    partition = _partition(old)
    with pytest.raises(StorageError, match="PARTITION_CATALOG_MISMATCH"):
        store.read_catalog_partition(replace(partition, month=2))
    with pytest.raises(StorageError, match="PARTITION_ROW_COUNT_MISMATCH"):
        store.read_catalog_partition(replace(partition, row_count=2))
    with pytest.raises(StorageError, match="PARTITION_COVERAGE_MISMATCH"):
        store.read_catalog_partition(replace(partition, coverage_end=_bar(2).bar_end))


def test_hash_and_parse_use_same_snapshot(tmp_path, monkeypatch):
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    original = store._read_bytes
    def read_then_change(fd, name):
        payload = original(fd, name)
        old.parquet_path.write_bytes(b"changed after reading")
        return payload
    monkeypatch.setattr(store, "_read_bytes", read_then_change)
    assert store.read_catalog_partition(_partition(old)) == (_bar(1),)
    with pytest.raises(StorageError):
        store.read_catalog_partition(_partition(old))


def test_concurrent_candidates_do_not_replace_one_another(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = CanonicalMonthlyStore(tmp_path)
    requests = [_request((_bar(1),)), _request((_bar(1), _bar(2)))] * 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(store.publish, requests))
    assert len({result.parquet_path for result in results}) == 2
    for result, request in zip(results, requests):
        assert store.read_catalog_partition(_partition(result)) == request.bars


def test_file_fsync_failure_keeps_previous_bytes(tmp_path, monkeypatch):
    import os
    store = CanonicalMonthlyStore(tmp_path)
    old = store.publish(_request((_bar(1),)))
    previous = old.parquet_path.read_bytes()
    def fail(fd):
        import stat
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("injected fsync failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(StorageError, match="ATOMIC_PUBLISH_FAILED"):
        store.publish(_request((_bar(1), _bar(2))))
    assert old.parquet_path.read_bytes() == previous
    assert store.read_catalog_partition(_partition(old)) == (_bar(1),)


def test_legacy_read_validates_full_time_series(tmp_path):
    import pyarrow as pa
    from app.market_data.storage import CANONICAL_SCHEMA
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish_legacy_shadow(_request((_bar(1), _bar(2))))
    pq.write_table(pa.Table.from_pylist([_bar(2).as_record(), _bar(1).as_record()], schema=CANONICAL_SCHEMA), result.parquet_path)
    with pytest.raises(StorageError, match="BAR_END_NOT_STRICTLY_INCREASING"):
        store.read_catalog_partition(_partition(result))


def test_missing_root_syncs_each_parent_before_creating_descendant(tmp_path, monkeypatch):
    import os
    original_mkdir, original_fsync = os.mkdir, os.fsync
    pending = []
    synced = []
    def mkdir(path, mode=0o777, *, dir_fd=None):
        assert not pending, "parent must be fsynced before creating next directory"
        original_mkdir(path, mode, dir_fd=dir_fd)
        assert dir_fd is not None, "directory creation must use safe parent descriptor"
        pending.append(os.fstat(dir_fd).st_ino)
    def fsync(fd):
        inode = os.fstat(fd).st_ino
        original_fsync(fd)
        if pending:
            assert inode == pending.pop()
            synced.append(inode)
    monkeypatch.setattr(os, "mkdir", mkdir)
    monkeypatch.setattr(os, "fsync", fsync)
    root = tmp_path / "new-parent" / "canonical"
    result = CanonicalMonthlyStore(root).publish(_request((_bar(1),)))
    assert result.parquet_path.is_file()
    assert synced[:2] == [tmp_path.stat().st_ino, root.parent.stat().st_ino]


def test_missing_root_parent_fsync_failure_stops_before_candidate(tmp_path, monkeypatch):
    import os
    original_fsync = os.fsync
    def fsync(fd):
        if os.fstat(fd).st_ino == tmp_path.stat().st_ino:
            raise OSError("injected root parent sync failure")
        original_fsync(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    root = tmp_path / "new-parent" / "canonical"
    with pytest.raises(StorageError):
        CanonicalMonthlyStore(root).publish(_request((_bar(1),)))
    assert not root.exists()
    assert not list(tmp_path.rglob("*.parquet"))


def test_root_symlink_is_not_resolved_before_safe_walk(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(StorageError):
        CanonicalMonthlyStore(alias / "canonical").publish(_request((_bar(1),)))
    assert not list(target.iterdir())


def test_retry_syncs_existing_root_parent_after_previous_fsync_failure(tmp_path, monkeypatch):
    import os
    root = tmp_path / "new-root"
    parent_inode = tmp_path.stat().st_ino
    original_fsync = os.fsync
    attempts = []
    def fail_parent(fd):
        if os.fstat(fd).st_ino == parent_inode:
            attempts.append(parent_inode)
            raise OSError("parent remains unsynced")
        original_fsync(fd)
    monkeypatch.setattr(os, "fsync", fail_parent)
    for _ in range(2):
        with pytest.raises(StorageError):
            CanonicalMonthlyStore(root).publish(_request((_bar(1),)))
    assert attempts == [parent_inode, parent_inode]
    assert not list(root.rglob("*.parquet"))


def test_concurrent_publisher_syncs_visible_but_unsynced_directory(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    import os
    root = tmp_path / "new-root"
    visible, release = Event(), Event()
    original_mkdir, original_fsync = os.mkdir, os.fsync
    parent_inode = tmp_path.stat().st_ino
    second_synced = Event()
    def mkdir(path, mode=0o777, *, dir_fd=None):
        original_mkdir(path, mode, dir_fd=dir_fd)
        if path == "new-root":
            visible.set()
            assert release.wait(5)
    def fsync(fd):
        if current_thread().name.startswith("second") and os.fstat(fd).st_ino == parent_inode:
            second_synced.set()
        original_fsync(fd)
    monkeypatch.setattr(os, "mkdir", mkdir)
    monkeypatch.setattr(os, "fsync", fsync)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as first, ThreadPoolExecutor(max_workers=1, thread_name_prefix="second") as second:
        pending = first.submit(CanonicalMonthlyStore(root).publish, _request((_bar(1),)))
        try:
            assert visible.wait(5)
            result = second.submit(CanonicalMonthlyStore(root).publish, _request((_bar(1),))).result(timeout=5)
            assert result.parquet_path.is_file()
            assert second_synced.is_set()
        finally:
            release.set()
        pending.result(timeout=5)


def test_parent_sync_failure_closes_both_directory_descriptors(tmp_path, monkeypatch):
    import os
    original_open, original_close = os.open, os.close
    opened = set()
    def open_fd(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd
    def close_fd(fd):
        original_close(fd)
        opened.remove(fd)
    def fail_sync(fd):
        raise OSError("sync failure with child already open")
    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(os, "close", close_fd)
    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(StorageError):
        CanonicalMonthlyStore(tmp_path).publish(_request((_bar(1),)))
    assert opened == set()
