from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.reference_trading.inputs import (
    HistoricalInputBar,
    HistoricalInputSnapshot,
    MarketDataHistoricalInputReader,
    _canonical,
)
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.packed_fingerprints import (
    PackedFingerprints, pack_fingerprints, packed_fingerprints_sha256,
)
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity


def test_saved_fusion_sources_rejects_partial_v5_base_before_action_read(monkeypatch):
    from datetime import UTC, date, datetime, timedelta
    from app.reference_trading.newow_fusion import SavedFusionSources
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

    cutoff = datetime(2026, 9, 2, 7, tzinfo=UTC)
    completed = cutoff - timedelta(seconds=1)
    request = SimpleNamespace(
        identity=build_fusion_stream_identity("rb", "1d"),
        since=date(2026, 9, 1), through=date(2026, 9, 2), as_of=cutoff,
    )
    manifest = {
        "reader": "newow_product_reader_prefix_v5",
        "input_fingerprints": pack_fingerprints(("a" * 64, "b" * 64)),
        "input_count": 2,
    }

    class Query:
        def streams(self, **_kwargs):
            return [{"stream_id": "trend", "active_revision_id": "rev", "latest_seq": 2}]

        def summary(self, *_args, **_kwargs):
            assert _kwargs["cutoff"] == completed
            return {"revision_id": "rev", "seq": 2, "snapshot": "snapshot"}

        def historical_actions(self, *_args, **_kwargs):
            raise AssertionError("partial base actions must not be read")

    loader = SavedFusionSources.__new__(SavedFusionSources)
    loader._query = Query()
    loader._persisted = SimpleNamespace(
        _factory=lambda: None,
        _manifest=lambda *_args: (
            build_product_identity("rb", ProductStrategy.TREND, ProductFrequency.DAILY),
            manifest,
        ),
    )
    loader._check_cancelled = None
    monkeypatch.setattr(
        "app.reference_trading.page_material_query.select_page_material",
        lambda *_args, **_kwargs: (
            None if _kwargs["cutoff"] == completed else pytest.fail("wrong cutoff")
        ),
    )
    with pytest.raises(ValueError, match="REFERENCE_FUSION_SOURCE_NOT_READY"):
        loader(request, manifest, source_integrity={"fresh": "proof"},
            target_completed_through=completed,
            target_trading_day=date(2026, 9, 2))


