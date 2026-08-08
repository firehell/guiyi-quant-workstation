"""Read-only Catalog/filesystem consistency checks."""

from __future__ import annotations

from pathlib import Path

from app.data_core.consistency import (
    ConsistencyCode,
    PartitionRef,
    check_catalog_filesystem_consistency,
)


def test_missing_catalog_file_is_reported_not_repaired(tmp_path: Path) -> None:
    report = check_catalog_filesystem_consistency(
        canonical_root=tmp_path,
        partitions=(
            PartitionRef(
                file_uri="provider/rqdata/missing.parquet",
                manifest_uri=None,
                manifest_digest=None,
                dataset_key="continuous:jm:JM.MAIN:1m",
            ),
        ),
    )
    assert report.blocking[0].code is ConsistencyCode.MISSING_FILE
    assert not report.ok


def test_orphan_file_is_reported_without_registration(tmp_path: Path) -> None:
    orphan = tmp_path / "provider" / "orphan.parquet"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    report = check_catalog_filesystem_consistency(
        canonical_root=tmp_path,
        partitions=(),
        orphan_paths=(orphan,),
    )
    assert any(item.code is ConsistencyCode.ORPHAN_FILE for item in report.findings)
    assert report.blocking == ()


def test_matching_partition_file_is_catalog_ok(tmp_path: Path) -> None:
    relative = Path("provider/rqdata/part.parquet")
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"ok")
    report = check_catalog_filesystem_consistency(
        canonical_root=tmp_path,
        partitions=(
            PartitionRef(
                file_uri=str(relative),
                manifest_uri=None,
                manifest_digest=None,
                dataset_key="continuous:jm:JM.MAIN:1m",
            ),
        ),
    )
    assert report.ok
    assert report.findings[0].code is ConsistencyCode.CATALOG_OK
