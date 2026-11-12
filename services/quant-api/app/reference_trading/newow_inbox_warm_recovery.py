"""Explicit same-revision recovery of a pristine H1 oscillation Inbox head."""

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.forward_authority import ForwardMarketAuthority
from app.reference_trading.forward_inputs import capture_newow_envelope
from app.reference_trading.inbox import _head_query, _validate_active, _verified_input
from app.reference_trading.inbox_recovery import InboxRecovery, require, verified_resolution_ids
from app.reference_trading.models import ReferenceInboxDelivery, ReferenceInboxInput
from app.reference_trading.newow_forward import _whole_number, evaluate_newow_capture
from app.reference_trading.recording_scope import recording_route_supported
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.retained_owner_transition import prove_rank1_owner_transition
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity, replay_step, seed_replay_state
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

POLICY = "newow_oscillation_inbox_warm_prefix_v1"


@dataclass(frozen=True)
class _WarmRecoveryInput:
    capture: ForwardCapture
    token: CheckpointToken
    original: AdapterCheckpoint
    warmed: AdapterCheckpoint
    manifest: dict

    def evaluate(self, token, checkpoint, evidence):
        require(
            token == self.token and checkpoint == self.original
            and evidence.get("forward_capture_v1") == self.capture.evidence()["forward_capture_v1"],
            "NEWOW_INBOX_WARM_CHECKPOINT_DRIFT",
        )
        return evaluate_newow_capture(token, self.warmed, evidence, dependency_manifest=self.manifest)


def _warm_bar(checkpoint, identity, capture, *, reset):
    payload, proof = capture.input_payload, capture.source_proof
    raw = payload["bar"]
    owner, calculation = proof["owner_segment_id"], proof["calculation_segment_id"]
    product = build_product_identity(
        identity.product, "oscillation", identity.frequency,
        input_quality_policy=payload["input_quality_policy"],
    )
    bar = NewowDailyBar(
        identity.product, payload["contract"], owner,
        date.fromisoformat(raw["trading_day"]),
        capture.bar_end, *(Decimal(raw[key]) for key in ("open", "high", "low", "close")),
        _whole_number(raw["volume"]),
        None if raw["open_interest"] is None else _whole_number(raw["open_interest"]),
        payload["source_identity"], True, True,
    )
    state, frame, _ = replay_step(
        product, seed_replay_state() if reset else checkpoint.strategy_state,
        ProductBar(
            bar,
            ProductFrequency(identity.frequency), calculation_segment_id=calculation,
            source_bar_sha256=payload["source_bar_sha256"],
        ),
    )
    require(frame is not None, "NEWOW_INBOX_WARM_DUPLICATE")
    return replace(
        checkpoint, strategy_state=state, computed_through=capture.bar_end,
        last_fingerprint=capture.capture_hash, physical_contract=payload["contract"],
        owner_segment_id=owner, calculation_segment_id=calculation,
    )