@pytest.mark.parametrize('reader,fail_actions,expected_enters', (
    ('newow_product_reader_prefix_v5', False, 2),
    ('newow_product_reader_prefix_v5', True, 1),
    ('newow_product_reader_prefix_v4', False, 0),
))
def test_saved_fusion_sources_scopes_each_v5_source_and_cleans_failure(
    monkeypatch, reader, fail_actions, expected_enters,
):
    from contextlib import contextmanager
    from datetime import UTC, date, datetime, timedelta
    from app.reference_trading.newow_fusion import SavedFusionSources
    from app.reference_trading.contracts import manifest_sha256
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

    cutoff = datetime(2026, 9, 2, 7, tzinfo=UTC)
    completed = cutoff - timedelta(seconds=1)
    request = SimpleNamespace(
        identity=build_fusion_stream_identity('rb', '60m'),
        since=date(2026, 9, 1), through=date(2026, 9, 2), as_of=cutoff,
    )
    source_integrity = {'fresh': 'proof'}
    manifests = {}
    for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION):
        manifests[strategy.value] = {
            'reader': reader, 'query_since': request.since.isoformat(),
            'quality_policy': 'halt', 'input_count': 1,
            'input_fingerprints': (pack_fingerprints(('a' * 64,))
                                   if reader.endswith('_v5') else ['a' * 64]),
        }
    active = []
    enters = []

    @contextmanager
    def scope(manifest, digest):
        assert not active
        assert digest == manifest_sha256(manifest)
        active.append(manifest)
        enters.append(manifest)
        try:
            yield
        finally:
            assert active == [manifest]
            active.clear()

    monkeypatch.setattr('app.reference_trading.manifest_storage.verified_manifest_scope', scope)
    monkeypatch.setattr('app.reference_trading.page_material_storage.validate_input_integrity',
                        lambda *_args, **_kwargs: None)

    class Manifest(dict):
        input_integrity = {'source_integrity': source_integrity}

    class Material:
        cutoff = completed
        through = date(2026, 9, 2)
        seq = 2
        revision_id = 'rev'
        field = {'binding': {'end_input_index': 1}}

        def envelope(self, *_args):
            assert active
            return {}

    def select_material(*_args, **_kwargs):
        assert active
        return Material()

    monkeypatch.setattr('app.reference_trading.page_material_query.select_page_material',
                        select_material)

    class Query:
        def streams(self, *, strategy, **_kwargs):
            assert bool(active) == reader.endswith('_v5')
            return [{'stream_id': strategy.removeprefix('newow_')}]

        def summary(self, *_args, **_kwargs):
            assert bool(active) == reader.endswith('_v5')
            return {'revision_id': 'rev', 'seq': 2, 'snapshot': 'snapshot'}

        def historical_actions(self, *_args, **_kwargs):
            assert bool(active) == reader.endswith('_v5')
            if fail_actions:
                raise ValueError('SOURCE_ACTION_FAILED')
            if False:
                yield None

    def load_manifest(stream_id, *_args):
        assert bool(active) == reader.endswith('_v5')
        strategy = ProductStrategy(stream_id.removeprefix('newow_'))
        return (build_product_identity('rb', strategy, ProductFrequency.HOURLY),
                Manifest(manifests[strategy.value]))

    loader = SavedFusionSources.__new__(SavedFusionSources)
    loader._query = Query()
    loader._persisted = SimpleNamespace(_factory=lambda: None,
                                        _manifest=load_manifest)
    loader._check_cancelled = None
    if fail_actions:
        with pytest.raises(ValueError, match='SOURCE_ACTION_FAILED'):
            loader(request, manifests['trend'], source_manifests=manifests,
                   source_integrity=source_integrity,
                   target_completed_through=completed,
                   target_trading_day=date(2026, 9, 2))
    else:
        actions, dependencies = loader(
            request, manifests['trend'], source_manifests=manifests,
            source_integrity=source_integrity,
            target_completed_through=completed,
            target_trading_day=date(2026, 9, 2),
        )
        assert list(actions.items()) == [] and len(dependencies) == 2
        actions.close()
    assert not active
    assert len(enters) == expected_enters


@pytest.mark.parametrize("frequency", ("1d", "1w", "60m"))
def test_fusion_manifest_binds_transformed_inputs_and_preserves_source_lineage(
    frequency,
):
    from newow.product_fixtures import ProductCases

    case = ProductCases().closed(frequency=frequency)
    stream = build_fusion_stream_identity("rb", frequency)
    bars = tuple(
        HistoricalInputBar(
            bar.bar.bar_end,
            bar.bar.trading_day,
            bar.bar.physical_contract,
            bar.bar.segment_id,
            bar.calculation_segment_id,
            bar.bar.close,
            str(index + 1) * 64,
            SimpleNamespace(bar=bar),
        )
        for index, bar in enumerate(case.bars)
    )
    manifest = {
        "reader": "newow_product_reader_prefix_v5",
        "input_fingerprints": pack_fingerprints(bar.fingerprint for bar in bars),
    }
    shadow = HistoricalInputSnapshot(
        stream,
        bars[0].trading_day,
        bars[-1].bar_end,
        bars,
        manifest,
        "source_token",
        1024,
    )
    reader = object.__new__(MarketDataHistoricalInputReader)
    reader._compact_intraday_inputs = True
    reader._read_newow = lambda request: replace(shadow, stream=request.identity)
    source_actions = {
        (
            bars[0].bar_end,
            bars[0].physical_contract,
            bars[0].owner_segment_id,
            bars[0].calculation_segment_id,
        ): (case.entry,)
    }
    reader._fusion_sources = lambda *args, **kwargs: (source_actions, [])
    request = HistoricalStreamRequest(
        stream, bars[0].trading_day, bars[-1].trading_day, case.as_of
    )

    snapshot = reader._read_fusion(request)
    actual = [bar.fingerprint for bar in snapshot.bars]
    assert actual != [bar.fingerprint for bar in bars]
    assert (snapshot.dependency_manifest["input_sha256"]
            == packed_fingerprints_sha256(snapshot.dependency_manifest["input_fingerprints"]))
    assert list(PackedFingerprints(snapshot.dependency_manifest["input_fingerprints"])) == actual
    assert snapshot.dependency_manifest["source_input_fingerprints"] == manifest["input_fingerprints"]
    assert snapshot.dependency_manifest["reader"] == "newow_fusion_saved_sources_v3"
    assert shadow.dependency_manifest == manifest


