from __future__ import annotations

from datetime import UTC, date, datetime

from app.data_core.catalog import CanonicalMainContractMapping
from app.services.product_retirement_refresh import build_refresh_targets


def test_refresh_targets_cover_continuous_and_actual_dominant_direct_periods() -> None:
    targets = build_refresh_targets(
        products=("jm",),
        mappings=(
            CanonicalMainContractMapping(
                id=1,
                symbol="jm",
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="rqdata-rank1",
                created_at=None,
            ),
        ),
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert {
        (item.dataset_kind, item.contract_or_series, item.frequency) for item in targets
    } == {
        ("continuous", "JM.MAIN", "1m"),
        ("continuous", "JM.MAIN", "1d"),
        ("continuous", "JM.MAIN", "1w"),
        ("actual_dominant", "JM2609", "1m"),
        ("actual_dominant", "JM2609", "1d"),
        ("actual_dominant", "JM2609", "1w"),
    }
