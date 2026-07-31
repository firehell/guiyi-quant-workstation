from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.data_core.canonical_store import CanonicalStore
from app.data_core.catalog import CatalogError, HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    DatasetKey,
    DatasetKind,
)
from app.data_core.historical_apply import (
    execute_prepared_historical_apply,
    filter_actual_dominant_sessions,
    prepare_historical_apply,
    prepare_historical_apply_roots,
)
from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
    load_apply_approval_packet,
    verify_approved_apply_progress,
)
from app.data_core.historical_apply_receipt import PartialApplyReceiptStore
from app.data_core.historical_migration import (
    build_jm_shadow_query_set,
    build_jm_apply_bound_facts,
    build_jm_current_state,
    build_jm_migration_plan,
    run_historical_shadow_query_set,
    ShadowException,
    inventory_jm_legacy_assets,
)
from app.data_core.historical_reader import CanonicalHistoricalReader
from app.data_core.historical_sessions import jm_provider_sessions
from app.data_core.historical_sync import (
    CanonicalBatchPublisher,
    HistoricalSynchronizer,
    plan_missing_windows,
)
from app.data_core.rqdata_provider import CanonicalRQDataAdapter
from app.services.rqdata_ingest.client import RqDataClient
from app.services.canonical_market_data import (
    CanonicalMarketDataService,
    jm_sessions,
)


def run_data_core_command(
    command: str,
    session: Session,
    args: Any,
) -> dict[str, Any]:
    if command == "verify":
        return _verify(session, args)
    if command in {"plan", "sync"} and not bool(getattr(args, "apply", False)):
        return _plan_sync(command, session, args)
    if command == "migrate.inventory":
        inventory = inventory_jm_legacy_assets(
            session,
            project_root=_absolute_path(args.project_root, "project_root"),
        )
        return {
            "schema_version": 1,
            "command": "data.migrate.inventory",
            "status": "passed",
            "readonly": True,
            "effects": _readonly_effects(),
            "items": [asdict(item) for item in inventory],
        }
    if command == "migrate.plan":
        project_root = _absolute_path(args.project_root, "project_root")
        _require_loaded_source_checkout(project_root)
        inventory = inventory_jm_legacy_assets(
            session,
            project_root=_absolute_path(args.legacy_root, "legacy_root"),
        )
        plan = build_jm_migration_plan(inventory)
        git_state = _git_state(project_root)
        start = _aware_datetime(args.start)
        end = _aware_datetime(args.end)
        canonical_root = _absolute_path(args.canonical_root, "canonical_root")
        current_state = build_jm_current_state(session, start=start, end=end)
        bound_facts = build_jm_apply_bound_facts(
            inventory,
            plan=plan,
            task_head=git_state["head"],
            canonical_root=canonical_root,
            staging_root=_absolute_path(
                args.staging_root,
                "staging_root",
            ),
            postgresql_target=_postgresql_target(session),
            start=start,
            end=end,
            source_checkout=_loaded_source_root(),
            current_state=current_state,
            receipt_path=(
                canonical_root.parent / "receipts" / "jm-historical-apply.json"
            ),
        )
        return {
            **plan,
            "command": "data.migrate.plan",
            "status": "planned",
            "readonly": True,
            "effects": _readonly_effects(),
            "git_state": git_state,
            "approval_bound_facts": bound_facts,
            "approval_packet": (
                build_apply_approval_packet(bound_facts=bound_facts)
                if git_state["clean"]
                else None
            ),
            "gate_status": (
                "packet_ready"
                if git_state["clean"]
                else "task_worktree_not_clean"
            ),
            "shadow_query_set": [
                asdict(item)
                for item in build_jm_shadow_query_set(
                    start=_aware_datetime(args.start),
                    end=_aware_datetime(args.end),
                )
            ],
        }
    if command == "migrate.shadow":
        queries = build_jm_shadow_query_set(
            start=_aware_datetime(args.start),
            end=_aware_datetime(args.end),
        )
        legacy = _read_shadow_bundle(args.legacy_json)
        canonical = _read_shadow_bundle(args.canonical_json)
        exceptions = _read_shadow_exceptions(args.exception_json)
        result = run_historical_shadow_query_set(
            queries,
            legacy_reader=lambda query: legacy[_shadow_query_id(query)],
            canonical_reader=lambda query: canonical[_shadow_query_id(query)],
            allowed_exceptions=exceptions,
        )
        return {
            "schema_version": 1,
            "command": "data.migrate.shadow",
            "readonly": True,
            "effects": _readonly_effects(),
            **result,
        }
    if command == "migrate.apply":
        return _apply_jm_migration(session, args)
    raise ValueError("data_core_command_not_implemented")