@pytest.mark.parametrize("tamper", (None, "source", "execution", "reader"))
def test_persisted_fusion_v2_page_checks_both_execution_and_source_sequences(
    monkeypatch, tamper
):
    from datetime import date, datetime, UTC
    from app.reference_trading.contracts import manifest_sha256
    from app.reference_trading.newow_fusion import PersistedFusionComparison
    from app.reference_trading.query import QueryConflict, _encode
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductStrategy, ProductFrequency
    from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION

    identity = build_fusion_stream_identity("rb", "1d")
    since, through = date(2026, 9, 1), date(2026, 9, 2)
    cutoff = datetime(2026, 9, 2, 8, tzinfo=UTC)
    base_identity = build_product_identity(
        "rb", ProductStrategy.TREND, ProductFrequency.DAILY
    )
    source = {
        "reader": "newow_product_reader_v2",
        "input_fingerprints": ["source1", "source2"],
        "calendar_session_effective_fingerprints": ["calendar"],
        "formula_versions": list(base_identity.formula_versions),
        "reference_model_version": REFERENCE_MODEL_VERSION,
    }
    base_manifest = {"base": "proven"}
    dependencies = [
        {
            "stream_id": name,
            "revision_id": "rev",
            "seq": 2,
            "dependency_digest": manifest_sha256(base_manifest),
        }
        for name in ("newow_trend", "newow_oscillation")
    ]
    actual = ["fusion1", "fusion2"]
    manifest = {
        **source,
        "reader": "newow_fusion_saved_sources_v2",
        "source_reader": source["reader"],
        "source_input_fingerprints": list(source["input_fingerprints"]),
        "input_fingerprints": list(actual),
        "input_count": 2,
        "input_sha256": sha256(_canonical(actual).encode()).hexdigest(),
        "query_since": since.isoformat(),
        "query_through": through.isoformat(),
        "query_as_of": cutoff.isoformat(),
        "source_dependencies": dependencies,
        "formula_versions": list(identity.formula_versions),
    }
    if tamper == "source":
        manifest["source_input_fingerprints"][0] = "wrong-source"
    if tamper == "execution":
        manifest["input_fingerprints"][0] = "wrong-execution"
    if tamper == "reader":
        manifest["reader"] = "unknown"

    class Query:
        def streams(self, *, strategy, **kwargs):
            return [
                {
                    "stream_id": strategy,
                    "active_revision_id": "rev",
                    "latest_seq": 2,
                    "reference_model_version": REFERENCE_MODEL_VERSION,
                }
            ]

        def summary(self, stream_id, **kwargs):
            return {
                "revision_id": "rev",
                "seq": 2,
                "closed_count": 0,
                "open_count": 0,
                "interrupted_count": 0,
                "sum_return_percentage_points": "0",
                "snapshot": _encode({"kind": "snapshot", "since": since.isoformat()}),
            }

        def trades(self, *args, **kwargs):
            return {"items": [], "next_cursor": None}

        def presentation_facts(self, *args, **kwargs):
            return {"action": []}

        def complete_trades(self, *args, **kwargs):
            return []

    comparison = object.__new__(PersistedFusionComparison)
    comparison._query = Query()
    comparison._persisted = SimpleNamespace(
        _manifest=lambda sid, *args: (
            identity,
            manifest if sid == "newow_dual_fusion" else base_manifest,
        )
    )
    monkeypatch.setattr(
        MarketDataHistoricalInputReader,
        "plan_stream",
        lambda *args: SimpleNamespace(
            dependency_manifest=source,
            bars=[
                SimpleNamespace(
                    strategy_input=True,
                    physical_contract="RB2610",
                    owner_segment_id="owner",
                )
            ],
        ),
    )
    kwargs = dict(
        product="rb",
        frequency="1d",
        since=since,
        through=through,
        cutoff=cutoff,
        reader=object(),
    )
    if tamper:
        with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
            comparison.comparison(**kwargs)
    else:
        result = comparison.comparison(**kwargs)
        assert result["page_parity"] is True and result["executable"] is False
        assert [group["model"] for group in result["groups"]] == [
            "trend",
            "oscillation",
            "fusion",
        ]


