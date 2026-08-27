"""Fail-closed composition for explicitly authorized, no-write shadow runs."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import text

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_strategy.machine import (
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
)
from app.market_data.subing_strategy.stream_contracts import AuthoritativeSegmentTerminal


SHADOW_ENABLE_ENV = "GUIYI_SUBING_STAGE2_SHADOW"
SHADOW_COMPOSITION_ENV = "GUIYI_SUBING_STAGE2_SHADOW_COMPOSITION"
LOCAL_READ_ONLY_COMPOSITION = "local_readonly"
_SEAL = object()
_WRITE_CAPABLE_NAMES = frozenset(
    {
        "add",
        "commit",
        "create",
        "delete",
        "execute_write",
        "flush",
        "merge",
        "publish",
        "save",
        "send",
        "set",
        "update",
        "write",
    }
)


class _RestoreService(Protocol):
    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState: ...


class _CurrentService(Protocol):
    def completed_live_after(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]: ...

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]: ...

    def authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None: ...


class _ShadowReadBackend(_RestoreService, _CurrentService, Protocol):
    pass


class SubingStrategyShadowAuthorizationError(RuntimeError):
    code = "SUBING_STRATEGY_SHADOW_NOT_AUTHORIZED"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyShadowCompositionNotConfigured(RuntimeError):
    code = "SHADOW_COMPOSITION_NOT_CONFIGURED"

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
    def create_event(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NullShadowNotificationSender:
    def send(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NoShadowCacheWriter:
    def write(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class NoShadowRuntimeStatusWriter:
    def write(self, *_args: object, **_kwargs: object) -> None:
        raise SubingStrategyShadowWriteBlocked()


@dataclass(frozen=True, slots=True)
class _LocalShadowReadService:
    """Trusted concrete service attested to its construction session."""

    __session_identity: object
    __service: _ShadowReadBackend
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self.__seal is not _SEAL:
            raise SubingStrategyShadowDependencyError()

    def _require_session(self, session: object) -> None:
        if self.__session_identity is not session:
            raise SubingStrategyShadowDependencyError()

    def restore_machine(
        self,
        session: object,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        self._require_session(session)
        return self.__service.restore_machine(symbol=symbol, now=now)

    def completed_live_after(
        self,
        session: object,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        self._require_session(session)
        return self.__service.completed_live_after(
            symbol=symbol,
            source_identity=source_identity,
            after_1m=after_1m,
            after_5m=after_5m,
            after_15m=after_15m,
            through=through,
        )

    def session_windows(
        self,
        session: object,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        self._require_session(session)
        return self.__service.session_windows(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )

    def authoritative_terminal(
        self,
        session: object,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        self._require_session(session)
        return self.__service.authoritative_terminal(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )


def _build_local_shadow_read_service(session: object) -> _LocalShadowReadService:
    """Trusted production builder: the same session builds and attests the service."""

    from app.market_data.composition import build_subing_strategy_current_service

    service = build_subing_strategy_current_service(session)  # type: ignore[arg-type]
    _reject_write_capable_service(service)
    return _LocalShadowReadService(session, service, _SEAL)


@dataclass(frozen=True, slots=True)
class _LocalShadowReadOnlyPostgres:
    """Private local executor with four fixed reads and no injected service factory."""

    __session_factory: Callable[[], Any]
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self.__seal is not _SEAL or not callable(self.__session_factory):
            raise SubingStrategyShadowDependencyError()

    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        with self.__verified_service() as (session, service):
            return service.restore_machine(session, symbol=symbol, now=now)

    def completed_live_after(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        with self.__verified_service() as (session, service):
            return service.completed_live_after(
                session,
                symbol=symbol,
                source_identity=source_identity,
                after_1m=after_1m,
                after_5m=after_5m,
                after_15m=after_15m,
                through=through,
            )

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        with self.__verified_service() as (session, service):
            return service.session_windows(
                session,
                symbol=symbol,
                trading_day=trading_day,
                source_identity=source_identity,
            )

    def authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        with self.__verified_service() as (session, service):
            return service.authoritative_terminal(
                session,
                symbol=symbol,
                trading_day=trading_day,
                source_identity=source_identity,
            )

    @contextmanager
    def __verified_service(self) -> Iterator[tuple[object, _LocalShadowReadService]]:
        try:
            with self.__session_factory() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                if session.scalar(text("SHOW transaction_read_only")) != "on":
                    raise SubingStrategyShadowDependencyError()
                try:
                    service = _build_local_shadow_read_service(session)
                    if type(service) is not _LocalShadowReadService:
                        raise SubingStrategyShadowDependencyError()
                    service._require_session(session)
                    yield session, service
                finally:
                    session.rollback()
        except SubingStrategyShadowDependencyError:
            raise
        except Exception as exc:
            from app.alerts.subing_strategy_runtime import (
                SubingStrategyRuntimeProductSourceError,
            )

            raise SubingStrategyRuntimeProductSourceError() from exc


@dataclass(frozen=True, slots=True)
class _RecordedShadowReadBackend:
    """Committed-fixture seam; it makes no PostgreSQL read-only attestation."""

    __restore_service: _RestoreService
    __current_service: _CurrentService
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self.__seal is not _SEAL:
            raise SubingStrategyShadowDependencyError()
        _reject_write_capable_service(self.__restore_service)
        _reject_write_capable_service(self.__current_service)

    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        return self.__restore_service.restore_machine(symbol=symbol, now=now)

    def completed_live_after(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        return self.__current_service.completed_live_after(
            symbol=symbol,
            source_identity=source_identity,
            after_1m=after_1m,
            after_5m=after_5m,
            after_15m=after_15m,
            through=through,
        )

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        return self.__current_service.session_windows(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )

    def authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        return self.__current_service.authoritative_terminal(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyCanonicalReader:
    """Expose only the Canonical reconstruction reads required by the evaluator."""

    __backend: _ShadowReadBackend
    __clock: Callable[[], datetime]
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.__seal is not _SEAL
            or type(self.__backend)
            not in {_LocalShadowReadOnlyPostgres, _RecordedShadowReadBackend}
            or not callable(self.__clock)
        ):
            raise SubingStrategyShadowDependencyError()

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        return self.__backend.restore_machine(symbol=symbol, now=started_at)

    def restore_rollover(
        self,
        *,
        symbol: str,
        trading_day: date,
        previous_identity: SubingStrategySourceIdentity,
        terminal: AuthoritativeSegmentTerminal,
    ) -> SubingStrategyMachineState:
        if (
            terminal.symbol != symbol
            or terminal.contract != previous_identity.contract
            or terminal.segment_start_trading_day
            != previous_identity.segment_start_trading_day
            or terminal.terminal_bar.trading_day >= trading_day
        ):
            from app.alerts.subing_strategy_runtime import (
                SubingStrategyRuntimeProductSourceError,
            )

            raise SubingStrategyRuntimeProductSourceError()
        return self.__backend.restore_machine(symbol=symbol, now=self.__clock())


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyLiveReader:
    """Expose only completed-Live reads required by the evaluator."""

    __backend: _ShadowReadBackend
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.__seal is not _SEAL
            or type(self.__backend)
            not in {_LocalShadowReadOnlyPostgres, _RecordedShadowReadBackend}
        ):
            raise SubingStrategyShadowDependencyError()

    def read_completed_bars(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        return dict(
            self.__backend.completed_live_after(
                symbol=symbol,
                source_identity=source_identity,
                after_1m=after_1m,
                after_5m=after_5m,
                after_15m=after_15m,
                through=through,
            )
        )

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        return self.__backend.session_windows(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        return self.__backend.authoritative_terminal(
            symbol=symbol,
            trading_day=trading_day,
            source_identity=source_identity,
        )


@dataclass(frozen=True, slots=True)
class SubingStrategyShadowDependencies:
    event_writer: NullShadowEventWriter
    notification_sender: NullShadowNotificationSender
    cache_writer: NoShadowCacheWriter
    runtime_status_writer: NoShadowRuntimeStatusWriter
    canonical_reader: ShadowReadOnlyCanonicalReader
    live_reader: ShadowReadOnlyLiveReader

    def __post_init__(self) -> None:
        expected: tuple[tuple[object, type[object]], ...] = (
            (self.event_writer, NullShadowEventWriter),
            (self.notification_sender, NullShadowNotificationSender),
            (self.cache_writer, NoShadowCacheWriter),
            (self.runtime_status_writer, NoShadowRuntimeStatusWriter),
            (self.canonical_reader, ShadowReadOnlyCanonicalReader),
            (self.live_reader, ShadowReadOnlyLiveReader),
        )
        if any(type(value) is not expected_type for value, expected_type in expected):
            raise SubingStrategyShadowDependencyError()


def _build_dependencies(
    backend: _ShadowReadBackend,
    *,
    clock: Callable[[], datetime] | None = None,
) -> SubingStrategyShadowDependencies:
    if type(backend) not in {
        _LocalShadowReadOnlyPostgres,
        _RecordedShadowReadBackend,
    }:
        raise SubingStrategyShadowDependencyError()
    return SubingStrategyShadowDependencies(
        event_writer=NullShadowEventWriter(),
        notification_sender=NullShadowNotificationSender(),
        cache_writer=NoShadowCacheWriter(),
        runtime_status_writer=NoShadowRuntimeStatusWriter(),
        canonical_reader=ShadowReadOnlyCanonicalReader(
            backend,
            clock or (lambda: datetime.now(UTC)),
            _SEAL,
        ),
        live_reader=ShadowReadOnlyLiveReader(backend, _SEAL),
    )


def build_recorded_subing_strategy_shadow_dependencies(
    *,
    restore_service: _RestoreService,
    current_service: _CurrentService,
    clock: Callable[[], datetime] | None = None,
) -> SubingStrategyShadowDependencies:
    """Build the committed-fixture seam without any database attestation claim."""

    return _build_dependencies(
        _RecordedShadowReadBackend(
            restore_service,
            current_service,
            _SEAL,
        ),
        clock=clock,
    )


def build_local_readonly_subing_strategy_shadow_dependencies(
    *,
    session_factory: Callable[[], Any] | None = None,
) -> SubingStrategyShadowDependencies:
    """Compose trusted local readers lazily; construction opens no connection."""

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    return _build_dependencies(
        _LocalShadowReadOnlyPostgres(session_factory, _SEAL),
    )


def build_manual_subing_strategy_shadow(
    *,
    environment: Mapping[str, str],
    composition_factories: Mapping[
        str,
        Callable[[], SubingStrategyShadowDependencies],
    ],
) -> SubingStrategyShadowDependencies:
    """Resolve an explicitly selected composition; marker alone is insufficient."""

    if environment.get(SHADOW_ENABLE_ENV) != "1":
        raise SubingStrategyShadowAuthorizationError()
    composition = environment.get(SHADOW_COMPOSITION_ENV)
    factory = composition_factories.get(composition or "")
    if factory is None:
        raise SubingStrategyShadowCompositionNotConfigured()
    dependencies = factory()
    return authorize_subing_strategy_shadow(
        environment=environment,
        dependencies=dependencies,
    )


def authorize_subing_strategy_shadow(
    *,
    environment: Mapping[str, str],
    dependencies: SubingStrategyShadowDependencies,
) -> SubingStrategyShadowDependencies:
    if environment.get(SHADOW_ENABLE_ENV) != "1":
        raise SubingStrategyShadowAuthorizationError()
    if type(dependencies) is not SubingStrategyShadowDependencies:
        raise SubingStrategyShadowDependencyError()
    return dependencies


def _reject_write_capable_service(service: object) -> None:
    if service is None:
        raise SubingStrategyShadowDependencyError()
    public = {name for name in dir(service) if not name.startswith("_")}
    if public & _WRITE_CAPABLE_NAMES:
        raise SubingStrategyShadowDependencyError()


__all__ = [
    "LOCAL_READ_ONLY_COMPOSITION",
    "NoShadowCacheWriter",
    "NoShadowRuntimeStatusWriter",
    "NullShadowEventWriter",
    "NullShadowNotificationSender",
    "SHADOW_COMPOSITION_ENV",
    "SHADOW_ENABLE_ENV",
    "ShadowReadOnlyCanonicalReader",
    "ShadowReadOnlyLiveReader",
    "SubingStrategyShadowAuthorizationError",
    "SubingStrategyShadowCompositionNotConfigured",
    "SubingStrategyShadowDependencies",
    "SubingStrategyShadowDependencyError",
    "SubingStrategyShadowWriteBlocked",
    "authorize_subing_strategy_shadow",
    "build_local_readonly_subing_strategy_shadow_dependencies",
    "build_manual_subing_strategy_shadow",
    "build_recorded_subing_strategy_shadow_dependencies",
]