def _apply_jm_migration(session: Session, args: Any) -> dict[str, Any]:
    project_root = _absolute_path(args.project_root, "project_root")
    _require_loaded_source_checkout(project_root)
    inventory = inventory_jm_legacy_assets(
        session,
        project_root=_absolute_path(args.legacy_root, "legacy_root"),
    )
    plan = build_jm_migration_plan(inventory)
    git_state = _git_state(project_root)
    if not git_state["clean"]:
        raise HistoricalApplyGateError("task_worktree_not_clean")
    start = _aware_datetime(args.start)
    end = _aware_datetime(args.end)
    canonical_root = _absolute_path(args.canonical_root, "canonical_root")
    current_state = build_jm_current_state(session, start=start, end=end)
    current_facts = build_jm_apply_bound_facts(
        inventory,
        plan=plan,
        task_head=git_state["head"],
        canonical_root=canonical_root,
        staging_root=_absolute_path(args.staging_root, "staging_root"),
        postgresql_target=_postgresql_target(session),
        start=start,
        end=end,
        source_checkout=_loaded_source_root(),
        current_state=current_state,
        receipt_path=(
            canonical_root.parent / "receipts" / "jm-historical-apply.json"
        ),
    )
    packet = load_apply_approval_packet(
        _absolute_path(args.approval_packet, "approval_packet"),
        approval_hash=args.approval_hash,
    )
    verified_progress = verify_approved_apply_progress(
        packet["bound_facts"],
        current_facts,
        verify_partition=lambda dataset, partition: _verify_partition_evidence(
            canonical_root,
            dataset,
            partition,
        ),
    )
    prepared = prepare_historical_apply(
        packet,
        approval_hash=args.approval_hash,
        current_facts=current_facts,
        verified_progress=verified_progress,
    )
    receipt_store = PartialApplyReceiptStore(
        prepared.receipt_path,
        bound_facts_digest=packet["packet_hash"],
    )
    _require_data_core_revision(session)
    expected_days = _expected_jm_trading_days(
        session,
        start=prepared.start,
        end=prepared.end,
    )

    prepare_historical_apply_roots(prepared)
    adapter = CanonicalRQDataAdapter(RqDataClient(load_env_file=True))
    metadata_factory = sessionmaker(
        bind=session.get_bind(),
        expire_on_commit=False,
    )
    store = CanonicalStore(
        staging_root=prepared.staging_root,
        canonical_root=prepared.canonical_root,
        metadata_session_factory=metadata_factory,
    )
    catalog = HistoricalCatalog(session)

    def provider_sessions(
        dataset: DatasetKey,
        window_start: datetime,
        window_end: datetime,
    ):
        sessions = jm_provider_sessions(
            session,
            dataset,
            window_start,
            window_end,
        )
        return filter_actual_dominant_sessions(
            dataset,
            sessions,
            actual_contract_for_day=lambda trading_day: (
                catalog.get_main_contract_mapping(
                    instrument_symbol="jm",
                    trade_date=trading_day,
                ).actual_contract
            ),
        )

    synchronizer = HistoricalSynchronizer(
        catalog=catalog,
        adapter=adapter,
        session_provider=provider_sessions,
        publish_batch=CanonicalBatchPublisher(store),
    )
    return execute_prepared_historical_apply(
        prepared,
        synchronizer=synchronizer,
        expected_trading_days=expected_days,
        commit=session.commit,
        rollback=session.rollback,
        receipt_store=receipt_store,
        reconcile_mapping=lambda rows: _reconcile_mapping(catalog, rows),
        reconcile_completed_dataset=lambda dataset, recorded: (
            _reconcile_completed_dataset(
                catalog,
                prepared.canonical_root,
                dataset,
                recorded,
            )
        ),
        capture_progress_state_digest=lambda: build_jm_current_state(
            session,
            start=prepared.start,
            end=prepared.end,
        )["state_digest"],
        capture_partition_evidence=lambda dataset: _partition_evidence(
            catalog,
            dataset,
        ),
    )


