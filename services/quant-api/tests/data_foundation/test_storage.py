from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pyarrow.parquet as pq
import pytest

from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CANONICAL_COLUMNS, CanonicalMonthlyStore, PublishRequest, StorageError


def _bar(minute: int) -> CanonicalBar:
    value = Decimal("100")
    return CanonicalBar(datetime(2025, 1, 2, 1, minute, tzinfo=UTC), date(2025, 1, 2), value, value, value, value, 1, 10, 20)


def _request(bars: tuple[CanonicalBar, ...], *, expected: tuple[datetime, ...] | None = None) -> PublishRequest:
    return PublishRequest(DatasetKey("continuous", "jm", "MAIN", "1m"), 2025, 1, bars, expected or tuple(bar.bar_end for bar in bars))


def test_publish_writes_only_one_validated_month_parquet(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish(_request((_bar(1), _bar(2))))

    assert result.parquet_path.relative_to(tmp_path).as_posix() == "kind=continuous/symbol=jm/series=MAIN/frequency=1m/year=2025/month=01/part.parquet"
    assert result.row_count == 2
    assert pq.read_schema(result.parquet_path).names == list(CANONICAL_COLUMNS)
    assert store.read_month(result.dataset, 2025, 1) == (_bar(1), _bar(2))
    assert not tuple(tmp_path.rglob("manifest.json"))
    assert not tuple(tmp_path.rglob("*.bak"))


def test_publish_rejects_invalid_or_incomplete_month(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    with pytest.raises(StorageError, match="BAR_END_NOT_STRICTLY_INCREASING"):
        store.publish(_request((_bar(1), _bar(1))))
    with pytest.raises(StorageError, match="TARGET_WINDOW_INCOMPLETE"):
        store.publish(_request((_bar(1),), expected=(_bar(1).bar_end, _bar(2).bar_end)))


def test_publish_rejects_naive_expected_bar_end(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)

    with pytest.raises(StorageError, match="EXPECTED_BAR_END_INVALID"):
        store.publish(_request((_bar(1),), expected=(datetime(2025, 1, 2, 1, 1),)))

    with pytest.raises(StorageError, match="EXPECTED_BAR_END_INVALID"):
        store.publish(_request((_bar(1),), expected=(cast(datetime, "invalid"),)))
