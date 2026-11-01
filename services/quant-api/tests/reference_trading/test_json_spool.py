from contextlib import ExitStack, nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import stat

import pytest

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from guiyi_quant.reference_trading import (
    BoundaryReason, RecordingMode, ReferenceBoundary, StreamIdentity,
)

from app.reference_trading.inputs import (
    HistoricalInputBar, HistoricalInputSnapshot, HistoricalInputSpool,
    MarketDataHistoricalInputReader,
    _insert_boundaries, _iter_insert_boundaries,
)
from app.reference_trading.json_spool import (
    JsonSpoolSequence, decode_product_bar, encode_product_bar,
)


def _stream():
    return StreamIdentity(
        "newow_trend", ("formula-v1",), "profile-v1", "reference-v1",
        "adaptation-v1", "RB", "1m", "actual_dominant",
        RecordingMode.HISTORICAL_REPLAY, None,
    )


def _bar(at, fingerprint):
    return HistoricalInputBar(
        at, at.date(), "RB2601", "owner", "calc", Decimal("100"),
        fingerprint, None,
    )


def test_spool_is_bounded_sequence_and_rejects_changed_bytes():
    at = datetime(2026, 10, 1, 8, tzinfo=UTC)
    product = ProductBar(NewowDailyBar(
        "rb", "RB2601", "owner", at.date(), at,
        Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"),
        10, 5, "canonical:rb", True, True,
    ), ProductFrequency.MINUTE, source_bar_sha256="a" * 64)
    spool = JsonSpoolSequence(encode=encode_product_bar, decode=decode_product_bar,
                              max_slice=1)
    try:
        spool.append(product)
        spool.append(product)
        spool.seal()
        assert len(spool) == 2
        assert spool[0] == product
        assert spool[-1] == product
        assert spool[:1] == (product,)
        with pytest.raises(ValueError, match="SLICE_EXCEEDED"):
            spool[:]
        path = spool._path / "bars.jsonl"
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        os.chmod(path, 0o600)
        with path.open("r+b") as file:
            file.seek(0)
            file.write(b"X")
        with pytest.raises(ValueError, match="CORRUPT"):
            spool[0]
    finally:
        spool.close()


def test_historical_spool_checks_identity_and_streaming_boundaries():
    stream = _stream()
    start = datetime(2026, 10, 1, 8, tzinfo=UTC)
    source = [_bar(start, "a" * 64),
              _bar(start + timedelta(minutes=2), "b" * 64)]
    boundary = ReferenceBoundary(
        stream, BoundaryReason.ROLLOVER, "RB2601", "owner", "calc",
        start + timedelta(minutes=1), start.date(),
    )
    expected = _insert_boundaries(source.copy(), (boundary,))
    actual = list(_iter_insert_boundaries(iter(source), (boundary,)))
    assert actual == expected
    spool = HistoricalInputSpool(stream)
    try:
        for item in actual:
            spool.append(item)
        spool.seal()
        snapshot = HistoricalInputSnapshot(
            stream, start.date(), start + timedelta(minutes=2), spool,
            {"reader": "test"}, "token", 1,
        )
        assert tuple(snapshot.bars) == tuple(expected)
        assert snapshot.bars[1].strategy_input is False
    finally:
        spool.close()


@pytest.mark.parametrize("fail", (False, True))
def test_nonpinned_planned_snapshot_closes_spool_on_success_and_failure(fail):
    stream = _stream()
    at = datetime(2026, 10, 1, 8, tzinfo=UTC)
    spool = HistoricalInputSpool(stream)
    spool.append(_bar(at, "a" * 64))
    spool.seal()
    path = spool._path
    snapshot = HistoricalInputSnapshot(
        stream, at.date(), at, spool, {"reader": "test"}, "token", 1,
    )
    reader = MarketDataHistoricalInputReader(newow_reader=None, subing_service=None)
    reader._read_uncached = lambda request: snapshot
    with pytest.raises(RuntimeError) if fail else nullcontext():
        with reader.planned_stream(object()) as observed:
            assert observed is snapshot
            if fail:
                raise RuntimeError("cancelled")
    assert not path.exists()


