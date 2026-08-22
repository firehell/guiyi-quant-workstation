"""Consistent-snapshot read models for Execution Review."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.alerts.models import AlertEvent, AlertRule
from app.execution_review.eligibility import (
    ELIGIBLE_FREQUENCIES,
    EventContext,
    eligible_direction,
    require_eligible_direction,
)
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
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class ReviewItem:
    item_kind: str
    state: str
    event_id: int
    decision_id: int | None
    episode_id: int | None
    symbol: str
    contract: str
    direction: str
    trading_day: date


@dataclass(frozen=True, slots=True)
class EventReviewState:
    event_id: int
    state: str
    decision_id: int | None
    episode_id: int | None


@dataclass(frozen=True, slots=True)
class OpportunityStats:
    eligible_events: int
    processed_events: int
    pending_events: int
    executed_decisions: int
    not_executed_decisions: int
    decision_completion_rate: Decimal | None
    execution_rate: Decimal | None
    primary_reason_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class EpisodeStateStats:
    open_episodes: int
    pending_review_episodes: int
    done_episodes: int


@dataclass(frozen=True, slots=True)
class ReviewIssueStats:
    entry: dict[str, int]
    holding: dict[str, int]
    exit_risk: dict[str, int]
    psychology: dict[str, int]


@dataclass(frozen=True, slots=True)
class _OpportunitySnapshot:
    event: AlertEvent
    rule_code: str
    decision: TradeDecision | None
    episode: TradeEpisode | None
    review: TradeReview | None


@dataclass(frozen=True, slots=True)
class ExecutionReviewStats:
    opportunities: OpportunityStats
    episode_states: EpisodeStateStats
    review_issue_top: ReviewIssueStats


@dataclass(frozen=True, slots=True)
class EpisodeDetail:
    episode: TradeEpisode
    origin_event: EventContext
    decisions: tuple[TradeDecision, ...]
    executions: tuple[TradeExecution, ...]
    review: TradeReview | None
    position: PositionState


class ExecutionReviewQueryService:
    """Own Execution Review read models for one request-scoped Session."""

    def __init__(
        self,
        session: Session,
        *,
        multipliers: Mapping[str, Decimal],
    ) -> None:
        self._session = session
        self._multipliers = dict(multipliers)

    def list_items(
        self,
        *,
        state: str,
        symbol: str | None = None,
        direction: str | None = None,
        frequency: str | None = None,
        start_trading_day: date | None = None,
        end_trading_day: date | None = None,
    ) -> tuple[ReviewItem, ...]:
        return self._read_call(
            lambda: self._list_items(
                state=state,
                symbol=symbol,
                direction=direction,
                frequency=frequency,
                start_trading_day=start_trading_day,
                end_trading_day=end_trading_day,
            )
        )

    def _list_items(
        self,
        *,
        state: str,
        symbol: str | None = None,
        direction: str | None = None,
        frequency: str | None = None,
        start_trading_day: date | None = None,
        end_trading_day: date | None = None,
    ) -> tuple[ReviewItem, ...]:
        """List opportunity and Episode work items under the canonical states."""

        if state not in {
            "pending_decision",
            "open",
            "pending_review",
            "done",
        }:
            raise _invalid("EXECUTION_REVIEW_STATE_INVALID")
        normalized_symbol = symbol.strip().lower() if symbol is not None else None
        if normalized_symbol == "":
            raise _invalid("EXECUTION_REVIEW_ITEMS_FILTER_INVALID")
        if direction is not None and direction not in {"LONG", "SHORT"}:
            raise _invalid("EXECUTION_REVIEW_ITEMS_FILTER_INVALID")
        if frequency is not None and frequency not in ELIGIBLE_FREQUENCIES:
            raise _invalid("EXECUTION_REVIEW_ITEMS_FILTER_INVALID")
        if (
            state == "done"
            and start_trading_day is not None
            and end_trading_day is not None
            and start_trading_day > end_trading_day
        ):
            raise _invalid("EXECUTION_REVIEW_DATE_RANGE_INVALID")
        items: list[ReviewItem] = []
        for row in self._opportunity_snapshot():
            event = row.event
            event_direction = eligible_direction(event, row.rule_code)
            if event_direction is None:
                continue
            if normalized_symbol is not None and event.symbol != normalized_symbol:
                continue
            if direction is not None and event_direction != direction:
                continue
            if frequency is not None and event.frequency != frequency:
                continue
            decision = row.decision
            if decision is None:
                items.append(
                    self._item(
                        event=event,
                        item_kind="decision",
                        state="pending_decision",
                    )
                )
            elif decision.disposition == "NOT_EXECUTED":
                items.append(
                    self._item(
                        event=event,
                        item_kind="decision",
                        state="done",
                        decision=decision,
                    )
                )
            elif row.episode is not None:
                item_state = (
                    "open"
                    if row.episode.closed_at is None
                    else "done"
                    if row.review is not None
                    else "pending_review"
                )
                items.append(
                    self._item(
                        event=event,
                        item_kind="episode",
                        state=item_state,
                        decision=decision,
                        episode=row.episode,
                    )
                )
        filtered = (item for item in items if item.state == state)
        if state == "done":
            filtered = (
                item
                for item in filtered
                if (start_trading_day is None or item.trading_day >= start_trading_day)
                and (end_trading_day is None or item.trading_day <= end_trading_day)
            )
        return tuple(
            sorted(filtered, key=lambda item: (item.trading_day, item.event_id))
        )

    def event_states(
        self,
        event_ids: tuple[int, ...],
    ) -> tuple[EventReviewState, ...]:
        return self._read_call(lambda: self._event_states(event_ids))

    def _event_states(
        self,
        event_ids: tuple[int, ...],
    ) -> tuple[EventReviewState, ...]:
        """Classify only requested Events using one statement snapshot."""

        requested_ids = tuple(dict.fromkeys(event_ids))
        if not requested_ids or any(
            event_id <= 0 or event_id > MAX_DATABASE_INTEGER
            for event_id in requested_ids
        ):
            raise _invalid("EXECUTION_REVIEW_EVENT_IDS_INVALID")
        rows = self._session.execute(
            select(
                AlertEvent,
                AlertRule.rule_code,
                TradeDecision,
                TradeExecution,
                TradeEpisode,
                TradeReview.id.label("review_id"),
            )
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .outerjoin(
                TradeDecision,
                TradeDecision.alert_event_id == AlertEvent.id,
            )
            .outerjoin(
                TradeExecution,
                TradeExecution.trigger_decision_id == TradeDecision.id,
            )
            .outerjoin(
                TradeEpisode,
                TradeEpisode.id == TradeExecution.episode_id,
            )
            .outerjoin(
                TradeReview,
                TradeReview.episode_id == TradeEpisode.id,
            )
            .where(AlertEvent.id.in_(requested_ids))
        ).all()
        rows_by_event_id = {row[0].id: row for row in rows}
        if any(event_id not in rows_by_event_id for event_id in requested_ids):
            raise _not_found("EXECUTION_REVIEW_EVENT_NOT_FOUND")
        result: list[EventReviewState] = []
        for event_id in requested_ids:
            event, rule_code, decision, execution, episode, review_id = (
                rows_by_event_id[event_id]
            )
            require_eligible_direction(event, rule_code)
            if decision is None:
                result.append(
                    EventReviewState(event.id, "pending_decision", None, None)
                )
                continue
            if decision.disposition == "NOT_EXECUTED":
                result.append(EventReviewState(event.id, "done", decision.id, None))
                continue
            if execution is None or episode is None:
                raise _conflict("DECISION_LINEAGE_INVALID")
            state = (
                "open"
                if episode.closed_at is None
                else "done"
                if review_id is not None
                else "pending_review"
            )
            result.append(EventReviewState(event.id, state, decision.id, episode.id))
        return tuple(result)

    def episode_detail(self, episode_id: int) -> EpisodeDetail:
        return self._read_call(lambda: self._episode_detail(episode_id))

    def _episode_detail(self, episode_id: int) -> EpisodeDetail:
        origin_decision_alias = aliased(TradeDecision)
        trigger_decision_alias = aliased(TradeDecision)
        origin_event_alias = aliased(AlertEvent)
        origin_rule_alias = aliased(AlertRule)
        rows = self._session.execute(
            select(
                TradeEpisode,
                origin_decision_alias,
                origin_event_alias,
                origin_rule_alias.rule_code,
                TradeExecution,
                trigger_decision_alias,
                TradeReview,
            )
            .join(
                origin_decision_alias,
                origin_decision_alias.id == TradeEpisode.origin_decision_id,
            )
            .join(
                origin_event_alias,
                origin_event_alias.id == origin_decision_alias.alert_event_id,
            )
            .join(
                origin_rule_alias,
                origin_rule_alias.id == origin_event_alias.rule_id,
            )
            .outerjoin(
                TradeExecution,
                TradeExecution.episode_id == TradeEpisode.id,
            )
            .outerjoin(
                trigger_decision_alias,
                trigger_decision_alias.id == TradeExecution.trigger_decision_id,
            )
            .outerjoin(
                TradeReview,
                TradeReview.episode_id == TradeEpisode.id,
            )
            .where(TradeEpisode.id == episode_id)
            .order_by(TradeExecution.sequence_no)
        ).all()
        if not rows:
            raise _not_found("TRADE_EPISODE_NOT_FOUND")
        episode = rows[0][0]
        origin_decision = rows[0][1]
        origin_event = rows[0][2]
        origin_rule_code = rows[0][3]
        if origin_event.trading_day is None:
            raise _conflict("DECISION_LINEAGE_INVALID")
        executions = tuple(row[4] for row in rows if row[4] is not None)
        decisions = [origin_decision]
        decision_ids = {origin_decision.id}
        for row in rows:
            trigger_decision = row[5]
            if trigger_decision is not None and trigger_decision.id not in decision_ids:
                decisions.append(trigger_decision)
                decision_ids.add(trigger_decision.id)
        facts = tuple(
            ExecutionFact(
                sequence_no=row.sequence_no,
                execution_type=row.execution_type,
                price=row.price,
                quantity=row.quantity,
            )
            for row in executions
        )
        position = self._calculate_position(episode, facts)
        review = rows[0][6]
        event_context = EventContext(
            id=origin_event.id,
            rule_code=origin_rule_code,
            symbol=origin_event.symbol,
            contract=origin_event.contract,
            trading_day=origin_event.trading_day,
            frequency=origin_event.frequency,
            bar_end=origin_event.bar_end,
            result_codes=tuple(origin_event.result_codes),
            lower_tf_confirmation=origin_event.lower_tf_confirmation,
            detected_at=origin_event.detected_at,
            notification_attempted_at=origin_event.notification_attempted_at,
        )
        return EpisodeDetail(
            episode=episode,
            origin_event=event_context,
            decisions=tuple(decisions),
            executions=executions,
            review=review,
            position=position,
        )

    def stats(
        self,
        *,
        trading_day_from: date | None = None,
        trading_day_to: date | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        frequency: str | None = None,
    ) -> ExecutionReviewStats:
        return self._read_call(
            lambda: self._stats(
                trading_day_from=trading_day_from,
                trading_day_to=trading_day_to,
                symbol=symbol,
                direction=direction,
                frequency=frequency,
            )
        )

    def _stats(
        self,
        *,
        trading_day_from: date | None = None,
        trading_day_to: date | None = None,
        symbol: str | None = None,
        direction: str | None = None,
        frequency: str | None = None,
    ) -> ExecutionReviewStats:
        """Compute separate opportunity and Episode-state denominators."""

        if (
            trading_day_from is not None
            and trading_day_to is not None
            and trading_day_from > trading_day_to
        ):
            raise _invalid("EXECUTION_REVIEW_DATE_RANGE_INVALID")
        normalized_symbol = symbol.strip().lower() if symbol is not None else None
        if normalized_symbol == "":
            raise _invalid("EXECUTION_REVIEW_STATS_FILTER_INVALID")
        if direction is not None and direction not in {"LONG", "SHORT"}:
            raise _invalid("EXECUTION_REVIEW_STATS_FILTER_INVALID")
        if frequency is not None and frequency not in ELIGIBLE_FREQUENCIES:
            raise _invalid("EXECUTION_REVIEW_STATS_FILTER_INVALID")
        backlog: list[_OpportunitySnapshot] = []
        for row in self._opportunity_snapshot():
            event_direction = eligible_direction(row.event, row.rule_code)
            if event_direction is None:
                continue
            if normalized_symbol is not None and row.event.symbol != normalized_symbol:
                continue
            if direction is not None and event_direction != direction:
                continue
            if frequency is not None and row.event.frequency != frequency:
                continue
            backlog.append(row)
        ranged_rows: list[_OpportunitySnapshot] = []
        for snapshot in backlog:
            trading_day = snapshot.event.trading_day
            assert trading_day is not None
            if trading_day_from is not None and trading_day < trading_day_from:
                continue
            if trading_day_to is not None and trading_day > trading_day_to:
                continue
            ranged_rows.append(snapshot)
        ranged = tuple(ranged_rows)
        decisions = tuple(row.decision for row in ranged if row.decision is not None)
        processed = len(decisions)
        executed = sum(row.disposition == "EXECUTED" for row in decisions)
        not_executed = processed - executed
        reasons: dict[str, int] = {}
        for decision_row in decisions:
            if (
                decision_row.disposition == "NOT_EXECUTED"
                and decision_row.primary_not_execute_reason is not None
            ):
                reasons[decision_row.primary_not_execute_reason] = (
                    reasons.get(decision_row.primary_not_execute_reason, 0) + 1
                )
        eligible = len(ranged)
        opportunity_stats = OpportunityStats(
            eligible_events=eligible,
            processed_events=processed,
            pending_events=eligible - processed,
            executed_decisions=executed,
            not_executed_decisions=not_executed,
            decision_completion_rate=(
                Decimal(processed) / Decimal(eligible) if eligible else None
            ),
            execution_rate=(
                Decimal(executed) / Decimal(processed) if processed else None
            ),
            primary_reason_counts=dict(sorted(reasons.items())),
        )
        episodes = tuple(row.episode for row in backlog if row.episode is not None)
        review_by_episode = {
            row.episode.id: row.review
            for row in backlog
            if row.episode is not None and row.review is not None
        }
        ranged_episode_ids = {
            row.episode.id for row in ranged if row.episode is not None
        }
        episode_stats = EpisodeStateStats(
            open_episodes=sum(row.closed_at is None for row in episodes),
            pending_review_episodes=sum(
                row.closed_at is not None and row.id not in review_by_episode
                for row in episodes
            ),
            done_episodes=sum(
                row.closed_at is not None
                and row.id in review_by_episode
                and row.id in ranged_episode_ids
                for row in episodes
            ),
        )
        reviews = tuple(
            row.review
            for row in ranged
            if row.episode is not None and row.review is not None
        )
        review_issue_stats = ReviewIssueStats(
            entry=_review_tag_counts(
                reviews,
                lambda review: review.entry_tags,
                neutral="REASONABLE",
            ),
            holding=_review_tag_counts(
                reviews,
                lambda review: review.holding_tags,
                neutral="NORMAL",
            ),
            exit_risk=_review_tag_counts(
                reviews,
                lambda review: review.exit_tags,
                neutral="NORMAL",
            ),
            psychology=_review_tag_counts(
                reviews,
                lambda review: review.psychology_tags,
                neutral="NONE",
            ),
        )
        return ExecutionReviewStats(
            opportunity_stats,
            episode_stats,
            review_issue_stats,
        )

    def _read_call(self, call: Callable[[], _T]) -> _T:
        try:
            return call()
        except ExecutionReviewDomainError:
            self._session.rollback()
            raise
        except SQLAlchemyError:
            self._session.rollback()
            raise _persistence_failure() from None

    def _opportunity_snapshot(self) -> tuple[_OpportunitySnapshot, ...]:
        rows = self._session.execute(
            select(
                AlertEvent,
                AlertRule.rule_code,
                TradeDecision,
                TradeEpisode,
                TradeReview,
            )
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .outerjoin(
                TradeDecision,
                TradeDecision.alert_event_id == AlertEvent.id,
            )
            .outerjoin(
                TradeEpisode,
                TradeEpisode.origin_decision_id == TradeDecision.id,
            )
            .outerjoin(
                TradeReview,
                TradeReview.episode_id == TradeEpisode.id,
            )
            .order_by(AlertEvent.trading_day, AlertEvent.id)
        ).all()
        return tuple(_OpportunitySnapshot(*row) for row in rows)

    @staticmethod
    def _item(
        *,
        event: AlertEvent,
        item_kind: str,
        state: str,
        decision: TradeDecision | None = None,
        episode: TradeEpisode | None = None,
    ) -> ReviewItem:
        direction = "LONG" if tuple(event.result_codes) == ("buy",) else "SHORT"
        assert event.trading_day is not None
        return ReviewItem(
            item_kind=item_kind,
            state=state,
            event_id=event.id,
            decision_id=decision.id if decision is not None else None,
            episode_id=episode.id if episode is not None else None,
            symbol=event.symbol,
            contract=event.contract,
            direction=direction,
            trading_day=event.trading_day,
        )

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


def _review_tag_counts(
    reviews: tuple[TradeReview, ...],
    tags: Callable[[TradeReview], list[str]],
    *,
    neutral: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for review in reviews:
        for tag in tags(review):
            if tag != neutral:
                counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
