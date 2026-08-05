"""Deterministic single/batch target expansion for data CLI commands."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.data_core.contracts import BarFrequency, DatasetKind
from app.services.data_operations.contracts import (
    DEFAULT_ADJUSTMENT,
    DEFAULT_PROVIDER,
    DEFAULT_SCHEMA_VERSION,
    MAX_BATCH_BYTES,
    MAX_BATCH_TARGETS,
    BatchTargetRequest,
    CliArgumentInvalid,
    DataTarget,
    SingleTargetRequest,
)


_REQUIRED_BATCH_FIELDS = frozenset({"symbol", "contract_or_series"})
_FORBIDDEN_BATCH_FIELDS = frozenset(
    {
        "output",
        "output_path",
        "canonical_root",
        "staging_root",
        "path",
        "file",
    }
)


def expand_targets(
    *,
    symbol: str | None,
    symbols_file: Path | None,
    dataset_kind: DatasetKind,
    contract_or_series: str | None,
    frequency: BarFrequency,
    start: datetime,
    end: datetime,
    provider: str = DEFAULT_PROVIDER,
    adjustment: str = DEFAULT_ADJUSTMENT,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    allowed_roots: Sequence[Path] = (),
) -> tuple[DataTarget, ...]:
    if (symbol is None) == (symbols_file is None):
        raise CliArgumentInvalid(
            facts={
                "field": "selector",
                "reason": "exactly_one_of_symbol_or_symbols_file",
            }
        )
    if symbols_file is None:
        if contract_or_series is None or not str(contract_or_series).strip():
            raise CliArgumentInvalid(
                facts={"field": "contract_or_series", "reason": "required"}
            )
        return TargetExpander().expand_single(
            SingleTargetRequest(
                symbol=symbol or "",
                dataset_kind=dataset_kind,
                contract_or_series=contract_or_series,
                frequency=frequency,
                start=start,
                end=end,
                provider=provider,
                adjustment=adjustment,
                schema_version=schema_version,
            )
        )
    return TargetExpander().expand_batch(
        BatchTargetRequest(
            symbols_file=symbols_file,
            dataset_kind=dataset_kind,
            frequency=frequency,
            start=start,
            end=end,
            provider=provider,
            adjustment=adjustment,
            schema_version=schema_version,
            allowed_roots=tuple(allowed_roots),
        )
    )


class TargetExpander:
    def expand_single(self, request: SingleTargetRequest) -> tuple[DataTarget, ...]:
        target = _build_target(
            symbol=request.symbol,
            contract_or_series=request.contract_or_series,
            dataset_kind=request.dataset_kind,
            frequency=request.frequency,
            start=request.start,
            end=request.end,
            provider=request.provider,
            adjustment=request.adjustment,
            schema_version=request.schema_version,
        )
        return (target,)

    def expand_batch(self, request: BatchTargetRequest) -> tuple[DataTarget, ...]:
        path = _normalize_allowed_path(
            request.symbols_file,
            allowed_roots=request.allowed_roots,
        )
        size = path.stat().st_size
        if size > request.max_bytes:
            raise CliArgumentInvalid(
                facts={
                    "field": "symbols_file",
                    "reason": "oversized",
                    "max_bytes": request.max_bytes,
                }
            )
        rows = _parse_manifest(path)
        if len(rows) > request.max_targets:
            raise CliArgumentInvalid(
                facts={
                    "field": "symbols_file",
                    "reason": "too_many_targets",
                    "max_targets": request.max_targets,
                }
            )
        targets: list[DataTarget] = []
        seen: set[tuple[object, ...]] = set()
        for row in rows:
            target = _build_target(
                symbol=str(row["symbol"]),
                contract_or_series=str(row["contract_or_series"]),
                dataset_kind=request.dataset_kind,
                frequency=request.frequency,
                start=request.start,
                end=request.end,
                provider=request.provider,
                adjustment=request.adjustment,
                schema_version=request.schema_version,
            )
            identity = target.identity_tuple()
            if identity in seen:
                continue
            seen.add(identity)
            targets.append(target)
        return tuple(targets)


def _build_target(
    *,
    symbol: str,
    contract_or_series: str,
    dataset_kind: DatasetKind,
    frequency: BarFrequency,
    start: datetime,
    end: datetime,
    provider: str,
    adjustment: str,
    schema_version: str,
) -> DataTarget:
    _require_aware_window(start, end)
    normalized_symbol = _normalize_symbol(symbol)
    normalized_contract = _normalize_contract(contract_or_series)
    if not isinstance(dataset_kind, DatasetKind):
        try:
            dataset_kind = DatasetKind(dataset_kind)
        except (TypeError, ValueError) as exc:
            raise CliArgumentInvalid(
                facts={"field": "dataset_kind", "reason": "invalid"}
            ) from exc
    if not isinstance(frequency, BarFrequency):
        try:
            frequency = BarFrequency(frequency)
        except (TypeError, ValueError) as exc:
            raise CliArgumentInvalid(
                facts={"field": "frequency", "reason": "invalid"}
            ) from exc
    return DataTarget(
        provider=_normalize_provider(provider),
        dataset_kind=dataset_kind,
        symbol=normalized_symbol,
        contract_or_series=normalized_contract,
        frequency=frequency,
        adjustment=_normalize_token(adjustment, field="adjustment", lower=True),
        schema_version=_normalize_token(schema_version, field="schema_version"),
        start=start,
        end=end,
    )


def _parse_manifest(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        if isinstance(payload, Mapping) and "targets" in payload:
            payload = payload["targets"]
        if not isinstance(payload, list):
            raise CliArgumentInvalid(
                facts={"field": "symbols_file", "reason": "schema_invalid"}
            )
        rows = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise CliArgumentInvalid(
                    facts={"field": "symbols_file", "reason": "row_invalid"}
                )
            rows.append(dict(item))
        return [_validate_row(row) for row in rows]

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise CliArgumentInvalid(
            facts={"field": "symbols_file", "reason": "schema_invalid"}
        )
    return [_validate_row(dict(row)) for row in reader]


def _validate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = {str(key).strip().lower() for key in row}
    if keys & {item.lower() for item in _FORBIDDEN_BATCH_FIELDS}:
        raise CliArgumentInvalid(
            facts={"field": "symbols_file", "reason": "caller_controlled_path_forbidden"}
        )
    normalized = {
        str(key).strip().lower(): value
        for key, value in row.items()
        if value is not None and str(value).strip() != ""
    }
    missing = _REQUIRED_BATCH_FIELDS - set(normalized)
    if missing:
        raise CliArgumentInvalid(
            facts={
                "field": "symbols_file",
                "reason": "missing_fields",
                "missing": tuple(sorted(missing)),
            }
        )
    # Dataset kind and frequency come from the command; reject overrides.
    if "dataset_kind" in normalized or "frequency" in normalized:
        raise CliArgumentInvalid(
            facts={"field": "symbols_file", "reason": "identity_override_forbidden"}
        )
    return {
        "symbol": normalized["symbol"],
        "contract_or_series": normalized["contract_or_series"],
    }


def _normalize_allowed_path(
    path: Path,
    *,
    allowed_roots: Sequence[Path],
) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if not allowed_roots:
        if not resolved.is_file():
            raise CliArgumentInvalid(
                facts={"field": "symbols_file", "reason": "not_found"}
            )
        return resolved
    for root in allowed_roots:
        root_resolved = root.expanduser().resolve(strict=False)
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        if not resolved.is_file():
            raise CliArgumentInvalid(
                facts={"field": "symbols_file", "reason": "not_found"}
            )
        return resolved
    raise CliArgumentInvalid(
        facts={"field": "symbols_file", "reason": "outside_allowed_root"}
    )


def _require_aware_window(start: datetime, end: datetime) -> None:
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
    ):
        raise CliArgumentInvalid(
            facts={"field": "window", "reason": "timezone_required"}
        )
    if start >= end:
        raise CliArgumentInvalid(facts={"field": "window", "reason": "invalid"})


def _normalize_symbol(value: str) -> str:
    return _normalize_token(value, field="symbol", lower=True)


def _normalize_contract(value: str) -> str:
    return _normalize_token(value, field="contract_or_series", upper=True)


def _normalize_provider(value: str) -> str:
    provider = _normalize_token(value, field="provider", lower=True)
    if provider != DEFAULT_PROVIDER:
        raise CliArgumentInvalid(facts={"field": "provider", "value": provider})
    return provider


def _normalize_token(
    value: object,
    *,
    field: str,
    lower: bool = False,
    upper: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CliArgumentInvalid(facts={"field": field, "reason": "empty"})
    text = value.strip()
    if lower:
        text = text.lower()
    if upper:
        text = text.upper()
    return text


# Re-export bounds for tests and validators.
__all__ = [
    "MAX_BATCH_BYTES",
    "MAX_BATCH_TARGETS",
    "TargetExpander",
    "expand_targets",
]
