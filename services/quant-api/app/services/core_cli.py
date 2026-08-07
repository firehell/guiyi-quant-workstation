from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarQuery,
    DataCoreError,
    DatasetKind,
    DatasetKey,
    parse_bar_frequency,
)
from app.data_core.bar_schema import CANONICAL_BAR_SCHEMA_VERSION
from app.services.active_dataset import ActiveDatasetDomainError
from app.services.canonical_market_data import build_canonical_reader
from app.services.market_data_service import MarketDataService
from app.services.rqdata_ingest.reference_metadata_gap_apply_plan import (
    build_reference_metadata_gap_apply_plan,
    write_reference_metadata_gap_apply_plan,
)


def verify_active_dataset(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    profile_id: str | None,
    access_mode: str,
    limit: int,
    legacy_compat: bool = False,
    service_factory: Callable[..., MarketDataService] | None = None,
    gap_lister: Callable[[DatasetKey], list[Any]] | None = None,
) -> dict[str, Any]:
    del legacy_compat, provider, profile_id, access_mode
    normalized_symbol = symbol.strip().lower()
    normalized_contract = contract.strip().upper()
    try:
        frequency = parse_bar_frequency(period)
    except DataCoreError as exc:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED") from exc

    if normalized_contract.endswith(".MAIN"):
        dataset_kind = DatasetKind.CONTINUOUS
    else:
        dataset_kind = DatasetKind.ACTUAL_DOMINANT

    window_end = _as_aware(end) if end is not None else datetime.now(UTC)
    if start is not None:
        window_start = _as_aware(start)
    else:
        window_start = window_end.replace(year=max(1970, window_end.year - 10))

    query = BarQuery(
        dataset_kind=dataset_kind,
        symbol=normalized_symbol,
        contract_or_series=normalized_contract,
        frequency=frequency,
        start=window_start,
        end=window_end,
    )
    key = DatasetKey(
        provider="rqdata",
        dataset_kind=dataset_kind,
        symbol=normalized_symbol,
        contract_or_series=normalized_contract,
        frequency=frequency,
        adjustment="none",
        schema_version=CANONICAL_BAR_SCHEMA_VERSION,
    )
    list_gaps = gap_lister or HistoricalCatalog(session).list_gaps
    gaps = list_gaps(key)
    intersecting = [
        gap
        for gap in gaps
        if _as_aware(gap.gap_end) >= window_start
        and _as_aware(gap.gap_start) <= window_end
    ]
    if intersecting:
        return _data_verify_payload(
            status="failed",
            request=_request_payload(
                symbol=normalized_symbol,
                contract=normalized_contract,
                period=period,
                start=start,
                end=end,
                provider=None,
                profile_id=None,
                access_mode="canonical",
                limit=limit,
            ),
            result={
                "response_bar_count": 0,
                "quality": {
                    "status": "failed",
                    "code": "DATA_GAP",
                    "report_count": len(intersecting),
                },
                "descriptor": {
                    "dataset_kind": dataset_kind.value,
                    "frequency": frequency.value,
                    "contract_or_series": normalized_contract,
                },
                "selection_mode": "market_data_service_bar_query",
            },
        )

    factory = service_factory or (
        lambda db: MarketDataService(db, canonical_reader=build_canonical_reader(db))
    )
    try:
        result = factory(session).get_bars(query)
    except DataCoreError as exc:
        return _data_verify_payload(
            status="failed",
            request=_request_payload(
                symbol=normalized_symbol,
                contract=normalized_contract,
                period=period,
                start=start,
                end=end,
                provider=None,
                profile_id=None,
                access_mode="canonical",
                limit=limit,
            ),
            result={
                "response_bar_count": 0,
                "quality": {
                    "status": "failed",
                    "code": exc.code,
                    "facts": dict(exc.facts),
                },
                "descriptor": None,
                "selection_mode": "market_data_service_bar_query",
            },
        )

    bars = list(result.bars)
    if limit > 0:
        bars = bars[-limit:]
    return _data_verify_payload(
        status="passed",
        request=_request_payload(
            symbol=normalized_symbol,
            contract=normalized_contract,
            period=period,
            start=start,
            end=end,
            provider=None,
            profile_id=None,
            access_mode="canonical",
            limit=limit,
        ),
        result={
            "response_bar_count": len(bars),
            "quality": {
                "status": "passed",
                "provider": "rqdata",
                "report_count": 0,
            },
            "descriptor": {
                "dataset_kind": dataset_kind.value,
                "frequency": frequency.value,
                "contract_or_series": normalized_contract,
            },
            "selection_mode": "market_data_service_bar_query",
        },
    )


def run_reference_metadata_gap_plan(
    *,
    project_root: Path,
    gap_ledger: Path,
    output_dir: Path,
) -> dict[str, Any]:
    resolved_ledger = (
        gap_ledger if gap_ledger.is_absolute() else project_root / gap_ledger
    )
    result = build_reference_metadata_gap_apply_plan(
        project_root=project_root,
        gap_ledger=resolved_ledger,
    )
    output_paths = write_reference_metadata_gap_apply_plan(
        result,
        output_dir=output_dir,
    )
    return {
        "schema_version": 1,
        "command": "data.reference-metadata-gap-plan",
        "status": "planned",
        "readonly": True,
        "effects": {**_data_effects(), "writes_report_files": True},
        "result": result,
        "outputs": {name: str(path) for name, path in output_paths.items()},
    }


def format_reference_metadata_plan_legacy(payload: dict[str, Any]) -> str:
    result = payload["result"]
    lines = [
        "Reference metadata gap apply plan completed",
        "writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False",
        f"candidate_rows={result['candidate_row_count']}",
        f"batch_count={result['batch_count']}",
    ]
    lines.extend(
        f"{name}={count}"
        for name, count in result["classification_counts"].items()
    )
    lines.extend(f"{name}: {path}" for name, path in payload["outputs"].items())
    return "\n".join(lines) + "\n"


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _data_verify_payload(
    *,
    status: str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command": "data.verify",
        "kind": "active-dataset",
        "status": status,
        "readonly": True,
        "effects": _data_effects(),
        "request": request,
        "result": result,
    }


def _data_effects() -> dict[str, bool]:
    return {
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
    }


def _request_payload(
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    profile_id: str | None,
    access_mode: str,
    limit: int,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "contract": contract,
        "period": period,
        "start": start.isoformat() if start is not None else None,
        "end": end.isoformat() if end is not None else None,
        "provider": provider,
        "profile_id": profile_id,
        "access_mode": access_mode,
        "limit": limit,
    }
