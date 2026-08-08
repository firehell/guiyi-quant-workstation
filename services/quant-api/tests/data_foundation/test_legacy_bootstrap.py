from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.market_data.domain import DatasetKey
from app.market_data.legacy_bootstrap import LegacyBootstrapAdapter, LegacyBootstrapError


def _roots(tmp_path: Path):
    contract = tmp_path / "actual_contract_bars"
    continuous = tmp_path / "dominant_contract_bars"
    previous = tmp_path / "canonical"
    for root in (contract, continuous, previous):
        root.mkdir()
    return contract, continuous, previous


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_legacy_adapter_uses_one_best_allowlisted_candidate_and_normalizes(tmp_path) -> None:
    contract, continuous, previous = _roots(tmp_path)
    base = contract / "product=jm/contract=JM2509/frequency=1d"
    _write(base / "partial.parquet", [_row(2, 100)])
    _write(base / "complete.parquet", [_row(2, 100), _row(3, 101)])
    adapter = LegacyBootstrapAdapter(
        contract_root=contract,
        continuous_raw_root=continuous,
        previous_canonical_root=previous,
    )
    expected = (
        datetime(2025, 1, 2, 7, tzinfo=UTC),
        datetime(2025, 1, 3, 7, tzinfo=UTC),
    )

    batch = adapter.fetch(DatasetKey("contract", "jm", "JM2509", "1d"), expected)

    assert batch is not None
    assert tuple(bar.bar_end for bar in batch.bars) == expected
    assert batch.source_kind == "legacy_staging"
    assert len(batch.source_digest) == 64


def test_legacy_adapter_rejects_unapproved_or_symlink_root(tmp_path) -> None:
    contract, continuous, previous = _roots(tmp_path)
    with pytest.raises(LegacyBootstrapError, match="LEGACY_BOOTSTRAP_ROOT_INVALID"):
        LegacyBootstrapAdapter(
            contract_root=contract,
            continuous_raw_root=continuous,
            previous_canonical_root=previous,
            allowed_roots=(contract, continuous),
        )


def _row(day: int, close: int) -> dict:
    return {
        "date": datetime(2025, 1, day),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 10,
        "total_turnover": 1000,
        "open_interest": 20,
    }
