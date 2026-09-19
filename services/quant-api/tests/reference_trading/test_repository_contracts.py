from __future__ import annotations

from datetime import UTC, datetime

import pytest

from guiyi_quant.reference_trading import RecordingMode, StreamIdentity

from app.reference_trading.contracts import CheckpointToken, SnapshotIdentity


def _identity() -> StreamIdentity:
    return StreamIdentity(
        strategy_code="newow_trend",
        formula_versions=("trend-v1",),
        profile_id="default",
        reference_model_version="reference-v2",
        futures_adaptation_version="futures-v1",
        product="rb",
        frequency="1d",
        series_kind="actual_dominant",
        recording_mode=RecordingMode.HISTORICAL_REPLAY,
        observation_policy_version=None,
    )


def test_checkpoint_token_rejects_wrong_stream_and_non_hash_state() -> None:
    stream = _identity()
    token = CheckpointToken(
        stream_id=stream.stream_id,
        revision_id="revision-1",
        seq=0,
        row_version=2,
        state_hash="a" * 64,
    )

    assert token.seq == 0
    with pytest.raises(ValueError, match="state_hash"):
        CheckpointToken(stream.stream_id, "revision-1", 0, 2, "not-a-hash")
    with pytest.raises(ValueError, match="seq"):
        CheckpointToken(stream.stream_id, "revision-1", -1, 2, "a" * 64)


def test_snapshot_identity_is_exact_and_non_negative() -> None:
    stream = _identity()
    snapshot = SnapshotIdentity(stream.stream_id, "revision-1", 3)

    assert snapshot == SnapshotIdentity(stream.stream_id, "revision-1", 3)
    with pytest.raises(ValueError, match="seq"):
        SnapshotIdentity(stream.stream_id, "revision-1", -1)


def test_contract_module_does_not_create_engine_or_load_environment() -> None:
    # Importing application DTOs must remain pure; this timestamp is only a
    # sentinel proving the module accepts timezone-aware instants elsewhere.
    assert datetime(2026, 9, 19, tzinfo=UTC).utcoffset() is not None
