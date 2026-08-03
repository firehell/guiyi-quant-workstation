from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.htdy_realtime_models import HtDyRealtimeSnapshot


REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = REPO_ROOT / "config" / "observation_plans.yaml"


def _active_plan():
    from app.services.observation_plans import ObservationPlanRegistry

    return ObservationPlanRegistry.from_file(PLAN_PATH).require_active_plan()


def _uninitialized_snapshot() -> HtDyRealtimeSnapshot:
    return object.__new__(HtDyRealtimeSnapshot)


def _candidate_snapshot() -> HtDyRealtimeSnapshot:
    from test_htdy_realtime_evaluator import _resolver_compatible_snapshot

    length = 130
    rng = np.random.default_rng(3838)
    center = 10 + np.cumsum(rng.normal(0, 0.08, length))
    body = rng.normal(0, 0.12, length)
    open_ = center - body / 2
    close = center + body / 2
    spread = np.abs(rng.normal(0.12, 0.08, length)) + 0.01
    return _resolver_compatible_snapshot(
        open_=open_,
        high=np.maximum(open_, close) + spread,
        low=np.minimum(open_, close) - spread,
        close=close,
        volume=1000 + rng.integers(0, 100, length),
    )


def test_htdy_adapter_delegates_to_frozen_evaluator_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.htdy_strategy_adapter as module
    from app.services.strategy_adapter import StrategyContext

    detected_at = datetime(2026, 7, 30, 7, 15, tzinfo=UTC)
    native_candidate = SimpleNamespace(
        observation_key="stable-key",
        direction="long",
        detected_at=detected_at,
        actual_contract="JM2609",
        period="15m",
        strategy_code="htdy_original_realtime_first_seen",
        strategy_version="v1.0",
        policy_id="htdy_original_xma_15m_first_seen_v1",
    )
    native_blocked = SimpleNamespace(reason="dual_direction_conflict")
    native_result = SimpleNamespace(
        candidates=(native_candidate,),
        blocked=(native_blocked,),
        snapshot_sha256="snapshot-hash",
        evaluated_at=detected_at,
        writes_enabled=False,
        signal_event_enabled=False,
        notification_enabled=False,
    )
    calls: list[tuple[object, datetime]] = []

    class FrozenEvaluatorSpy:
        def evaluate(self, snapshot, *, detected_at):
            calls.append((snapshot, detected_at))
            return native_result

    monkeypatch.setattr(module, "HtDyRealtimeCandidateEvaluator", FrozenEvaluatorSpy)
    snapshot = _uninitialized_snapshot()
    result = module.HtDyStrategyAdapter().evaluate(
        StrategyContext(
            plan=_active_plan(),
            market_snapshot=snapshot,
            detected_at=detected_at,
        )
    )

    assert calls == [(snapshot, detected_at)]
    assert result.snapshot_sha256 == "snapshot-hash"
    assert result.evaluated_at == detected_at
    assert result.blocked == (native_blocked,)
    assert result.writes_enabled is False
    assert result.signal_event_enabled is False
    assert result.notification_enabled is False
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.observation_key == native_candidate.observation_key
    assert candidate.direction == native_candidate.direction
    assert candidate.actual_contract == native_candidate.actual_contract
    assert candidate.period == native_candidate.period
    assert candidate.strategy_code == native_candidate.strategy_code
    assert candidate.strategy_version == native_candidate.strategy_version
    assert candidate.policy_id == native_candidate.policy_id
    assert candidate.native_candidate is native_candidate


def test_htdy_adapter_matches_real_frozen_evaluator_candidate_contract() -> None:
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator
    from app.services.htdy_strategy_adapter import HtDyStrategyAdapter
    from app.services.strategy_adapter import StrategyContext

    snapshot = _candidate_snapshot()

    native = HtDyRealtimeCandidateEvaluator().evaluate(
        snapshot, detected_at=snapshot.as_of
    )
    adapted = HtDyStrategyAdapter().evaluate(
        StrategyContext(
            plan=_active_plan(),
            market_snapshot=snapshot,
            detected_at=snapshot.as_of,
        )
    )

    assert native.candidates
    assert tuple(item.native_candidate for item in adapted.candidates) == (
        native.candidates
    )
    assert tuple(item.observation_key for item in adapted.candidates) == tuple(
        item.observation_key for item in native.candidates
    )
    assert tuple(item.direction for item in adapted.candidates) == tuple(
        item.direction for item in native.candidates
    )
    assert adapted.blocked == native.blocked
    assert adapted.snapshot_sha256 == native.snapshot_sha256
    assert adapted.writes_enabled is False
    assert adapted.signal_event_enabled is False
    assert adapted.notification_enabled is False


