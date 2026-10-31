from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
import json

from app.market_data.domain import ResolvedContractSegment
from app.market_data.newow.product_reader import NewowProductReader
from app.reference_trading.packed_fingerprints import PackedFingerprintBuilder


def _reader(endpoint_counts, *, metadata=None):
    first = date(2026, 1, 5)
    owners = tuple(
        ResolvedContractSegment(
            f"RB26{index + 1:02d}",
            first + timedelta(days=index), first + timedelta(days=index),
        ) for index in range(len(endpoint_counts))
    )
    def windows(**kwargs):
        return (
            SimpleNamespace(start=datetime(2026, 1, 5, 1, tzinfo=UTC),
                            end=datetime(2026, 1, 5, 2, tzinfo=UTC)),
        )
    market = SimpleNamespace(
        actual_dominant_segments=lambda symbol, since, through: tuple(
            owner for owner in owners
            if owner.start_trading_day <= through and owner.end_trading_day >= since
        ),
        session_windows=windows,
        session_windows_overlapping_window=lambda **kwargs: tuple(
            (owner.start_trading_day, windows()) for owner in owners
        ),
        contract_lifecycle_start=lambda **kwargs: date(2025, 12, 1),
        expected_contract_replay_endpoints=lambda **kwargs: tuple(
            range(endpoint_counts[next(index for index, owner in enumerate(owners)
                                        if owner.contract == kwargs["contract"])])),
        historical_metadata_evidence=lambda **kwargs: metadata or {
            "schema_version": "historical_metadata_evidence_v1",
            "since": kwargs["since"].isoformat(),
            "through": kwargs["through"].isoformat(),
            "calendar": [], "sessions": [],
        },
    )
    reader = NewowProductReader(
        market, coverage=SimpleNamespace(product_start=lambda symbol: first,
                                         latest_complete_day=lambda products: owners[-1].end_trading_day),
        active_products=("rb",),
        now=lambda: datetime(2026, 2, 1, tzinfo=UTC),
    )
    return reader, owners


def _bound(reader, owners, *, fusion=False, frequency="60m"):
    return reader.historical_spool_bound(
        product="rb", frequency=frequency,
        since=owners[0].start_trading_day,
        through=owners[-1].end_trading_day,
        as_of=datetime(2026, 1, 6, 2, tzinfo=UTC),
        formula_versions=("formula-v1",),
        reference_model_version="reference-v1",
        fusion=fusion,
    )


def test_spooled_bound_counts_endpoints_plus_rollovers():
    reader, owners = _reader((3, 4))
    count, byte_bound = _bound(reader, owners)
    assert count == 8  # Seven physical endpoints plus one rollover.
    assert byte_bound >= 390 * count
    fusion_count, fusion_bytes = _bound(reader, owners, fusion=True)
    assert fusion_count == count
    assert fusion_bytes >= 457 * count


def test_spooled_bound_allows_weekly_owner_without_endpoint():
    reader, owners = _reader((0, 2))
    count, _ = _bound(reader, owners, frequency="1w")
    assert count == 3


def test_spooled_bound_counts_later_asof_owner_boundary():
    reader, owners = _reader((3, 4))
    count, _ = reader.historical_spool_bound(
        product="rb", frequency="60m",
        since=owners[0].start_trading_day,
        through=owners[0].end_trading_day,
        as_of=datetime(2026, 1, 6, 2, tzinfo=UTC),
        formula_versions=("formula-v1",),
        reference_model_version="reference-v1",
    )
    assert count == 4  # Three Bars plus the later mapped owner boundary.


def test_spooled_bound_includes_packed_wire_headers_for_one_endpoint():
    reader, owners = _reader((1,))
    wire_bytes = len(json.dumps(
        PackedFingerprintBuilder().finish(), sort_keys=True,
        separators=(",", ":"), ensure_ascii=True,
    ).encode())
    count, regular_bytes = _bound(reader, owners)
    assert count == 1
    assert regular_bytes - 390 * count >= 2 * wire_bytes
    _, fusion_bytes = _bound(reader, owners, fusion=True)
    assert fusion_bytes - 457 * count >= 3 * wire_bytes
