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
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity


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
    manifest = {"reader": "source_reader", "input_sha256": "source_hash"}
    if frequency in {"1d", "1w"}:
        manifest["input_fingerprints"] = [bar.fingerprint for bar in bars]
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
    assert (
        snapshot.dependency_manifest["input_sha256"]
        == sha256(_canonical(actual).encode()).hexdigest()
    )
    if frequency in {"1d", "1w"}:
        assert snapshot.dependency_manifest["input_fingerprints"] == actual
        assert (
            snapshot.dependency_manifest["source_input_fingerprints"]
            == manifest["input_fingerprints"]
        )
        assert snapshot.dependency_manifest["reader"] == "newow_fusion_saved_sources_v2"
    else:
        assert "input_fingerprints" not in snapshot.dependency_manifest
        assert snapshot.dependency_manifest["reader"] == "newow_fusion_saved_sources_v1"
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
