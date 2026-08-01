"""Read-only, packet-bound JM historical provider preflight."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.data_core.canonical_store import validate_parquet_representability
from app.data_core.contracts import DatasetKey
from app.data_core.historical_apply import PreparedHistoricalApply
from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    approval_basis_digest,
)
from app.data_core.quality import validate_provider_batch
from app.data_core.rqdata_adapter import ProviderBarRequest, TradingSessionCoverage


class PreflightAdapter(Protocol):
    def fetch_bars(self, request: ProviderBarRequest) -> object: ...


def execute_historical_preflight(
    prepared: PreparedHistoricalApply,
    *,
    adapter: PreflightAdapter,
    session_provider: Callable[
        [DatasetKey, datetime, datetime], Sequence[TradingSessionCoverage]
    ],
    reconcile_completed_dataset: Callable[[DatasetKey, Mapping[str, Any]], bool],
    approval_packet_hash: str,
    approval_basis: str,
) -> dict[str, Any]:
    mapping_rows = prepared.verified_mapping_rows
    actual_contracts = tuple(
        sorted({str(item["actual_contract"]) for item in mapping_rows})
    )
    if actual_contracts != prepared.allowed_actual_contracts:
        raise ValueError("historical_preflight_contract_matrix_incomplete")
    datasets = prepared.datasets_for_contracts(actual_contracts)
    expected_count = 3 + 2 * len(prepared.allowed_actual_contracts)
    if len(datasets) != expected_count:
        raise ValueError("historical_preflight_dataset_matrix_incomplete")
    completed = {
        _dataset_token(item["dataset"]): item
        for item in prepared.verified_completed_datasets
    }
    results: list[dict[str, Any]] = []
    for dataset in datasets:
        identity = _dataset_identity(dataset)
        recorded = completed.get(_dataset_token(identity))
        if recorded is not None:
            if not reconcile_completed_dataset(dataset, recorded):
                raise ValueError("historical_preflight_reconciliation_failed")
            results.append(
                {
                    "dataset": identity,
                    "status": "reconciled",
                    "execution_run_count": 0,
                    "row_count": sum(
                        int(item.get("row_count", 0))
                        for item in recorded["partition_evidence"]
                    ),
                }
            )
            continue
        runs = dict(prepared.execution_runs_by_dataset).get(_dataset_token(identity))
        if not runs:
            raise ValueError("historical_preflight_execution_runs_missing")
        row_count = 0
        for window_start, window_end in runs:
            sessions = tuple(session_provider(dataset, window_start, window_end))
            request = ProviderBarRequest(
                dataset=dataset,
                start=window_start,
                end=window_end,
                sessions=sessions,
            )
            validated = validate_provider_batch(adapter.fetch_bars(request))
            validate_parquet_representability(validated.bars)
            row_count += validated.row_count
        results.append(
            {
                "dataset": identity,
                "status": "validated",
                "execution_run_count": len(runs),
                "row_count": row_count,
            }
        )
    body = {
        "schema_version": 1,
        "command": "data.migrate.preflight",
        "gate": "GY-DATA-CORE-V2-JM-HISTORICAL-PREFLIGHT",
        "status": "passed",
        "readonly": True,
        "effects": {
            "calls_rqdata": True,
            "writes_postgresql": False,
            "writes_parquet": False,
        },
        "approval_packet_hash": approval_packet_hash,
        "approval_basis_digest": approval_basis,
        "current_state_digest": prepared.verified_progress_state_digest,
        "expected_dataset_count": expected_count,
        "dataset_count": len(results),
        "datasets": results,
    }
    return {**body, "preflight_hash": _digest(body)}


def load_historical_preflight_receipt(
    path: Path,
    *,
    preflight_hash: str,
    approval_packet_hash: str,
    bound_facts: Mapping[str, Any],
    current_state_digest: str,
) -> dict[str, Any]:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise HistoricalApplyGateError("preflight_receipt_path_invalid")
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise HistoricalApplyGateError("preflight_receipt_path_invalid")
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except HistoricalApplyGateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalApplyGateError("preflight_receipt_invalid") from exc
    if not isinstance(parsed, dict):
        raise HistoricalApplyGateError("preflight_receipt_invalid")
    stored_hash = parsed.pop("preflight_hash", None)
    expected_count = 3 + 2 * len(bound_facts["mapping_write_plan"]["allowed_contracts"])
    datasets = parsed.get("datasets")
    expected_identities = _expected_dataset_identities(bound_facts)
    actual_tokens: list[str] = []
    valid_items = isinstance(datasets, list)
    if valid_items:
        for item in datasets:
            if not isinstance(item, dict) or set(item) != {
                "dataset",
                "status",
                "execution_run_count",
                "row_count",
            }:
                valid_items = False
                break
            dataset = item["dataset"]
            if not isinstance(dataset, Mapping):
                valid_items = False
                break
            actual_tokens.append(_dataset_token(dataset))
            if (
                item["status"] not in {"validated", "reconciled"}
                or not isinstance(item["row_count"], int)
                or item["row_count"] <= 0
                or not isinstance(item["execution_run_count"], int)
                or item["status"] == "validated"
                and item["execution_run_count"] <= 0
                or item["status"] == "reconciled"
                and item["execution_run_count"] != 0
            ):
                valid_items = False
                break
    if (
        stored_hash != preflight_hash
        or stored_hash != _digest(parsed)
        or parsed.get("schema_version") != 1
        or parsed.get("command") != "data.migrate.preflight"
        or parsed.get("gate") != "GY-DATA-CORE-V2-JM-HISTORICAL-PREFLIGHT"
        or parsed.get("status") != "passed"
        or parsed.get("readonly") is not True
        or parsed.get("effects")
        != {
            "calls_rqdata": True,
            "writes_postgresql": False,
            "writes_parquet": False,
        }
        or parsed.get("approval_packet_hash") != approval_packet_hash
        or parsed.get("approval_basis_digest") != approval_basis_digest(bound_facts)
        or parsed.get("current_state_digest") != current_state_digest
        or parsed.get("expected_dataset_count") != expected_count
        or parsed.get("dataset_count") != expected_count
        or not isinstance(datasets, list)
        or len(datasets) != expected_count
        or not valid_items
        or len(actual_tokens) != len(set(actual_tokens))
        or set(actual_tokens) != expected_identities
    ):
        raise HistoricalApplyGateError("preflight_receipt_mismatch")
    return {**parsed, "preflight_hash": stored_hash}


def _dataset_identity(dataset: DatasetKey) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }


def _dataset_token(dataset: Mapping[str, Any]) -> str:
    return json.dumps(dict(dataset), sort_keys=True, separators=(",", ":"))


def _expected_dataset_identities(bound_facts: Mapping[str, Any]) -> set[str]:
    scope = bound_facts["scope"]
    contracts = bound_facts["mapping_write_plan"]["allowed_contracts"]
    matrix = scope["direct_frequency_matrix"]
    identities = [
        {
            "provider": "rqdata",
            "dataset_kind": "continuous",
            "symbol": "jm",
            "contract_or_series": "JM.MAIN",
            "frequency": frequency,
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
        }
        for frequency in matrix["continuous"]
    ]
    identities.extend(
        {
            "provider": "rqdata",
            "dataset_kind": "actual_dominant",
            "symbol": "jm",
            "contract_or_series": contract,
            "frequency": frequency,
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
        }
        for contract in contracts
        for frequency in matrix["actual_dominant"]
    )
    return {_dataset_token(item) for item in identities}


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
