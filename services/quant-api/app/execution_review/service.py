"""Transactional mutation authority for Execution Review human facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent
from app.execution_review.contracts import (
    MULTIPLIER_POLICY_ID,
    STOP_BASES,
    ExecutionReviewContractError,
    validate_execution_reasons,
    validate_not_executed,
    validate_review,
)
from app.execution_review.eligibility import eligible_event
from app.execution_review.errors import (
    ExecutionReviewDomainError,
    conflict as _conflict,
    invalid as _invalid,
    not_found as _not_found,
    persistence_failure as _persistence_failure,
)
from app.execution_review.models import (
    TradeDecision,
    TradeEpisode,
    TradeExecution,
    TradeReview,
)
from app.execution_review.pnl import (
    ExecutionFact,
    ExecutionTopologyError,
    PositionState,
    calculate_position_state,
)

MAX_DATABASE_INTEGER = 2_147_483_647
MAX_DATABASE_DECIMAL = Decimal("10000000000000000")


class DefensiveReconcileResult(Protocol):
    @property
    def status(self) -> str: ...


@dataclass(frozen=True, slots=True)
class NotExecutedCommand:
    primary_reason: str
    secondary_reasons: tuple[str, ...] = ()
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedCommand:
    executed_at: datetime
    price: Decimal
    quantity: int
    execution_reason_tags: tuple[str, ...]
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    planned_stop_price: Decimal | None = None
    stop_basis: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedResult:
    decision: TradeDecision
    episode: TradeEpisode
    execution: TradeExecution
    position: PositionState


@dataclass(frozen=True, slots=True)
class ExecutionCommand:
    execution_type: str
    executed_at: datetime
    price: Decimal
    quantity: int
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    episode: TradeEpisode
    execution: TradeExecution
    position: PositionState


@dataclass(frozen=True, slots=True)
class ExecutionUpdateCommand:
    executed_at: datetime
    price: Decimal
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TimelineExecutionCommand:
    execution_id: int | None
    execution_type: str
    executed_at: datetime
    price: Decimal
    quantity: int
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TimelineResult:
    episode: TradeEpisode
    executions: tuple[TradeExecution, ...]
    position: PositionState


@dataclass(frozen=True, slots=True)
class DecisionUpdateCommand:
    first_viewed_at: datetime | None
    decided_at: datetime
    primary_not_execute_reason: str | None
    secondary_not_execute_reasons: tuple[str, ...]
    note: str | None
    execution_reason_tags: tuple[str, ...]
    planned_stop_price: Decimal | None
    stop_basis: str | None


@dataclass(frozen=True, slots=True)
class DispositionCorrectionCommand:
    target_disposition: str
    primary_reason: str | None = None
    secondary_reasons: tuple[str, ...] = ()
    execution_reason_tags: tuple[str, ...] = ()
    executed_at: datetime | None = None
    price: Decimal | None = None
    quantity: int | None = None
    first_viewed_at: datetime | None = None
    decided_at: datetime | None = None
    planned_stop_price: Decimal | None = None
    stop_basis: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DispositionCorrectionResult:
    decision: TradeDecision
    episode: TradeEpisode | None
    execution: TradeExecution | None
    position: PositionState | None


@dataclass(frozen=True, slots=True)
class ReviewCommand:
    signal_execution_adherence: str
    entry_tags: tuple[str, ...]
    holding_tags: tuple[str, ...]
    exit_tags: tuple[str, ...]
    market_context_tags: tuple[str, ...]
    psychology_tags: tuple[str, ...]
    summary: str | None = None


class ExecutionReviewService:
    """Own every Execution Review mutation for one request-scoped Session."""

    def __init__(
        self,
        session: Session,
        *,
        multipliers: Mapping[str, Decimal],
        clock: Callable[[], datetime],
        reconcile_symbol: Callable[[str], DefensiveReconcileResult] | None = None,
    ) -> None:
        self._session = session
        self._multipliers = dict(multipliers)
        self._clock = clock
        self._reconcile_symbol = reconcile_symbol

    def record_not_executed(
        self,
        event_id: int,
        command: NotExecutedCommand,
    ) -> TradeDecision:
        """Atomically store one eligible Event's NOT_EXECUTED decision."""

        try:
            event, _ = eligible_event(self._session, event_id)
            if self._decision_for_event(event.id) is not None:
                raise _conflict("DECISION_ALREADY_EXISTS")
            try:
                validate_not_executed(
                    primary_reason=command.primary_reason,
                    secondary_reasons=command.secondary_reasons,
                    note=command.note,
                )
            except ExecutionReviewContractError as exc:
                raise _invalid(exc.code) from None
            decided_at = command.decided_at or self._clock()
            _require_aware(decided_at)
            if command.first_viewed_at is not None:
                _require_aware(command.first_viewed_at)
            if _utc(decided_at) < _utc(event.bar_end):
                raise _invalid("DECISION_TIME_BEFORE_SIGNAL")
            decision = TradeDecision(
                alert_event_id=event.id,
                disposition="NOT_EXECUTED",
                first_viewed_at=command.first_viewed_at,
                decided_at=decided_at,
                primary_not_execute_reason=command.primary_reason,
                secondary_not_execute_reasons=list(command.secondary_reasons),
                decision_note=command.note,
                execution_reason_tags=[],
                planned_stop_price=None,
                stop_basis=None,
            )
            self._session.add(decision)
            self._commit_rows(decision)
            return decision
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def record_executed(
        self,
        event_id: int,
        command: ExecutedCommand,
    ) -> ExecutedResult:
        """Atomically create an EXECUTED Decision and its OPEN or ADD fact."""

        event_symbol: str | None = None
        event_contract: str | None = None
        event_direction: str | None = None
        try:
            event, direction = eligible_event(self._session, event_id)
            event_symbol = event.symbol
            event_contract = event.contract
            event_direction = direction
            if self._decision_for_event(event.id) is not None:
                raise _conflict("DECISION_ALREADY_EXISTS")
            self._validate_executed_command(event, command)
            has_open_episode = (
                self._session.scalar(
                    select(TradeEpisode.id)
                    .where(
                        TradeEpisode.symbol == event.symbol,
                        TradeEpisode.closed_at.is_(None),
                    )
                    .limit(1)
                )
                is not None
            )
            if has_open_episode and self._reconcile_symbol is not None:
                try:
                    reconcile_result = self._reconcile_symbol(event.symbol)
                except ExecutionReviewDomainError:
                    raise
                except Exception:
                    raise _persistence_failure() from None
                if reconcile_result.status == "ROLL_RECONCILIATION_REQUIRED":
                    raise _conflict("ROLL_RECONCILIATION_REQUIRED")
                if reconcile_result.status not in {"NOOP", "DOMINANT_ROLL"}:
                    raise _persistence_failure()
                self._session.expire_all()
                event, direction = eligible_event(self._session, event_id)
                event_symbol = event.symbol
                event_contract = event.contract
                event_direction = direction
                if self._decision_for_event(event.id) is not None:
                    raise _conflict("DECISION_ALREADY_EXISTS")
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(
                    TradeEpisode.symbol == event.symbol,
                    TradeEpisode.closed_at.is_(None),
                )
                .with_for_update()
            )
            if episode is not None and episode.contract != event.contract:
                raise _conflict("OPEN_EPISODE_CONFLICT")
            if episode is not None and episode.direction != direction:
                raise _conflict("OPPOSITE_EPISODE_OPEN")

            decided_at = command.decided_at or command.executed_at
            decision = TradeDecision(
                alert_event_id=event.id,
                disposition="EXECUTED",
                first_viewed_at=command.first_viewed_at,
                decided_at=decided_at,
                primary_not_execute_reason=None,
                secondary_not_execute_reasons=[],
                decision_note=command.note,
                execution_reason_tags=list(command.execution_reason_tags),
                planned_stop_price=command.planned_stop_price,
                stop_basis=command.stop_basis,
            )
            self._session.add(decision)
            self._session.flush()

            if episode is None:
                multiplier = self._multipliers.get(event.symbol)
                episode = TradeEpisode(
                    origin_decision_id=decision.id,
                    symbol=event.symbol,
                    contract=event.contract,
                    direction=direction,
                    opened_at=command.executed_at,
                    closed_at=None,
                    close_reason=None,
                    roll_reference_exit_price=None,
                    roll_reference_bar_end=None,
                    contract_multiplier_snapshot=multiplier,
                    multiplier_policy_id=(
                        MULTIPLIER_POLICY_ID if multiplier is not None else None
                    ),
                )
                self._session.add(episode)
                self._session.flush()
                execution_type = "OPEN"
                sequence_no = 1
                existing_facts: tuple[ExecutionFact, ...] = ()
            else:
                existing_facts = self._execution_facts(episode.id)
                execution_type = "ADD"
                sequence_no = len(existing_facts) + 1

            execution = TradeExecution(
                episode_id=episode.id,
                trigger_decision_id=decision.id,
                sequence_no=sequence_no,
                execution_type=execution_type,
                executed_at=command.executed_at,
                price=command.price,
                quantity=command.quantity,
                note=command.note,
            )
            candidate = existing_facts + (
                ExecutionFact(
                    sequence_no=sequence_no,
                    execution_type=execution_type,
                    price=command.price,
                    quantity=command.quantity,
                ),
            )
            position = self._calculate_position(episode, candidate)
            self._session.add(execution)
            self._commit_rows(decision, episode, execution)
            return ExecutedResult(
                decision=decision,
                episode=episode,
                execution=execution,
                position=position,
            )
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            constraint_name = _constraint_name(exc)
            self._session.rollback()
            if (
                constraint_name == "uq_trade_episodes_symbol_open"
                and event_symbol is not None
            ):
                raise self._open_episode_race_error(
                    symbol=event_symbol,
                    contract=event_contract,
                    direction=event_direction,
                ) from None
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def append_execution(
        self,
        episode_id: int,
        command: ExecutionCommand,
    ) -> ExecutionResult:
        """Append one manual fact with a server-owned consecutive sequence."""

        try:
            if command.execution_type == "OPEN":
                raise _invalid("MANUAL_OPEN_NOT_ALLOWED")
            if command.execution_type not in {"ADD", "REDUCE", "CLOSE"}:
                raise _invalid("EXECUTION_TYPE_INVALID")
            _require_aware(command.executed_at)
            _validate_price_quantity(command.price, command.quantity)
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(TradeEpisode.id == episode_id)
                .with_for_update()
            )
            if episode is None:
                raise _not_found("TRADE_EPISODE_NOT_FOUND")
            if episode.closed_at is not None:
                raise _conflict("EPISODE_ALREADY_CLOSED")
            existing_facts = self._execution_facts(episode.id)
            sequence_no = len(existing_facts) + 1
            candidate = existing_facts + (
                ExecutionFact(
                    sequence_no=sequence_no,
                    execution_type=command.execution_type,
                    price=command.price,
                    quantity=command.quantity,
                ),
            )
            position = self._calculate_position(episode, candidate)
            if command.execution_type == "CLOSE" and _utc(command.executed_at) < _utc(
                episode.opened_at
            ):
                raise _invalid("EXECUTION_REVIEW_TIME_INVALID")
            execution = TradeExecution(
                episode_id=episode.id,
                trigger_decision_id=None,
                sequence_no=sequence_no,
                execution_type=command.execution_type,
                executed_at=command.executed_at,
                price=command.price,
                quantity=command.quantity,
                note=command.note,
            )
            self._session.add(execution)
            if command.execution_type == "CLOSE":
                episode.closed_at = command.executed_at
                episode.close_reason = "EXECUTION_NET_ZERO"
                episode.roll_reference_exit_price = None
                episode.roll_reference_bar_end = None
            self._commit_rows(episode, execution)
            return ExecutionResult(
                episode=episode,
                execution=execution,
                position=position,
            )
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def update_execution(
        self,
        execution_id: int,
        command: ExecutionUpdateCommand,
    ) -> ExecutionResult:
        """Correct only time, price, and note without changing lineage/topology."""

        try:
            identity = self._session.execute(
                select(
                    TradeExecution.episode_id,
                    TradeExecution.trigger_decision_id,
                ).where(TradeExecution.id == execution_id)
            ).one_or_none()
            if identity is None:
                raise _not_found("TRADE_EXECUTION_NOT_FOUND")
            if identity.trigger_decision_id is not None:
                decision = self._session.scalar(
                    select(TradeDecision)
                    .where(TradeDecision.id == identity.trigger_decision_id)
                    .with_for_update()
                )
                if decision is None:
                    raise _conflict("DECISION_LINEAGE_INVALID")
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(TradeEpisode.id == identity.episode_id)
                .with_for_update()
            )
            if episode is None:
                raise _not_found("TRADE_EPISODE_NOT_FOUND")
            execution = self._session.scalar(
                select(TradeExecution)
                .where(TradeExecution.id == execution_id)
                .with_for_update()
            )
            if (
                execution is None
                or execution.episode_id != episode.id
                or execution.trigger_decision_id != identity.trigger_decision_id
            ):
                raise _conflict("EXECUTION_CORRECTION_CONFLICT")
            if episode.close_reason == "DOMINANT_ROLL":
                raise _conflict("EXECUTION_CORRECTION_CONFLICT")
            _require_aware(command.executed_at)
            _validate_price_quantity(command.price, execution.quantity)
            self._validate_trigger_time(
                execution.trigger_decision_id, command.executed_at
            )
            facts = tuple(
                ExecutionFact(
                    sequence_no=row.sequence_no,
                    execution_type=row.execution_type,
                    price=command.price if row.id == execution.id else row.price,
                    quantity=row.quantity,
                )
                for row in self._executions(episode.id)
            )
            position = self._calculate_position(episode, facts)
            execution.executed_at = command.executed_at
            execution.price = command.price
            execution.note = command.note
            if execution.execution_type == "OPEN":
                if episode.closed_at is not None and _utc(command.executed_at) > _utc(
                    episode.closed_at
                ):
                    raise _invalid("EXECUTION_REVIEW_TIME_INVALID")
                episode.opened_at = command.executed_at
            if execution.execution_type == "CLOSE":
                if _utc(command.executed_at) < _utc(episode.opened_at):
                    raise _invalid("EXECUTION_REVIEW_TIME_INVALID")
                episode.closed_at = command.executed_at
            self._commit_rows(episode, execution)
            return ExecutionResult(
                episode=episode,
                execution=execution,
                position=position,
            )
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def replace_execution_timeline(
        self,
        episode_id: int,
        commands: tuple[TimelineExecutionCommand, ...],
    ) -> TimelineResult:
        """Atomically rebuild a complete client-ordered timeline as ``1..N``."""

        try:
            preexisting = tuple(
                self._session.execute(
                    select(
                        TradeExecution.id,
                        TradeExecution.trigger_decision_id,
                    ).where(TradeExecution.episode_id == episode_id)
                ).all()
            )
            trigger_decision_ids = sorted(
                row.trigger_decision_id
                for row in preexisting
                if row.trigger_decision_id is not None
            )
            if trigger_decision_ids:
                locked_decision_ids = set(
                    self._session.scalars(
                        select(TradeDecision.id)
                        .where(TradeDecision.id.in_(trigger_decision_ids))
                        .order_by(TradeDecision.id)
                        .with_for_update()
                    ).all()
                )
                if locked_decision_ids != set(trigger_decision_ids):
                    raise _conflict("DECISION_LINEAGE_INVALID")
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(TradeEpisode.id == episode_id)
                .with_for_update()
            )
            if episode is None:
                raise _not_found("TRADE_EPISODE_NOT_FOUND")
            replacing_roll_estimate = episode.close_reason == "DOMINANT_ROLL"
            existing = self._executions(episode.id, for_update=True)
            if {(row.id, row.trigger_decision_id) for row in existing} != {
                (row.id, row.trigger_decision_id) for row in preexisting
            }:
                raise _conflict("EXECUTION_CORRECTION_CONFLICT")
            existing_by_id = {row.id: row for row in existing}
            supplied_ids = tuple(
                command.execution_id
                for command in commands
                if command.execution_id is not None
            )
            if len(supplied_ids) != len(set(supplied_ids)):
                raise _invalid("EXECUTION_LINEAGE_INVALID")
            if any(row_id not in existing_by_id for row_id in supplied_ids):
                raise _invalid("EXECUTION_LINEAGE_INVALID")
            triggered_ids = {
                row.id for row in existing if row.trigger_decision_id is not None
            }
            if triggered_ids != {
                row_id
                for row_id in supplied_ids
                if existing_by_id[row_id].trigger_decision_id is not None
            }:
                raise _invalid("EXECUTION_LINEAGE_INVALID")

            facts: list[ExecutionFact] = []
            lineage: list[int | None] = []
            for sequence_no, command in enumerate(commands, start=1):
                _require_aware(command.executed_at)
                _validate_price_quantity(command.price, command.quantity)
                existing_row = (
                    existing_by_id.get(command.execution_id)
                    if command.execution_id is not None
                    else None
                )
                trigger_id = (
                    existing_row.trigger_decision_id
                    if existing_row is not None
                    else None
                )
                if trigger_id is not None:
                    required_type = (
                        "OPEN" if trigger_id == episode.origin_decision_id else "ADD"
                    )
                    if command.execution_type != required_type:
                        raise _invalid("EXECUTION_LINEAGE_INVALID")
                    if required_type == "OPEN" and sequence_no != 1:
                        raise _invalid("EXECUTION_LINEAGE_INVALID")
                    self._validate_trigger_time(trigger_id, command.executed_at)
                elif command.execution_type == "OPEN":
                    raise _invalid("EXECUTION_LINEAGE_INVALID")
                facts.append(
                    ExecutionFact(
                        sequence_no=sequence_no,
                        execution_type=command.execution_type,
                        price=command.price,
                        quantity=command.quantity,
                    )
                )
                lineage.append(trigger_id)
            position = self._calculate_position(episode, tuple(facts))
            if replacing_roll_estimate and (
                position.remaining_quantity != 0
                or not commands
                or commands[-1].execution_type != "CLOSE"
            ):
                raise _conflict("EXECUTION_CORRECTION_CONFLICT")
            if position.remaining_quantity == 0 and _utc(
                commands[-1].executed_at
            ) < _utc(commands[0].executed_at):
                raise _invalid("EXECUTION_REVIEW_TIME_INVALID")
            if (
                position.remaining_quantity > 0
                and self._session.scalar(
                    select(TradeReview.id).where(TradeReview.episode_id == episode.id)
                )
                is not None
            ):
                raise _conflict("REVIEW_LINEAGE_CONFLICT")

            for row in existing:
                self._session.expunge(row)
            self._session.execute(
                delete(TradeExecution).where(TradeExecution.episode_id == episode.id)
            )
            self._session.flush()
            rebuilt: list[TradeExecution] = []
            for sequence_no, (command, trigger_id) in enumerate(
                zip(commands, lineage, strict=True),
                start=1,
            ):
                row = TradeExecution(
                    id=command.execution_id,
                    episode_id=episode.id,
                    trigger_decision_id=trigger_id,
                    sequence_no=sequence_no,
                    execution_type=command.execution_type,
                    executed_at=command.executed_at,
                    price=command.price,
                    quantity=command.quantity,
                    note=command.note,
                )
                self._session.add(row)
                rebuilt.append(row)
            episode.opened_at = commands[0].executed_at
            if position.remaining_quantity == 0:
                episode.closed_at = commands[-1].executed_at
                episode.close_reason = "EXECUTION_NET_ZERO"
            else:
                episode.closed_at = None
                episode.close_reason = None
            episode.roll_reference_exit_price = None
            episode.roll_reference_bar_end = None
            self._commit_rows(episode, *rebuilt)
            return TimelineResult(
                episode=episode,
                executions=tuple(rebuilt),
                position=position,
            )
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def update_decision(
        self,
        decision_id: int,
        command: DecisionUpdateCommand,
    ) -> TradeDecision:
        """Update fields under the Decision's immutable disposition contract."""

        try:
            decision = self._session.scalar(
                select(TradeDecision)
                .where(TradeDecision.id == decision_id)
                .with_for_update()
            )
            if decision is None:
                raise _not_found("TRADE_DECISION_NOT_FOUND")
            event = self._event_for_decision(decision)
            _require_aware(command.decided_at)
            if command.first_viewed_at is not None:
                _require_aware(command.first_viewed_at)
            if _utc(command.decided_at) < _utc(event.bar_end):
                raise _invalid("DECISION_TIME_BEFORE_SIGNAL")
            if decision.disposition == "NOT_EXECUTED":
                if (
                    command.execution_reason_tags
                    or command.planned_stop_price is not None
                    or command.stop_basis is not None
                ):
                    raise _invalid("DECISION_FIELDS_INVALID")
                try:
                    validate_not_executed(
                        primary_reason=command.primary_not_execute_reason,
                        secondary_reasons=command.secondary_not_execute_reasons,
                        note=command.note,
                    )
                except ExecutionReviewContractError as exc:
                    raise _invalid(exc.code) from None
            else:
                if (
                    command.primary_not_execute_reason is not None
                    or command.secondary_not_execute_reasons
                ):
                    raise _invalid("DECISION_FIELDS_INVALID")
                try:
                    validate_execution_reasons(command.execution_reason_tags)
                except ExecutionReviewContractError as exc:
                    raise _invalid(exc.code) from None
                _validate_stop(command.planned_stop_price, command.stop_basis)
                trigger_episode_id = self._session.scalar(
                    select(TradeExecution.episode_id).where(
                        TradeExecution.trigger_decision_id == decision.id,
                    )
                )
                if trigger_episode_id is None:
                    raise _conflict("DECISION_LINEAGE_INVALID")
                episode = self._session.scalar(
                    select(TradeEpisode)
                    .where(TradeEpisode.id == trigger_episode_id)
                    .with_for_update()
                )
                trigger = self._session.scalar(
                    select(TradeExecution)
                    .where(TradeExecution.trigger_decision_id == decision.id)
                    .with_for_update()
                )
                if episode is None or trigger is None:
                    raise _conflict("DECISION_LINEAGE_INVALID")
                if _utc(command.decided_at) > _utc(trigger.executed_at):
                    raise _invalid("DECISION_AFTER_EXECUTION")
            decision.first_viewed_at = command.first_viewed_at
            decision.decided_at = command.decided_at
            decision.primary_not_execute_reason = command.primary_not_execute_reason
            decision.secondary_not_execute_reasons = list(
                command.secondary_not_execute_reasons
            )
            decision.decision_note = command.note
            decision.execution_reason_tags = list(command.execution_reason_tags)
            decision.planned_stop_price = command.planned_stop_price
            decision.stop_basis = command.stop_basis
            self._commit_rows(decision)
            return decision
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def correct_disposition(
        self,
        decision_id: int,
        command: DispositionCorrectionCommand,
    ) -> DispositionCorrectionResult:
        """Perform the only bounded transition between Decision dispositions."""

        race_context: tuple[str, str, str] | None = None
        try:
            decision = self._session.scalar(
                select(TradeDecision)
                .where(TradeDecision.id == decision_id)
                .with_for_update()
            )
            if decision is None:
                raise _not_found("TRADE_DECISION_NOT_FOUND")
            if command.target_disposition not in {"EXECUTED", "NOT_EXECUTED"}:
                raise _invalid("DECISION_DISPOSITION_INVALID")
            if decision.disposition == command.target_disposition:
                raise _conflict("DECISION_DISPOSITION_UNCHANGED")
            if command.target_disposition == "EXECUTED":
                event = self._event_for_decision(decision)
                _, direction = eligible_event(self._session, event.id)
                race_context = (event.symbol, event.contract, direction)
                result = self._correct_to_executed(decision, command)
            else:
                result = self._correct_to_not_executed(decision, command)
            rows: list[object] = [decision]
            if result.episode is not None:
                rows.append(result.episode)
            if result.execution is not None:
                rows.append(result.execution)
            self._commit_rows(*rows)
            return result
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            constraint_name = _constraint_name(exc)
            self._session.rollback()
            if (
                constraint_name == "uq_trade_episodes_symbol_open"
                and race_context is not None
            ):
                symbol, contract, direction = race_context
                raise self._open_episode_race_error(
                    symbol=symbol,
                    contract=contract,
                    direction=direction,
                ) from None
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def submit_review(
        self,
        episode_id: int,
        command: ReviewCommand,
    ) -> TradeReview:
        """Create the first structured Review for a closed Episode."""

        try:
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(TradeEpisode.id == episode_id)
                .with_for_update()
            )
            if episode is None:
                raise _not_found("TRADE_EPISODE_NOT_FOUND")
            if episode.closed_at is None:
                raise _conflict("EPISODE_REVIEW_NOT_READY")
            if (
                self._session.scalar(
                    select(TradeReview.id).where(TradeReview.episode_id == episode.id)
                )
                is not None
            ):
                raise _conflict("REVIEW_ALREADY_EXISTS")
            self._validate_review(command)
            now = self._clock()
            _require_aware(now)
            review = TradeReview(
                episode_id=episode.id,
                signal_execution_adherence=command.signal_execution_adherence,
                entry_tags=list(command.entry_tags),
                holding_tags=list(command.holding_tags),
                exit_tags=list(command.exit_tags),
                market_context_tags=list(command.market_context_tags),
                psychology_tags=list(command.psychology_tags),
                summary=command.summary,
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(review)
            self._commit_rows(review)
            return review
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def update_review(self, review_id: int, command: ReviewCommand) -> TradeReview:
        """Edit structured Review content while preserving first submission time."""

        try:
            review = self._session.scalar(
                select(TradeReview).where(TradeReview.id == review_id).with_for_update()
            )
            if review is None:
                raise _not_found("TRADE_REVIEW_NOT_FOUND")
            self._validate_review(command)
            now = self._clock()
            _require_aware(now)
            review.signal_execution_adherence = command.signal_execution_adherence
            review.entry_tags = list(command.entry_tags)
            review.holding_tags = list(command.holding_tags)
            review.exit_tags = list(command.exit_tags)
            review.market_context_tags = list(command.market_context_tags)
            review.psychology_tags = list(command.psychology_tags)
            review.summary = command.summary
            review.updated_at = now
            self._commit_rows(review)
            return review
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            raise self._integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    @staticmethod
    def _validate_review(command: ReviewCommand) -> None:
        try:
            validate_review(
                signal_execution_adherence=command.signal_execution_adherence,
                entry_tags=command.entry_tags,
                holding_tags=command.holding_tags,
                exit_tags=command.exit_tags,
                market_context_tags=command.market_context_tags,
                psychology_tags=command.psychology_tags,
            )
        except ExecutionReviewContractError as exc:
            raise _invalid(exc.code) from None

    def _commit_rows(self, *rows: object) -> None:
        """Commit without any fallible database read after transaction success."""

        self._session.flush()
        for row in rows:
            if row in self._session:
                self._session.expunge(row)
        self._session.commit()

    def _open_episode_race_error(
        self,
        *,
        symbol: str,
        contract: str | None,
        direction: str | None,
    ) -> ExecutionReviewDomainError:
        """Classify a rolled-back OPEN race from scalar winner facts."""

        try:
            winner = self._session.execute(
                select(TradeEpisode.contract, TradeEpisode.direction).where(
                    TradeEpisode.symbol == symbol,
                    TradeEpisode.closed_at.is_(None),
                )
            ).one_or_none()
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None
        self._session.rollback()
        if winner is not None and winner.contract != contract:
            return _conflict("OPEN_EPISODE_CONFLICT")
        if winner is not None and winner.direction != direction:
            return _conflict("OPPOSITE_EPISODE_OPEN")
        return _conflict("OPEN_EPISODE_CONFLICT")

    def _correct_to_executed(
        self,
        decision: TradeDecision,
        command: DispositionCorrectionCommand,
    ) -> DispositionCorrectionResult:
        if (
            command.primary_reason is not None
            or command.secondary_reasons
            or command.executed_at is None
            or command.price is None
            or command.quantity is None
        ):
            raise _invalid("DECISION_FIELDS_INVALID")
        event = self._event_for_decision(decision)
        executed = ExecutedCommand(
            executed_at=command.executed_at,
            price=command.price,
            quantity=command.quantity,
            execution_reason_tags=command.execution_reason_tags,
            first_viewed_at=command.first_viewed_at,
            decided_at=command.decided_at,
            planned_stop_price=command.planned_stop_price,
            stop_basis=command.stop_basis,
            note=command.note,
        )
        self._validate_executed_command(event, executed)
        _, direction = eligible_event(self._session, event.id)
        episode = self._session.scalar(
            select(TradeEpisode)
            .where(
                TradeEpisode.symbol == event.symbol,
                TradeEpisode.closed_at.is_(None),
            )
            .with_for_update()
        )
        if episode is not None and episode.contract != event.contract:
            raise _conflict("OPEN_EPISODE_CONFLICT")
        if episode is not None and episode.direction != direction:
            raise _conflict("OPPOSITE_EPISODE_OPEN")
        decision.disposition = "EXECUTED"
        decision.first_viewed_at = command.first_viewed_at
        decision.decided_at = command.decided_at or command.executed_at
        decision.primary_not_execute_reason = None
        decision.secondary_not_execute_reasons = []
        decision.decision_note = command.note
        decision.execution_reason_tags = list(command.execution_reason_tags)
        decision.planned_stop_price = command.planned_stop_price
        decision.stop_basis = command.stop_basis
        if episode is None:
            multiplier = self._multipliers.get(event.symbol)
            episode = TradeEpisode(
                origin_decision_id=decision.id,
                symbol=event.symbol,
                contract=event.contract,
                direction=direction,
                opened_at=command.executed_at,
                contract_multiplier_snapshot=multiplier,
                multiplier_policy_id=(
                    MULTIPLIER_POLICY_ID if multiplier is not None else None
                ),
            )
            self._session.add(episode)
            self._session.flush()
            execution_type = "OPEN"
            existing: tuple[ExecutionFact, ...] = ()
        else:
            execution_type = "ADD"
            existing = self._execution_facts(episode.id)
        sequence_no = len(existing) + 1
        execution = TradeExecution(
            episode_id=episode.id,
            trigger_decision_id=decision.id,
            sequence_no=sequence_no,
            execution_type=execution_type,
            executed_at=command.executed_at,
            price=command.price,
            quantity=command.quantity,
            note=command.note,
        )
        position = self._calculate_position(
            episode,
            existing
            + (
                ExecutionFact(
                    sequence_no=sequence_no,
                    execution_type=execution_type,
                    price=command.price,
                    quantity=command.quantity,
                ),
            ),
        )
        self._session.add(execution)
        return DispositionCorrectionResult(decision, episode, execution, position)

    def _correct_to_not_executed(
        self,
        decision: TradeDecision,
        command: DispositionCorrectionCommand,
    ) -> DispositionCorrectionResult:
        if (
            command.execution_reason_tags
            or command.executed_at is not None
            or command.price is not None
            or command.quantity is not None
            or command.planned_stop_price is not None
            or command.stop_basis is not None
        ):
            raise _invalid("DECISION_FIELDS_INVALID")
        try:
            validate_not_executed(
                primary_reason=command.primary_reason,
                secondary_reasons=command.secondary_reasons,
                note=command.note,
            )
        except ExecutionReviewContractError as exc:
            raise _invalid(exc.code) from None
        event = self._event_for_decision(decision)
        decided_at = command.decided_at or self._clock()
        _require_aware(decided_at)
        if command.first_viewed_at is not None:
            _require_aware(command.first_viewed_at)
        if _utc(decided_at) < _utc(event.bar_end):
            raise _invalid("DECISION_TIME_BEFORE_SIGNAL")
        trigger_episode_id = self._session.scalar(
            select(TradeExecution.episode_id).where(
                TradeExecution.trigger_decision_id == decision.id,
            )
        )
        if trigger_episode_id is None:
            raise _conflict("DECISION_CORRECTION_CONFLICT")
        episode = self._session.scalar(
            select(TradeEpisode)
            .where(TradeEpisode.id == trigger_episode_id)
            .with_for_update()
        )
        trigger = self._session.scalar(
            select(TradeExecution)
            .where(TradeExecution.trigger_decision_id == decision.id)
            .with_for_update()
        )
        if (
            episode is None
            or self._session.scalar(
                select(TradeReview.id).where(
                    TradeReview.episode_id == trigger_episode_id
                )
            )
            is not None
        ):
            raise _conflict("DECISION_CORRECTION_CONFLICT")
        if trigger is None or trigger.episode_id != episode.id:
            raise _conflict("DECISION_CORRECTION_CONFLICT")
        rows = self._executions(episode.id)
        is_origin = episode.origin_decision_id == decision.id
        if is_origin:
            if (
                len(rows) != 1
                or trigger.execution_type != "OPEN"
                or episode.closed_at is not None
            ):
                raise _conflict("DECISION_CORRECTION_CONFLICT")
            self._session.delete(trigger)
            self._session.flush()
            self._session.delete(episode)
            resulting_episode: TradeEpisode | None = None
            position = None
        else:
            if trigger.execution_type != "ADD":
                raise _conflict("DECISION_CORRECTION_CONFLICT")
            remaining_rows = tuple(row for row in rows if row.id != trigger.id)
            facts = tuple(
                ExecutionFact(
                    sequence_no=index,
                    execution_type=row.execution_type,
                    price=row.price,
                    quantity=row.quantity,
                )
                for index, row in enumerate(remaining_rows, start=1)
            )
            try:
                position = calculate_position_state(
                    direction=episode.direction,
                    executions=facts,
                    multiplier=episode.contract_multiplier_snapshot,
                )
            except ExecutionTopologyError:
                raise _conflict("DECISION_CORRECTION_CONFLICT") from None
            removed_sequence = trigger.sequence_no
            self._session.delete(trigger)
            self._session.flush()
            for row in remaining_rows:
                if row.sequence_no > removed_sequence:
                    row.sequence_no -= 1
                    self._session.flush()
            if position.remaining_quantity == 0:
                final = remaining_rows[-1]
                episode.closed_at = final.executed_at
                episode.close_reason = "EXECUTION_NET_ZERO"
            else:
                episode.closed_at = None
                episode.close_reason = None
            episode.roll_reference_exit_price = None
            episode.roll_reference_bar_end = None
            resulting_episode = episode
        decision.disposition = "NOT_EXECUTED"
        decision.first_viewed_at = command.first_viewed_at
        decision.decided_at = decided_at
        decision.primary_not_execute_reason = command.primary_reason
        decision.secondary_not_execute_reasons = list(command.secondary_reasons)
        decision.decision_note = command.note
        decision.execution_reason_tags = []
        decision.planned_stop_price = None
        decision.stop_basis = None
        return DispositionCorrectionResult(
            decision=decision,
            episode=resulting_episode,
            execution=None,
            position=position,
        )

    def _decision_for_event(self, event_id: int) -> TradeDecision | None:
        return self._session.scalar(
            select(TradeDecision).where(TradeDecision.alert_event_id == event_id)
        )

    def _event_for_decision(self, decision: TradeDecision) -> AlertEvent:
        event = self._session.get(AlertEvent, decision.alert_event_id)
        if event is None:
            raise _conflict("DECISION_LINEAGE_INVALID")
        return event

    def _validate_executed_command(
        self,
        event: AlertEvent,
        command: ExecutedCommand,
    ) -> None:
        _require_aware(command.executed_at)
        decided_at = command.decided_at or command.executed_at
        _require_aware(decided_at)
        if command.first_viewed_at is not None:
            _require_aware(command.first_viewed_at)
        if _utc(command.executed_at) < _utc(event.bar_end):
            raise _invalid("EXECUTION_TIME_BEFORE_SIGNAL")
        if _utc(decided_at) < _utc(event.bar_end):
            raise _invalid("DECISION_TIME_BEFORE_SIGNAL")
        if _utc(decided_at) > _utc(command.executed_at):
            raise _invalid("DECISION_AFTER_EXECUTION")
        try:
            validate_execution_reasons(command.execution_reason_tags)
        except ExecutionReviewContractError as exc:
            raise _invalid(exc.code) from None
        _validate_price_quantity(command.price, command.quantity)
        _validate_stop(command.planned_stop_price, command.stop_basis)

    def _execution_facts(self, episode_id: int) -> tuple[ExecutionFact, ...]:
        executions = self._executions(episode_id)
        return tuple(
            ExecutionFact(
                sequence_no=row.sequence_no,
                execution_type=row.execution_type,
                price=row.price,
                quantity=row.quantity,
            )
            for row in executions
        )

    def _executions(
        self,
        episode_id: int,
        *,
        for_update: bool = False,
    ) -> tuple[TradeExecution, ...]:
        statement = (
            select(TradeExecution)
            .where(TradeExecution.episode_id == episode_id)
            .order_by(TradeExecution.sequence_no)
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(self._session.scalars(statement).all())

    def _validate_trigger_time(
        self,
        trigger_decision_id: int | None,
        executed_at: datetime,
    ) -> None:
        if trigger_decision_id is None:
            return
        causal_times = self._session.execute(
            select(AlertEvent.bar_end, TradeDecision.decided_at)
            .join(TradeDecision, TradeDecision.alert_event_id == AlertEvent.id)
            .where(TradeDecision.id == trigger_decision_id)
        ).one_or_none()
        if causal_times is None:
            raise _invalid("EXECUTION_TIME_BEFORE_SIGNAL")
        event_bar_end, decided_at = causal_times
        if _utc(executed_at) < _utc(event_bar_end):
            raise _invalid("EXECUTION_TIME_BEFORE_SIGNAL")
        if _utc(executed_at) < _utc(decided_at):
            raise _invalid("DECISION_AFTER_EXECUTION")

    @staticmethod
    def _calculate_position(
        episode: TradeEpisode,
        facts: tuple[ExecutionFact, ...],
    ) -> PositionState:
        try:
            return calculate_position_state(
                direction=episode.direction,
                executions=facts,
                multiplier=episode.contract_multiplier_snapshot,
            )
        except ExecutionTopologyError as exc:
            raise _invalid(exc.code) from None

    @staticmethod
    def _integrity_error(exc: IntegrityError) -> ExecutionReviewDomainError:
        constraint_name = _constraint_name(exc)
        if constraint_name in {
            "uq_trade_decisions_alert_event",
            "uq_trade_episodes_origin_decision",
        }:
            return _conflict("DECISION_ALREADY_EXISTS")
        if constraint_name == "uq_trade_episodes_symbol_open":
            return _conflict("OPEN_EPISODE_CONFLICT")
        if constraint_name == "uq_trade_executions_trigger_decision":
            return _conflict("TRIGGER_DECISION_ALREADY_USED")
        if constraint_name == "uq_trade_executions_episode_sequence":
            return _conflict("EXECUTION_TOPOLOGY_INVALID")
        if constraint_name == "uq_trade_reviews_episode":
            return _conflict("REVIEW_ALREADY_EXISTS")
        return _persistence_failure()


def _require_aware(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _invalid("EXECUTION_REVIEW_TIME_INVALID")


def _validate_price_quantity(price: Decimal, quantity: int) -> None:
    _validate_database_decimal(price, "PRICE_INVALID")
    if type(quantity) is not int or quantity <= 0 or quantity > MAX_DATABASE_INTEGER:
        raise _invalid("EXECUTION_QUANTITY_INVALID")


def _validate_stop(price: Decimal | None, basis: str | None) -> None:
    if price is None:
        if basis is not None:
            raise _invalid("PLANNED_STOP_PRICE_REQUIRED")
        return
    _validate_database_decimal(price, "STOP_PRICE_INVALID")
    if basis is None:
        raise _invalid("STOP_BASIS_REQUIRED")
    if basis not in STOP_BASES:
        raise _invalid("UNKNOWN_STOP_BASIS")


def _validate_database_decimal(value: object, code: str) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= 0
        or value >= MAX_DATABASE_DECIMAL
    ):
        raise _invalid(code)
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -8:
        raise _invalid(code)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostics = getattr(getattr(exc, "orig", None), "diag", None)
    value = getattr(diagnostics, "constraint_name", None)
    return value if isinstance(value, str) else None
