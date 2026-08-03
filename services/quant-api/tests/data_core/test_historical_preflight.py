from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from app.data_core.bar_schema import CanonicalBar
from app.data_core.historical_apply import PreparedHistoricalApply
from app.data_core.historical_apply_gate import HistoricalApplyGateError
from app.data_core import historical_preflight
from app.data_core.historical_preflight import (
    execute_historical_preflight,
    load_historical_preflight_receipt,
)
from app.data_core.rqdata_adapter import ProviderBarBatch, TradingSessionCoverage


def _prepared_85() -> PreparedHistoricalApply:
    contracts = tuple(f"JM{1301 + item:04d}" for item in range(41))
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=1)
    seed = PreparedHistoricalApply(
        task_head="a" * 40,
        plan_digest="b" * 64,
        start=start,
        end=end,
        allowed_actual_contracts=contracts,
        canonical_root=Path("/tmp/data/parquet/data-core-v2/canonical"),
        staging_root=Path("/tmp/data/parquet/data-core-v2/staging"),
        receipt_path=Path("/tmp/data/parquet/data-core-v2/receipts/apply.json"),
        mapping_trading_days=tuple(
            date(2026, 1, 1) + timedelta(days=item) for item in range(41)
        ),
        mapping_session_windows=(),
        verified_mapping_rows=tuple(
            {
                "symbol": "jm",
                "trading_day": (date(2026, 1, 1) + timedelta(days=item)).isoformat(),
                "actual_contract": contract,
                "rank": 1,
                "data_version": "rqdata-test",
            }
            for item, contract in enumerate(contracts)
        ),
        verified_completed_datasets=(),
        verified_progress_state_digest="c" * 64,
    )
    runs = tuple(
        (
            json.dumps(_identity(dataset), sort_keys=True, separators=(",", ":")),
            ((start, end),),
        )
        for dataset in seed.datasets_for_contracts(contracts)
    )
    return PreparedHistoricalApply(
        **{
            field: getattr(seed, field)
            for field in seed.__dataclass_fields__
            if field != "execution_runs_by_dataset"
        },
        execution_runs_by_dataset=runs,
    )


def _identity(dataset) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }


def _bound_facts(prepared: PreparedHistoricalApply) -> dict[str, object]:
    return {
        "scope": {
            "direct_frequency_matrix": {
                "continuous": ["1m", "1d", "1w"],
                "actual_dominant": ["1m", "1d"],
            }
        },
        "mapping_write_plan": {
            "allowed_contracts": list(prepared.allowed_actual_contracts)
        },
    }


def _preflight_receipt(prepared: PreparedHistoricalApply) -> dict[str, object]:
    datasets = [
        {
            "dataset": _identity(dataset),
            "status": "validated",
            "execution_run_count": 1,
            "row_count": 1,
        }
        for dataset in prepared.datasets_for_contracts(
            prepared.allowed_actual_contracts
        )
    ]
    body: dict[str, object] = {
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
        "approval_packet_hash": "d" * 64,
        "approval_basis_digest": "e" * 64,
        "current_state_digest": "c" * 64,
        "expected_dataset_count": 85,
        "dataset_count": 85,
        "datasets": datasets,
    }
    body["preflight_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return body


def test_readonly_preflight_validates_exact_85_dataset_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared_85()
    observed = []

    class Adapter:
        def fetch_bars(self, request):
            observed.append(request.dataset)
            bar_end = request.sessions[0].expected_bar_ends[0]
            return ProviderBarBatch(
                request=request,
                bars=(
                    CanonicalBar(
                        provider="rqdata",
                        dataset_kind=request.dataset.dataset_kind,
                        symbol="jm",
                        contract_or_series=request.dataset.contract_or_series,
                        frequency=request.dataset.frequency,
                        bar_end=bar_end,
                        trading_day=request.sessions[0].trading_day,
                        open=Decimal("1"),
                        high=Decimal("2"),
                        low=Decimal("1"),
                        close=Decimal("2"),
                        volume=Decimal("1"),
                        turnover=Decimal("1"),
                        open_interest=Decimal("1"),
                        adjustment="none",
                        schema_version="canonical-bar-v1",
                    ),
                ),
                data_version="rqdata-test",
            )

    def sessions(_dataset, start, end):
        return (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=start,
                end=end,
                expected_bar_ends=(end,),
            ),
        )

    result = execute_historical_preflight(
        prepared,
        adapter=Adapter(),
        session_provider=sessions,
        reconcile_completed_dataset=lambda *_args: False,
        approval_packet_hash="d" * 64,
        approval_basis="e" * 64,
    )

    assert result["status"] == "passed"
    assert result["readonly"] is True
    assert result["dataset_count"] == result["expected_dataset_count"] == 85
    assert len(observed) == 85
    assert len(result["preflight_hash"]) == 64
    receipt_path = tmp_path / "preflight.json"
    receipt_path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(
        historical_preflight,
        "approval_basis_digest",
        lambda _facts: "e" * 64,
    )
    loaded = load_historical_preflight_receipt(
        receipt_path,
        preflight_hash=result["preflight_hash"],
        approval_packet_hash="d" * 64,
        bound_facts=_bound_facts(prepared),
        current_state_digest="c" * 64,
    )
    assert loaded["dataset_count"] == 85


