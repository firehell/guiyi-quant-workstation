from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.services.provider_readiness import (
    ProviderReadinessError,
    collect_provider_readiness,
    provider_frame_identity,
    require_provider_readiness,
    wait_for_provider_readiness,
)


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.requested_categories = None

    def market_data_readiness(self, *, expected_date, categories):
        assert expected_date == date(2026, 7, 20)
        self.requested_categories = categories
        return {category: self.payload[category] for category in categories}


def _row(category: str, *, latest_date: str = "2026-07-20", ready: bool = True) -> dict:
    return {
        "market": "cn",
        "category": category,
        "latest_date": latest_date,
        "update_time": "2026-07-20T16:19:00",
        "expected_date": "2026-07-20",
        "ready": ready,
    }


def test_s603_requires_minbar_and_daybar_ready() -> None:
    client = FakeClient(
        {
            "future_minbar": _row("future_minbar"),
            "future_daybar": _row("future_daybar", latest_date="2026-07-17", ready=False),
        }
    )

    with pytest.raises(ProviderReadinessError, match="provider_data_pending:future_daybar"):
        require_provider_readiness(
            client,
            expected_date=date(2026, 7, 20),
            categories=("future_minbar", "future_daybar"),
        )


def test_t4_can_require_minbar_without_waiting_for_daybar() -> None:
    client = FakeClient(
        {
            "future_minbar": _row("future_minbar"),
            "future_daybar": _row("future_daybar", latest_date="2026-07-17", ready=False),
        }
    )

    result = collect_provider_readiness(
        client,
        expected_date=date(2026, 7, 20),
        observed_categories=("future_minbar", "future_daybar"),
        required_categories=("future_minbar",),
    )

    assert result["future_minbar"]["ready"] is True
    assert result["future_daybar"]["ready"] is False
    assert client.requested_categories == ("future_minbar", "future_daybar")


def test_ready_true_with_stale_latest_date_fails_closed() -> None:
    client = FakeClient({"future_minbar": _row("future_minbar", latest_date="2026-07-17", ready=True)})

    with pytest.raises(ProviderReadinessError, match="provider_data_stale:future_minbar"):
        require_provider_readiness(
            client,
            expected_date=date(2026, 7, 20),
            categories=("future_minbar",),
        )


def test_provider_frame_identity_is_order_stable_and_target_bound() -> None:
    frame = pd.DataFrame(
        [
            {"datetime": "2026-07-20 09:02:00", "trading_date": "2026-07-20", "open": 2, "high": 3, "low": 1, "close": 2, "volume": 20},
            {"datetime": "2026-07-20 09:01:00", "trading_date": "2026-07-20", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 10},
        ]
    )

    first = provider_frame_identity(frame, target=date(2026, 7, 20), expected_row_count=2)
    second = provider_frame_identity(frame.iloc[::-1], target=date(2026, 7, 20), expected_row_count=2)

    assert first == second
    assert first["row_count"] == 2
    assert len(first["sha256"]) == 64


def test_provider_frame_identity_rejects_incomplete_target() -> None:
    frame = pd.DataFrame(
        [{"datetime": "2026-07-20 09:01:00", "trading_date": "2026-07-20", "close": 1}]
    )

    with pytest.raises(ProviderReadinessError, match="provider_target_row_count_mismatch:1!=2"):
        provider_frame_identity(frame, target=date(2026, 7, 20), expected_row_count=2)


def test_wait_for_provider_readiness_retries_pending_until_ready() -> None:
    class SequenceClient(FakeClient):
        def __init__(self):
            super().__init__({})
            self.calls = 0

        def market_data_readiness(self, *, expected_date, categories):
            self.calls += 1
            ready = self.calls > 1
            return {category: _row(category, latest_date="2026-07-20" if ready else "2026-07-17", ready=ready) for category in categories}

    client = SequenceClient()
    sleeps: list[float] = []

    result = wait_for_provider_readiness(
        client,
        expected_date=date(2026, 7, 20),
        observed_categories=("future_minbar",),
        required_categories=("future_minbar",),
        timeout_seconds=60,
        poll_seconds=1,
        sleep=sleeps.append,
    )

    assert result["future_minbar"]["ready"] is True
    assert client.calls == 2
    assert sleeps == [1]
