from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.rqdata_ingest.actual_contract_bars_batch import (
    build_actual_contract_bars_batch_dry_run_payload,
    run_actual_contract_bars_batch,
)
from tests.test_actual_contract_bars_pilot import FakeBarsClient, _seed_reference_data, _session_factory


@pytest.fixture(name="session_factory")
def fixture_session_factory():
    return _session_factory()


def test_batch_dry_run_does_not_require_client() -> None:
    payload = build_actual_contract_bars_batch_dry_run_payload(
        products=["jm", "rb"],
        trade_date=date(2026, 7, 7),
        start_date=date(2026, 7, 6),
        end_date=date(2026, 7, 7),
        periods=("15m",),
        output_root=Path("/tmp/data"),
    )
    assert payload["mode"] == "dry-run"
    assert payload["product_count"] == 2
    assert payload["would_call_rqdata"] is False


def test_batch_write_reuses_pilot_for_single_product(session_factory, tmp_path: Path) -> None:
    factory = session_factory
    with factory() as session:
        _seed_reference_data(session)
        session.commit()
        result = run_actual_contract_bars_batch(
            session=session,
            client=FakeBarsClient(),
            output_root=tmp_path,
            products=["jm"],
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7),
            periods=("1m", "5m", "15m", "30m", "60m"),
            dry_run=False,
        )
        assert result["success_count"] == 1
        assert result["results"]["jm"]["actual_contract"] == "JM2609"
