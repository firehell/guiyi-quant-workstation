from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.htdy_activation import SCHEMA
from app.reference_trading.htdy_conflict_source import HtdyConflictSource
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.htdy import (
    HtdyBarFact,
    HtdyForwardState,
    MODEL_VERSION,
)
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
from tests.reference_trading.test_htdy_60m_forward import (
    Read,
    capture,
    identity,
    original,
)


def fixture():
    old = Read()
    current = Read()
    revised = replace(old.bars[5], close=Decimal("3501"))
    current.bars = (
        *old.bars[1:5],
        revised,
        *old.bars[6:],
        replace(old.bars[-1], bar_end=old.bars[-1].bar_end + timedelta(hours=1)),
    )
    cap = capture(current)
    event = original(current)
    cap = replace(
        cap,
        source_proof={
            **cap.source_proof,
            "inbox_delivery_id": "delivery",
            "journal_envelope_sha256": sha256(event.to_json().encode()).hexdigest(),
        },
    )
    stream = identity()
    state = HtdyForwardState(
        MODEL_VERSION,
        stream.observation_policy_version,
        tuple(
            HtdyBarFact(
                b.bar_end,
                b.trading_day,
                "RB2610",
                b.open,
                b.high,
                b.low,
                b.close,
                int(b.volume),
            )
            for b in old.bars
        ),
    )
    cp = AdapterCheckpoint(
        state,
        old.bars[-1].bar_end,
        "a" * 64,
        "RB2610",
        "owner",
        "calc",
        stream,
        ReferenceState.flat(stream, recording_start=old.bars[0].bar_end),
    )
    raw = adapter_checkpoint_to_json(cp, strategy_schema=SCHEMA)
    binding = {
        "stream_id": stream.stream_id,
        "revision_id": "r",
        "checkpoint": json.loads(raw),
        "checkpoint_sha256": sha256(raw.encode()).hexdigest(),
        "captures": [
            {
                "batch_id": "c",
                "kind": "capture",
                "stream_id": stream.stream_id,
                "revision_id": "r",
                "payload_hash": cap.capture_hash,
                "source_evidence": cap.evidence(),
            }
        ],
        "deliveries": [
            {
                "delivery_id": "delivery",
                "original": {
                    "delivery": {
                        "stream_id": stream.stream_id,
                        "revision_id": "r",
                        "generation": 1,
                    },
                    "input": {
                        "canonical_envelope": event.to_json(),
                        "journal_id": event.stream_id,
                    },
                },
            }
        ],
    }

    class Market:
        catalog = SimpleNamespace(
            contract_fact=lambda *_: SimpleNamespace(provider="rqdata"),
            partitions=lambda *_: (SimpleNamespace(frequency="x"),),
        )
        store = SimpleNamespace(
            read_publication_provenance=lambda p: {
                "version": 1,
                "input_source": "rqdata" if p.frequency == "1m" else "canonical_1m",
                "input_sha256": "b" * 64,
            }
        )

        def validate_actual_dominant_alert_window(self, **kw):
            assert len(kw["bars"]) == 32 and kw["bar_contracts"] == ("RB2610",) * 32

        def contract_source_evidence(self, **kw):
            self.catalog.partitions = lambda key, *_: (
                SimpleNamespace(frequency=key.frequency.value),
            )
            return {
                "contract": "RB2610",
                "frequency": kw["frequency"].value,
                "partitions": [{"content_sha256": "b" * 64, "quality_sha256": None}],
            }

        def query_page_inclusive(self, query):
            return SimpleNamespace(bars=(revised,))

    market = Market()
    authority = SimpleNamespace(
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *_: (cap.bar_end,),
    )
    return HtdyConflictSource(market, authority), stream, binding, cap


def test_exact_source_conflict_is_proved_without_rewriting_old_window():
    source, stream, binding, cap = fixture()
    before = deepcopy(binding)
    result = source(stream, binding, {})
    assert result["boundary_end"] == cap.bar_end.isoformat()
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["fields"] == {"close": {"old": "3500", "new": "3501"}}
    assert binding == before


