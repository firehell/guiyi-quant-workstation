"""Dispatch validated ``guiyi data`` operation commands to application services."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.data_core.contracts import BarFrequency, DatasetKind
from app.guiyi_cli.data_parser import (
    CliUsageError,
    optional_paired_window,
    parse_dataset_kind,
    parse_frequency,
    require_paired_window,
)
from app.services.data_operations.aggregate import AggregateApplicationService
from app.services.data_operations.audit_v2 import AuditFinding, AuditV2ApplicationService
from app.services.data_operations.contracts import (
    AggregateRequest,
    AuditRequest,
    AuditScope,
    CliArgumentInvalid,
    CommandResult,
    DownloadRequest,
    LiveRequest,
    MetadataSyncRequest,
    MetadataSyncScope,
    empty_effects,
)
from app.services.data_operations.download import DownloadApplicationService
from app.services.data_operations.live import LiveConfig, LiveObservationApplicationService
from app.services.data_operations.metadata_sync import MetadataSyncApplicationService
from app.services.data_operations.target_expander import expand_targets


NEW_DATA_COMMANDS = frozenset({"download", "aggregate", "live", "audit"})
METADATA_SYNC_COMMAND = "sync"


def is_new_data_operation(args: argparse.Namespace) -> bool:
    if getattr(args, "domain", None) != "data":
        return False
    command = getattr(args, "data_command", None)
    if command in NEW_DATA_COMMANDS:
        return True
    if command == METADATA_SYNC_COMMAND and getattr(args, "scope", None):
        # Metadata sync replaces historical sync once scope grammar is present.
        return True
    return False


def build_data_operation_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path] = (),
) -> object:
    """Validate and build the typed request before opening dependencies."""
    command = args.data_command
    if command == "download":
        return _download_request(args, allowed_roots=allowed_roots)
    if command == "aggregate":
        return _aggregate_request(args, allowed_roots=allowed_roots)
    if command == "live":
        return _live_request(args, allowed_roots=allowed_roots)
    if command == "sync":
        return _metadata_request(args, allowed_roots=allowed_roots)
    if command == "audit":
        return _audit_request(args, allowed_roots=allowed_roots)
    raise CliUsageError(f"unsupported data operation: {command}")


def run_data_operation(
    args: argparse.Namespace,
    *,
    session: Session,
    download_service: DownloadApplicationService | None = None,
    aggregate_service: AggregateApplicationService | None = None,
    live_service: LiveObservationApplicationService | None = None,
    metadata_service: MetadataSyncApplicationService | None = None,
    audit_service: AuditV2ApplicationService | None = None,
    allowed_roots: Sequence[Path] = (),
) -> dict[str, Any]:
    command = args.data_command
    request = build_data_operation_request(args, allowed_roots=allowed_roots)
    if command == "download":
        service = download_service or _default_download_service(session)
        return service.run(request).as_payload()  # type: ignore[arg-type]
    if command == "aggregate":
        service = aggregate_service or _default_aggregate_service(session)
        return service.run(request).as_payload()  # type: ignore[arg-type]
    if command == "live":
        service = live_service or _default_live_service(session)
        return service.listen(request).as_payload()  # type: ignore[arg-type]
    if command == "sync":
        service = metadata_service or _default_metadata_service(session)
        return service.run(request).as_payload()  # type: ignore[arg-type]
    if command == "audit":
        service = audit_service or _default_audit_service(session)
        return service.run(request).as_payload()  # type: ignore[arg-type]
    raise CliUsageError(f"unsupported data operation: {command}")


def _download_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path],
) -> DownloadRequest:
    start, end = require_paired_window(args.start, args.end)
    frequency = parse_frequency(args.frequency)
    if frequency.value not in {"1m", "1d", "1w"}:
        raise CliArgumentInvalid(facts={"field": "frequency", "allowed": "direct"})
    targets = expand_targets(
        symbol=args.symbol,
        symbols_file=args.symbols_file,
        dataset_kind=parse_dataset_kind(args.dataset_kind),
        contract_or_series=args.contract_or_series,
        frequency=frequency,
        start=start,
        end=end,
        allowed_roots=allowed_roots,
    )
    return DownloadRequest(
        targets=targets,
        apply=bool(args.apply),
        batch_size=getattr(args, "batch_size", None),
    )


def _aggregate_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path],
) -> AggregateRequest:
    start, end = require_paired_window(args.start, args.end)
    frequency = parse_frequency(args.frequency)
    if frequency.value not in {"5m", "15m", "30m", "60m"}:
        raise CliArgumentInvalid(facts={"field": "frequency", "allowed": "derived"})
    targets = expand_targets(
        symbol=args.symbol,
        symbols_file=args.symbols_file,
        dataset_kind=parse_dataset_kind(args.dataset_kind),
        contract_or_series=args.contract_or_series,
        frequency=frequency,
        start=start,
        end=end,
        allowed_roots=allowed_roots,
    )
    return AggregateRequest(
        targets=targets,
        apply=bool(args.apply),
        batch_size=getattr(args, "batch_size", None),
    )


def _live_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path],
) -> LiveRequest:
    # Live uses an explicit identity window placeholder for expansion contracts.
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    start = now
    end = now.replace(microsecond=0) + timedelta(seconds=1)
    if args.start or args.end:
        start, end = require_paired_window(args.start, args.end)
    targets = expand_targets(
        symbol=args.symbol,
        symbols_file=args.symbols_file,
        dataset_kind=parse_dataset_kind(args.dataset_kind),
        contract_or_series=args.contract_or_series,
        frequency=parse_frequency(args.frequency),
        start=start,
        end=end,
        allowed_roots=allowed_roots,
    )
    return LiveRequest(
        targets=targets,
        confirm_observation_write=bool(args.confirm_observation_write),
    )


def _metadata_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path],
) -> MetadataSyncRequest:
    del allowed_roots
    scope = MetadataSyncScope(args.scope)
    window = optional_paired_window(args.start, args.end)
    symbols: list[str] = []
    if args.symbol:
        symbols.append(str(args.symbol).strip().lower())
    if args.symbols_file is not None:
        from app.services.data_operations.target_expander import TargetExpander
        from app.services.data_operations.contracts import BatchTargetRequest
        from datetime import UTC, datetime

        # Reuse batch parser for symbol rows only; frequency/kind are placeholders.
        placeholder_start = datetime(2020, 1, 1, tzinfo=UTC)
        placeholder_end = datetime(2020, 1, 2, tzinfo=UTC)
        batch = TargetExpander().expand_batch(
            BatchTargetRequest(
                symbols_file=args.symbols_file,
                dataset_kind=DatasetKind.CONTINUOUS,
                frequency=BarFrequency.D1,
                start=placeholder_start,
                end=placeholder_end,
            )
        )
        symbols.extend(item.symbol for item in batch)
    return MetadataSyncRequest(
        scope=scope,
        apply=bool(args.apply),
        symbols=tuple(dict.fromkeys(symbols)),
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


def _audit_request(
    args: argparse.Namespace,
    *,
    allowed_roots: Sequence[Path],
) -> AuditRequest:
    del allowed_roots
    window = optional_paired_window(args.start, args.end)
    symbols: list[str] = []
    if args.symbol:
        symbols.append(str(args.symbol).strip().lower())
    return AuditRequest(
        scope=AuditScope(args.scope),
        symbols=tuple(symbols),
        dataset_kind=(
            parse_dataset_kind(args.dataset_kind)
            if args.dataset_kind
            else None
        ),
        frequency=parse_frequency(args.frequency) if args.frequency else None,
        start=None if window is None else window[0],
        end=None if window is None else window[1],
    )


def _default_download_service(session: Session) -> DownloadApplicationService:
    from app.data_core.catalog import HistoricalCatalog
    from app.data_core.historical_sync import HistoricalSynchronizer

    catalog = HistoricalCatalog(session)

    def factory() -> HistoricalSynchronizer:
        raise CliArgumentInvalid(
            facts={
                "reason": "download_apply_requires_injected_synchronizer",
            }
        )

    return DownloadApplicationService(
        synchronizer_factory=factory,
        catalog=catalog,
    )


def _default_aggregate_service(session: Session) -> AggregateApplicationService:
    from app.data_core.catalog import HistoricalCatalog

    catalog = HistoricalCatalog(session)

    class _UnavailableMarket:
        def get_bars(self, request: object) -> object:
            raise CliArgumentInvalid(
                facts={"reason": "aggregate_requires_injected_market_data"}
            )

    return AggregateApplicationService(
        market_data=_UnavailableMarket(),
        session_provider=lambda *_args, **_kwargs: (),
        catalog=catalog,
        publisher=None,
    )


def _default_live_service(session: Session) -> LiveObservationApplicationService:
    from app.live_review_loop.live import LiveObservationStore

    store = LiveObservationStore(session)

    def stream_factory(_targets: Sequence[Any]) -> list[Any]:
        return []

    return LiveObservationApplicationService(
        store=store,
        stream_factory=stream_factory,
        config_provider=lambda: LiveConfig(enabled=False, missing=True),
    )


def _default_metadata_service(session: Session) -> MetadataSyncApplicationService:
    class _ReadonlyStub:
        def plan(self, **kwargs: Any) -> Mapping[str, Any]:
            return {"dry_run": True, **kwargs}

        def apply(self, **kwargs: Any) -> Mapping[str, Any]:
            raise CliArgumentInvalid(
                facts={"reason": "metadata_apply_requires_injected_services"}
            )

    stub = _ReadonlyStub()
    return MetadataSyncApplicationService(
        services={scope: stub for scope in MetadataSyncScope if scope is not MetadataSyncScope.ALL},
        begin_transaction=session.begin,
        commit=session.commit,
        rollback=session.rollback,
    )


def _default_audit_service(session: Session) -> AuditV2ApplicationService:
    del session

    def _empty(_request: AuditRequest) -> Sequence[AuditFinding]:
        return ()

    return AuditV2ApplicationService(
        checkers={scope: _empty for scope in AuditScope if scope is not AuditScope.ALL}
    )
