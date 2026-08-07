from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.data_core.contracts import BarQuery, DatasetKind
from app.services.core_cli import verify_active_dataset


def test_verify_active_dataset_delegates_to_facade_and_returns_no_write_contract() -> None:
    observed: dict[str, object] = {}

    class Facade:
        def __init__(self, session) -> None:
            observed["session"] = session

        def get_bars(self, request: BarQuery):
            observed["request"] = request
            return SimpleNamespace(
                bars=(
                    SimpleNamespace(
                        symbol="jm",
                        contract_or_series="JM.MAIN",
                        bar_end=datetime(2026, 7, 29, 15, tzinfo=UTC),
                        trading_day=datetime(2026, 7, 29).date(),
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                        volume=1,
                        turnover=None,
                        open_interest=None,
                        frequency=request.frequency,
                        provider="rqdata",
                    ),
                )
            )

    payload = verify_active_dataset(
        object(),
        symbol="jm",
        contract="jm.MAIN",
        period="15m",
        start=datetime(2026, 7, 29, tzinfo=UTC),
        end=datetime(2026, 7, 29, 23, 59, 59, tzinfo=UTC),
        limit=5000,
        service_factory=Facade,
        gap_lister=lambda _key: [],
    )

    request = observed["request"]
    assert isinstance(request, BarQuery)
    assert request.dataset_kind is DatasetKind.CONTINUOUS
    assert request.symbol == "jm"
    assert request.contract_or_series == "JM.MAIN"
    assert payload["status"] == "passed"
    assert payload["readonly"] is True
    assert payload["effects"] == {
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
    }
    assert payload["result"]["response_bar_count"] == 1
    assert payload["result"]["selection_mode"] == "market_data_service_bar_query"
    assert payload["result"]["descriptor"]["dataset_kind"] == "continuous"
