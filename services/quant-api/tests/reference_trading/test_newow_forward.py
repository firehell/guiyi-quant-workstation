from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json

import pytest

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.newow_forward import evaluate_newow_capture
from guiyi_quant.reference_trading import (
    ActionKind, RecordingMode, ReferenceAction, ReferenceState, StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.newow.product_adapters import replay_step, seed_replay_state


def _case():
    from newow.product_fixtures import ProductCases

    return ProductCases().primitive_input("trend", "1d")


def _stream(case):
    return StreamIdentity(
        "newow_trend", case.identity.formula_versions, case.identity.profile_id,
        "newow_reference_v3", "newow_futures_v1", case.identity.product,
        "1d", "actual_dominant", RecordingMode.FORWARD_OBSERVATION,
        "completed_canonical_v1",
    )


def _capture(stream, bar, *, observed=None, generation=1):
    wire = {
        "bar_end": bar.bar.bar_end.isoformat(),
        "trading_day": bar.bar.trading_day.isoformat(),
        "open": str(bar.bar.open), "high": str(bar.bar.high),
        "low": str(bar.bar.low), "close": str(bar.bar.close),
        "volume": str(bar.bar.volume),
        "open_interest": None if bar.bar.open_interest is None else str(bar.bar.open_interest),
    }
    source_hash = sha256(json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    capture = ForwardCapture(
        stream.stream_id, "revision", generation,
        f"{bar.bar.physical_contract}:{bar.bar.bar_end.isoformat()}",
        bar.bar.bar_end, observed or bar.bar.bar_end + timedelta(seconds=5),
        "canonical_completed",
        {"bar": wire, "contract": bar.bar.physical_contract,
         "product": stream.product, "source_identity": bar.bar.source_identity,
         "source_bar_sha256": bar.source_bar_sha256 or source_hash,
         "input_quality_policy": case_identity_policy(stream)},
        {"source_sha256": source_hash, "owner_segment_id": bar.bar.segment_id,
         "calculation_segment_id": bar.calculation_segment_id,
         "previous_watermark": None, "expected_endpoints": [bar.bar.bar_end.isoformat()],
         "frequency": stream.frequency, "source": "canonical_completed"},
        "completed_observation",
    )
    return capture


def case_identity_policy(_stream):
    from guiyi_quant.newow.product_identity import InputQualityPolicy

    return InputQualityPolicy.V1.value


@pytest.mark.parametrize("strategy,frequency", [
    ("trend", "1d"), ("oscillation", "1w"), ("main_rise", "60m"),
])
def test_newow_forward_reuses_real_incremental_kernel(strategy, frequency):
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input(strategy, frequency)
    stream = StreamIdentity(
        f"newow_{strategy}", case.identity.formula_versions,
        case.identity.profile_id, "newow_reference_v3", "newow_futures_v1",
        case.identity.product, frequency, "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "completed_observation_v1",
    )
    bar = case.bars[0]
    capture = _capture(stream, bar)
    if frequency == "60m":
        from dataclasses import replace

        capture = replace(capture, source_kind="completed_live")
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), stream=stream,
        reference_state=ReferenceState.flat(stream, recording_start=bar.bar.bar_end),
    )
    token = CheckpointToken(stream.stream_id, "revision", 1, 1, sha256(b"seed").hexdigest())
    prepared = evaluate_newow_capture(
        token, checkpoint, {**capture.evidence(), "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    assert prepared.checkpoint.computed_through == bar.bar.bar_end
    assert prepared.input_observed_at == capture.observed_at
    assert prepared.checkpoint.reference_state is not None
    assert prepared.source_evidence["presentation_v1"]["points"]


def test_prewarmed_hold_first_clear_has_no_observed_entry():
    case = _case()
    stream = _stream(case)
    prewarmed = seed_replay_state()
    for bar in case.bars[:39]:
        prewarmed, _frame, _diagnostics = replay_step(case.identity, prewarmed, bar)
    first_observed = case.bars[39]
    checkpoint = AdapterCheckpoint(
        prewarmed, stream=stream,
        reference_state=ReferenceState.flat(
            stream, recording_start=first_observed.bar.bar_end,
        ),
    )
    token = CheckpointToken(stream.stream_id, "revision", 1, 1, sha256(b"seed").hexdigest())
    prepared = evaluate_newow_capture(
        token, checkpoint,
        {**_capture(stream, first_observed).evidence(), "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    assert prepared.source_actions == ()
    assert prepared.checkpoint.reference_state.open_trade is None
    diagnostics = [
        point["value"]["code"]
        for point in prepared.source_evidence["presentation_v1"]["points"]
        if point["kind"] == "diagnostic" and "code" in point["value"]
    ]
    assert "NO_OBSERVED_ENTRY" in diagnostics


def test_owner_switch_interrupts_old_open_before_new_owner_input():
    case = _case()
    stream = _stream(case)
    bar = case.bars[0]
    previous = bar.bar.bar_end - timedelta(days=1)
    entry = ReferenceAction(
        stream=stream, source_action_id="old-entry", sequence=0,
        kind=ActionKind.OPEN_LONG, physical_contract="RB2609",
        owner_segment_id="old-owner", calculation_segment_id="old-calc",
        bar_end=previous, trading_day=previous.date(),
        reference_price=bar.bar.close,
    )
    opened = reduce_reference(
        ReferenceState.flat(stream, recording_start=previous), actions=(entry,),
        completed_bar_end=previous, completed_trading_day=previous.date(),
        completed_reference_price=bar.bar.close,
    )
    checkpoint = AdapterCheckpoint(
        seed_replay_state(), computed_through=previous,
        physical_contract="RB2609", owner_segment_id="old-owner",
        calculation_segment_id="old-calc", stream=stream,
        reference_state=opened.state,
    )
    capture = _capture(stream, bar)
    raw = capture.evidence()["forward_capture_v1"]
    raw["source_proof"]["previous_watermark"] = previous.isoformat()
    token = CheckpointToken(stream.stream_id, "revision", 2, 1, sha256(b"seed").hexdigest())
    prepared = evaluate_newow_capture(
        token, checkpoint, {"forward_capture_v1": raw, "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    assert prepared.source_actions == ()
    interrupted = prepared.transitions[0].changed_trades[0]
    assert interrupted.status.value == "ROLLOVER_INTERRUPTED"
    assert interrupted.exit_reference_price is None
    assert prepared.checkpoint.reference_state.open_trade is None
