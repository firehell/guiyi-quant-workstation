from datetime import UTC, datetime

from types import SimpleNamespace

from app.reference_trading.inputs import (
    _newow_input_fingerprint,
    _newow_replay_fingerprints,
)


def test_reused_source_bar_has_distinct_calculation_input_identity() -> None:
    common = dict(
        source_bar_sha256="a" * 64,
        bar_end=datetime(2026, 6, 1, 7, tzinfo=UTC),
        physical_contract="BZ2607",
        owner_segment_id="owner-2607",
        quality_policy="strict",
    )
    first = _newow_input_fingerprint(**common, calculation_segment_id="calc-2607")
    reused = _newow_input_fingerprint(**common, calculation_segment_id="calc-2608")

    assert first != reused
    assert first == _newow_input_fingerprint(
        **common, calculation_segment_id="calc-2607"
    )


def test_replay_fingerprints_are_prefix_stable_when_a_bar_is_reused_later() -> None:
    at = datetime(2026, 6, 1, 7, tzinfo=UTC)

    def item(source: str, calculation: str):
        return SimpleNamespace(
            source_bar_sha256=source,
            calculation_segment_id=calculation,
            bar=SimpleNamespace(
                bar_end=at,
                physical_contract="BZ2607",
                segment_id="owner-2607",
            ),
        )

    bars = (
        item("a" * 64, "calc-2607"),
        item("a" * 64, "calc-2608"),
        item("b" * 64, "calc-2608"),
    )
    fingerprints = _newow_replay_fingerprints(bars, "strict")

    assert len(set(fingerprints)) == len(bars)
    assert _newow_replay_fingerprints(bars[:1], "strict") == fingerprints[:1]
    assert _newow_replay_fingerprints(bars[:2], "strict") == fingerprints[:2]


def test_pinned_input_is_reused_only_inside_explicit_maintenance_lease():
    from contextlib import contextmanager
    from app.reference_trading.inputs import MarketDataHistoricalInputReader
    from types import SimpleNamespace

    events = []

    @contextmanager
    def guard():
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    reader = MarketDataHistoricalInputReader(
        newow_reader=None,
        subing_service=None,
        read_guard=guard,
        pin_verified_inputs=True,
    )
    reads = []

    def read(request):
        reads.append(request)
        return SimpleNamespace(source_token=str(len(reads)))

    reader._read_uncached = read
    request = object()
    with reader.pin_stream(request):
        assert reader._read(request).source_token == "1"
        assert reader.revalidate(request, expected_source_token="1")
        assert reader._read(request).source_token == "1"
    assert events == ["lock", "unlock"]
    assert reader._read(request).source_token == "2"
    assert len(reads) == 2


def test_pinned_input_is_discarded_on_failure():
    from contextlib import nullcontext
    from app.reference_trading.inputs import MarketDataHistoricalInputReader
    from types import SimpleNamespace
    import pytest

    reader = MarketDataHistoricalInputReader(
        newow_reader=None,
        subing_service=None,
        read_guard=nullcontext,
        pin_verified_inputs=True,
    )
    calls = []
    reader._read_uncached = lambda request: (
        calls.append(request) or SimpleNamespace(source_token=str(len(calls)))
    )
    request = object()
    with pytest.raises(RuntimeError):
        with reader.pin_stream(request):
            assert reader._read(request).source_token == "1"
            raise RuntimeError("interrupted")
    assert reader._read(request).source_token == "2"


def test_verified_pin_shares_exact_plan_manifest_and_closes_one_snapshot():
    from contextlib import nullcontext
    from app.reference_trading.inputs import MarketDataHistoricalInputReader

    reader = MarketDataHistoricalInputReader(
        newow_reader=None, subing_service=None, read_guard=nullcontext,
        pin_verified_inputs=True,
    )
    expected = {"reader": "newow_product_reader_prefix_v5", "leaves": ["a" * 64]}
    fresh = dict(expected)
    closes = []
    snapshot = SimpleNamespace(
        source_token="frozen", dependency_manifest=fresh,
        close=lambda: closes.append("closed"),
    )
    reads = []
    reader._read_uncached = lambda request: reads.append(request) or snapshot
    request = object()
    with reader.pin_verified_stream(
        request, expected_manifest=expected, expected_source_token="frozen",
    ):
        assert reader.load_stream(request, expected_source_token="frozen") is snapshot
        assert snapshot.dependency_manifest is expected
        reader.release_snapshot(snapshot)
        assert not closes and reads == [request]
    assert closes == ["closed"]
    assert reader._pinned_snapshot is None


def test_verified_pin_rejects_token_or_manifest_drift_and_closes_fresh_input():
    from contextlib import nullcontext
    from app.reference_trading.inputs import MarketDataHistoricalInputReader
    import pytest

    reader = MarketDataHistoricalInputReader(
        newow_reader=None, subing_service=None, read_guard=nullcontext,
        pin_verified_inputs=True,
    )
    closes = []
    request = object()
    for source_token, manifest in (("changed", {"bar": 1}), ("frozen", {"bar": 2})):
        snapshot = SimpleNamespace(
            source_token=source_token, dependency_manifest=manifest,
            close=lambda: closes.append("closed"),
        )
        reader._read_uncached = lambda _request: snapshot
        with pytest.raises(ValueError, match="^SOURCE_CHANGED$"):
            with reader.pin_verified_stream(
                request, expected_manifest={"bar": 1}, expected_source_token="frozen",
            ):
                pytest.fail("unverified snapshot became visible")
        assert reader._pinned_snapshot is None
        assert reader._pinned_request is None
    assert closes == ["closed", "closed"]


def test_verified_pin_rejects_python_equal_but_canonically_distinct_manifest():
    from contextlib import nullcontext
    import pytest
    from app.reference_trading.inputs import (
        MarketDataHistoricalInputReader, _stream_manifest_sha256,
    )

    reader = MarketDataHistoricalInputReader(
        newow_reader=None, subing_service=None, read_guard=nullcontext,
        pin_verified_inputs=True,
    )
    fresh = {"input_count": 1}
    fresh_token = _stream_manifest_sha256(fresh)[0]
    closed = []
    for replacement in (1.0, True):
        snapshot = SimpleNamespace(
            source_token=fresh_token, dependency_manifest=fresh,
            close=lambda: closed.append(True),
        )
        reader._read_uncached = lambda _request: snapshot
        planned = {"input_count": replacement}
        assert fresh == planned
        assert _stream_manifest_sha256(fresh) != _stream_manifest_sha256(planned)
        with pytest.raises(ValueError, match="^SOURCE_CHANGED$"):
            with reader.pin_verified_stream(
                object(), expected_manifest=planned,
                expected_source_token=fresh_token,
            ):
                pytest.fail("different canonical manifest became pinned")
        assert reader._pinned_snapshot is None
        assert reader._pinned_request is None
    assert closed == [True, True]