def test_retained_warm_streaming_sequence_hash_preserves_canonical_identity():
    from app.reference_trading.original_conflict_warm_seed import _hash
    from app.reference_trading.retained_warm_loader import _hash_rows

    rows = [("RB2601", "owner", "calc", "2026-10-01T08:00:00+00:00"),
            ("RB2601", "owner", "calc", "2026-10-01T09:00:00+00:00")]
    assert _hash_rows(iter(rows)) == _hash(rows)


def test_v5_gap_manifest_uses_semantics_not_opaque_source_witness():
    from dataclasses import replace
    from types import SimpleNamespace
    from app.reference_trading.packed_fingerprints import pack_fingerprints
    from app.reference_trading.planning import HistoricalStreamRequest
    from app.reference_trading.service import NewowHistoricalPayload
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import (
        DataInterruption, ProductFrequency, ProductStrategy,
    )
    from tests.newow.product_fixtures import ProductCases
    from tests.reference_trading.test_historical_integration import _newow_stream

    case = ProductCases().closed(frequency="60m")
    product = build_product_identity("rb", ProductStrategy.TREND, ProductFrequency.HOURLY)
    stream = _newow_stream(ProductStrategy.TREND, ProductFrequency.HOURLY)
    source_bar = case.bars[0]
    request = HistoricalStreamRequest(
        stream, source_bar.bar.trading_day, source_bar.bar.trading_day,
        source_bar.bar.bar_end,
    )
    item = HistoricalInputBar(
        source_bar.bar.bar_end, source_bar.bar.trading_day,
        source_bar.bar.physical_contract, source_bar.bar.segment_id,
        source_bar.calculation_segment_id or source_bar.bar.segment_id,
        source_bar.bar.close, "a" * 64,
        NewowHistoricalPayload(product, source_bar),
    )
    gap = DataInterruption(
        "rb", ProductFrequency.HOURLY, item.physical_contract,
        item.owner_segment_id, item.trading_day, item.bar_end,
        "canonical-byte-witness-A",
    )
    owner = SimpleNamespace(
        contract=item.physical_contract,
        start_trading_day=item.trading_day,
        end_trading_day=item.trading_day,
    )
    reader = object.__new__(MarketDataHistoricalInputReader)
    reader._compact_intraday_inputs = False
    newow = SimpleNamespace(historical_metadata_evidence=lambda **_: {
        "schema_version": "v1", "exchange": "SHFE", "symbol": "rb",
        "since": item.trading_day.isoformat(), "calendar": [], "sessions": [],
    })
    semantic = "b" * 64

    def finish(witness, semantic_hash):
        spool = HistoricalInputSpool(stream)
        spool.append(item)
        spool.seal()
        read = SimpleNamespace(
            owners=(owner,), boundaries=(), data_interruptions=(witness,),
            semantic_gap_hashes=(semantic_hash,), lifecycle_evidence=(),
            input_quality_policy=product.input_quality_policy,
            sources={ProductFrequency.HOURLY: SimpleNamespace(
                source_identity="canonical", input_policy_version="v1",
            )},
        )
        try:
            return reader._finish_newow_snapshot(
                request, SimpleNamespace(product="rb"), newow, read,
                ProductFrequency.HOURLY, spool,
                pack_fingerprints([item.fingerprint]), pack_fingerprints(["c" * 64]),
                product, production_historical=False,
            )
        except BaseException:
            spool.close()
            raise

    with ExitStack() as owned:
        first = finish(gap, semantic)
        owned.callback(first.close)
        witness_changed = finish(replace(gap, source_identity="canonical-byte-witness-B"), semantic)
        owned.callback(witness_changed.close)
        semantic_changed = finish(gap, "d" * 64)
        owned.callback(semantic_changed.close)
        assert first.dependency_manifest["data_interruptions"] == [semantic]
        assert first.source_token == witness_changed.source_token
        assert first.source_token != semantic_changed.source_token