@pytest.mark.parametrize("frequency", ("1m", "5m", "15m", "30m", "60m", "1d", "1w"))
def test_full_semantic_fusion_sources_keep_each_strategys_boundary_identity(frequency):
    """Full v4 proofs contain stream-boundary hashes even on minute periods.

    Shared market lineage must agree, but an oscillator's boundary fingerprint
    is checked against its own replay rather than a trend replay fingerprint.
    """
    from datetime import UTC, date, datetime
    from decimal import Decimal
    from app.reference_trading.service import NewowHistoricalPayload
    from app.reference_trading.newow_fusion import fusion_input_policy
    from guiyi_quant.newow.models import NewowDailyBar
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency, ProductStrategy
    at = datetime(2026, 10, 30, 7, tzinfo=UTC)
    day = date(2026, 10, 30)
    stream = build_fusion_stream_identity("rb", frequency)
    calls = []
    reader = object.__new__(MarketDataHistoricalInputReader)
    reader._compact_intraday_inputs = True
    def snapshot(request):
        strategy = request.identity.strategy_code.removeprefix('newow_')
        calls.append(strategy)
        fingerprint = ('a' if strategy == 'trend' else 'b') * 64
        product_identity = build_product_identity(
            'rb', ProductStrategy(strategy), ProductFrequency(frequency),
            input_quality_policy=fusion_input_policy(stream),
        )
        product_bar = ProductBar(NewowDailyBar(
            'rb', 'RB2701', 'owner', day, at,
            Decimal('3500'), Decimal('3500'), Decimal('3500'), Decimal('3500'),
            1, 1, 'canonical:rb', True, True,
        ), ProductFrequency(frequency), calculation_segment_id='calc',
            source_bar_sha256='c' * 64)
        bar = HistoricalInputBar(at, day, 'RB2701', 'owner', 'calc', Decimal('3500'),
            fingerprint, NewowHistoricalPayload(product_identity, product_bar, True))
        manifest = {'reader': 'newow_product_reader_prefix_v5',
            'input_fingerprints': pack_fingerprints([fingerprint]),
            'rank1': [['RB2701', '2026-10-01', '2026-10-30']],
            'calendar_session_effective_fingerprints': pack_fingerprints(['c' * 64]),
            'quality_policy': 'fixed'}
        return HistoricalInputSnapshot(request.identity, day, at, (bar,), manifest,
            'token-' + strategy, 1024)
    reader._read_newow = snapshot
    def sources(request, market_manifest, *, source_manifests, source_integrity,
                target_completed_through, target_trading_day):
        assert source_integrity is None
        assert target_completed_through == at and target_trading_day == day
        assert set(source_manifests) == {'trend', 'oscillation'}
        assert list(PackedFingerprints(source_manifests['trend']['input_fingerprints'])) == ['a' * 64]
        assert list(PackedFingerprints(source_manifests['oscillation']['input_fingerprints'])) == ['b' * 64]
        assert source_manifests['trend']['rank1'] == source_manifests['oscillation']['rank1']
        return {}, []
    reader._fusion_sources = sources
    result = reader._read_fusion(HistoricalStreamRequest(stream, day, day, at))
    assert calls == ['trend', 'oscillation']
    assert list(PackedFingerprints(result.dependency_manifest['source_input_fingerprints'])) == ['a' * 64]
    result.close()