def _reconcile_mapping(catalog: HistoricalCatalog, rows: Any) -> bool:
    try:
        for row in rows:
            current = catalog.get_main_contract_mapping(
                instrument_symbol=row.symbol,
                trade_date=row.trading_day,
            )
            if (
                current.actual_contract != row.actual_contract
                or current.data_version != row.data_version
            ):
                return False
        return True
    except (CatalogError, AttributeError, TypeError, ValueError):
        return False


def _partition_evidence(
    catalog: HistoricalCatalog,
    dataset: DatasetKey,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "coverage_start": item.coverage_start.isoformat(),
            "coverage_end": item.coverage_end.isoformat(),
            "manifest_digest": item.manifest_digest,
            "checksum": item.checksum,
            "file_uri": item.file_uri,
            "manifest_uri": item.manifest_uri,
        }
        for item in catalog.list_partitions(dataset)
    )


def _reconcile_completed_dataset(
    catalog: HistoricalCatalog,
    canonical_root: Path,
    dataset: DatasetKey,
    recorded: Any,
) -> bool:
    expected = recorded.get("partition_evidence") if isinstance(recorded, dict) else None
    current = _partition_evidence(catalog, dataset)
    if not isinstance(expected, list) or expected != [dict(item) for item in current]:
        return False
    for item in current:
        if not _verify_partition_evidence(canonical_root, _dataset_identity_dict(dataset), item):
            return False
    return True


