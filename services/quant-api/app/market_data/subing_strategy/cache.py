"""Expendable, identity-bound local cache for SuBing Strategy V1."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from ..domain import BarFrequency, CanonicalBar
from ..subing_lifecycle import ConfirmationSource
from ..subing_research import SubingDirection
from ..subing_structure import ConfirmedPivot, PivotKind
from .contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
    SubingStrategyFillBasis,
    SubingStrategyPositionState,
)
from .direction_context import SubingStrategyDirectionContext


_SCHEMA_VERSION = 3


class SubingStrategyCacheError(RuntimeError):
    code = "SUBING_STRATEGY_CACHE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyCacheIdentity:
    strategy_policy_sha256: str
    strategy_id: str
    formula_version: str
    calibration_id: str
    lifecycle_policy_id: str
    lifecycle_formula_version: str
    daily_watch_projection_version: str
    daily_watch_formula_version: str
    daily_watch_history_mode: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    segment_end_trading_day: date
    cutoff_1m: datetime
    cutoff_5m: datetime
    cutoff_15m: datetime
    cutoff_d1: datetime
    cutoff_60m: datetime
    bars_1m_digest: str
    bars_5m_digest: str
    bars_15m_digest: str
    direction_context_digest: str
    through: date

    def __post_init__(self) -> None:
        digest_fields = (
            self.strategy_policy_sha256,
            self.bars_1m_digest,
            self.bars_5m_digest,
            self.bars_15m_digest,
            self.direction_context_digest,
        )
        if (
            any(
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in digest_fields
            )
            or type(self.segment_start_trading_day) is not date
            or type(self.segment_end_trading_day) is not date
            or type(self.through) is not date
            or self.segment_start_trading_day > self.segment_end_trading_day
            or any(
                value.tzinfo is None or value.utcoffset() is None
                for value in (
                    self.cutoff_1m,
                    self.cutoff_5m,
                    self.cutoff_15m,
                    self.cutoff_d1,
                    self.cutoff_60m,
                )
            )
        ):
            raise SubingStrategyCacheError()


@dataclass(frozen=True, slots=True)
class CachedSubingStrategySegmentProjection:
    actions: tuple[SubingStrategyAction, ...]
    episodes: tuple[SubingStrategyEpisode, ...]
    final_position: SubingStrategyPositionState
    pending_action: bool


class NullSubingStrategyCache:
    available = False

    def read(
        self,
        identity: SubingStrategyCacheIdentity,
    ) -> CachedSubingStrategySegmentProjection | None:
        return None

    def write(
        self,
        identity: SubingStrategyCacheIdentity,
        projection: CachedSubingStrategySegmentProjection,
    ) -> None:
        return None


class SubingStrategyCache:
    available = True

    def __init__(
        self,
        root: Path,
        *,
        root_validator: Callable[[], Path],
    ) -> None:
        self._root = root
        self._root_validator = root_validator

    def path_for(self, identity: SubingStrategyCacheIdentity) -> Path:
        digest = sha256(_canonical_bytes(_identity_payload(identity))).hexdigest()
        return (
            self._root
            / identity.symbol
            / identity.contract
            / identity.segment_start_trading_day.isoformat()
            / f"{digest}.json"
        )

    def read(
        self,
        identity: SubingStrategyCacheIdentity,
    ) -> CachedSubingStrategySegmentProjection | None:
        path = self.path_for(identity)
        self._preflight(path)
        if not path.exists():
            self._preflight(path)
            return None
        try:
            content = path.read_bytes()
            self._preflight(path)
            payload = json.loads(content)
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != _SCHEMA_VERSION
                or payload.get("identity") != _identity_payload(identity)
                or not isinstance(payload.get("projection"), dict)
                or payload.get("projection_sha256")
                != sha256(_canonical_bytes(payload["projection"])).hexdigest()
            ):
                raise SubingStrategyCacheError()
            return _parse_projection(payload["projection"])
        except SubingStrategyCacheError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            raise SubingStrategyCacheError() from None

    def write(
        self,
        identity: SubingStrategyCacheIdentity,
        projection: CachedSubingStrategySegmentProjection,
    ) -> None:
        path = self.path_for(identity)
        self._preflight(path)
        projection_payload = _projection_payload(projection)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "identity": _identity_payload(identity),
            "projection": projection_payload,
            "projection_sha256": sha256(
                _canonical_bytes(projection_payload)
            ).hexdigest(),
        }
        try:
            self._ensure_parent(path.parent)
            self._preflight(path)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(_canonical_bytes(payload))
                    handle.flush()
                    os.fsync(handle.fileno())
                self._preflight(path)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        except SubingStrategyCacheError:
            raise
        except OSError:
            raise SubingStrategyCacheError() from None

    def _preflight(self, path: Path) -> None:
        try:
            if self._root_validator() != self._root:
                raise SubingStrategyCacheError()
            path.relative_to(self._root)
            current = self._root
            for part in path.relative_to(self._root).parts:
                if current.exists() and current.is_symlink():
                    raise SubingStrategyCacheError()
                current = current / part
            if current.exists() and current.is_symlink():
                raise SubingStrategyCacheError()
        except (OSError, ValueError):
            raise SubingStrategyCacheError() from None

    def _ensure_parent(self, parent: Path) -> None:
        parent.relative_to(self._root)
        current = self._root
        for part in parent.relative_to(self._root).parts:
            if current.exists() and current.is_symlink():
                raise SubingStrategyCacheError()
            current.mkdir(mode=0o700, parents=False, exist_ok=True)
            os.chmod(current, 0o700)
            current = current / part
        current.mkdir(mode=0o700, parents=False, exist_ok=True)
        os.chmod(current, 0o700)


def digest_canonical_bars(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start: date,
) -> str:
    payload = [
        {
            "bar_end": bar.bar_end.astimezone(UTC).isoformat(),
            "trading_day": bar.trading_day.isoformat(),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "turnover": str(bar.turnover) if bar.turnover is not None else None,
            "open_interest": (
                str(bar.open_interest) if bar.open_interest is not None else None
            ),
            "contract": contract,
            "segment_start_trading_day": segment_start.isoformat(),
        }
        for bar in bars
    ]
    return sha256(_canonical_bytes(payload)).hexdigest()


def digest_direction_contexts(
    contexts: Mapping[date, SubingStrategyDirectionContext],
) -> str:
    payload = [
        {
            "target_trading_day": day.isoformat(),
            "source_trading_day": (
                context.source_trading_day.isoformat()
                if context.source_trading_day is not None
                else None
            ),
            "direction": context.direction.value,
            "reason_codes": list(context.reason_codes),
            "daily_bar_end": (
                context.daily_bar_end.astimezone(UTC).isoformat()
                if context.daily_bar_end is not None
                else None
            ),
            "hourly_bar_end": (
                context.hourly_bar_end.astimezone(UTC).isoformat()
                if context.hourly_bar_end is not None
                else None
            ),
            "physical_contract": context.physical_contract,
        }
        for day, context in sorted(contexts.items())
    ]
    return sha256(_canonical_bytes(payload)).hexdigest()


def strategy_policy_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise SubingStrategyCacheError() from None


def _identity_payload(identity: SubingStrategyCacheIdentity) -> dict[str, object]:
    payload = asdict(identity)
    for field in (
        "segment_start_trading_day",
        "segment_end_trading_day",
        "through",
    ):
        payload[field] = payload[field].isoformat()
    for field in (
        "cutoff_1m",
        "cutoff_5m",
        "cutoff_15m",
        "cutoff_d1",
        "cutoff_60m",
    ):
        payload[field] = payload[field].astimezone(UTC).isoformat()
    return payload


def _projection_payload(
    projection: CachedSubingStrategySegmentProjection,
) -> dict[str, object]:
    return {
        "actions": [_action_payload(action) for action in projection.actions],
        "episodes": [_episode_payload(episode) for episode in projection.episodes],
        "final_position": projection.final_position.value,
        "pending_action": projection.pending_action,
    }


def _action_payload(action: SubingStrategyAction) -> dict[str, object]:
    return {
        "action_id": action.action_id,
        "episode_id": action.episode_id,
        "strategy_id": action.strategy_id,
        "formula_version": action.formula_version,
        "kind": action.kind.value,
        "symbol": action.symbol,
        "contract": action.contract,
        "trading_day": action.trading_day.isoformat(),
        "segment_start_trading_day": action.segment_start_trading_day.isoformat(),
        "opportunity_id": action.opportunity_id,
        "decision_at": action.decision_at.astimezone(UTC).isoformat(),
        "effective_open_at": (
            action.effective_open_at.astimezone(UTC).isoformat()
            if action.effective_open_at is not None
            else None
        ),
        "effective_bar_end": action.effective_bar_end.astimezone(UTC).isoformat(),
        "reference_price": str(action.reference_price),
        "fill_basis": action.fill_basis.value,
        "confirmation_source": (
            action.confirmation_source.value
            if action.confirmation_source is not None
            else None
        ),
        "reason_codes": list(action.reason_codes),
        "direction_context_source_day": (
            action.direction_context_source_day.isoformat()
            if action.direction_context_source_day is not None
            else None
        ),
        "direction_context_target_day": (
            action.direction_context_target_day.isoformat()
            if action.direction_context_target_day is not None
            else None
        ),
        "bound_reference_pivot": _pivot_payload(action.bound_reference_pivot),
    }


def _episode_payload(episode: SubingStrategyEpisode) -> dict[str, object]:
    return {
        "episode_id": episode.episode_id,
        "direction": episode.direction.value,
        "entry_action": _action_payload(episode.entry_action),
        "exit_action": (
            _action_payload(episode.exit_action)
            if episode.exit_action is not None
            else None
        ),
        "state": episode.state.value,
        "holding_bar_count": episode.holding_bar_count,
        "reference_change_percent": _decimal_text(episode.reference_change_percent),
        "current_reference_change_percent": _decimal_text(
            episode.current_reference_change_percent
        ),
        "latest_reference_price": _decimal_text(episode.latest_reference_price),
        "exit_reason_codes": list(episode.exit_reason_codes),
        "structure_exit_available": episode.structure_exit_available,
    }


def _pivot_payload(pivot: ConfirmedPivot | None) -> dict[str, object] | None:
    if pivot is None:
        return None
    return {
        "pivot_id": pivot.pivot_id,
        "kind": pivot.kind.value,
        "source_timeframe": pivot.source_timeframe.value,
        "pivot_time": pivot.pivot_time.astimezone(UTC).isoformat(),
        "confirmed_at": pivot.confirmed_at.astimezone(UTC).isoformat(),
        "price": str(pivot.price),
        "contract": pivot.contract,
        "segment_start_trading_day": pivot.segment_start_trading_day.isoformat(),
    }


def _parse_projection(payload: object) -> CachedSubingStrategySegmentProjection:
    if not isinstance(payload, dict):
        raise SubingStrategyCacheError()
    try:
        actions = tuple(_parse_action(item) for item in payload["actions"])
        episodes = tuple(_parse_episode(item) for item in payload["episodes"])
        final_position = SubingStrategyPositionState(payload["final_position"])
        pending_action = payload["pending_action"]
    except (KeyError, TypeError, ValueError):
        raise SubingStrategyCacheError() from None
    if type(pending_action) is not bool:
        raise SubingStrategyCacheError()
    action_ids = {action.action_id for action in actions}
    if len(action_ids) != len(actions):
        raise SubingStrategyCacheError()
    return CachedSubingStrategySegmentProjection(
        actions=actions,
        episodes=episodes,
        final_position=final_position,
        pending_action=pending_action,
    )


def _parse_action(payload: object) -> SubingStrategyAction:
    if not isinstance(payload, dict):
        raise SubingStrategyCacheError()
    try:
        return SubingStrategyAction(
            action_id=str(payload["action_id"]),
            episode_id=str(payload["episode_id"]),
            strategy_id=str(payload["strategy_id"]),
            formula_version=str(payload["formula_version"]),
            kind=SubingStrategyActionKind(payload["kind"]),
            symbol=str(payload["symbol"]),
            contract=str(payload["contract"]),
            trading_day=date.fromisoformat(str(payload["trading_day"])),
            segment_start_trading_day=date.fromisoformat(
                str(payload["segment_start_trading_day"])
            ),
            opportunity_id=str(payload["opportunity_id"]),
            decision_at=datetime.fromisoformat(str(payload["decision_at"])),
            effective_open_at=(
                datetime.fromisoformat(str(payload["effective_open_at"]))
                if payload["effective_open_at"] is not None
                else None
            ),
            effective_bar_end=datetime.fromisoformat(str(payload["effective_bar_end"])),
            reference_price=_decimal(payload["reference_price"]),
            fill_basis=SubingStrategyFillBasis(payload["fill_basis"]),
            confirmation_source=(
                ConfirmationSource(payload["confirmation_source"])
                if payload["confirmation_source"] is not None
                else None
            ),
            reason_codes=tuple(payload["reason_codes"]),
            direction_context_source_day=(
                date.fromisoformat(str(payload["direction_context_source_day"]))
                if payload["direction_context_source_day"] is not None
                else None
            ),
            direction_context_target_day=(
                date.fromisoformat(str(payload["direction_context_target_day"]))
                if payload["direction_context_target_day"] is not None
                else None
            ),
            bound_reference_pivot=_parse_pivot(payload["bound_reference_pivot"]),
        )
    except (KeyError, TypeError, ValueError):
        raise SubingStrategyCacheError() from None


def _parse_episode(payload: object) -> SubingStrategyEpisode:
    if not isinstance(payload, dict):
        raise SubingStrategyCacheError()
    try:
        entry = _parse_action(payload["entry_action"])
        exit_action = (
            _parse_action(payload["exit_action"])
            if payload["exit_action"] is not None
            else None
        )
        episode = SubingStrategyEpisode(
            episode_id=str(payload["episode_id"]),
            direction=SubingDirection(payload["direction"]),
            entry_action=entry,
            exit_action=exit_action,
            state=SubingStrategyEpisodeState(payload["state"]),
            holding_bar_count=int(payload["holding_bar_count"]),
            reference_change_percent=_optional_decimal(
                payload["reference_change_percent"]
            ),
            current_reference_change_percent=_optional_decimal(
                payload["current_reference_change_percent"]
            ),
            latest_reference_price=_optional_decimal(payload["latest_reference_price"]),
            exit_reason_codes=tuple(payload["exit_reason_codes"]),
            structure_exit_available=payload["structure_exit_available"],
        )
    except (KeyError, TypeError, ValueError):
        raise SubingStrategyCacheError() from None
    if (
        episode.episode_id != entry.episode_id
        or episode.holding_bar_count < 1
        or type(episode.structure_exit_available) is not bool
        or (exit_action is None) != (episode.state is SubingStrategyEpisodeState.OPEN)
        or (
            exit_action is not None
            and (
                exit_action.episode_id != episode.episode_id
                or episode.exit_reason_codes != exit_action.reason_codes
            )
        )
    ):
        raise SubingStrategyCacheError()
    return episode


def _parse_pivot(payload: object) -> ConfirmedPivot | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise SubingStrategyCacheError()
    try:
        return ConfirmedPivot(
            pivot_id=str(payload["pivot_id"]),
            kind=PivotKind(payload["kind"]),
            source_timeframe=BarFrequency(payload["source_timeframe"]),
            pivot_time=datetime.fromisoformat(str(payload["pivot_time"])),
            confirmed_at=datetime.fromisoformat(str(payload["confirmed_at"])),
            price=_decimal(payload["price"]),
            contract=str(payload["contract"]),
            segment_start_trading_day=date.fromisoformat(
                str(payload["segment_start_trading_day"])
            ),
        )
    except (KeyError, TypeError, ValueError):
        raise SubingStrategyCacheError() from None


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise SubingStrategyCacheError()
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise SubingStrategyCacheError() from None
    if not result.is_finite():
        raise SubingStrategyCacheError()
    return result


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