@pytest.mark.parametrize(
    "mutation",
    [
        "capture_hash",
        "window_hash",
        "checkpoint_hash",
        "unknown_price",
        "identity",
        "source_kind",
    ],
)
def test_corrupt_or_unexplained_original_never_gets_source_permission(mutation):
    source, stream, binding, cap = fixture()
    wire = binding["captures"][0]["source_evidence"]["forward_capture_v1"]
    if mutation == "capture_hash":
        binding["captures"][0]["payload_hash"] = "0" * 64
    elif mutation == "window_hash":
        wire["source_proof"]["window_sha256"] = "0" * 64
    elif mutation == "checkpoint_hash":
        binding["checkpoint_sha256"] = "0" * 64
    elif mutation == "unknown_price":
        wire["input_payload"]["bars"][4]["close"] = "NaN"
    elif mutation == "identity":
        wire["input_payload"]["bar_contracts"][4] = "RB2701"
    else:
        wire["source_kind"] = "historical_replay"
    if mutation in {"unknown_price", "identity", "source_kind"}:
        wire["source_proof"]["window_sha256"] = sha256(
            json.dumps(
                wire["input_payload"]["bars"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        rebuilt = ForwardCapture(
            stream.stream_id,
            "r",
            wire["generation"],
            wire["source_key"],
            cap.bar_end,
            cap.observed_at,
            wire["source_kind"],
            wire["input_payload"],
            wire["source_proof"],
            wire["eligibility"],
        )
        wire["hash"] = rebuilt.capture_hash
        binding["captures"][0]["payload_hash"] = rebuilt.capture_hash
    with pytest.raises((ValueError, RuntimeError)):
        source(stream, binding, {})


def test_canonical_match_to_old_or_third_revision_stays_blocked():
    source, stream, binding, _ = fixture()
    source.market.query_page_inclusive = lambda _: SimpleNamespace(
        bars=(Read().bars[5],)
    )
    with pytest.raises(ValueError, match="HTDY_CONFLICT_CANONICAL_MISMATCH"):
        source(stream, binding, {})


def test_missing_session_or_owner_is_not_a_numeric_revision():
    source, stream, binding, _ = fixture()
    source.authority.owner_segments = lambda *_: ("other", "other")
    with pytest.raises(ValueError, match="HTDY_CONFLICT_OWNER_UNPROVEN"):
        source(stream, binding, {})


def test_missing_actual_endpoint_cannot_be_relabelled_source_conflict():
    source, stream, binding, _ = fixture()
    source.authority.expected_endpoints = lambda *_: ()
    with pytest.raises(ValueError, match="HTDY_CONFLICT_ENDPOINT_UNPROVEN"):
        source(stream, binding, {})


def test_non_rqdata_or_wrong_aggregation_provenance_is_rejected():
    source, stream, binding, _ = fixture()
    source.market.catalog.contract_fact = lambda *_: SimpleNamespace(provider="other")
    with pytest.raises(ValueError, match="HTDY_CONFLICT_PROVIDER_UNPROVEN"):
        source(stream, binding, {})


def test_wrong_minute_or_aggregation_provenance_stays_blocked():
    source, stream, binding, _ = fixture()
    source.market.store.read_publication_provenance = lambda _: {
        "version": 1,
        "input_source": "unverified",
        "input_sha256": "b" * 64,
    }
    with pytest.raises(ValueError, match="HTDY_CONFLICT_PROVENANCE_UNPROVEN"):
        source(stream, binding, {})


def test_corrupt_original_cannot_authorize_retirement_even_with_valid_capture_hash():
    source, stream, binding, _ = fixture()
    original = binding["deliveries"][0]["original"]["input"]
    original["canonical_envelope"] = original["canonical_envelope"].replace(
        "3500", "3502"
    )
    with pytest.raises(ValueError, match="HTDY_CONFLICT_ORIGINAL_UNPROVEN"):
        source(stream, binding, {})
