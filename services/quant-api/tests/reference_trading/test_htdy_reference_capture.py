from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json

from guiyi_quant.reference_trading import RecordingMode, ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.htdy import (
    HtdyForwardState, MODEL_VERSION, project_first_seen,
)

from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.htdy import evaluate_htdy_capture


def test_exact_32_bar_htdy_capture_projects_without_alert_or_history_write():
    base = datetime(2026, 9, 23, 0, tzinfo=UTC)
    stream = StreamIdentity(
        strategy_code="htdy", formula_versions=("huotian_dayou_original_v0",),
        profile_id="htdy-v1", reference_model_version=MODEL_VERSION,
        futures_adaptation_version="actual_dominant_v1", product="RB", frequency="15m",
        series_kind="actual_dominant", recording_mode=RecordingMode.FORWARD_OBSERVATION,
        observation_policy_version="latest_only_32_v1",
    )
    bars = [{
        "bar_end": (base + timedelta(minutes=15 * index)).isoformat(),
        "trading_day": date(2026, 9, 23).isoformat(),
        "open": "3500", "high": "3510", "low": "3490", "close": "3500",
        "volume": "100", "turnover": None, "open_interest": None,
    } for index in range(32)]
    latest = base + timedelta(minutes=15 * 31)
    observed = latest + timedelta(seconds=2)
    window_hash = sha256(json.dumps(bars, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    capture = {
        "hash": sha256(b"capture").hexdigest(), "generation": 1,
        "source_key": "RB2610:latest", "bar_end": latest.isoformat(),
        "observed_at": observed.isoformat(), "eligibility": "first_seen",
        "input_payload": {"bars": bars, "bar_contracts": ["RB2610"] * 32, "contract": "RB2610"},
        "source_proof": {
            "window_sha256": window_hash, "owner_segment_id": "owner",
            "calculation_segment_id": "calc",
            "event_bar_end": latest.isoformat(),
        },
    }
    checkpoint = AdapterCheckpoint(
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        stream=stream, reference_state=ReferenceState.flat(stream, recording_start=latest),
    )
    token = CheckpointToken(stream.stream_id, "revision", 1, 1, sha256(b"seed").hexdigest())
    prepared = evaluate_htdy_capture(
        token, checkpoint, {"forward_capture_v1": capture, "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    assert prepared.input_observed_at == observed
    assert prepared.checkpoint.computed_through == latest
    assert prepared.source_evidence["presentation_v1"]["points"][0]["value"]["first_seen"] is True

    previous = latest - timedelta(minutes=15)
    _, opened = project_first_seen(
        ReferenceState.flat(stream, recording_start=previous), observations=("buy",),
        physical_contract="RB2609", owner_segment_id="old-owner",
        calculation_segment_id="old-calc", bar_end=previous,
        trading_day=date(2026, 9, 23), close=Decimal("3500"),
    )
    old_checkpoint = AdapterCheckpoint(
        HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        computed_through=previous, physical_contract="RB2609",
        owner_segment_id="old-owner", calculation_segment_id="old-calc",
        stream=stream, reference_state=opened.state,
    )
    interrupted = evaluate_htdy_capture(
        token, old_checkpoint, {"forward_capture_v1": capture, "capture_id": "capture-id"},
        dependency_manifest={"source": "fixture"},
    )
    assert interrupted.source_actions == ()
    assert interrupted.transitions[0].changed_trades[0].status.value == "ROLLOVER_INTERRUPTED"
    assert interrupted.transitions[0].changed_trades[0].exit_reference_price is None
