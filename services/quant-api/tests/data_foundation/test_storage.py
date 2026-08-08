from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json

import pyarrow.parquet as pq
import pytest

from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import (
    CANONICAL_COLUMNS,
    CanonicalMonthlyStore,
    PublishRequest,
    SourceMetadata,
    StorageError,
)


def _bar(minute: int, *, close: str = "100", volume: str = "1") -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        trading_day=date(2025, 1, 2),
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=volume,
        turnover="10",
        open_interest="20",
    )


def _request(
    bars: tuple[CanonicalBar, ...],
    *,
    expected: tuple[datetime, ...] | None = None,
    source: SourceMetadata | None = None,
) -> PublishRequest:
    return PublishRequest(
        dataset=DatasetKey(
            kind="continuous",
            symbol="jm",
            series_or_contract="MAIN",
            frequency="1m",
        ),
        year=2025,
        month=1,
        bars=bars,
        expected_bar_ends=expected or tuple(bar.bar_end for bar in bars),
        source=source or SourceMetadata(source_kind="rqdata", source_digest="a" * 64),
    )


def test_publish_writes_minimal_month_partition_and_manifest(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    bars = (_bar(1), _bar(2), _bar(3))

    result = store.publish(_request(bars))

    assert result.parquet_path.relative_to(tmp_path).as_posix() == (
        "kind=continuous/symbol=jm/series=MAIN/frequency=1m/"
        "year=2025/month=01/part.parquet"
    )
    assert pq.read_schema(result.parquet_path).names == list(CANONICAL_COLUMNS)
    assert store.read_month(result.dataset, 2025, 1) == bars
    payload = json.loads(result.manifest_path.read_text())
    assert payload["dataset_key"] == {
        "kind": "continuous",
        "symbol": "jm",
        "series_or_contract": "MAIN",
        "frequency": "1m",
    }
    assert payload["row_count"] == 3
    assert payload["parquet_checksum"] == result.checksum
    assert payload["source_digest"] == "a" * 64


def test_publish_rejects_duplicate_unsorted_and_coverage_holes(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    first = _bar(1)
    second = _bar(2)

    with pytest.raises(StorageError, match="BAR_END_NOT_STRICTLY_INCREASING"):
        store.publish(_request((first, first)))
    with pytest.raises(StorageError, match="BAR_END_NOT_STRICTLY_INCREASING"):
        store.publish(_request((second, first)))
    with pytest.raises(StorageError, match="TARGET_WINDOW_INCOMPLETE"):
        store.publish(
            _request(
                (first,),
                expected=(first.bar_end, second.bar_end),
            )
        )


def test_publish_rejects_wrong_month_and_session_boundary(tmp_path) -> None:
    wrong_month = CanonicalBar(
        **{
            **_bar(1).as_record(),
            "bar_end": datetime(2025, 2, 1, 1, 1, tzinfo=UTC),
            "trading_day": date(2025, 2, 1),
        }
    )
    with pytest.raises(StorageError, match="PARTITION_MONTH_MISMATCH"):
        CanonicalMonthlyStore(tmp_path).publish(_request((wrong_month,)))

    store = CanonicalMonthlyStore(tmp_path, boundary_validator=lambda _key, bar: bar.bar_end.minute != 2)
    with pytest.raises(StorageError, match="SESSION_BOUNDARY_INVALID"):
        store.publish(_request((_bar(1), _bar(2))))


def test_derived_manifest_requires_source_and_session_digests(tmp_path) -> None:
    dataset = DatasetKey(
        kind="continuous",
        symbol="jm",
        series_or_contract="MAIN",
        frequency="5m",
    )
    request = PublishRequest(
        dataset=dataset,
        year=2025,
        month=1,
        bars=(_bar(1),),
        expected_bar_ends=(_bar(1).bar_end,),
        source=SourceMetadata(
            source_kind="derived_1m",
            source_digest="b" * 64,
            source_1m_digests=("c" * 64,),
            session_digest="d" * 64,
        ),
    )

    result = CanonicalMonthlyStore(tmp_path).publish(request)
    payload = json.loads(result.manifest_path.read_text())

    assert payload["source_1m_digests"] == ["c" * 64]
    assert payload["session_digest"] == "d" * 64


def test_failed_replace_preserves_last_valid_partition(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    original = store.publish(_request((_bar(1),)))
    original_bytes = original.parquet_path.read_bytes()

    def fail_before_replace(stage: str) -> None:
        if stage == "before_replace":
            raise RuntimeError("injected")

    failing = CanonicalMonthlyStore(tmp_path, fault_hook=fail_before_replace)
    with pytest.raises(StorageError, match="ATOMIC_PUBLISH_FAILED"):
        failing.publish(_request((_bar(1), _bar(2))))

    assert original.parquet_path.read_bytes() == original_bytes
    assert store.read_month(original.dataset, 2025, 1) == (_bar(1),)
    assert not tuple(tmp_path.rglob("*.tmp"))


def test_reader_rejects_checksum_or_row_count_drift(tmp_path) -> None:
    store = CanonicalMonthlyStore(tmp_path)
    result = store.publish(_request((_bar(1), _bar(2))))
    manifest = json.loads(result.manifest_path.read_text())
    manifest["row_count"] = 3
    result.manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(StorageError, match="PHYSICAL_CONSISTENCY_INVALID"):
        store.read_month(result.dataset, 2025, 1)
