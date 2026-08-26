"""Fail-closed dependency boundary for no-write SuBing Strategy shadow runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


_SHADOW_ENABLE_ENV = "GUIYI_SUBING_STAGE2_SHADOW"


class SubingStrategyShadowAuthorizationError(RuntimeError):
    code = "SUBING_STRATEGY_SHADOW_NOT_AUTHORIZED"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyShadowDependencyError(RuntimeError):
    code = "SUBING_STRATEGY_SHADOW_DEPENDENCY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyShadowWriteBlocked(RuntimeError):
    code = "SUBING_STRATEGY_SHADOW_WRITE_BLOCKED"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class NullShadowEventWriter:
    """Sealed Event sink whose only behavior is to reject a write attempt."""

    def create_event(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NullShadowNotificationSender:
    """Sealed notification sink whose only behavior is to reject a send."""

    def send(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NoShadowCacheWriter:
    """Sealed cache sink that makes shadow cache mutation impossible."""

    def write(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NoShadowRuntimeStatusWriter:
    """Sealed Runtime-status sink that makes Redis status writes impossible."""

    def write(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyPostgresTransaction:
    """Narrow adapter for a transaction independently verified as read-only."""

    verify_read_only: Callable[[], bool]
    read: Callable[[object], object]

    def __post_init__(self) -> None:
        if not callable(self.verify_read_only) or not callable(self.read):
            raise SubingStrategyShadowDependencyError()

    def verify(self) -> None:
        try:
            verified = self.verify_read_only()
        except Exception as exc:
            raise SubingStrategyShadowDependencyError() from exc
        if verified is not True:
            raise SubingStrategyShadowDependencyError()


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyCanonicalReader:
    """Read-only Canonical adapter; no publish or maintenance method is exposed."""

    reader: object

    def __post_init__(self) -> None:
        if not callable(getattr(self.reader, "restore", None)) or not callable(
            getattr(self.reader, "restore_rollover", None)
        ):
            raise SubingStrategyShadowDependencyError()


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyLiveReader:
    """Read-only completed-Live adapter; no Redis mutation method is exposed."""

    reader: object

    def __post_init__(self) -> None:
        required = (
            "read_completed_bars",
            "read_session_windows",
            "read_authoritative_terminal",
        )
        if any(not callable(getattr(self.reader, method, None)) for method in required):
            raise SubingStrategyShadowDependencyError()


@dataclass(frozen=True, slots=True)
class SubingStrategyShadowDependencies:
    """Exact no-write composition accepted by a Stage 2 shadow run."""

    event_writer: NullShadowEventWriter
    notification_sender: NullShadowNotificationSender
    cache_writer: NoShadowCacheWriter
    runtime_status_writer: NoShadowRuntimeStatusWriter
    postgres_transaction: ShadowReadOnlyPostgresTransaction
    canonical_reader: ShadowReadOnlyCanonicalReader
    live_reader: ShadowReadOnlyLiveReader

    def __post_init__(self) -> None:
        expected: tuple[tuple[object, type[object]], ...] = (
            (self.event_writer, NullShadowEventWriter),
            (self.notification_sender, NullShadowNotificationSender),
            (self.cache_writer, NoShadowCacheWriter),
            (self.runtime_status_writer, NoShadowRuntimeStatusWriter),
            (self.postgres_transaction, ShadowReadOnlyPostgresTransaction),
            (self.canonical_reader, ShadowReadOnlyCanonicalReader),
            (self.live_reader, ShadowReadOnlyLiveReader),
        )
        if any(type(value) is not expected_type for value, expected_type in expected):
            raise SubingStrategyShadowDependencyError()
        self.postgres_transaction.verify()


def authorize_subing_strategy_shadow(
    *,
    environment: Mapping[str, str],
    dependencies: SubingStrategyShadowDependencies,
) -> SubingStrategyShadowDependencies:
    """Admit a run only with the exact marker and sealed no-write composition."""

    if environment.get(_SHADOW_ENABLE_ENV) != "1":
        raise SubingStrategyShadowAuthorizationError()
    if type(dependencies) is not SubingStrategyShadowDependencies:
        raise SubingStrategyShadowDependencyError()
    dependencies.postgres_transaction.verify()
    return dependencies


__all__ = [
    "NoShadowCacheWriter",
    "NoShadowRuntimeStatusWriter",
    "NullShadowEventWriter",
    "NullShadowNotificationSender",
    "ShadowReadOnlyCanonicalReader",
    "ShadowReadOnlyLiveReader",
    "ShadowReadOnlyPostgresTransaction",
    "SubingStrategyShadowAuthorizationError",
    "SubingStrategyShadowDependencies",
    "SubingStrategyShadowDependencyError",
    "SubingStrategyShadowWriteBlocked",
    "authorize_subing_strategy_shadow",
]