@pytest.mark.parametrize("with_candidate", [False, True])
def test_htdy_adapter_rejects_confirmed_only_snapshot_for_realtime_first_seen(
    with_candidate: bool,
) -> None:
    from dataclasses import replace

    from app.services.htdy_strategy_adapter import HtDyStrategyAdapter
    from app.services.strategy_adapter import StrategyContext
    from test_htdy_realtime_evaluator import _snapshot

    snapshot = _candidate_snapshot() if with_candidate else _snapshot()
    confirmed_only = replace(snapshot, partial_allowed=False)

    with pytest.raises(
        ValueError, match="STRATEGY_ADAPTER_PARTIAL_POLICY_MISMATCH"
    ):
        HtDyStrategyAdapter().evaluate(
            StrategyContext(
                plan=_active_plan(),
                market_snapshot=confirmed_only,
                detected_at=confirmed_only.as_of,
            )
        )


def test_htdy_adapter_rejects_disabled_plan_before_evaluation() -> None:
    from dataclasses import replace

    from app.services.htdy_strategy_adapter import HtDyStrategyAdapter
    from app.services.strategy_adapter import StrategyContext

    with pytest.raises(ValueError, match="STRATEGY_ADAPTER_PLAN_DISABLED"):
        HtDyStrategyAdapter().evaluate(
            StrategyContext(
                plan=replace(_active_plan(), enabled=False),
                market_snapshot=_uninitialized_snapshot(),
                detected_at=datetime(2026, 7, 30, 7, 15, tzinfo=UTC),
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product", "rb"),
        ("period", "5m"),
        ("notification_enabled", True),
        ("purpose", "trading"),
        ("strategy_version", "v2.0"),
    ],
)
def test_htdy_adapter_rejects_plan_contract_drift(field: str, value: object) -> None:
    from dataclasses import replace

    from app.services.htdy_strategy_adapter import HtDyStrategyAdapter
    from app.services.strategy_adapter import StrategyContext

    with pytest.raises(ValueError, match="STRATEGY_ADAPTER_PLAN_CONTRACT_MISMATCH"):
        HtDyStrategyAdapter().evaluate(
            StrategyContext(
                plan=replace(_active_plan(), **{field: value}),
                market_snapshot=_uninitialized_snapshot(),
                detected_at=datetime(2026, 7, 30, 7, 15, tzinfo=UTC),
            )
        )


def test_htdy_adapter_fail_closes_if_wrapped_result_exposes_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.htdy_strategy_adapter as module
    from app.services.strategy_adapter import StrategyContext

    detected_at = datetime(2026, 7, 30, 7, 15, tzinfo=UTC)

    class UnsafeEvaluator:
        def evaluate(self, snapshot, *, detected_at):
            return SimpleNamespace(
                candidates=(),
                blocked=(),
                snapshot_sha256="snapshot-hash",
                evaluated_at=detected_at,
                writes_enabled=True,
                signal_event_enabled=False,
                notification_enabled=False,
            )

    monkeypatch.setattr(module, "HtDyRealtimeCandidateEvaluator", UnsafeEvaluator)

    with pytest.raises(ValueError, match="STRATEGY_ADAPTER_WRITE_CAPABILITY_FORBIDDEN"):
        module.HtDyStrategyAdapter().evaluate(
            StrategyContext(
                plan=_active_plan(),
                market_snapshot=_uninitialized_snapshot(),
                detected_at=detected_at,
            )
        )


def test_htdy_adapter_rejects_non_snapshot_payload() -> None:
    from app.services.htdy_strategy_adapter import HtDyStrategyAdapter
    from app.services.strategy_adapter import StrategyContext

    with pytest.raises(ValueError, match="STRATEGY_ADAPTER_SNAPSHOT_TYPE"):
        HtDyStrategyAdapter().evaluate(
            StrategyContext(
                plan=_active_plan(),
                market_snapshot=object(),
                detected_at=datetime(2026, 7, 30, 7, 15, tzinfo=UTC),
            )
        )
