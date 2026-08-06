"""Observation-only live listening orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Mapping, Protocol, Sequence

from app.data_core.contracts import BarFrequency
from app.live_review_loop.live import LiveObservationInput, LiveObservationStore
from app.services.data_operations.contracts import (
    CliArgumentInvalid,
    CommandResult,
    CommandStatus,
    DataTarget,
    EffectSummary,
    LiveRequest,
    PublicError,
    TargetResult,
    empty_effects,
    overall_batch_status,
    require_direct_frequency,
)
from app.services.data_operations.guards import to_dataset_key


class LiveConfigError(RuntimeError):
    code = "LIVE_OBSERVATION_DISABLED"


class _BarStream(Protocol):
    def __iter__(self) -> Iterator[LiveObservationInput]: ...


@dataclass(frozen=True, slots=True)
class LiveConfig:
    enabled: bool
    expired: bool = False
    inconsistent: bool = False
    missing: bool = False


class LiveObservationApplicationService:
    """Route received 1m bars only to the live observation repository."""

    def __init__(
        self,
        *,
        store: LiveObservationStore,
        stream_factory: Callable[[Sequence[DataTarget]], _BarStream],
        config_provider: Callable[[], LiveConfig],
        notification_sender: Callable[[Mapping[str, object]], None] | None = None,
        order_creator: Callable[[Mapping[str, object]], None] | None = None,
        historical_promoter: Callable[[LiveObservationInput], None] | None = None,
    ) -> None:
        self._store = store
        self._stream_factory = stream_factory
        self._config_provider = config_provider
        self._notification_sender = notification_sender
        self._order_creator = order_creator
        self._historical_promoter = historical_promoter
        self._notification_count = 0
        self._order_count = 0
        self._historical_promotion_count = 0

    def listen(self, request: LiveRequest) -> CommandResult:
        for target in request.targets:
            require_direct_frequency(target.frequency)
            if target.frequency is not BarFrequency.M1:
                raise CliArgumentInvalid(
                    facts={"field": "frequency", "reason": "live_requires_1m"}
                )
            to_dataset_key(target)

        if not request.confirm_observation_write:
            results = [
                TargetResult(target=target, status=CommandStatus.BLOCKED)
                for target in request.targets
            ]
            return CommandResult(
                command="data.live",
                status=CommandStatus.BLOCKED,
                readonly=True,
                effects=empty_effects(),
                targets=tuple(results),
                error=PublicError(
                    code="LIVE_OBSERVATION_CONFIRMATION_REQUIRED",
                    type="LiveConfigError",
                ),
            )

        config = self._config_provider()
        if (
            config.missing
            or not config.enabled
            or config.expired
            or config.inconsistent
        ):
            return CommandResult(
                command="data.live",
                status=CommandStatus.BLOCKED,
                readonly=True,
                effects=empty_effects(),
                error=PublicError(
                    code="LIVE_OBSERVATION_DISABLED",
                    type="LiveConfigError",
                ),
                targets=tuple(
                    TargetResult(target=target, status=CommandStatus.BLOCKED)
                    for target in request.targets
                ),
            )

        results: list[TargetResult] = []
        written = 0
        stream = self._stream_factory(request.targets)
        try:
            for item in stream:
                # No historical promotion path is exposed on this service.
                if self._historical_promoter is not None:
                    raise LiveConfigError("historical promotion must stay unavailable")
                self._store.put(item)
                written += 1
        except Exception as exc:  # noqa: BLE001 - fail closed, no silent drop
            return CommandResult(
                command="data.live",
                status=CommandStatus.ERROR,
                readonly=False,
                effects=EffectSummary(writes_live_observation=written > 0),
                error=PublicError(
                    code=getattr(exc, "code", "LIVE_OBSERVATION_FAILED"),
                    type=type(exc).__name__,
                ),
                targets=tuple(
                    TargetResult(
                        target=target,
                        status=CommandStatus.ERROR,
                        detail={"written": written},
                    )
                    for target in request.targets
                ),
            )

        for target in request.targets:
            results.append(
                TargetResult(
                    target=target,
                    status=CommandStatus.PASSED,
                    detail={"written": written, "observation_only": True},
                )
            )
        # Notifications and orders remain disabled regardless of injected hooks.
        assert self._notification_count == 0
        assert self._order_count == 0
        assert self._historical_promotion_count == 0
        return CommandResult(
            command="data.live",
            status=overall_batch_status(results),
            readonly=False,
            effects=EffectSummary(writes_live_observation=True),
            targets=tuple(results),
            extras={
                "observation_writes": written,
                "historical_promotions": 0,
                "notifications": 0,
                "orders": 0,
                "auto_order": False,
            },
        )

    # Intentionally no promote_to_historical method.
