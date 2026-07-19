from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.backtest.htdy_stage45_closeout import (
    BASELINE_GATE,
    BLOCKED_DATA_GATE,
    DATA_EQUIVALENT_GATE,
    build_baseline,
    compare_bar_rows,
    file_sha256,
    load_window_rows,
    packet_hash,
    verify_packet_hash,
    write_evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


FIELDS = (
    "datetime",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "turnover",
    "provider",
    "source",
    "data_role",
    "quality_status",
    "period",
    "symbol",
    "contract",
)


def _row(minute: int = 0, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "datetime": datetime(2026, 1, 2, 9, minute),
        "trading_day": date(2026, 1, 2),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "open_interest": 20.0,
        "turnover": 30.0,
        "provider": "rqdata",
        "source": "local_parquet",
        "data_role": "primary",
        "quality_status": "passed",
        "period": "15m",
        "symbol": "jm",
        "contract": "jm.MAIN",
    }
    row.update(overrides)
    return row


def test_compare_identical_rows_is_exact_and_hash_bound() -> None:
    result = compare_bar_rows([_row(), _row(15)], [_row(), _row(15)], fields=FIELDS)

    assert result["gate"] == DATA_EQUIVALENT_GATE
    assert result["comparison_result"] == "equivalent"
    assert result["row_count"] == 2
    assert result["difference_count"] == 0
    assert result["old_ordered_bar_hash"] == result["new_ordered_bar_hash"]
    assert verify_packet_hash(result)


@pytest.mark.parametrize("field,value", [("close", 101.5), ("source", "changed")])
def test_compare_blocks_single_field_difference(field: str, value: object) -> None:
    result = compare_bar_rows([_row()], [_row(**{field: value})], fields=FIELDS)

    assert result["gate"] == BLOCKED_DATA_GATE
    assert result["difference_count"] == 1
    assert result["difference_fields"] == {field: 1}
    assert result["first_difference"]["field"] == field


@pytest.mark.parametrize(
    ("old_rows", "new_rows", "reason"),
    [
        ([_row(), _row(15)], [_row()], "missing_in_new"),
        ([_row()], [_row(), _row(15)], "extra_in_new"),
    ],
)
def test_compare_blocks_missing_or_extra_bar(old_rows, new_rows, reason: str) -> None:
    result = compare_bar_rows(old_rows, new_rows, fields=FIELDS)

    assert result["gate"] == BLOCKED_DATA_GATE
    assert result["first_difference"]["reason"] == reason


def test_compare_blocks_duplicate_datetime() -> None:
    result = compare_bar_rows([_row(), _row()], [_row()], fields=FIELDS)

    assert result["gate"] == BLOCKED_DATA_GATE
    assert result["first_difference"]["reason"] == "duplicate_datetime_old"


def test_load_window_rows_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="asset is missing"):
        load_window_rows(
            tmp_path / "missing.parquet",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 3),
            fields=FIELDS,
            declared_sha256="0" * 64,
        )


def test_load_window_rows_rejects_hash_tamper(tmp_path: Path) -> None:
    source = tmp_path / "bars.parquet"
    pq.write_table(pa.Table.from_pylist([_row()]), source)

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        load_window_rows(
            source,
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 3),
            fields=FIELDS,
            declared_sha256="0" * 64,
        )


def test_load_window_rows_filters_inclusively_and_returns_identity(tmp_path: Path) -> None:
    source = tmp_path / "bars.parquet"
    pq.write_table(pa.Table.from_pylist([_row(), _row(15)]), source)
    digest = file_sha256(source)

    loaded = load_window_rows(
        source,
        start=datetime(2026, 1, 2, 9, 15),
        end=datetime(2026, 1, 2, 9, 15),
        fields=FIELDS,
        declared_sha256=digest,
    )

    assert loaded["actual_sha256"] == digest
    assert loaded["row_count"] == 1
    assert loaded["rows"][0]["datetime"] == datetime(2026, 1, 2, 9, 15)


def test_load_window_rows_does_not_infer_hive_partition_columns(tmp_path: Path) -> None:
    partition_dir = tmp_path / "provider=rqdata" / "period=15m"
    partition_dir.mkdir(parents=True)
    source = partition_dir / "bars.parquet"
    pq.write_table(pa.Table.from_pylist([_row()]), source)

    loaded = load_window_rows(
        source,
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 3),
        fields=FIELDS,
        declared_sha256=file_sha256(source),
    )

    assert loaded["rows"][0]["provider"] == "rqdata"


def test_packet_hash_verification_rejects_tamper() -> None:
    packet = {"gate": DATA_EQUIVALENT_GATE}
    packet["packet_hash"] = packet_hash(packet)
    assert verify_packet_hash(packet)
    packet["gate"] = BLOCKED_DATA_GATE
    assert not verify_packet_hash(packet)


def test_real_baseline_recomputes_frozen_file_hash_and_preserves_rejection() -> None:
    baseline = build_baseline(REPO_ROOT, source_commit="2ef3abba" + "0" * 32)

    assert baseline["gate"] == BASELINE_GATE
    assert baseline["research_outcome"] == "REJECTED_RESEARCH_CANDIDATE"
    assert baseline["protocol_hash"] == baseline["protocol_file_sha256"]
    assert verify_packet_hash(baseline)


def test_write_evidence_is_versioned_and_refuses_overwrite(tmp_path: Path) -> None:
    packet = {"gate": DATA_EQUIVALENT_GATE}
    packet["packet_hash"] = packet_hash(packet)

    write_evidence(tmp_path, stem="DATA_EQUIVALENCE", title="Data Equivalence", packet=packet)

    assert json.loads((tmp_path / "DATA_EQUIVALENCE.json").read_text())["packet_hash"] == packet["packet_hash"]
    assert DATA_EQUIVALENT_GATE in (tmp_path / "DATA_EQUIVALENCE.md").read_text()
    with pytest.raises(ValueError, match="already populated"):
        write_evidence(tmp_path, stem="DATA_EQUIVALENCE", title="Data Equivalence", packet=packet)
