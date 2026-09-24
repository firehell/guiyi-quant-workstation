"""Historical build/resume orchestration over the P2 reducer and P3 repository."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from hashlib import sha256
import json
from time import monotonic
from typing import Literal, cast

from guiyi_quant.reference_trading import (
    ActionKind,
    CompletedReferenceBar,
    RecordingMode,
    ReferenceAction,
    ReferenceState,
    ReferenceTransition,
    StreamIdentity,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.subing_reference import (
    ReferenceBar,
    ReferenceSegment,
    SubingReplayState,
    replay_subing_step,
    seed_subing_replay_state,
)

from app.reference_trading.contracts import (
    DependencyAdvance,
    PreparedBatch,
    SeedChunk,
    SnapshotIdentity,
    SourceAction,
    prove_dependency_append,
)
from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputReader
from app.reference_trading.planning import (
    HistoricalReferencePlan,
    HistoricalStreamPlan,
    canonical_sha256,
)
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict


class ServiceInterrupted(RuntimeError):
    """Controlled test/host interruption at a committed batch boundary."""


class CommitOutcomeUnknown(RuntimeError):
    """A commit failed without an authoritative receipt proving its outcome."""


@dataclass(frozen=True, slots=True)
class SubingHistoricalPayload:
    segment: ReferenceSegment
    bar: ReferenceBar
    since: date
    through: date
    quality_segmented: bool


@dataclass(frozen=True, slots=True)
class NewowHistoricalPayload:
    identity: object
    bar: object
    verified_lifecycle: bool = False


@dataclass(frozen=True, slots=True)
class ResumeToken:
    plan_hash: str
    stream_id: str
    revision_id: str
    next_input_index: int
    source_token: str
    last_batch_key: str

    def __post_init__(self) -> None:
        for name in (
            "plan_hash", "stream_id", "revision_id", "source_token",
            "last_batch_key",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")
        if len(self.plan_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.plan_hash
        ):
            raise ValueError("plan_hash must be a lowercase sha256")
        if type(self.next_input_index) is not int or self.next_input_index < 0:
            raise ValueError("next_input_index must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class StreamBatchReport:
    stream_id: str
    status: Literal["completed", "partial", "blocked", "failed", "noop"]
    reason: str | None
    completed_bars: int
    candidate_revision_id: str | None
    active_revision_id: str | None
    last_batch_key: str | None
    resume_token: ResumeToken | None
    snapshot: SnapshotIdentity | None = None


@dataclass(frozen=True, slots=True)
class BatchReport:
    status: Literal["completed", "partial", "blocked", "failed", "noop"]
    streams: tuple[StreamBatchReport, ...]


def _source_guard(reader: object, request: object, source_token: str):
    factory = getattr(reader, "source_guard", None)
    if factory is None:
        return nullcontext()
    return factory(request, expected_source_token=source_token)


def _seed_checkpoint(stream: StreamIdentity) -> tuple[AdapterCheckpoint[object], str]:
    if stream.strategy_code.replace("-", "_") == "subing_reference":
        state: object = seed_subing_replay_state()
        schema = "subing_replay_v1"
    else:
        from guiyi_quant.newow.product_adapters import seed_replay_state

        state = seed_replay_state()
        schema = "newow_product_replay_v1"
    return AdapterCheckpoint(
        state, stream=stream, reference_state=ReferenceState.flat(stream),
    ), schema


def _checkpoint_watermark(
    checkpoint: AdapterCheckpoint[object], item: HistoricalInputBar,
    reference_state: ReferenceState,
):
    candidates = tuple(
        value for value in (
            checkpoint.computed_through,
            item.bar_end,
            reference_state.computed_through,
            None if reference_state.last_event_key is None else reference_state.last_event_key[0],
        )
        if value is not None
    )
    return max(candidates)


def _subing_step(
    stream: StreamIdentity,
    checkpoint: AdapterCheckpoint[object],
    item: HistoricalInputBar,
    presentation: list[dict[str, object]] | None = None,
) -> tuple[
    AdapterCheckpoint[object], tuple[SourceAction, ...], ReferenceTransition,
]:
    if not isinstance(checkpoint.strategy_state, SubingReplayState):
        raise ValueError("REFERENCE_CHECKPOINT_STRATEGY_CONFLICT")
    prior_reference = checkpoint.reference_state
    if prior_reference is None:
        raise ValueError("REFERENCE_CHECKPOINT_STATE_CONFLICT")
    if not item.strategy_input:
        transition = reduce_reference(
            prior_reference,
            boundaries=item.boundaries,
            return_policy="delta_over_entry",
        )
        strategy_state = deepcopy(checkpoint.strategy_state)
        strategy_state.reference_state = transition.state
        if transition.state.open_trade is None:
            strategy_state.current = None
        return (
            AdapterCheckpoint(
                strategy_state,
                _checkpoint_watermark(checkpoint, item, transition.state),
                item.fingerprint,
                item.physical_contract,
                item.owner_segment_id,
                item.calculation_segment_id,
                stream,
                transition.state,
            ),
            (),
            transition,
        )
    reference_price = item.reference_price
    if reference_price is None:
        raise ValueError("REFERENCE_INPUT_PRICE_MISSING")
    payload = item.payload
    if not isinstance(payload, SubingHistoricalPayload):
        raise ValueError("REFERENCE_INPUT_PAYLOAD_INVALID")
    strategy_state = checkpoint.strategy_state
    if (
        checkpoint.physical_contract != item.physical_contract
        or checkpoint.calculation_segment_id != item.calculation_segment_id
    ):
        strategy_state = seed_subing_replay_state()
        strategy_state.reference_state = prior_reference
    next_state, signal, _closed, indicator = replay_subing_step(
        stream.product.lower(),
        payload.segment,
        stream.frequency,
        payload.quality_segmented,
        strategy_state,
        payload.bar,
        # Historical state starts at authoritative ownership, not at the
        # presentation/query window.  Otherwise a pre-window signal mutates
        # P2 pairing state without exposing the source action to P4.
        since=payload.segment.owner_since,
        through=payload.through,
    )
    if presentation is not None:
        if signal is not None:
            presentation.append(presentation_point(
                kind="signal", value=signal, trading_day=item.trading_day,
                formula_versions=stream.formula_versions,
            ))
        if indicator is not None:
            presentation.append(presentation_point(
                kind="indicator", value=indicator, trading_day=item.trading_day,
                formula_versions=stream.formula_versions,
            ))
    actions: list[ReferenceAction] = []
    if signal is not None and signal.action != "SAME_DIRECTION":
        if signal.action.startswith("REVERSE"):
            if prior_reference.open_trade is None:
                raise ValueError("REFERENCE_CHECKPOINT_OPEN_CONFLICT")
            actions.append(ReferenceAction(
                stream=stream,
                source_action_id=f"{signal.signal_id}:close",
                physical_contract=item.physical_contract,
                owner_segment_id=item.owner_segment_id,
                calculation_segment_id=item.calculation_segment_id,
                bar_end=item.bar_end,
                trading_day=item.trading_day,
                sequence=0,
                kind=ActionKind.CLOSE,
                reference_price=reference_price,
                entry_action_id=prior_reference.open_trade.entry_action_id,
                reference_price_type="subing_signal_close",
            ))
        if signal.action in {
            "OPEN_LONG", "OPEN_SHORT", "REVERSE_TO_LONG", "REVERSE_TO_SHORT",
        }:
            actions.append(ReferenceAction(
                stream=stream,
                source_action_id=f"{signal.signal_id}:open",
                physical_contract=item.physical_contract,
                owner_segment_id=item.owner_segment_id,
                calculation_segment_id=item.calculation_segment_id,
                bar_end=item.bar_end,
                trading_day=item.trading_day,
                sequence=1 if signal.action.startswith("REVERSE") else 0,
                kind=(
                    ActionKind.OPEN_LONG
                    if signal.action.endswith("LONG") else ActionKind.OPEN_SHORT
                ),
                reference_price=reference_price,
                reference_price_type="subing_signal_close",
            ))
    in_owner_window = (
        payload.segment.owner_since <= item.trading_day <= payload.segment.owner_through
        and item.trading_day <= payload.through
    )
    transition = reduce_reference(
        prior_reference,
        actions=tuple(actions),
        boundaries=item.boundaries,
        completed_bar=(
            CompletedReferenceBar(
                item.physical_contract,
                item.owner_segment_id,
                item.calculation_segment_id,
                item.bar_end,
                item.trading_day,
                reference_price,
            )
            if in_owner_window else None
        ),
        return_policy="delta_over_entry",
    )
    if not in_owner_window:
        # Warm-up advances only the strategy kernel.  Keep the embedded P2
        # projection checkpoint aligned with the unified no-formal-event state.
        next_state.reference_state = transition.state
    if item.boundaries:
        next_state.reference_state = transition.state
        if transition.state.open_trade is None:
            next_state.current = None
    if next_state.reference_state != transition.state:
        raise ValueError("REFERENCE_STRATEGY_REDUCER_DIVERGENCE")
    return (
        AdapterCheckpoint(
            next_state,
            _checkpoint_watermark(checkpoint, item, transition.state),
            item.fingerprint,
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            stream,
            transition.state,
        ),
        tuple(SourceAction(action) for action in actions),
        transition,
    )


def _newow_step(
    stream: StreamIdentity,
    checkpoint: AdapterCheckpoint[object],
    item: HistoricalInputBar,
    presentation: list[dict[str, object]] | None = None,
    *, observed_at: datetime | None = None,
) -> tuple[
    AdapterCheckpoint[object], tuple[SourceAction, ...], ReferenceTransition,
]:
    from guiyi_quant.newow.product_adapters import ProductReplayState, replay_step
    from guiyi_quant.newow.product_contracts import (
        ActionKind as NewowActionKind,
        ProductBar,
        ProductIdentity,
        TradeEligibility,
    )
    from guiyi_quant.newow.product_identity import build_reference_trade_id

    if not isinstance(checkpoint.strategy_state, ProductReplayState):
        raise ValueError("REFERENCE_INPUT_PAYLOAD_INVALID")
    prior_reference = checkpoint.reference_state
    if prior_reference is None:
        raise ValueError("REFERENCE_CHECKPOINT_STATE_CONFLICT")
    if not item.strategy_input:
        transition = reduce_reference(prior_reference, boundaries=item.boundaries)
        return (
            AdapterCheckpoint(
                checkpoint.strategy_state,
                _checkpoint_watermark(checkpoint, item, transition.state),
                item.fingerprint,
                item.physical_contract,
                item.owner_segment_id,
                item.calculation_segment_id,
                stream,
                transition.state,
            ),
            (),
            transition,
        )
    reference_price = item.reference_price
    if reference_price is None:
        raise ValueError("REFERENCE_INPUT_PRICE_MISSING")
    payload = item.payload
    if (
        not isinstance(payload, NewowHistoricalPayload)
        or not isinstance(payload.identity, ProductIdentity)
        or not isinstance(payload.bar, ProductBar)
    ):
        raise ValueError("REFERENCE_INPUT_PAYLOAD_INVALID")
    identity = payload.identity
    if (
        stream.strategy_code.replace("-", "_")
        != f"newow_{identity.strategy.value}"
        or stream.product != identity.product
        or stream.frequency != identity.frequency.value
        or stream.series_kind != identity.series_kind
        or stream.formula_versions != identity.formula_versions
    ):
        raise ValueError("REFERENCE_INPUT_IDENTITY_CONFLICT")
    next_state, frame, diagnostics = replay_step(
        identity,
        checkpoint.strategy_state,
        payload.bar,
        verified_lifecycle=payload.verified_lifecycle,
    )
    if frame is None:
        raise ValueError("REFERENCE_DUPLICATE_INPUT")
    if presentation is not None:
        presentation.append(presentation_point(
            kind="availability",
            value={
                "bar_end": item.bar_end,
                "physical_contract": item.physical_contract,
                "segment_id": item.owner_segment_id,
                "calculation_segment_id": item.calculation_segment_id,
                "status": frame.availability.status,
            },
            trading_day=item.trading_day,
            formula_versions=stream.formula_versions,
        ))
        for action in frame.actions:
            presentation.append(presentation_point(
                kind="action", value=action, trading_day=item.trading_day,
                formula_versions=stream.formula_versions,
            ))
            if (
                action.kind is NewowActionKind.BUILD
                and action.trade_eligibility is TradeEligibility.ELIGIBLE
            ):
                presentation.append(presentation_point(
                    kind="trade_identity",
                    value={
                        "source_action_id": action.signal_id,
                        "public_trade_id": build_reference_trade_id(action),
                        "bar_end": action.bar_end,
                        "physical_contract": action.physical_contract,
                        "segment_id": action.segment_id,
                    },
                    trading_day=item.trading_day,
                    formula_versions=stream.formula_versions,
                ))
        for hint in frame.hints:
            presentation.append(presentation_point(
                kind="hint", value=hint, trading_day=item.trading_day,
                formula_versions=stream.formula_versions,
            ))
        for diagnostic in diagnostics:
            presentation.append(presentation_point(
                kind="diagnostic", value=diagnostic, trading_day=item.trading_day,
                formula_versions=stream.formula_versions,
            ))
    actions: list[ReferenceAction] = []
    forward_entry_id = (
        prior_reference.open_trade.entry_action_id
        if stream.recording_mode is RecordingMode.FORWARD_OBSERVATION
        and prior_reference.open_trade is not None else None
    )
    for action in frame.actions:
        if action.trade_eligibility is not TradeEligibility.ELIGIBLE:
            if (
                stream.recording_mode is RecordingMode.FORWARD_OBSERVATION
                and action.kind is NewowActionKind.CLEAR
                and presentation is not None
            ):
                presentation.append(presentation_point(
                    kind="diagnostic",
                    value={"bar_end": action.bar_end, "code": "NO_OBSERVED_ENTRY"},
                    trading_day=item.trading_day,
                    formula_versions=stream.formula_versions,
                ))
            continue
        if action.kind is NewowActionKind.BUILD:
            kind = ActionKind.OPEN_LONG
            entry_id = None
            if stream.recording_mode is RecordingMode.FORWARD_OBSERVATION:
                forward_entry_id = action.signal_id
        else:
            kind = ActionKind.CLOSE
            entry_id = action.related_build_id
            if entry_id is None:
                raise ValueError("REFERENCE_ACTION_PAIRING_CONFLICT")
            if stream.recording_mode is RecordingMode.FORWARD_OBSERVATION:
                if forward_entry_id is None:
                    if presentation is not None:
                        presentation.append(presentation_point(
                            kind="diagnostic",
                            value={"bar_end": action.bar_end, "code": "NO_OBSERVED_ENTRY"},
                            trading_day=item.trading_day,
                            formula_versions=stream.formula_versions,
                        ))
                    continue
                if entry_id != forward_entry_id:
                    raise ValueError("REFERENCE_ACTION_PAIRING_CONFLICT")
                forward_entry_id = None
        actions.append(ReferenceAction(
            stream=stream,
            source_action_id=action.signal_id,
            physical_contract=action.physical_contract,
            owner_segment_id=action.segment_id,
            calculation_segment_id=item.calculation_segment_id,
            bar_end=action.bar_end,
            trading_day=action.trading_day,
            sequence=action.sequence,
            kind=kind,
            reference_price=action.reference_price,
            entry_action_id=entry_id,
            reference_price_type="newow_strategy_reference",
        ))
    next_sequence = max((action.sequence for action in actions), default=-1) + 1
    for offset, hint in enumerate(frame.hints):
        if hint.anchor_price is None:
            continue
        actions.append(ReferenceAction(
            stream=stream,
            source_action_id=hint.hint_id,
            physical_contract=hint.physical_contract,
            owner_segment_id=hint.segment_id,
            calculation_segment_id=item.calculation_segment_id,
            bar_end=hint.bar_end,
            trading_day=hint.trading_day,
            sequence=next_sequence + offset,
            kind=ActionKind.HINT,
            reference_price=hint.anchor_price,
            reference_price_type="newow_strategy_hint",
        ))
    completed = None
    if payload.bar.bar.observation_eligible:
        completed = CompletedReferenceBar(
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            item.bar_end,
            item.trading_day,
            reference_price,
        )
    transition = reduce_reference(
        prior_reference,
        actions=tuple(actions),
        boundaries=item.boundaries,
        completed_bar=completed,
    )
    return (
        AdapterCheckpoint(
            next_state,
            _checkpoint_watermark(checkpoint, item, transition.state),
            item.fingerprint,
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            stream,
            transition.state,
        ),
        tuple(SourceAction(action, observed_at) for action in actions),
        transition,
    )


def _advance_batch(
    stream: StreamIdentity,
    checkpoint: AdapterCheckpoint[object],
    bars: tuple[HistoricalInputBar, ...],
    presentation: list[dict[str, object]] | None = None,
) -> tuple[
    AdapterCheckpoint[object],
    tuple[SourceAction, ...],
    tuple[ReferenceTransition, ...],
    str,
]:
    current = checkpoint
    sources: list[SourceAction] = []
    transitions: list[ReferenceTransition] = []
    for item in bars:
        if presentation is not None:
            for boundary in item.boundaries:
                presentation.append(presentation_point(
                    kind="boundary",
                    value={
                        "reason": boundary.reason,
                        "physical_contract": boundary.physical_contract,
                        "owner_segment_id": boundary.owner_segment_id,
                        "calculation_segment_id": boundary.calculation_segment_id,
                        "bar_end": boundary.bar_end,
                    },
                    trading_day=boundary.trading_day,
                    formula_versions=stream.formula_versions,
                ))
        if stream.strategy_code.replace("-", "_") == "subing_reference":
            current, found_sources, transition = _subing_step(stream, current, item, presentation)
            schema = "subing_replay_v1"
        elif stream.strategy_code.replace("-", "_").startswith("newow_"):
            current, found_sources, transition = _newow_step(stream, current, item, presentation)
            schema = "newow_product_replay_v1"
        else:
            raise ValueError("REFERENCE_STRATEGY_DRIVER_UNSUPPORTED")
        sources.extend(found_sources)
        transitions.append(transition)
    return current, tuple(sources), tuple(transitions), schema


class HistoricalReferenceService:
    def __init__(
        self,
        repository: ReferenceRepository,
        input_reader: HistoricalInputReader,
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        cancelled: Callable[[], bool] = lambda: False,
        after_batch: Callable[[str, dict[str, object]], None] | None = None,
        step_counter: Callable[[int], None] | None = None,
    ) -> None:
        self._repository = repository
        self._reader = input_reader
        self._clock = monotonic_clock
        self._cancelled = cancelled
        self._after_batch = after_batch or (lambda _stage, _context: None)
        self._step_counter = step_counter or (lambda _count: None)

    def execute(self, plan: HistoricalReferencePlan, expected_plan_hash: str) -> BatchReport:
        self._validate_plan(plan, expected_plan_hash, operation="build")
        deadline = self._clock() + plan.budget.max_elapsed_seconds
        reports = tuple(
            self._isolated_stream(
                item.request.identity.stream_id,
                partial(self._build_stream, plan, item, None, deadline),
            )
            for item in plan.streams
        )
        return BatchReport(self._overall(reports), reports)

    def resume(
        self,
        plan: HistoricalReferencePlan,
        resume_token: ResumeToken,
        expected_plan_hash: str,
    ) -> BatchReport:
        if plan.operation not in {"build", "rebuild"}:
            raise ValueError("REFERENCE_RESUME_PLAN_CONFLICT")
        self._validate_plan(plan, expected_plan_hash, operation=plan.operation)
        deadline = self._clock() + plan.budget.max_elapsed_seconds
        if resume_token.plan_hash != plan.plan_hash:
            raise ValueError("REFERENCE_RESUME_PLAN_CONFLICT")
        matches = tuple(
            item for item in plan.streams
            if item.request.identity.stream_id == resume_token.stream_id
        )
        if len(matches) != 1:
            raise ValueError("REFERENCE_RESUME_STREAM_CONFLICT")
        report = self._isolated_stream(
            resume_token.stream_id,
            lambda: self._build_stream(plan, matches[0], resume_token, deadline),
        )
        return BatchReport(self._overall((report,)), (report,))

    def advance(
        self, plan: HistoricalReferencePlan, expected_plan_hash: str,
    ) -> BatchReport:
        self._validate_plan(plan, expected_plan_hash, operation="advance")
        deadline = self._clock() + plan.budget.max_elapsed_seconds
        reports = tuple(
            self._isolated_stream(
                item.request.identity.stream_id,
                partial(self._advance_stream, plan, item, deadline),
            )
            for item in plan.streams
        )
        return BatchReport(self._overall(reports), reports)

    def rebuild(
        self, plan: HistoricalReferencePlan, expected_plan_hash: str,
    ) -> BatchReport:
        self._validate_plan(plan, expected_plan_hash, operation="rebuild")
        deadline = self._clock() + plan.budget.max_elapsed_seconds
        reports: list[StreamBatchReport] = []
        for item in plan.streams:
            stream_id = item.request.identity.stream_id
            try:
                current = self._repository.read_state(stream_id)
                self._repository.invalidate_revision(
                    stream_id,
                    current.revision_id,
                    current.stream.row_version,
                    "P4_SOURCE_REVISION_REBUILD",
                )
            except RepositoryConflict as error:
                reports.append(StreamBatchReport(
                    stream_id, "blocked", str(error), 0, None, None, None, None,
                ))
                continue
            reports.append(self._isolated_stream(
                stream_id, partial(self._build_stream, plan, item, None, deadline),
            ))
        result = tuple(reports)
        return BatchReport(self._overall(result), result)

    @staticmethod
    def _validate_plan(
        plan: HistoricalReferencePlan, expected_plan_hash: str, *, operation: str,
    ) -> None:
        if (
            not isinstance(plan, HistoricalReferencePlan)
            or plan.plan_hash != expected_plan_hash
            or canonical_sha256(plan) != expected_plan_hash
            or plan.operation != operation
        ):
            raise ValueError("REFERENCE_PLAN_HASH_CONFLICT")

    @staticmethod
    def _isolated_stream(
        stream_id: str, operation: Callable[[], StreamBatchReport],
    ) -> StreamBatchReport:
        try:
            return operation()
        except Exception as error:  # noqa: BLE001 - per-stream failure boundary
            reason = str(error)
            if not reason or any(
                char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in reason
            ):
                reason = "REFERENCE_STREAM_FAILED"
            return StreamBatchReport(
                stream_id, "failed", reason, 0, None, None, None, None,
            )

    def _commit_once(self, token, prepared: PreparedBatch):
        """Commit once; on an uncertain transport failure, read the receipt only."""
        try:
            return self._repository.commit_batch(token, prepared)
        except RepositoryConflict:
            raise
        except Exception as error:  # noqa: BLE001 - commit outcome may be unknown
            try:
                receipt = self._repository.read_batch(
                    prepared.stream_id, prepared.revision_id, prepared.batch_key,
                )
            except Exception as read_error:  # noqa: BLE001 - no authoritative result
                raise CommitOutcomeUnknown("COMMIT_OUTCOME_UNKNOWN") from read_error
            if receipt is None:
                raise CommitOutcomeUnknown("COMMIT_OUTCOME_UNKNOWN") from error
            return receipt

    def _publish_once(
        self,
        stream_id: str,
        revision_id: str,
        expected_row_version: int,
        expected_dependency_digest: str,
    ) -> SnapshotIdentity:
        try:
            return self._repository.publish_revision(
                stream_id, revision_id, expected_row_version,
                expected_dependency_digest,
            )
        except RepositoryConflict:
            raise
        except Exception as error:  # noqa: BLE001 - publish outcome may be unknown
            try:
                state = self._repository.read_state(stream_id, revision_id)
            except Exception as read_error:  # noqa: BLE001 - no authoritative result
                raise CommitOutcomeUnknown("PUBLISH_OUTCOME_UNKNOWN") from read_error
            if (
                state.revision_status == "active"
                and state.stream.active_revision_id == revision_id
            ):
                return SnapshotIdentity(stream_id, revision_id, state.checkpoint.seq)
            raise CommitOutcomeUnknown("PUBLISH_OUTCOME_UNKNOWN") from error

    def _build_stream(
        self,
        plan: HistoricalReferencePlan,
        stream_plan: HistoricalStreamPlan,
        resume: ResumeToken | None,
        deadline: float,
    ) -> StreamBatchReport:
        stream = stream_plan.request.identity
        if resume is not None and not self._reader.revalidate(
            stream_plan.request, expected_source_token=resume.source_token,
        ):
            return StreamBatchReport(
                stream.stream_id, "blocked", "SOURCE_CHANGED", resume.next_input_index,
                resume.revision_id, None, resume.last_batch_key, resume,
            )
        snapshot = self._reader.load_stream(
            stream_plan.request, expected_source_token=stream_plan.source_token,
        )
        if not self._snapshot_matches(stream_plan, snapshot):
            return StreamBatchReport(
                stream.stream_id, "blocked", "SOURCE_CHANGED",
                0 if resume is None else resume.next_input_index,
                None if resume is None else resume.revision_id,
                None, None if resume is None else resume.last_batch_key, resume,
            )
        if resume is not None:
            try:
                (
                    resume_index, resume_batch_key, already_published,
                ) = self._validate_resume_position(
                    plan, stream_plan, snapshot, resume,
                )
            except (RepositoryConflict, ValueError) as error:
                return StreamBatchReport(
                    stream.stream_id, "blocked", str(error), 0,
                    resume.revision_id, None, resume.last_batch_key, resume,
                )
            if already_published is not None:
                if resume_index != len(snapshot.bars):
                    return StreamBatchReport(
                        stream.stream_id, "blocked",
                        "REFERENCE_RESUME_POSITION_CONFLICT", resume_index,
                        resume.revision_id, resume.revision_id,
                        resume_batch_key, resume,
                    )
                return StreamBatchReport(
                    stream.stream_id, "completed", None, resume_index,
                    resume.revision_id, resume.revision_id,
                    resume_batch_key, None, already_published,
                )
        if resume is None:
            stored = self._repository.ensure_stream(stream)
            revision_id = self._repository.create_revision(
                stream.stream_id, stored.row_version, stream_plan.dependency_digest,
            )
            seed, schema = _seed_checkpoint(stream)
            seed_text = json.dumps(
                {"plan_hash": plan.plan_hash, "stream_id": stream.stream_id},
                sort_keys=True, separators=(",", ":"),
            )
            root = sha256(seed_text.encode()).hexdigest()
            self._repository.stage_seed_chunk(
                revision_id, SeedChunk("seed:" + root, 0, 1, root, seed_text),
            )
            token = self._repository.seal_seed(
                revision_id, stream_plan.input_manifest, seed, schema,
            )
            index = 0
            last_batch_key = "seed:" + root
        else:
            revision_id = resume.revision_id
            token, _checkpoint = self._repository.load_checkpoint(
                stream.stream_id, revision_id,
            )
            index = resume_index
            last_batch_key = resume_batch_key
        try:
            while index < len(snapshot.bars):
                if self._cancelled():
                    raise ServiceInterrupted("cancelled")
                if self._clock() >= deadline:
                    raise ServiceInterrupted("budget exhausted")
                chunk = snapshot.bars[index:index + plan.batch_size]
                token, checkpoint = self._repository.load_checkpoint(
                    stream.stream_id, revision_id,
                )
                presentation: list[dict[str, object]] = []
                next_checkpoint, sources, transitions, schema = _advance_batch(
                    stream, checkpoint, chunk, presentation,
                )
                self._step_counter(len(chunk))
                batch_key = "calculation:" + sha256(json.dumps(
                    [
                        revision_id, token.state_hash, stream_plan.source_token,
                        chunk[0].fingerprint, chunk[-1].fingerprint,
                    ], separators=(",", ":"),
                ).encode()).hexdigest()
                prepared = PreparedBatch(
                    stream.stream_id,
                    revision_id,
                    batch_key,
                    token,
                    stream_plan.input_manifest,
                    sources,
                    transitions,
                    next_checkpoint,
                    schema,
                    {
                        "source_token": stream_plan.source_token,
                        "first_fingerprint": chunk[0].fingerprint,
                        "last_fingerprint": chunk[-1].fingerprint,
                        "start_input_index": index,
                        "end_input_index": index + len(chunk),
                        "presentation_v1": envelope(presentation),
                    },
                )
                with _source_guard(
                    self._reader, stream_plan.request, stream_plan.source_token,
                ):
                    if not self._reader.revalidate(
                        stream_plan.request, expected_source_token=stream_plan.source_token,
                    ):
                        raise RepositoryConflict("SOURCE_CHANGED")
                    self._commit_once(token, prepared)
                index += len(chunk)
                last_batch_key = batch_key
                current_resume = ResumeToken(
                    plan.plan_hash, stream.stream_id, revision_id, index,
                    stream_plan.source_token, last_batch_key,
                )
                self._after_batch("committed", {"resume_token": current_resume})
        except ServiceInterrupted:
            current_resume = ResumeToken(
                plan.plan_hash, stream.stream_id, revision_id, index,
                stream_plan.source_token, last_batch_key,
            )
            return StreamBatchReport(
                stream.stream_id, "partial", "INTERRUPTED", index, revision_id,
                None, last_batch_key, current_resume,
            )
        except CommitOutcomeUnknown:
            current_resume = ResumeToken(
                plan.plan_hash, stream.stream_id, revision_id, index,
                stream_plan.source_token, last_batch_key,
            )
            return StreamBatchReport(
                stream.stream_id, "partial", "COMMIT_OUTCOME_UNKNOWN", index,
                revision_id, None, last_batch_key, current_resume,
            )
        except RepositoryConflict as error:
            reason = str(error) if str(error) else "REFERENCE_COMMIT_CONFLICT"
            current_resume = ResumeToken(
                plan.plan_hash, stream.stream_id, revision_id, index,
                stream_plan.source_token, last_batch_key,
            )
            return StreamBatchReport(
                stream.stream_id, "blocked", reason, index, revision_id,
                None, last_batch_key, current_resume,
            )
        except ValueError as error:
            if str(error) != "SOURCE_CHANGED":
                raise
            current_resume = ResumeToken(
                plan.plan_hash, stream.stream_id, revision_id, index,
                stream_plan.source_token, last_batch_key,
            )
            return StreamBatchReport(
                stream.stream_id, "blocked", "SOURCE_CHANGED", index, revision_id,
                None, last_batch_key, current_resume,
            )
        if not self._reader.revalidate(
            stream_plan.request, expected_source_token=stream_plan.source_token,
        ):
            return StreamBatchReport(
                stream.stream_id, "blocked", "SOURCE_CHANGED", index, revision_id,
                None, last_batch_key,
                ResumeToken(
                    plan.plan_hash, stream.stream_id, revision_id, index,
                    stream_plan.source_token, last_batch_key,
                ),
            )
        final_token, _ = self._repository.load_checkpoint(stream.stream_id, revision_id)
        with _source_guard(
            self._reader, stream_plan.request, stream_plan.source_token,
        ):
            if not self._reader.revalidate(
                stream_plan.request, expected_source_token=stream_plan.source_token,
            ):
                return StreamBatchReport(
                    stream.stream_id, "blocked", "SOURCE_CHANGED", index,
                    revision_id, None, last_batch_key,
                    ResumeToken(
                        plan.plan_hash, stream.stream_id, revision_id, index,
                        stream_plan.source_token, last_batch_key,
                    ),
                )
            try:
                published = self._publish_once(
                    stream.stream_id, revision_id, final_token.row_version,
                    stream_plan.dependency_digest,
                )
            except CommitOutcomeUnknown:
                return StreamBatchReport(
                    stream.stream_id, "partial", "PUBLISH_OUTCOME_UNKNOWN", index,
                    revision_id, None, last_batch_key,
                    ResumeToken(
                        plan.plan_hash, stream.stream_id, revision_id, index,
                        stream_plan.source_token, last_batch_key,
                    ),
                )
        return StreamBatchReport(
            stream.stream_id, "completed", None, index, revision_id, revision_id,
            last_batch_key, None, published,
        )

    def _validate_resume_position(
        self, plan, stream_plan, snapshot, resume: ResumeToken,
    ) -> tuple[int, str, SnapshotIdentity | None]:
        stream = stream_plan.request.identity
        if resume.source_token != stream_plan.source_token:
            raise ValueError("REFERENCE_RESUME_SOURCE_CONFLICT")
        state = self._repository.read_state(stream.stream_id, resume.revision_id)
        if (
            state.dependency_digest != stream_plan.dependency_digest
            or state.dependency_manifest != stream_plan.input_manifest
        ):
            raise ValueError("REFERENCE_RESUME_REVISION_CONFLICT")
        already_published = None
        if state.revision_status == "active":
            if state.stream.active_revision_id != resume.revision_id:
                raise ValueError("REFERENCE_RESUME_REVISION_CONFLICT")
            already_published = SnapshotIdentity(
                stream.stream_id, resume.revision_id, state.checkpoint.seq,
            )
        elif state.revision_status != "candidate":
            raise ValueError("REFERENCE_RESUME_REVISION_CONFLICT")
        token, _checkpoint = self._repository.load_checkpoint(
            stream.stream_id, resume.revision_id,
        )
        if state.checkpoint_batch_key.startswith("seed:"):
            current_index = 0
            seed_text = json.dumps(
                {"plan_hash": plan.plan_hash, "stream_id": stream.stream_id},
                sort_keys=True, separators=(",", ":"),
            )
            expected_batch_key = "seed:" + sha256(seed_text.encode()).hexdigest()
            if (
                token.seq != 1
                or state.checkpoint_batch_key != expected_batch_key
            ):
                raise ValueError("REFERENCE_RESUME_RECEIPT_CONFLICT")
        else:
            current_raw = state.source_evidence.get("end_input_index")
            start_raw = state.source_evidence.get("start_input_index")
            if (
                type(current_raw) is not int
                or type(start_raw) is not int
            ):
                raise ValueError("REFERENCE_RESUME_POSITION_CONFLICT")
            current_index = cast(int, current_raw)
            start_index = cast(int, start_raw)
            if (
                not 0 <= start_index < current_index <= len(snapshot.bars)
                or state.source_evidence.get("first_fingerprint")
                != snapshot.bars[start_index].fingerprint
                or state.source_evidence.get("last_fingerprint")
                != snapshot.bars[current_index - 1].fingerprint
            ):
                raise ValueError("REFERENCE_RESUME_POSITION_CONFLICT")
        if resume.last_batch_key.startswith("seed:"):
            seed_text = json.dumps(
                {"plan_hash": plan.plan_hash, "stream_id": stream.stream_id},
                sort_keys=True, separators=(",", ":"),
            )
            expected_resume_key = "seed:" + sha256(seed_text.encode()).hexdigest()
            if resume.last_batch_key != expected_resume_key:
                raise ValueError("REFERENCE_RESUME_RECEIPT_CONFLICT")
            claimed_index = 0
        else:
            receipt = self._repository.read_batch(
                stream.stream_id, resume.revision_id, resume.last_batch_key,
            )
            evidence = self._repository.read_batch_evidence(
                stream.stream_id, resume.revision_id, resume.last_batch_key,
            )
            if receipt is None or evidence is None or receipt.seq > token.seq:
                raise ValueError("REFERENCE_RESUME_RECEIPT_CONFLICT")
            claimed_raw = evidence.get("end_input_index")
            if type(claimed_raw) is not int:
                raise ValueError("REFERENCE_RESUME_RECEIPT_CONFLICT")
            claimed_index = cast(int, claimed_raw)
        if resume.next_input_index != claimed_index:
            raise ValueError("REFERENCE_RESUME_POSITION_CONFLICT")
        return current_index, state.checkpoint_batch_key, already_published

    def _advance_stream(
        self, plan: HistoricalReferencePlan, stream_plan: HistoricalStreamPlan,
        deadline: float,
    ) -> StreamBatchReport:
        stream = stream_plan.request.identity
        try:
            state = self._repository.read_state(stream.stream_id)
        except RepositoryConflict as error:
            return StreamBatchReport(
                stream.stream_id, "blocked", str(error), 0, None, None, None, None,
            )
        if state.revision_status != "active":
            return StreamBatchReport(
                stream.stream_id, "blocked", "ACTIVE_REVISION_REQUIRED", 0,
                state.revision_id, state.stream.active_revision_id, None, None,
            )
        snapshot = self._reader.load_stream(
            stream_plan.request, expected_source_token=stream_plan.source_token,
        )
        if not self._snapshot_matches(stream_plan, snapshot):
            return StreamBatchReport(
                stream.stream_id, "blocked", "SOURCE_CHANGED", 0,
                state.revision_id, state.revision_id, None, None,
            )
        token, _checkpoint = self._repository.load_checkpoint(
            stream.stream_id, state.revision_id,
        )
        processed = state.source_evidence.get("end_input_index")
        if (
            type(processed) is not int
            or not 0 < processed <= len(snapshot.bars)
            or state.source_evidence.get("last_fingerprint")
            != snapshot.bars[processed - 1].fingerprint
        ):
            return StreamBatchReport(
                stream.stream_id, "blocked", "REBUILD_REQUIRED", 0,
                state.revision_id, state.revision_id, None, None,
            )
        tail = snapshot.bars[processed:]
        dependency_advance: DependencyAdvance | None
        if state.dependency_manifest == stream_plan.input_manifest:
            dependency_advance = None
            if not tail:
                return StreamBatchReport(
                    stream.stream_id, "noop", None, 0, state.revision_id,
                    state.revision_id, None, None,
                    SnapshotIdentity(stream.stream_id, state.revision_id, token.seq),
                )
        else:
            try:
                dependency_advance = prove_dependency_append(
                    state.dependency_manifest,
                    stream_plan.input_manifest,
                    appended_ranges=tuple(item.fingerprint for item in tail),
                )
            except ValueError:
                return StreamBatchReport(
                    stream.stream_id, "blocked", "REBUILD_REQUIRED", 0,
                    state.revision_id, state.revision_id, None, None,
                )
            if not tail:
                return StreamBatchReport(
                    stream.stream_id, "blocked", "REBUILD_REQUIRED", 0,
                    state.revision_id, state.revision_id, None, None,
                )
        index = 0
        last_batch_key: str | None = None
        while index < len(tail):
            if (
                self._cancelled()
                or self._clock() >= deadline
            ):
                return StreamBatchReport(
                    stream.stream_id, "partial", "INTERRUPTED", index,
                    state.revision_id, state.revision_id, last_batch_key, None,
                )
            token, checkpoint = self._repository.load_checkpoint(
                stream.stream_id, state.revision_id,
            )
            chunk = tail[index:index + plan.batch_size]
            presentation: list[dict[str, object]] = []
            next_checkpoint, sources, transitions, schema = _advance_batch(
                stream, checkpoint, chunk, presentation,
            )
            self._step_counter(len(chunk))
            batch_key = "advance:" + sha256(json.dumps(
                [
                    state.revision_id, token.state_hash, stream_plan.source_token,
                    chunk[0].fingerprint, chunk[-1].fingerprint,
                ], separators=(",", ":"),
            ).encode()).hexdigest()
            prepared = PreparedBatch(
                stream.stream_id,
                state.revision_id,
                batch_key,
                token,
                stream_plan.input_manifest,
                sources,
                transitions,
                next_checkpoint,
                schema,
                {
                    "source_token": stream_plan.source_token,
                    "first_fingerprint": chunk[0].fingerprint,
                    "last_fingerprint": chunk[-1].fingerprint,
                    "start_input_index": processed + index,
                    "end_input_index": processed + index + len(chunk),
                    "presentation_v1": envelope(presentation),
                },
                dependency_advance=dependency_advance if index == 0 else None,
            )
            try:
                with _source_guard(
                    self._reader, stream_plan.request, stream_plan.source_token,
                ):
                    if not self._reader.revalidate(
                        stream_plan.request, expected_source_token=stream_plan.source_token,
                    ):
                        raise RepositoryConflict("SOURCE_CHANGED")
                    self._commit_once(token, prepared)
            except CommitOutcomeUnknown:
                return StreamBatchReport(
                    stream.stream_id, "partial", "COMMIT_OUTCOME_UNKNOWN", index,
                    state.revision_id, state.revision_id, last_batch_key, None,
                )
            except (RepositoryConflict, ValueError) as error:
                if isinstance(error, ValueError) and str(error) != "SOURCE_CHANGED":
                    raise
                return StreamBatchReport(
                    stream.stream_id, "blocked", str(error), index,
                    state.revision_id, state.revision_id, last_batch_key, None,
                )
            dependency_advance = None
            index += len(chunk)
            last_batch_key = batch_key
        final, _ = self._repository.load_checkpoint(stream.stream_id, state.revision_id)
        return StreamBatchReport(
            stream.stream_id, "completed", None, index, state.revision_id,
            state.revision_id, last_batch_key, None,
            SnapshotIdentity(stream.stream_id, state.revision_id, final.seq),
        )

    @staticmethod
    def _snapshot_matches(stream_plan: HistoricalStreamPlan, snapshot) -> bool:
        return (
            snapshot.stream == stream_plan.request.identity
            and snapshot.source_token == stream_plan.source_token
            and snapshot.completed_through == stream_plan.target_completed_through
            and len(snapshot.bars) == stream_plan.input_count
            and snapshot.input_bytes == stream_plan.input_bytes
            and canonical_sha256(snapshot.dependency_manifest)
            == stream_plan.dependency_digest
        )

    @staticmethod
    def _overall(reports: tuple[StreamBatchReport, ...]):
        statuses = {report.status for report in reports}
        if statuses == {"completed"}:
            return "completed"
        if statuses == {"noop"}:
            return "noop"
        if "partial" in statuses or len(statuses) > 1:
            return "partial"
        if statuses == {"blocked"}:
            return "blocked"
        return "failed"
