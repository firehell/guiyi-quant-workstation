from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.active_dataset import DatasetRequest
from app.services.market_data_reader import MarketDataReader
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
    service_factory: Callable[..., MarketDataService] = MarketDataService,
    reader_factory: Callable[..., MarketDataReader] = MarketDataReader,
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().lower()
    if normalized_symbol != "jm":
        if not legacy_compat:
            from app.services.active_dataset import ActiveDatasetDomainError

            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        quality = reader_factory(session).get_quality_status(
            symbol=normalized_symbol,
            contract=contract,
            period=period,
            start=start if start is not None else datetime.min,
            end=end if end is not None else datetime.max,
            provider=provider,
        )
        return _data_verify_payload(
            status=str(quality.get("status", "failed")),
            request=_request_payload(
                symbol=normalized_symbol,
                contract=contract,
                period=period,
                start=start,
                end=end,
                provider=provider,
                profile_id=profile_id,
                access_mode=access_mode,
                limit=limit,
            ),
            result={
                "response_bar_count": None,
                "quality": quality,
                "descriptor": None,
                "selection_mode": "legacy_non_jm",
            },
        )

    result = service_factory(session).get_bars(
        DatasetRequest(
            data_context="historical",
            symbol=normalized_symbol,
            contract_selector="explicit",
            contract=contract,
            period=period,
            access_mode=access_mode,
            profile_id=profile_id,
            provider=provider,
        ),
        start=start,
        end=end,
        limit=limit,
        tail=False,
    )
    return _data_verify_payload(
        status=str(result.quality.get("status", "failed")),
        request=_request_payload(
            symbol=normalized_symbol,
            contract=contract,
            period=period,
            start=start,
            end=end,
            provider=provider,
            profile_id=profile_id,
            access_mode=access_mode,
            limit=limit,
        ),
        result={
            "response_bar_count": result.response_bar_count,
            "quality": result.quality,
            "descriptor": asdict(result.descriptor),
            "selection_mode": "jm_active_dataset_facade",
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
