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


class _ShadowReadService(Protocol):
    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState: ...

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
class BoundShadowReadService:
    """Exact composition token binding one read service to one session object."""

    __session: object
    __service: _ShadowReadService
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self.__seal is not _SEAL:
            raise SubingStrategyShadowDependencyError()

    def _require_session(self, session: object) -> None:
        if self.__session is not session:
            raise SubingStrategyShadowDependencyError()

    def _restore_machine(
        self,
        session: object,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        self._require_session(session)
        return self.__service.restore_machine(symbol=symbol, now=now)

    def _completed_live_after(
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

    def _session_windows(
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

    def _authoritative_terminal(
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


def bind_shadow_read_service(
    session: object,
    service: _ShadowReadService,
) -> BoundShadowReadService:
    """Create the exact session/service binding required by the transaction."""

    _reject_write_capable_service(service)
    return BoundShadowReadService(session, service, _SEAL)


@dataclass(frozen=True, slots=True)
class _ShadowReadOnlyPostgresTransaction:
    """Private executor with four fixed read operations and no callable escape."""

    __session_factory: Callable[[], Any]
    __service_factory: Callable[[Any], BoundShadowReadService]
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.__seal is not _SEAL
            or not callable(self.__session_factory)
            or not callable(self.__service_factory)
        ):
            raise SubingStrategyShadowDependencyError()

    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        with self.__verified_bound() as (session, bound):
            return bound._restore_machine(session, symbol=symbol, now=now)

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
        with self.__verified_bound() as (session, bound):
            return bound._completed_live_after(
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
        with self.__verified_bound() as (session, bound):
            return bound._session_windows(
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
        with self.__verified_bound() as (session, bound):
            return bound._authoritative_terminal(
                session,
                symbol=symbol,
                trading_day=trading_day,
                source_identity=source_identity,
            )

    @contextmanager
    def __verified_bound(self) -> Iterator[tuple[object, BoundShadowReadService]]:
        try:
            with self.__session_factory() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                if session.scalar(text("SHOW transaction_read_only")) != "on":
                    raise SubingStrategyShadowDependencyError()
                try:
                    bound = self.__service_factory(session)
                    if type(bound) is not BoundShadowReadService:
                        raise SubingStrategyShadowDependencyError()
                    bound._require_session(session)
                    yield session, bound
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
class ShadowReadOnlyCanonicalReader:
    """Expose only the Canonical reconstruction reads required by the evaluator."""

    __transaction: _ShadowReadOnlyPostgresTransaction
    __clock: Callable[[], datetime]
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.__seal is not _SEAL
            or type(self.__transaction) is not _ShadowReadOnlyPostgresTransaction
            or not callable(self.__clock)
        ):
            raise SubingStrategyShadowDependencyError()

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        return self.__transaction.restore_machine(symbol=symbol, now=started_at)

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
        return self.__transaction.restore_machine(symbol=symbol, now=self.__clock())


@dataclass(frozen=True, slots=True)
class ShadowReadOnlyLiveReader:
    """Expose only completed-Live reads required by the evaluator."""

    __transaction: _ShadowReadOnlyPostgresTransaction
    __seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.__seal is not _SEAL
            or type(self.__transaction) is not _ShadowReadOnlyPostgresTransaction
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
            self.__transaction.completed_live_after(
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
        return self.__transaction.session_windows(
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
        return self.__transaction.authoritative_terminal(
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


def build_subing_strategy_shadow_dependencies(
    *,
    session_factory: Callable[[], Any],
    service_factory: Callable[[Any], BoundShadowReadService],
    clock: Callable[[], datetime] | None = None,
) -> SubingStrategyShadowDependencies:
    """Build sealed adapters without opening a database or Live connection."""

    transaction = _ShadowReadOnlyPostgresTransaction(
        session_factory,
        service_factory,
        _SEAL,
    )
    return SubingStrategyShadowDependencies(
        event_writer=NullShadowEventWriter(),
        notification_sender=NullShadowNotificationSender(),
        cache_writer=NoShadowCacheWriter(),
        runtime_status_writer=NoShadowRuntimeStatusWriter(),
        canonical_reader=ShadowReadOnlyCanonicalReader(
            transaction,
            clock or (lambda: datetime.now(UTC)),
            _SEAL,
        ),
        live_reader=ShadowReadOnlyLiveReader(transaction, _SEAL),
    )


def build_local_readonly_subing_strategy_shadow_dependencies(
) -> SubingStrategyShadowDependencies:
    """Compose production-shaped readers lazily; construction performs no I/O."""

    from app.db.session import SessionLocal
    from app.market_data.composition import build_subing_strategy_current_service

    def service_factory(session: Any) -> BoundShadowReadService:
        return bind_shadow_read_service(
            session,
            build_subing_strategy_current_service(session),
        )

    return build_subing_strategy_shadow_dependencies(
        session_factory=SessionLocal,
        service_factory=service_factory,
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


def _reject_write_capable_service(service: _ShadowReadService) -> None:
    if service is None:
        raise SubingStrategyShadowDependencyError()
    public = {name for name in dir(service) if not name.startswith("_")}
    if public & _WRITE_CAPABLE_NAMES:
        raise SubingStrategyShadowDependencyError()


__all__ = [
    "BoundShadowReadService",
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
    "bind_shadow_read_service",
    "build_local_readonly_subing_strategy_shadow_dependencies",
    "build_manual_subing_strategy_shadow",
    "build_subing_strategy_shadow_dependencies",
]
