from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.data_core.canonical_store import CanonicalStore, canonical_json_digest
from app.data_core.aggregation import aggregate_bars
from app.data_core.bar_schema import CanonicalBar
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
    approval_basis_digest,
    build_apply_approval_packet,
    load_apply_approval_packet,
    verify_approved_apply_progress,
)
from app.data_core.historical_apply_receipt import PartialApplyReceiptStore
from app.data_core.historical_preflight import (
    execute_historical_preflight,
    load_historical_preflight_receipt,
)
from app.data_core.historical_shadow import (
    ShadowReadResult,
    expected_shadow_bar_keys,
    filter_initial_partial_week_sessions,
    run_chunked_historical_shadow_query_set,
)
from app.data_core.historical_migration import (
    build_jm_shadow_query_set,
    build_jm_apply_bound_facts,
    build_jm_current_state,
    build_jm_migration_plan,
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
from app.services.market_data_reader import MarketDataReader
from app.models.data_center import MarketDataFile
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
        staging_root = _absolute_path(args.staging_root, "staging_root")
        postgresql_target = _postgresql_target(session)
        current_state = build_jm_current_state(
            session,
            start=start,
            end=end,
            catalog_ready=_data_core_catalog_ready_for_plan(session),
        )
        bound_facts = build_jm_apply_bound_facts(
            inventory,
            plan=plan,
            task_head=git_state["head"],
            canonical_root=canonical_root,
            staging_root=staging_root,
            postgresql_target=postgresql_target,
            start=start,
            end=end,
            source_checkout=_loaded_source_root(),
            current_state=current_state,
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
        return _run_jm_historical_shadow(session, args)
    if command == "migrate.preflight":
        return _preflight_jm_migration(session, args)
    if command == "migrate.apply":
        return _apply_jm_migration(session, args)
    raise ValueError("data_core_command_not_implemented")


def _apply_jm_migration(session: Session, args: Any) -> dict[str, Any]:
    project_root = _absolute_path(args.project_root, "project_root")
    _require_loaded_source_checkout(project_root)
    _require_data_core_revision(session)
    packet = load_apply_approval_packet(
        _absolute_path(args.approval_packet, "approval_packet"),
        approval_hash=args.approval_hash,
    )
    approved_receipt_path = Path(
        packet["bound_facts"]["write_set"]["partial_apply_receipt"]
    )
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
        receipt_path=approved_receipt_path,
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
    load_historical_preflight_receipt(
        _absolute_path(args.preflight_receipt, "preflight_receipt"),
        preflight_hash=args.preflight_hash,
        approval_packet_hash=packet["packet_hash"],
        bound_facts=packet["bound_facts"],
        current_state_digest=prepared.verified_progress_state_digest,
    )
    receipt_store = PartialApplyReceiptStore(
        prepared.receipt_path,
        approval_basis_digest=approval_basis_digest(packet["bound_facts"]),
        approval_packet_hash=packet["packet_hash"],
    )
    receipt_store.begin_resume()
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
            first_approved_trading_day=prepared.mapping_trading_days[0],
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


def _preflight_jm_migration(session: Session, args: Any) -> dict[str, Any]:
    project_root = _absolute_path(args.project_root, "project_root")
    _require_loaded_source_checkout(project_root)
    _require_data_core_revision(session)
    packet = load_apply_approval_packet(
        _absolute_path(args.approval_packet, "approval_packet"),
        approval_hash=args.approval_hash,
    )
    approved_receipt_path = Path(
        packet["bound_facts"]["write_set"]["partial_apply_receipt"]
    )
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
        receipt_path=approved_receipt_path,
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
    adapter = CanonicalRQDataAdapter(RqDataClient(load_env_file=True))
    catalog = HistoricalCatalog(session)

    def provider_sessions(
        dataset: DatasetKey,
        window_start: datetime,
        window_end: datetime,
    ):
        sessions = jm_provider_sessions(session, dataset, window_start, window_end)
        return filter_actual_dominant_sessions(
            dataset,
            sessions,
            actual_contract_for_day=lambda trading_day: (
                catalog.get_main_contract_mapping(
                    instrument_symbol="jm",
                    trade_date=trading_day,
                ).actual_contract
            ),
            first_approved_trading_day=prepared.mapping_trading_days[0],
        )

    return execute_historical_preflight(
        prepared,
        adapter=adapter,
        session_provider=provider_sessions,
        reconcile_completed_dataset=lambda dataset, recorded: (
            _reconcile_completed_dataset(
                catalog,
                prepared.canonical_root,
                dataset,
                recorded,
            )
        ),
        approval_packet_hash=packet["packet_hash"],
        approval_basis=approval_basis_digest(packet["bound_facts"]),
    )


def _run_jm_historical_shadow(session: Session, args: Any) -> dict[str, Any]:
    project_root = _absolute_path(args.project_root, "project_root")
    _require_loaded_source_checkout(project_root)
    _require_data_core_revision(session)
    packet = load_apply_approval_packet(
        _absolute_path(args.approval_packet, "approval_packet"),
        approval_hash=args.approval_hash,
    )
    git_state = _git_state(project_root)
    if not git_state["clean"] or git_state["head"] != packet["bound_facts"]["task_head"]:
        raise HistoricalApplyGateError("task_worktree_not_clean_exact_head")
    start = _aware_datetime(args.start)
    end = _aware_datetime(args.end)
    scope_window = packet["bound_facts"]["scope"]["window"]
    if start != _aware_datetime(scope_window["start"]) or end != _aware_datetime(
        scope_window["end"]
    ):
        raise HistoricalApplyGateError("shadow_scope_mismatch")
    apply_receipt_path = _absolute_path(args.apply_receipt, "apply_receipt")
    if apply_receipt_path != Path(
        packet["bound_facts"]["write_set"]["partial_apply_receipt"]
    ):
        raise HistoricalApplyGateError("shadow_apply_receipt_path_mismatch")
    apply_receipt = PartialApplyReceiptStore(
        apply_receipt_path,
        approval_basis_digest=approval_basis_digest(packet["bound_facts"]),
        approval_packet_hash=packet["packet_hash"],
    ).snapshot()
    if (
        apply_receipt.get("status") != "passed"
        or apply_receipt.get("receipt_digest") != args.apply_receipt_hash
    ):
        raise HistoricalApplyGateError("shadow_apply_receipt_not_passed")
    current_state = build_jm_current_state(session, start=start, end=end)
    if current_state["state_digest"] != apply_receipt["progress_state_digest"]:
        raise HistoricalApplyGateError("shadow_apply_state_changed")
    if not current_state["mapping_complete"]:
        raise HistoricalApplyGateError("shadow_mapping_incomplete")
    mapping = {
        item["trading_day"]: item["actual_contract"]
        for item in current_state["mapping_rows"]
    }
    first_approved_trading_day = min(
        date.fromisoformat(item) for item in mapping
    )
    canonical_root = _absolute_path(args.canonical_root, "canonical_root")
    if canonical_root != Path(packet["bound_facts"]["write_set"]["canonical_root"]):
        raise HistoricalApplyGateError("shadow_canonical_root_mismatch")
    catalog = HistoricalCatalog(session)
    canonical = CanonicalHistoricalReader(
        catalog=catalog,
        canonical_root=canonical_root,
        session_provider=lambda symbol, window_start, window_end: jm_sessions(
            session,
            symbol=symbol,
            start=window_start,
            end=window_end,
        ),
    )
    weekly_canonical = CanonicalHistoricalReader(
        catalog=catalog,
        canonical_root=canonical_root,
        session_provider=lambda symbol, window_start, window_end: (
            filter_initial_partial_week_sessions(
                jm_sessions(
                    session,
                    symbol=symbol,
                    start=window_start - timedelta(days=7),
                    end=window_end + timedelta(days=7),
                ),
                first_approved_trading_day=first_approved_trading_day,
            )
        ),
    )
    legacy_root = _absolute_path(args.legacy_root, "legacy_root")
    legacy_inventory = inventory_jm_legacy_assets(
        session,
        project_root=legacy_root,
    )
    legacy_plan = _require_shadow_legacy_plan(
        legacy_inventory,
        approved_plan_digest=packet["bound_facts"]["plan_digest"],
    )
    legacy = MarketDataReader(session, project_root=legacy_root)
    frozen_legacy_assets = _freeze_shadow_legacy_assets(
        session,
        legacy=legacy,
        shadow_assets=legacy_plan["shadow_assets"],
    )
    canonical_cache: dict[str, ShadowReadResult] = {}

    def canonical_reader(query: Any) -> ShadowReadResult:
        key = json.dumps(asdict(query), sort_keys=True, separators=(",", ":"))
        cached = canonical_cache.get(key)
        if cached is not None:
            return cached
        reader = weekly_canonical if query.frequency == "1w" else canonical
        result = reader.get_bars(_canonical_shadow_query(query))
        rows = tuple(_canonical_shadow_row(item) for item in result.bars)
        value = ShadowReadResult(
            rows=rows,
            lineage={
                "source_datasets": [
                    _dataset_identity_dict(item) for item in result.source_datasets
                ],
                "manifest_digests": list(result.manifest_digests),
                "source_data_versions": list(result.source_data_versions),
            },
        )
        canonical_cache[key] = value
        return value

    def legacy_reader(query: Any) -> ShadowReadResult:
        window_start = _aware_datetime(query.start)
        window_end = _aware_datetime(query.end)
        source_period = (
            query.frequency
            if query.frequency in {"1m", "1d", "1w"}
            else "1m"
        )
        contracts = (
            _frozen_continuous_contracts(
                frozen_legacy_assets,
                period=source_period,
            )
            if query.dataset_kind == "continuous"
            else tuple(
                sorted(
                    {
                        contract
                        for trading_day, contract in mapping.items()
                        if window_start.date() - timedelta(days=3)
                        <= date.fromisoformat(trading_day)
                        <= window_end.date() + timedelta(days=3)
                    }
                )
            )
        )
        source_bars: list[CanonicalBar] = []
        lineages: list[dict[str, Any]] = []
        for contract in contracts:
            assets = _select_frozen_shadow_assets(
                frozen_legacy_assets,
                dataset_kind=query.dataset_kind,
                contract=contract,
                period=source_period,
            )
            _verify_frozen_shadow_assets_current(
                session,
                legacy=legacy,
                assets=assets,
            )
            reader_symbol, reader_contract, reader_period = (
                _frozen_shadow_reader_identity(assets)
            )
            loaded = legacy.load_bars_from_market_files(
                market_data_file_ids=[
                    int(item["market_data_file_id"]) for item in assets
                ],
                asset_evidence=[item["db_evidence"] for item in assets],
                symbol=reader_symbol,
                contract=reader_contract,
                period=reader_period,
                start=window_start,
                end=window_end,
                passed_only=True,
                limit=None,
                tail=False,
                deduplicate=False,
            )
            lineages.extend(item["plan_evidence"] for item in assets)
            normalized = tuple(
                _legacy_canonical_bar(
                    item,
                    query=query,
                    source_period=source_period,
                )
                for item in loaded
            )
            source_bars.extend(
                item
                for item in normalized
                if window_start < item.bar_end <= window_end
                and (
                    query.dataset_kind == "continuous"
                    or mapping.get(item.trading_day.isoformat()) == contract
                )
            )
        if query.frequency in {"5m", "15m", "30m", "60m"}:
            sessions = tuple(
                jm_sessions(
                    session,
                    symbol="jm",
                    start=window_start,
                    end=window_end,
                )
            )
            if query.dataset_kind == "actual_dominant":
                aggregated = tuple(
                    bar
                    for contract in contracts
                    for bar in aggregate_bars(
                        tuple(
                            item
                            for item in source_bars
                            if item.contract_or_series == contract
                        ),
                        target_frequency=BarFrequency(query.frequency),
                        sessions=tuple(
                            item
                            for item in sessions
                            if mapping.get(item.trading_day.isoformat()) == contract
                        ),
                        requested_window=(window_start, window_end),
                    )
                )
            else:
                aggregated = aggregate_bars(
                    tuple(source_bars),
                    target_frequency=BarFrequency(query.frequency),
                    sessions=sessions,
                    requested_window=(window_start, window_end),
                )
            rows = tuple(_canonical_shadow_row(item) for item in aggregated)
        else:
            rows = tuple(_canonical_shadow_row(item) for item in source_bars)
        return ShadowReadResult(
            rows=rows,
            lineage={
                "assets": lineages,
                "source_period": source_period,
                "derived_frequency": (
                    query.frequency if source_period == "1m" and query.frequency != "1m" else None
                ),
                "mapping_digest": current_state["mapping_digest"],
            },
        )

    queries = build_jm_shadow_query_set(start=start, end=end)

    def expected_keys_reader(query: Any) -> tuple[str, ...]:
        window_start = _aware_datetime(query.start)
        window_end = _aware_datetime(query.end)
        calendar_end = (
            window_end + timedelta(days=7)
            if query.frequency == "1w"
            else window_end
        )
        calendar_start = (
            window_start - timedelta(days=7)
            if query.frequency == "1w"
            else window_start
        )
        sessions = jm_sessions(
            session,
            symbol="jm",
            start=calendar_start,
            end=calendar_end,
        )
        if query.frequency == "1w":
            sessions = filter_initial_partial_week_sessions(
                sessions,
                first_approved_trading_day=first_approved_trading_day,
            )
        return expected_shadow_bar_keys(query, sessions)

    result = run_chunked_historical_shadow_query_set(
        queries,
        legacy_reader=legacy_reader,
        canonical_reader=canonical_reader,
        expected_keys_reader=expected_keys_reader,
        allowed_exceptions=_read_shadow_exceptions(args.exception_json),
        expected_actual_contract_by_day=mapping,
    )
    _verify_frozen_shadow_assets_current(
        session,
        legacy=legacy,
        assets=frozen_legacy_assets,
    )
    session.expire_all()
    final_state = build_jm_current_state(session, start=start, end=end)
    _require_shadow_final_state(
        initial_state=current_state,
        final_state=final_state,
        apply_receipt=apply_receipt,
    )
    final_facts = build_jm_apply_bound_facts(
        legacy_inventory,
        plan=legacy_plan,
        task_head=git_state["head"],
        canonical_root=canonical_root,
        staging_root=Path(packet["bound_facts"]["write_set"]["staging_root"]),
        postgresql_target=_postgresql_target(session),
        start=start,
        end=end,
        source_checkout=_loaded_source_root(),
        current_state=final_state,
        receipt_path=apply_receipt_path,
    )
    verify_approved_apply_progress(
        packet["bound_facts"],
        final_facts,
        verify_partition=lambda dataset, partition: _verify_partition_evidence(
            canonical_root,
            dataset,
            partition,
        ),
    )
    result_body = dict(result)
    result_body.pop("receipt_digest")
    result_body.update(
        {
            "command": "data.migrate.shadow",
            "readonly": True,
            "effects": _readonly_effects(),
            "approval_packet_hash": packet["packet_hash"],
            "approval_basis_digest": approval_basis_digest(
                packet["bound_facts"]
            ),
            "apply_receipt_digest": apply_receipt["receipt_digest"],
            "final_state_digest": final_state["state_digest"],
            "legacy_plan_digest": legacy_plan["plan_digest"],
            "legacy_root_digest": canonical_json_digest(
                {"legacy_root": str(legacy_root)}
            ),
        }
    )
    return {
        **result_body,
        "receipt_digest": canonical_json_digest(result_body),
    }


def _canonical_shadow_query(query: Any) -> BarQuery:
    return BarQuery(
        dataset_kind=DatasetKind(query.dataset_kind),
        symbol="jm",
        contract_or_series=query.contract_or_series,
        frequency=BarFrequency(query.frequency),
        start=_aware_datetime(query.start),
        end=_aware_datetime(query.end),
    )


def _freeze_shadow_legacy_assets(
    session: Session,
    *,
    legacy: MarketDataReader,
    shadow_assets: Any,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(shadow_assets, list) or not shadow_assets:
        raise HistoricalApplyGateError("shadow_legacy_assets_empty")
    frozen: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for raw in shadow_assets:
        if not isinstance(raw, dict):
            raise HistoricalApplyGateError("shadow_legacy_asset_invalid")
        market_data_file_id = raw.get("market_data_file_id")
        if (
            not isinstance(market_data_file_id, int)
            or isinstance(market_data_file_id, bool)
            or market_data_file_id in seen_ids
            or raw.get("provider") != "rqdata"
            or raw.get("data_role") != "primary"
            or raw.get("quality_status") != "passed"
            or raw.get("period") not in {"1m", "1d", "1w"}
            or (
                raw.get("dataset_kind") == "actual_dominant"
                and raw.get("period") == "1w"
            )
            or not raw.get("contract_or_series")
            or not isinstance(raw.get("reader_symbol"), str)
            or not raw.get("reader_symbol")
            or not isinstance(raw.get("reader_contract"), str)
            or not raw.get("reader_contract")
            or not isinstance(raw.get("reader_period"), str)
            or not raw.get("reader_period")
            or raw.get("reader_symbol", "").lower() != raw.get("symbol")
            or raw.get("reader_contract", "").upper()
            != raw.get("contract_or_series")
            or raw.get("reader_period", "").lower() != raw.get("period")
            or raw.get("physical_exists") is not True
            or raw.get("checksum_status") not in {"matched", "computed"}
        ):
            raise HistoricalApplyGateError("shadow_legacy_asset_invalid")
        row = session.get(
            MarketDataFile,
            market_data_file_id,
            populate_existing=True,
        )
        if row is None:
            raise HistoricalApplyGateError("shadow_legacy_asset_missing")
        db_evidence = legacy.asset_evidence(row)
        if (
            db_evidence.get("provider") != raw.get("provider")
            or db_evidence.get("data_role") != raw.get("data_role")
            or db_evidence.get("quality_status") != raw.get("quality_status")
            or db_evidence.get("data_version") != raw.get("data_version")
            or db_evidence.get("checksum") != raw.get("checksum_declared")
            or not _shadow_source_interval_compatible(
                db_evidence.get("source_interval"),
                raw.get("period"),
                raw.get("source_intervals"),
            )
            or str(row.instrument_symbol) != raw.get("reader_symbol")
            or str(row.contract_code) != raw.get("reader_contract")
            or str(row.period) != raw.get("reader_period")
        ):
            raise HistoricalApplyGateError("shadow_legacy_asset_evidence_mismatch")
        frozen.append(
            {
                "market_data_file_id": market_data_file_id,
                "dataset_kind": raw.get("dataset_kind"),
                "contract_or_series": raw.get("contract_or_series"),
                "period": raw.get("period"),
                "file_path": raw.get("file_path"),
                "checksum_actual": raw.get("checksum_actual"),
                "db_evidence": db_evidence,
                "reader_identity": {
                    "symbol": raw.get("reader_symbol"),
                    "contract": raw.get("reader_contract"),
                    "period": raw.get("reader_period"),
                },
                "plan_evidence": dict(raw),
            }
        )
        seen_ids.add(market_data_file_id)
    result = tuple(frozen)
    _verify_frozen_shadow_asset_checksums(result)
    return result


def _shadow_source_interval_compatible(
    value: object,
    period: object,
    physical_intervals: object,
) -> bool:
    if not isinstance(period, str):
        return False
    if isinstance(value, str):
        intervals = {value}
    elif isinstance(value, (list, tuple)) and all(
        isinstance(item, str) for item in value
    ):
        intervals = set(value)
    else:
        return False
    if not intervals:
        return False
    if not isinstance(physical_intervals, (list, tuple)) or not all(
        isinstance(item, str) for item in physical_intervals
    ):
        return False
    return intervals.issubset({period, *physical_intervals})


def _require_shadow_legacy_plan(
    inventory: Any,
    *,
    approved_plan_digest: str,
) -> dict[str, Any]:
    plan = build_jm_migration_plan(inventory)
    if plan["plan_digest"] != approved_plan_digest:
        raise HistoricalApplyGateError("shadow_legacy_plan_mismatch")
    return plan


def _require_shadow_final_state(
    *,
    initial_state: Mapping[str, Any],
    final_state: Mapping[str, Any],
    apply_receipt: Mapping[str, Any],
) -> None:
    if (
        final_state.get("state_digest") != initial_state.get("state_digest")
        or final_state.get("state_digest")
        != apply_receipt.get("progress_state_digest")
    ):
        raise HistoricalApplyGateError("shadow_apply_state_changed")


def _frozen_continuous_contracts(
    assets: tuple[dict[str, Any], ...],
    *,
    period: str,
) -> tuple[str, ...]:
    contracts = tuple(
        sorted(
            {
                str(item["contract_or_series"])
                for item in assets
                if item["dataset_kind"] == "continuous"
                and item["period"] == period
            }
        )
    )
    if len(contracts) != 1:
        raise HistoricalApplyGateError("shadow_legacy_continuous_ambiguous")
    return contracts


def _select_frozen_shadow_assets(
    assets: tuple[dict[str, Any], ...],
    *,
    dataset_kind: str,
    contract: str,
    period: str,
) -> tuple[dict[str, Any], ...]:
    selected = tuple(
        item
        for item in assets
        if item["dataset_kind"] == dataset_kind
        and item["contract_or_series"] == contract
        and item["period"] == period
    )
    if not selected:
        raise HistoricalApplyGateError("shadow_legacy_source_missing")
    return selected


def _frozen_shadow_reader_identity(
    assets: tuple[dict[str, Any], ...],
) -> tuple[str, str, str]:
    if not assets or any(
        not isinstance(item.get("reader_identity"), dict) for item in assets
    ):
        raise HistoricalApplyGateError("shadow_legacy_reader_identity_ambiguous")
    identities = {
        (
            item.get("reader_identity", {}).get("symbol"),
            item.get("reader_identity", {}).get("contract"),
            item.get("reader_identity", {}).get("period"),
        )
        for item in assets
    }
    if (
        len(identities) != 1
        or any(
            not isinstance(value, str) or not value
            for value in next(iter(identities), (None, None, None))
        )
    ):
        raise HistoricalApplyGateError("shadow_legacy_reader_identity_ambiguous")
    return next(iter(identities))


def _verify_frozen_shadow_asset_checksums(
    assets: tuple[dict[str, Any], ...],
) -> None:
    for item in assets:
        path = item.get("file_path")
        checksum = item.get("checksum_actual")
        try:
            valid = bool(
                isinstance(path, str)
                and isinstance(checksum, str)
                and len(checksum) == 64
                and _sha256_file(Path(path)) == checksum
            )
        except OSError:
            valid = False
        if not valid:
            raise HistoricalApplyGateError("shadow_legacy_physical_checksum_mismatch")


def _verify_frozen_shadow_assets_current(
    session: Session,
    *,
    legacy: MarketDataReader,
    assets: tuple[dict[str, Any], ...],
) -> None:
    for item in assets:
        row = session.get(
            MarketDataFile,
            item["market_data_file_id"],
            populate_existing=True,
        )
        if row is None:
            raise HistoricalApplyGateError("shadow_legacy_asset_missing")
        current_path = Path(row.file_path)
        if not current_path.is_absolute():
            current_path = legacy.project_root / current_path
        plan = item["plan_evidence"]
        reader_identity = item.get("reader_identity")
        if (
            str(current_path.resolve(strict=False)) != item["file_path"]
            or legacy.asset_evidence(row) != item["db_evidence"]
            or not isinstance(reader_identity, dict)
            or str(row.instrument_symbol) != reader_identity.get("symbol")
            or str(row.contract_code) != reader_identity.get("contract")
            or str(row.period) != reader_identity.get("period")
            or str(row.instrument_symbol).lower() != plan["symbol"]
            or str(row.contract_code).upper() != plan["contract_or_series"]
            or str(row.period).lower() != plan["period"]
        ):
            raise HistoricalApplyGateError("shadow_legacy_asset_evidence_mismatch")
    _verify_frozen_shadow_asset_checksums(assets)


def _canonical_shadow_row(bar: Any) -> dict[str, Any]:
    return {
        "provider": bar.provider,
        "dataset_kind": bar.dataset_kind.value,
        "symbol": bar.symbol,
        "contract_or_series": bar.contract_or_series,
        "frequency": bar.frequency.value,
        "adjustment": bar.adjustment,
        "schema_version": bar.schema_version,
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": (
            None if bar.open_interest is None else str(bar.open_interest)
        ),
    }


def _legacy_canonical_bar(
    item: Mapping[str, Any],
    *,
    query: Any,
    source_period: str,
) -> CanonicalBar:
    timestamp = item.get("datetime") or item.get("time")
    if not isinstance(timestamp, datetime):
        timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timezone = (
            UTC
            if query.frequency in {"1d", "1w"}
            else ZoneInfo("Asia/Shanghai")
        )
        timestamp = timestamp.replace(tzinfo=timezone)
    contract = str(item.get("contract") or "").upper()
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind(query.dataset_kind),
        symbol="jm",
        contract_or_series=(
            "JM.MAIN" if query.dataset_kind == "continuous" else contract
        ),
        frequency=BarFrequency(source_period),
        bar_end=timestamp.astimezone(UTC),
        trading_day=date.fromisoformat(_legacy_trading_day(item)),
        open=Decimal(str(item.get("open"))),
        high=Decimal(str(item.get("high"))),
        low=Decimal(str(item.get("low"))),
        close=Decimal(str(item.get("close"))),
        volume=Decimal(str(item.get("volume"))),
        turnover=(
            None
            if item.get("turnover") is None
            else Decimal(str(item["turnover"]))
        ),
        open_interest=(
            None
            if item.get("openInterest", item.get("open_interest")) is None
            else Decimal(
                str(item.get("openInterest", item.get("open_interest")))
            )
        ),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _legacy_trading_day(item: Mapping[str, Any]) -> str:
    value = item.get("trading_day")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


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
            "row_count": item.row_count,
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
            and _aware_datetime(manifest_partition.get("coverage_start"))
            == _aware_datetime(item["coverage_start"])
            and _aware_datetime(manifest_partition.get("coverage_end"))
            == _aware_datetime(item["coverage_end"])
            and manifest_partition.get("file_uri") == item["file_uri"]
            and manifest_partition.get("manifest_uri") == item["manifest_uri"]
            and manifest_partition.get("row_count") == item["row_count"]
            and pq.ParquetFile(file_path).metadata.num_rows == item["row_count"]
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
    return canonical_json_digest(payload)


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
    revision = _data_core_revision(session)
    if revision != "20260730_0027":
        raise HistoricalApplyGateError("data_core_migration_revision_not_ready")


def _data_core_catalog_ready_for_plan(session: Session) -> bool:
    revision = _data_core_revision(session)
    if revision == "20260721_0025":
        return False
    if revision == "20260730_0027":
        return True
    raise HistoricalApplyGateError("data_core_plan_revision_not_supported")


def _data_core_revision(session: Session) -> str:
    return str(
        session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    )


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