def _verify_partition_evidence(
    canonical_root: Path,
    dataset: Mapping[str, Any],
    item: Mapping[str, Any],
) -> bool:
    try:
        file_candidate = canonical_root / str(item["file_uri"])
        manifest_candidate = canonical_root / str(item["manifest_uri"])
        if file_candidate.is_symlink() or manifest_candidate.is_symlink():
            return False
        file_path = file_candidate.resolve(strict=False)
        manifest_path = manifest_candidate.resolve(strict=False)
        file_path.relative_to(canonical_root.resolve())
        manifest_path.relative_to(canonical_root.resolve())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_partition = manifest.get("partition")
        return bool(
            file_path.is_file()
            and _sha256_file(file_path) == item["checksum"]
            and manifest.get("dataset_key") == dict(dataset)
            and isinstance(manifest_partition, dict)
            and manifest_partition.get("coverage_start") == item["coverage_start"]
            and manifest_partition.get("coverage_end") == item["coverage_end"]
            and manifest_partition.get("file_uri") == item["file_uri"]
            and manifest_partition.get("manifest_uri") == item["manifest_uri"]
            and manifest.get("manifest_digest") == item["manifest_digest"]
            and manifest.get("file_checksum") == item["checksum"]
            and _manifest_payload_digest(manifest) == item["manifest_digest"]
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _dataset_identity_dict(dataset: DatasetKey) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_payload_digest(document: Any) -> str:
    if not isinstance(document, dict) or "manifest_digest" not in document:
        return ""
    payload = dict(document)
    payload.pop("manifest_digest")
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _verify(session: Session, args: Any) -> dict[str, Any]:
    start = _aware_datetime(args.start)
    end = _aware_datetime(args.end)
    query = BarQuery(
        dataset_kind=DatasetKind(args.dataset_kind),
        symbol=args.symbol,
        contract_or_series=args.contract_or_series,
        frequency=BarFrequency(args.frequency),
        start=start,
        end=end,
    )
    reader = CanonicalHistoricalReader(
        catalog=HistoricalCatalog(session),
        canonical_root=_absolute_path(args.canonical_root, "canonical_root"),
        session_provider=lambda symbol, window_start, window_end: jm_sessions(
            session,
            symbol=symbol,
            start=window_start,
            end=window_end,
        ),
    )
    response = CanonicalMarketDataService(session, reader=reader).get_bars(query)
    return {
        "schema_version": 1,
        "command": "data.verify",
        "status": "passed",
        "readonly": True,
        "effects": _readonly_effects(),
        "result": {
            "bar_count": len(response.bars),
            "quality_status": response.quality.status,
            "lineage_token": response.lineage.lineage_token,
            "data_identity": response.data_identity.model_dump(mode="json"),
        },
    }


def _plan_sync(command: str, session: Session, args: Any) -> dict[str, Any]:
    dataset = DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind(args.dataset_kind),
        symbol=args.symbol,
        contract_or_series=args.contract_or_series,
        frequency=BarFrequency(args.frequency),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    start = _aware_datetime(args.start)
    end = _aware_datetime(args.end)
    partitions = HistoricalCatalog(session).list_partitions(dataset)
    windows = plan_missing_windows(
        dataset=dataset,
        start=start,
        end=end,
        covered_windows=tuple(
            (partition.coverage_start, partition.coverage_end)
            for partition in partitions
        ),
    )
    return {
        "schema_version": 1,
        "command": f"data.{command}",
        "status": "planned",
        "readonly": True,
        "effects": _readonly_effects(),
        "dataset": {
            "provider": dataset.provider,
            "dataset_kind": dataset.dataset_kind.value,
            "symbol": dataset.symbol,
            "contract_or_series": dataset.contract_or_series,
            "frequency": dataset.frequency.value,
            "adjustment": dataset.adjustment,
            "schema_version": dataset.schema_version,
        },
        "requested_window": [start.isoformat(), end.isoformat()],
        "missing_windows": [
            [window_start.isoformat(), window_end.isoformat()]
            for window_start, window_end in windows
        ],
    }


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("rfc3339_datetime_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("rfc3339_timezone_required")
    return parsed


def _absolute_path(value: object, field: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ValueError(f"{field}_must_be_absolute")
    return value


def _loaded_source_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _require_loaded_source_checkout(project_root: Path) -> None:
    if project_root.resolve(strict=False) != _loaded_source_root().resolve(strict=False):
        raise HistoricalApplyGateError("loaded_source_checkout_mismatch")


def _read_json_array(path: object) -> list[dict[str, Any]]:
    source = _absolute_path(path, "json_path")
    parsed = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(parsed, list) or not all(
        isinstance(item, dict) for item in parsed
    ):
        raise ValueError("shadow_json_array_required")
    return parsed


def _read_shadow_bundle(path: object) -> dict[str, list[dict[str, Any]]]:
    source = _absolute_path(path, "shadow_bundle_path")
    parsed = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str)
        and isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        for key, rows in parsed.items()
    ):
        raise ValueError("shadow_query_bundle_required")
    return parsed


def _read_shadow_exceptions(
    path: object,
) -> dict[str, tuple[ShadowException, ...]]:
    if path is None:
        return {}
    source = _absolute_path(path, "shadow_exception_path")
    parsed = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("shadow_exception_bundle_required")
    try:
        return {
            query_id: tuple(ShadowException(**item) for item in items)
            for query_id, items in parsed.items()
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("shadow_exception_bundle_required") from exc


def _shadow_query_id(query: object) -> str:
    return f"{query.dataset_kind}:{query.frequency}"


def _readonly_effects() -> dict[str, bool]:
    return {
        "calls_rqdata": False,
        "writes_postgresql": False,
        "writes_parquet": False,
    }


def _git_state(project_root: Path) -> dict[str, object]:
    head = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(project_root),
            "rev-parse",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(project_root),
            "status",
            "--porcelain",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"head": head, "clean": not bool(status.strip())}


def _postgresql_target(session: Session) -> dict[str, object]:
    url = session.get_bind().url
    target = {
        "drivername": url.drivername,
        "username": url.username or "",
        "host": url.host,
        "port": url.port,
        "database": url.database or "",
    }
    if target["drivername"] != "postgresql+psycopg":
        raise ValueError("postgresql_psycopg_target_required")
    return target


def _require_data_core_revision(session: Session) -> None:
    revision = session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    if revision != "20260730_0027":
        raise HistoricalApplyGateError("data_core_migration_revision_not_ready")


def _expected_jm_trading_days(
    session: Session,
    *,
    start: datetime,
    end: datetime,
) -> tuple[date, ...]:
    days = tuple(
        sorted(
            {
                item.trading_day
                for item in jm_sessions(
                    session,
                    symbol="jm",
                    start=start,
                    end=end,
                )
            }
        )
    )
    if not days:
        raise HistoricalApplyGateError("jm_trading_calendar_empty")
    return days
