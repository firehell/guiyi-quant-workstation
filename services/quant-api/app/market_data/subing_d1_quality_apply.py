"""Exact, all-or-nothing publication of frozen SuBing D1 quality candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.domain import (
    BarFrequency,
    DatasetKey,
    DatasetKind,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.source_quality import (
    NonpositiveCloseFact,
    PriceUnavailableFact,
    SourceQualityFact,
    source_quality_fact_from_record,
)
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest, PublishedPartition
from app.market_data.subing_d1_quality_plan import canonical_json, validate_apply_binding
from app.models import MarketDataset, MarketPartition


class QualityCandidateApplyError(RuntimeError):
    """The approved batch cannot be applied without widening or drifting scope."""


@dataclass(frozen=True, slots=True)
class _OldPointer:
    dataset_id: int | None
    partition_id: int | None
    values: Mapping[str, Any] | None


def preflight_frozen_candidates(
    *,
    session: Session,
    active_root: Path,
    candidate_root: Path,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    expected_plan_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, int | str]:
    """Verify the exact batch and current pointers without installing files."""
    active = active_root.resolve(strict=True)
    candidates_root = candidate_root.resolve(strict=True)
    if active == candidates_root or active in candidates_root.parents or candidates_root in active.parents:
        raise QualityCandidateApplyError("CANDIDATE_ROOT_INVALID")
    _validate_inputs(plan, manifest, expected_plan_sha256, expected_manifest_sha256)
    items = tuple(manifest["candidates"])
    catalog = MarketCatalog(session, active)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise QualityCandidateApplyError("MAINTENANCE_LOCKED")
    try:
        tuple(_load_candidate(candidates_root, item) for item in items)
        states = tuple(
            _current_state(session, active, target, item)
            for target, item in zip(plan["targets"], items, strict=True)
        )
        if all(state in {"old", "noop"} for state in states):
            status = "ready"
        elif all(state in {"applied", "noop"} for state in states):
            status = "already_applied"
        else:
            raise QualityCandidateApplyError("PARTIAL_APPLY_STATE_INVALID")
        return {
            "status": status,
            "target_count": len(items),
            "old_count": states.count("old"),
            "noop_count": states.count("noop"),
        }
    finally:
        session.rollback()
        lease.release()


def apply_frozen_candidates(
    *,
    session: Session,
    active_root: Path,
    candidate_root: Path,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    expected_plan_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, int | str]:
    """Publish one hash-bound batch under the global maintenance lease.

    Every current Catalog pointer is checked before any immutable file is
    installed.  Catalog changes share one database transaction, so a failed
    target leaves all old pointers visible; installed content-addressed files
    are harmless and reusable by an idempotent retry.
    """
    active = active_root.resolve(strict=True)
    candidates_root = candidate_root.resolve(strict=True)
    if active == candidates_root or active in candidates_root.parents or candidates_root in active.parents:
        raise QualityCandidateApplyError("CANDIDATE_ROOT_INVALID")
    _validate_inputs(plan, manifest, expected_plan_sha256, expected_manifest_sha256)
    items = tuple(manifest["candidates"])
    catalog = MarketCatalog(session, active)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise QualityCandidateApplyError("MAINTENANCE_LOCKED")
    try:
        prepared = tuple(
            _load_candidate(candidates_root, item)
            for item in items
        )
        old_pointers = tuple(
            _snapshot_old_pointer(session, target)
            for target in plan["targets"]
        )
        states = tuple(
            _current_state(session, active, target, item)
            for target, item in zip(plan["targets"], items, strict=True)
        )
        if all(state in {"applied", "noop"} for state in states):
            session.rollback()
            return {
                "status": "already_applied",
                "target_count": len(items),
                "applied_count": 0,
                "noop_count": states.count("noop"),
            }
        if any(state not in {"old", "noop"} for state in states):
            session.rollback()
            raise QualityCandidateApplyError("PARTIAL_APPLY_STATE_INVALID")

        active_store = CanonicalMonthlyStore(active)
        published: list[PublishedPartition] = []
        for partition, bars, facts in prepared:
            installed = active_store.publish(PublishRequest(
                dataset=partition.dataset,
                year=partition.year,
                month=partition.month,
                bars=bars,
                expected_bar_ends=tuple(sorted((
                    *(bar.bar_end for bar in bars),
                    *(fact.bar_end for fact in facts),
                ))),
                price_unavailable=tuple(
                    fact for fact in facts if isinstance(fact, PriceUnavailableFact)
                ),
                nonpositive_close=tuple(
                    fact for fact in facts if isinstance(fact, NonpositiveCloseFact)
                ),
            ))
            item = items[len(published)]
            if (
                sha256(installed.parquet_path.read_bytes()).hexdigest()
                != item["candidate_file_sha256"]
                or installed.source_quality_sha256
                != item["candidate_source_quality_sha256"]
            ):
                raise QualityCandidateApplyError("INSTALLED_CANDIDATE_HASH_MISMATCH")
            published.append(installed)

        for installed in published:
            catalog.register_partition(installed)
        _strict_batch_readback(session, active, prepared)
        try:
            session.commit()
        except BaseException as exc:
            _best_effort_rollback(session)
            try:
                _read_commit_outcome(
                    session.get_bind(), active, plan["targets"], items,
                    prepared,
                )
            except BaseException:
                pass
            raise QualityCandidateApplyError("COMMIT_OUTCOME_UNKNOWN") from exc

        try:
            with Session(session.get_bind()) as read_session:
                _strict_batch_readback(read_session, active, prepared)
                for item in items:
                    if _current_state(read_session, active, item, item) not in {"applied", "noop"}:
                        raise QualityCandidateApplyError("POST_COMMIT_READBACK_INVALID")
                read_session.rollback()
        except BaseException as exc:
            try:
                _restore_old_pointers(
                    session.get_bind(), active, plan["targets"], items,
                    old_pointers,
                )
            except BaseException as restore_exc:
                raise QualityCandidateApplyError(
                    "POST_COMMIT_READBACK_AND_ROLLBACK_UNKNOWN"
                ) from restore_exc
            raise QualityCandidateApplyError("POST_COMMIT_READBACK_INVALID_ROLLED_BACK") from exc
        session.rollback()
        return {
            "status": "applied",
            "target_count": len(items),
            "applied_count": states.count("old"),
            "noop_count": states.count("noop"),
        }
    except QualityCandidateApplyError:
        _best_effort_rollback(session)
        raise
    except Exception as exc:
        _best_effort_rollback(session)
        raise QualityCandidateApplyError("APPLY_FAILED") from exc
    finally:
        lease.release()


def _validate_inputs(
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    expected_plan_sha256: str,
    expected_manifest_sha256: str,
) -> None:
    try:
        validate_apply_binding(plan, expected_plan_sha256)
    except ValueError as exc:
        raise QualityCandidateApplyError(str(exc)) from exc
    body = dict(manifest)
    actual_manifest = body.pop("manifest_sha256", None)
    if (
        actual_manifest != expected_manifest_sha256
        or sha256(canonical_json(body)).hexdigest() != expected_manifest_sha256
        or manifest.get("state") != "ALL_CANDIDATES_FROZEN"
        or manifest.get("parent_plan_sha256") != expected_plan_sha256
        or manifest.get("blocked_target_count") != 0
        or manifest.get("frozen_candidate_count") != plan.get("target_partition_count")
    ):
        raise QualityCandidateApplyError("CANDIDATE_MANIFEST_INVALID")
    targets = plan.get("targets")
    items = manifest.get("candidates")
    if not isinstance(targets, list) or not isinstance(items, list) or len(targets) != len(items):
        raise QualityCandidateApplyError("CANDIDATE_SCOPE_INVALID")
    for target, item in zip(targets, items, strict=True):
        fields = ("symbol", "contract", "month", "operation", "partition_id")
        if any(target.get(field) != item.get(field) for field in fields):
            raise QualityCandidateApplyError("CANDIDATE_SCOPE_INVALID")


def _load_candidate(
    root: Path, item: Mapping[str, Any]
) -> tuple[CatalogPartition, tuple[Any, ...], tuple[SourceQualityFact, ...]]:
    parquet_path, parquet_bytes = _read_bound_file(
        root, item.get("candidate_file_uri"), item.get("candidate_file_sha256")
    )
    sidecar_path, sidecar_bytes = _read_bound_file(
        root,
        item.get("candidate_quality_sidecar_uri"),
        item.get("candidate_quality_sidecar_sha256"),
    )
    try:
        payload = json.loads(sidecar_bytes)
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema") != "canonical-source-quality-sidecar-v1"
            or not isinstance(payload.get("source_quality"), list)
        ):
            raise ValueError
        facts = tuple(source_quality_fact_from_record(value) for value in payload["source_quality"])
        year, month = (int(value) for value in str(item["month"]).split("-"))
        key = DatasetKey(
            DatasetKind.CONTRACT,
            str(item["symbol"]),
            str(item["contract"]),
            BarFrequency.D1,
        )
        partition = CatalogPartition(
            dataset=key,
            year=year,
            month=month,
            coverage_start=_datetime(item.get("coverage_start")),
            coverage_end=_datetime(item.get("coverage_end")),
            file_path=parquet_path,
            row_count=int(item["row_count"]),
            source_coverage_start=_datetime(item.get("source_coverage_start")),
            source_coverage_end=_datetime(item.get("source_coverage_end")),
            source_quality=facts,
            source_quality_sha256=str(item["candidate_source_quality_sha256"]),
        )
        bars, read_facts = CanonicalMonthlyStore(root).read_catalog_partition_quality(partition)
    except (KeyError, TypeError, ValueError) as exc:
        raise QualityCandidateApplyError("CANDIDATE_RECORD_INVALID") from exc
    content = {
        "bars": [_bar_record(bar) for bar in bars],
        "source_quality": [fact.to_record() for fact in read_facts],
    }
    if (
        len(parquet_bytes) == 0
        or len(read_facts) != item.get("source_quality_count")
        or sha256(canonical_json(content)).hexdigest() != item.get("candidate_content_sha256")
    ):
        raise QualityCandidateApplyError("CANDIDATE_CONTENT_HASH_MISMATCH")
    return partition, bars, read_facts


def _strict_batch_readback(
    session: Session,
    active_root: Path,
    prepared: tuple[
        tuple[CatalogPartition, tuple[Any, ...], tuple[SourceQualityFact, ...]], ...
    ],
) -> None:
    market = MarketDataService(
        MarketCatalog(session, active_root), CanonicalMonthlyStore(active_root)
    )
    for partition, expected_bars, expected_facts in prepared:
        start = partition.source_coverage_start
        end = partition.source_coverage_end
        if start is None or end is None:
            raise QualityCandidateApplyError("CANDIDATE_COVERAGE_INVALID")
        bars, facts = market.read_physical_daily_quality_union(SeriesQuery(
            SeriesKind.CONTRACT,
            partition.dataset.symbol,
            BarFrequency.D1,
            start,
            end,
            contract=partition.dataset.series_or_contract,
        ))
        expected = tuple(sorted((
            *((bar.bar_end, bar.trading_day) for bar in expected_bars),
            *((fact.bar_end, fact.trading_day) for fact in expected_facts),
        )))
        actual = tuple(sorted((
            *((bar.bar_end, bar.trading_day) for bar in bars),
            *((fact.bar_end, fact.trading_day) for fact in facts),
        )))
        if bars != expected_bars or facts != expected_facts or actual != expected:
            raise QualityCandidateApplyError("STRICT_MDS_READBACK_INVALID")


def _snapshot_old_pointer(
    session: Session, target: Mapping[str, Any]
) -> _OldPointer:
    year, month = (int(value) for value in str(target["month"]).split("-"))
    dataset = session.scalar(select(MarketDataset).where(
        MarketDataset.kind == DatasetKind.CONTRACT.value,
        MarketDataset.symbol == target["symbol"],
        MarketDataset.series_or_contract == target["contract"],
        MarketDataset.frequency == BarFrequency.D1.value,
    ))
    if dataset is None:
        return _OldPointer(None, None, None)
    row = session.scalar(select(MarketPartition).where(
        MarketPartition.dataset_id == dataset.id,
        MarketPartition.year == year,
        MarketPartition.month == month,
    ).with_for_update())
    if row is None:
        return _OldPointer(dataset.id, None, None)
    fields = (
        "coverage_start", "coverage_end", "source_coverage_start",
        "source_coverage_end", "source_quality", "source_quality_sha256",
        "file_uri", "row_count",
    )
    return _OldPointer(
        dataset.id,
        row.id,
        {field: getattr(row, field) for field in fields},
    )


def _restore_old_pointers(
    bind: Any,
    active_root: Path,
    targets: list[Mapping[str, Any]],
    items: tuple[Mapping[str, Any], ...],
    snapshots: tuple[_OldPointer, ...],
) -> None:
    with Session(bind) as restore:
        catalog = MarketCatalog(restore, active_root)
        for target, snapshot in zip(targets, snapshots, strict=True):
            year, month = (int(value) for value in str(target["month"]).split("-"))
            dataset = catalog.dataset_row(DatasetKey(
                DatasetKind.CONTRACT,
                str(target["symbol"]),
                str(target["contract"]),
                BarFrequency.D1,
            ))
            if dataset is None:
                if snapshot.dataset_id is not None:
                    raise QualityCandidateApplyError("ROLLBACK_DATASET_MISSING")
                continue
            row = restore.scalar(select(MarketPartition).where(
                MarketPartition.dataset_id == dataset.id,
                MarketPartition.year == year,
                MarketPartition.month == month,
            ).with_for_update())
            if snapshot.partition_id is None:
                if row is not None:
                    restore.delete(row)
                    restore.flush()
                if snapshot.dataset_id is None:
                    remaining = restore.scalar(
                        select(MarketPartition.id).where(
                            MarketPartition.dataset_id == dataset.id
                        ).limit(1)
                    )
                    if remaining is None:
                        restore.delete(dataset)
                continue
            if row is None or row.id != snapshot.partition_id or snapshot.values is None:
                raise QualityCandidateApplyError("ROLLBACK_POINTER_DRIFT")
            for field, value in snapshot.values.items():
                setattr(row, field, value)
        restore.commit()
    with Session(bind) as verify:
        states = tuple(
            _current_state(verify, active_root, target, item)
            for target, item in zip(targets, items, strict=True)
        )
        if any(state not in {"old", "noop"} for state in states):
            raise QualityCandidateApplyError("ROLLBACK_READBACK_INVALID")
        _strict_old_pointer_readback(verify, active_root, targets)
        verify.rollback()


def _read_commit_outcome(
    bind: Any,
    active_root: Path,
    targets: list[Mapping[str, Any]],
    items: tuple[Mapping[str, Any], ...],
    prepared: tuple[
        tuple[CatalogPartition, tuple[Any, ...], tuple[SourceQualityFact, ...]], ...
    ],
) -> None:
    """Independently observe an uncertain commit without mutating its outcome."""
    with Session(bind) as verify:
        states = tuple(
            _current_state(verify, active_root, target, item)
            for target, item in zip(targets, items, strict=True)
        )
        if all(state in {"old", "noop"} for state in states):
            _strict_old_pointer_readback(verify, active_root, targets)
        elif all(state in {"applied", "noop"} for state in states):
            _strict_batch_readback(verify, active_root, prepared)
        verify.rollback()


def _strict_old_pointer_readback(
    session: Session,
    active_root: Path,
    targets: list[Mapping[str, Any]],
) -> None:
    market = MarketDataService(
        MarketCatalog(session, active_root), CanonicalMonthlyStore(active_root)
    )
    for target in targets:
        if target.get("operation") != "REPLACE_EXISTING_PARTITION":
            continue
        year, month = (int(value) for value in str(target["month"]).split("-"))
        key = DatasetKey(
            DatasetKind.CONTRACT,
            str(target["symbol"]),
            str(target["contract"]),
            BarFrequency.D1,
        )
        partition = next(
            value for value in MarketCatalog(session, active_root).all_partitions(key)
            if value.year == year and value.month == month
        )
        if partition.source_coverage_start is None or partition.source_coverage_end is None:
            raise QualityCandidateApplyError("ROLLBACK_COVERAGE_INVALID")
        market.read_physical_daily_quality_union(SeriesQuery(
            SeriesKind.CONTRACT,
            key.symbol,
            BarFrequency.D1,
            partition.source_coverage_start,
            partition.source_coverage_end,
            contract=key.series_or_contract,
        ))
        if _file_sha256(partition.file_path) != target.get("old_file_sha256"):
            raise QualityCandidateApplyError("ROLLBACK_FILE_HASH_INVALID")


def _best_effort_rollback(session: Session) -> None:
    try:
        session.rollback()
    except BaseException:
        pass


def _current_state(
    session: Session,
    active_root: Path,
    target: Mapping[str, Any],
    item: Mapping[str, Any],
) -> str:
    year, month = (int(value) for value in str(item["month"]).split("-"))
    dataset = session.scalar(select(MarketDataset).where(
        MarketDataset.kind == DatasetKind.CONTRACT.value,
        MarketDataset.symbol == item["symbol"],
        MarketDataset.series_or_contract == item["contract"],
        MarketDataset.frequency == BarFrequency.D1.value,
    ))
    row = None if dataset is None else session.scalar(
        select(MarketPartition).where(
            MarketPartition.dataset_id == dataset.id,
            MarketPartition.year == year,
            MarketPartition.month == month,
        ).with_for_update()
    )
    candidate_path = active_root / str(item.get("candidate_file_uri"))
    if (
        row is not None
        and _row_matches_candidate(row, item)
        and _file_sha256(candidate_path) == item.get("candidate_file_sha256")
    ):
        partition = MarketCatalog(session, active_root).all_partitions(
            DatasetKey(DatasetKind.CONTRACT, str(item["symbol"]), str(item["contract"]), BarFrequency.D1)
        )
        selected = next(value for value in partition if value.year == year and value.month == month)
        CanonicalMonthlyStore(active_root).read_catalog_partition_quality(selected)
        if (
            target.get("operation") == "REPLACE_EXISTING_PARTITION"
            and row.id == target.get("partition_id")
            and target.get("old_file_uri") == item.get("candidate_file_uri")
            and target.get("old_file_sha256") == item.get("candidate_file_sha256")
            and target.get("old_source_quality_sha256")
            == item.get("candidate_source_quality_sha256")
        ):
            return "noop"
        return "applied"
    if target.get("operation") == "CREATE_MIXED_UNION_PARTITION":
        if row is None and target.get("partition_id") is None:
            return "old"
        raise QualityCandidateApplyError("CREATE_PARTITION_DRIFT")
    if row is None or row.id != target.get("partition_id"):
        raise QualityCandidateApplyError("OLD_PARTITION_POINTER_DRIFT")
    old_path = active_root / str(target.get("old_file_uri"))
    if (
        row.file_uri != target.get("old_file_uri")
        or row.source_quality_sha256 != target.get("old_source_quality_sha256")
        or _file_sha256(old_path) != target.get("old_file_sha256")
    ):
        raise QualityCandidateApplyError("OLD_PARTITION_POINTER_DRIFT")
    return "old"


def _row_matches_candidate(row: MarketPartition, item: Mapping[str, Any]) -> bool:
    return (
        row.file_uri == item.get("candidate_file_uri")
        and row.row_count == item.get("row_count")
        and row.source_quality_sha256 == item.get("candidate_source_quality_sha256")
        and _iso(row.coverage_start) == item.get("coverage_start")
        and _iso(row.coverage_end) == item.get("coverage_end")
        and _iso(row.source_coverage_start) == item.get("source_coverage_start")
        and _iso(row.source_coverage_end) == item.get("source_coverage_end")
    )


def _read_bound_file(root: Path, relative_value: Any, expected_digest: Any) -> tuple[Path, bytes]:
    if not isinstance(relative_value, str) or not isinstance(expected_digest, str):
        raise QualityCandidateApplyError("CANDIDATE_RECORD_INVALID")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise QualityCandidateApplyError("CANDIDATE_PATH_INVALID")
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        if root not in resolved.parents or path.is_symlink():
            raise OSError
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise OSError
            raw = stream.read()
    except OSError as exc:
        raise QualityCandidateApplyError("CANDIDATE_FILE_UNREADABLE") from exc
    if sha256(raw).hexdigest() != expected_digest:
        raise QualityCandidateApplyError("CANDIDATE_FILE_HASH_MISMATCH")
    return path, raw


def _file_sha256(path: Path) -> str | None:
    try:
        if path.is_symlink():
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            return sha256(stream.read()).hexdigest()
    except OSError:
        return None


def _datetime(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _bar_record(bar: Any) -> dict[str, str]:
    return {
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": "" if bar.turnover is None else str(bar.turnover),
        "open_interest": "" if bar.open_interest is None else str(bar.open_interest),
    }
