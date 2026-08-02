from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.rqdata_adapter import (
    ProviderBarRequest,
    RQDataBarAdapter,
    TradingSessionCoverage,
)
from app.data_core.quality import validate_provider_batch
from app.live_review_loop.contracts import canonical_digest, canonical_json
from app.live_review_loop.live import LiveObservationInput, aggregate_confirmed_15m
from app.models.live_review_loop import SignalDecision


class RQDataProviderFinalLoader:
    """Fetch the exact decision window from RQData through the frozen adapter."""

    def __init__(self, adapter: RQDataBarAdapter) -> None:
        self.adapter = adapter

    def __call__(self, decision: SignalDecision) -> ProviderFinalSnapshot:
        expected_ends = tuple(
            _datetime(item["bar_end"])
            for item in decision.input_snapshot["live_inputs"]
        )
        if len(expected_ends) != 15:
            raise ValueError("EOD_PROVIDER_FINAL_WINDOW_INVALID")
        start = _datetime(decision.input_snapshot["live_inputs"][0]["source_start"])
        end = expected_ends[-1]
        request = ProviderBarRequest(
            dataset=_dataset_key(decision.dataset_key),
            start=start,
            end=end,
            sessions=(
                TradingSessionCoverage(
                    trading_day=decision.trading_day,
                    start=start,
                    end=end,
                    expected_bar_ends=expected_ends,
                ),
            ),
        )
        batch = self.adapter.fetch_bars(request)
        validated = validate_provider_batch(batch)
        if batch.request != request or validated.dataset != request.dataset:
            raise ValueError("EOD_PROVIDER_FINAL_BATCH_IDENTITY_INVALID")
        if tuple(bar.bar_end for bar in validated.bars) != expected_ends:
            raise ValueError("EOD_PROVIDER_FINAL_WINDOW_INCOMPLETE")
        if any(
            bar.provider != "rqdata"
            or bar.dataset_kind is not DatasetKind.ACTUAL_DOMINANT
            or bar.symbol != "jm"
            or bar.contract_or_series != decision.actual_contract
            or bar.frequency is not BarFrequency.M1
            or bar.trading_day != decision.trading_day
            or bar.adjustment != "none"
            or bar.schema_version != "canonical-bar-v1"
            for bar in validated.bars
        ):
            raise ValueError("EOD_PROVIDER_FINAL_BAR_IDENTITY_INVALID")
        live_inputs = [
            LiveObservationInput(
                provider="rqdata",
                source_mode="rqdata_live_1m_v2",
                product="jm",
                actual_contract=decision.actual_contract,
                trading_day=decision.trading_day,
                period="1m",
                bar_end=bar.bar_end,
                revision=0,
                confirmed=True,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                open_interest=bar.open_interest,
                turnover=bar.turnover,
                source_start=bar.bar_end - timedelta(minutes=1),
                source_end=bar.bar_end,
                source_bar_count=1,
                expected_bar_count=1,
            )
            for bar in validated.bars
        ]
        decision_bar = aggregate_confirmed_15m(
            live_inputs,
            session_start=start,
            session_end=end,
        )
        snapshot = deepcopy(decision.input_snapshot)
        snapshot["live_inputs"] = [item.to_payload() for item in live_inputs]
        snapshot["decision_bar"] = decision_bar.to_payload()
        request_digest = canonical_digest(
            {
                "schema_version": "eod_provider_final_request_v1",
                "dataset_key": decision.dataset_key,
                "trading_day": decision.trading_day,
                "actual_contract": decision.actual_contract,
                "window_start": start,
                "window_end": end,
                "expected_bar_ends": expected_ends,
                "data_version": validated.data_version,
            }
        )
        return ProviderFinalSnapshot(
            strategy_input=json.loads(canonical_json(snapshot)),
            data_version=validated.data_version,
            request_digest=request_digest,
        )


@dataclass(frozen=True, slots=True)
class ProviderFinalSnapshot:
    strategy_input: dict[str, Any]
    data_version: str
    request_digest: str


def _dataset_key(raw: dict[str, Any]) -> DatasetKey:
    key = DatasetKey(
        provider=str(raw["provider"]),
        dataset_kind=DatasetKind(str(raw["dataset_kind"])),
        symbol=str(raw["symbol"]),
        contract_or_series=str(raw["contract_or_series"]),
        frequency=BarFrequency(str(raw["frequency"])),
        adjustment=str(raw["adjustment"]),
        schema_version=str(raw["schema_version"]),
    )
    if (
        key.provider != "rqdata"
        or key.dataset_kind is not DatasetKind.ACTUAL_DOMINANT
        or key.symbol != "jm"
        or key.contract_or_series.endswith(".MAIN")
        or key.frequency is not BarFrequency.M1
    ):
        raise ValueError("EOD_PROVIDER_FINAL_DATASET_INVALID")
    return key


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("EOD_PROVIDER_FINAL_DATETIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("EOD_PROVIDER_FINAL_DATETIME_INVALID")
    return parsed.astimezone(UTC)