class NewowOscillationInboxWarmRecovery:
    """Warm from frozen, pre-activation originals and atomically resolve one head."""

    def __init__(self, factory, *, attempt_dir, verify_fence, market_factory=build_market_data_service):
        self.factory = factory
        self.market_factory = market_factory
        self.inbox = InboxRecovery(
            factory, attempt_dir=attempt_dir, verify_fence=verify_fence,
            verify_source=self._verify_source,
        )

    def prepare(self, delivery_id):
        with self.factory() as session, readonly_transaction(session, timeout_seconds=30):
            return self._prepare(session, delivery_id)

    def _prepare(self, session, delivery_id):
        delivery = session.get(ReferenceInboxDelivery, delivery_id)
        require(
            delivery is not None and delivery.status == "BLOCKED" and delivery.code == "OBSERVATION_GAP",
            "NEWOW_INBOX_WARM_DELIVERY_INVALID",
        )
        _validate_active(session, delivery, lock=False)
        resolved = verified_resolution_ids(session, stream_ids=(delivery.stream_id,))
        head = session.scalar(_head_query(delivery.stream_id, resolved))
        require(head is not None and head.delivery_id == delivery_id, "NEWOW_INBOX_WARM_HEAD_CHANGED")
        repository = ReferenceRepository(lambda: nullcontext(session))
        identity, revision, generation, start, after, *_ = repository.forward_source_context(delivery.stream_id)
        token, checkpoint = repository.load_checkpoint(delivery.stream_id)
        require(
            identity.strategy_code == "newow_oscillation" and identity.frequency == "60m"
            and token.seq == 1 and after is not None and after < start
            and checkpoint.reference_state == ReferenceState.flat(identity, recording_start=start),
            "NEWOW_INBOX_WARM_SEED_INVALID",
        )
        item = session.get(ReferenceInboxInput, delivery.input_id)
        original = _verified_input(item)
        require(start <= item.bar_end <= original.confirmed_at, "NEWOW_INBOX_WARM_BOUNDARY_INVALID")
        market = self.market_factory(session)
        authority = ForwardMarketAuthority(market)
        contract = original.data["contract"]
        day = original.trading_day
        ends = authority.expected_endpoints(identity, contract, day, after, item.bar_end)
        require(
            2 <= len(ends) <= 257 and ends[-1] == item.bar_end
            and tuple(sorted(set(ends))) == ends and ends[-2] < start,
            "NEWOW_INBOX_WARM_ENDPOINTS_INVALID",
        )
        transition = None
        if checkpoint.physical_contract != contract:
            transition = prove_rank1_owner_transition(
                market, authority, identity, checkpoint,
                previous_day=market.previous_trading_day(identity.product, day),
                trading_day=day, knowledge_at=start,
            )
        rows = session.scalars(select(ReferenceInboxInput).where(
            ReferenceInboxInput.product == item.product,
            ReferenceInboxInput.frequency == item.frequency,
            ReferenceInboxInput.trading_day == day,
            ReferenceInboxInput.bar_end.in_(ends[:-1]),
        ).limit(len(ends))).all()
        require(len(rows) == len(ends) - 1, "NEWOW_INBOX_WARM_ORIGINALS_INVALID")
        originals = {row.bar_end: row for row in rows}
        routed = session.scalar(select(ReferenceInboxDelivery.delivery_id).where(
            ReferenceInboxDelivery.stream_id == delivery.stream_id,
            ReferenceInboxDelivery.input_id.in_([row.input_id for row in rows]),
        ).limit(1))
        require(routed is None, "NEWOW_INBOX_WARM_ALREADY_ROUTED")

        def capture(event, watermark):
            result = capture_newow_envelope(
                event, identity, revision_id=revision, generation=generation, after=watermark,
                now=event.confirmed_at, owner_segments=authority.owner_segments,
                expected_endpoints=authority.expected_endpoints,
                capability_ready=lambda value: recording_route_supported(value.strategy_code, value.frequency),
            )
            require(result is not None, "NEWOW_INBOX_WARM_CAPTURE_INVALID")
            return result

        warmed, prefix = checkpoint, []
        for end in ends[:-1]:
            row = originals.get(end)
            require(row is not None, "NEWOW_INBOX_WARM_ORIGINALS_INVALID")
            event = _verified_input(row)
            require(
                event.notification_eligible and event.data["contract"] == contract
                and event.confirmed_at is not None and end <= event.confirmed_at < start,
                "NEWOW_INBOX_WARM_ORIGINAL_BOUNDARY_INVALID",
            )
            captured = capture(event, warmed.computed_through)
            owner = (
                contract, captured.source_proof["owner_segment_id"],
                captured.source_proof["calculation_segment_id"],
            )
            reset = owner != (warmed.physical_contract, warmed.owner_segment_id, warmed.calculation_segment_id)
            if reset:
                require(
                    not prefix and transition is not None and owner == (
                        transition.contract, transition.owner_segment_id, transition.calculation_segment_id,
                    ),
                    "NEWOW_INBOX_WARM_OWNER_UNPROVEN",
                )
            warmed = _warm_bar(warmed, identity, captured, reset=reset)
            prefix.append({"input_id": row.input_id, "envelope_sha256": row.envelope_sha256, "capture_sha256": captured.capture_hash})
        result = capture(original, warmed.computed_through)
        proof = {
            **result.source_proof,
            "inbox_delivery_id": delivery_id,
            "ingested_at": item.ingested_at.isoformat(),
            POLICY: {
                "checkpoint_sha256": token.state_hash,
                "recording_start": start.isoformat(),
                "originals": prefix,
                "owner_transition": transition.proof if transition is not None else None,
            },
        }
        return _WarmRecoveryInput(
            replace(result, source_proof=proof), token, checkpoint, warmed,
            repository.read_state(delivery.stream_id).dependency_manifest,
        )

    def _verify_source(self, plan):
        fresh = self.prepare(plan.delivery_id)
        require(
            fresh.token == plan.checkpoint and fresh.capture == plan.capture,
            "NEWOW_INBOX_WARM_SOURCE_DRIFT",
        )

    def plan(self, delivery_id, *, expires_at):
        prepared = self.prepare(delivery_id)
        return self.inbox.plan(delivery_id, capture=prepared.capture, expires_at=expires_at)

    def readback(self, plan):
        return self.inbox.readback(plan)

    def apply(self, plan, *, expected_plan_hash, commit_guard):
        require(expected_plan_hash == plan.plan_hash, "REFERENCE_INBOX_RECOVERY_PLAN_HASH_CONFLICT")
        existing = self.readback(plan)
        if existing is not None:
            return existing
        require(callable(commit_guard), "NEWOW_INBOX_WARM_COMMIT_GUARD_REQUIRED")
        prepared = self.prepare(plan.delivery_id)
        require(
            prepared.token == plan.checkpoint and prepared.capture == plan.capture,
            "NEWOW_INBOX_WARM_SOURCE_DRIFT",
        )
        return self.inbox.apply(
            plan, expected_plan_hash=expected_plan_hash,
            evaluator=prepared.evaluate, commit_guard=commit_guard,
        )