def test_apply_loader_rejects_even_rehashed_84_of_85_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared_85()
    result = _preflight_receipt(prepared)
    result["dataset_count"] = 84
    result["datasets"] = result["datasets"][:-1]
    result.pop("preflight_hash")
    result["preflight_hash"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(
        historical_preflight,
        "approval_basis_digest",
        lambda _facts: "e" * 64,
    )

    with pytest.raises(HistoricalApplyGateError, match="preflight_receipt_mismatch"):
        load_historical_preflight_receipt(
            path,
            preflight_hash=result["preflight_hash"],
            approval_packet_hash="d" * 64,
            bound_facts=_bound_facts(prepared),
            current_state_digest="c" * 64,
        )


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_identity", "zero_rows"])
def test_apply_loader_rejects_rehashed_invalid_85_dataset_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    prepared = _prepared_85()
    result = _preflight_receipt(prepared)
    datasets = result["datasets"]
    assert isinstance(datasets, list)
    if mutation == "duplicate":
        datasets[-1] = json.loads(json.dumps(datasets[0]))
    elif mutation == "wrong_identity":
        datasets[-1]["dataset"]["contract_or_series"] = "JM9999"
    else:
        datasets[-1]["row_count"] = 0
    result.pop("preflight_hash")
    result["preflight_hash"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / f"preflight-{mutation}.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(
        historical_preflight,
        "approval_basis_digest",
        lambda _facts: "e" * 64,
    )

    with pytest.raises(HistoricalApplyGateError, match="preflight_receipt_mismatch"):
        load_historical_preflight_receipt(
            path,
            preflight_hash=result["preflight_hash"],
            approval_packet_hash="d" * 64,
            bound_facts=_bound_facts(prepared),
            current_state_digest="c" * 64,
        )


def test_readonly_preflight_supports_two_reconciled_and_83_validated() -> None:
    prepared = _prepared_85()
    completed = tuple(
        {
            "dataset": _identity(dataset),
            "partition_evidence": [{"row_count": 10}],
        }
        for dataset in prepared.datasets_for_contracts(
            prepared.allowed_actual_contracts
        )[:2]
    )
    prepared = replace(prepared, verified_completed_datasets=completed)
    provider_calls = 0

    class Adapter:
        def fetch_bars(self, request):
            nonlocal provider_calls
            provider_calls += 1
            end = request.sessions[0].expected_bar_ends[0]
            bar = CanonicalBar(
                provider="rqdata",
                dataset_kind=request.dataset.dataset_kind,
                symbol="jm",
                contract_or_series=request.dataset.contract_or_series,
                frequency=request.dataset.frequency,
                bar_end=end,
                trading_day=request.sessions[0].trading_day,
                open=Decimal("1"),
                high=Decimal("2"),
                low=Decimal("1"),
                close=Decimal("2"),
                volume=Decimal("1"),
                turnover=Decimal("1"),
                open_interest=Decimal("1"),
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
            return ProviderBarBatch(request, (bar,), "rqdata-test")

    result = execute_historical_preflight(
        prepared,
        adapter=Adapter(),
        session_provider=lambda _dataset, start, end: (
            TradingSessionCoverage(date(2026, 7, 1), start, end, (end,)),
        ),
        reconcile_completed_dataset=lambda *_args: True,
        approval_packet_hash="d" * 64,
        approval_basis="e" * 64,
    )

    assert provider_calls == 83
    assert [item["status"] for item in result["datasets"]].count("reconciled") == 2
    assert all(item["row_count"] > 0 for item in result["datasets"])
