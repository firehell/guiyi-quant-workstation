"""Read-only Catalog ↔ filesystem consistency checks.

Never promotes orphan Parquet/Manifest into the Catalog. Publication remains
solely via CanonicalStore (or its existing recovery contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence


class ConsistencyCode(StrEnum):
    CATALOG_OK = "CATALOG_OK"
    MISSING_FILE = "MISSING_FILE"
    ORPHAN_FILE = "ORPHAN_FILE"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"


@dataclass(frozen=True, slots=True)
class ConsistencyFinding:
    code: ConsistencyCode
    path: str | None = None
    dataset_key: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    findings: tuple[ConsistencyFinding, ...]

    @property
    def ok(self) -> bool:
        return all(item.code is ConsistencyCode.CATALOG_OK for item in self.findings) or (
            not self.findings
        )

    @property
    def blocking(self) -> tuple[ConsistencyFinding, ...]:
        return tuple(
            item
            for item in self.findings
            if item.code
            in {
                ConsistencyCode.MISSING_FILE,
                ConsistencyCode.MANIFEST_MISMATCH,
            }
        )


@dataclass(frozen=True, slots=True)
class PartitionRef:
    file_uri: str
    manifest_uri: str | None
    manifest_digest: str | None
    dataset_key: str


def check_catalog_filesystem_consistency(
    *,
    canonical_root: Path,
    partitions: Sequence[PartitionRef],
    orphan_paths: Sequence[Path] | None = None,
) -> ConsistencyReport:
    """Compare Catalog partition URIs to the configured canonical root.

    ``orphan_paths`` may be supplied by a caller that already scanned disk;
    this function never registers them — it only reports ``ORPHAN_FILE``.
    """
    root = canonical_root.resolve()
    findings: list[ConsistencyFinding] = []
    if not partitions and not orphan_paths:
        return ConsistencyReport(findings=(ConsistencyFinding(code=ConsistencyCode.CATALOG_OK),))

    for partition in partitions:
        file_path = _resolve_under_root(root, partition.file_uri)
        if file_path is None or not file_path.is_file():
            findings.append(
                ConsistencyFinding(
                    code=ConsistencyCode.MISSING_FILE,
                    path=partition.file_uri,
                    dataset_key=partition.dataset_key,
                    detail="catalog_file_missing",
                )
            )
            continue
        if partition.manifest_uri:
            manifest_path = _resolve_under_root(root, partition.manifest_uri)
            if manifest_path is None or not manifest_path.is_file():
                findings.append(
                    ConsistencyFinding(
                        code=ConsistencyCode.MANIFEST_MISMATCH,
                        path=partition.manifest_uri,
                        dataset_key=partition.dataset_key,
                        detail="manifest_file_missing",
                    )
                )
                continue
        findings.append(
            ConsistencyFinding(
                code=ConsistencyCode.CATALOG_OK,
                path=partition.file_uri,
                dataset_key=partition.dataset_key,
            )
        )

    for orphan in orphan_paths or ():
        findings.append(
            ConsistencyFinding(
                code=ConsistencyCode.ORPHAN_FILE,
                path=str(orphan),
                detail="not_registered_in_catalog",
            )
        )
    return ConsistencyReport(findings=tuple(findings))


def _resolve_under_root(root: Path, uri: str) -> Path | None:
    raw = str(uri).strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved
