"""Explicit, fenced, append-only repair. Normal workers never grant recovery."""

from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import os
import json
import stat
from sqlalchemy import select
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.models import (
    ReferenceActivationReceipt,
    ReferenceBatch,
    ReferenceInboxDelivery,
    ReferenceInboxInput,
    ReferenceInboxRecoveryResult,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.repository import _wire
from app.reference_trading.transaction_guards import (
    receipt_hash,
    consumed_bound_receipt,
)

POLICY = "reference_inbox_recovery_v1"
CODES = frozenset(
    {
        "REFERENCE_INBOX_NO_CALCULATION",
        "REFERENCE_FUSION_SOURCE_ACTION_CORRUPT",
        "OBSERVATION_GAP",
    }
)
MAX_RESULTS = 120000


def require(value, code="REFERENCE_INBOX_RECOVERY_UNPROVEN"):
    if not value:
        raise ValueError(code)


def _recoverable_delivery(delivery, stream):
    if delivery.status != "BLOCKED" or delivery.code in CODES:
        return True
    if delivery.code != "HTDY_WINDOW_UNAVAILABLE":
        return False
    # A frozen eligible H1 original may have been rejected by a later recovery
    # watermark. Only the exact accepted HTDY identity uses this explicit path;
    # the normal source, fence, original, checkpoint and atomic closure gates stay.
    from app.reference_trading.htdy_activation import htdy_identity
    from app.reference_trading.repository import _identity_from_row
    return _identity_from_row(stream) == htdy_identity(stream.product.lower())


def digest(value):
    import json

    return sha256(
        json.dumps(
            _wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def stable_receipt_hash(receipt):
    # disabled_at is the only permitted later lifecycle change.
    return digest(
        {
            c.name: getattr(receipt, c.name)
            for c in receipt.__table__.columns
            if c.name != "disabled_at"
        }
    )


def original_digest(delivery, item):
    from app.reference_trading.inbox import _verified_input
    _verified_input(item)
    return _original_content_digest(delivery, item)


def _original_content_digest(delivery, item):
    from app.reference_trading.inbox import _aware
    return digest(
        {
            "delivery": {
                c.name: (
                    _aware(v)
                    if isinstance(v := getattr(delivery, c.name), datetime)
                    else v
                )
                for c in delivery.__table__.columns
            },
            "input": {
                c.name: (
                    _aware(v) if isinstance(v := getattr(item, c.name), datetime) else v
                )
                for c in item.__table__.columns
            },
        }
    )


@dataclass(frozen=True)
class InboxRecoveryPlan:
    delivery_id: str
    input_id: str
    original_sha256: str
    source_receipt_sha256: str
    target_receipt_id: str
    target_receipt_sha256: str
    checkpoint: CheckpointToken
    capture: ForwardCapture
    fence_sha256: str
    expires_at: datetime
    attempt_namespace_sha256: str
    plan_hash: str

    def proof(self):
        return {
            "policy": POLICY,
            "delivery_id": self.delivery_id,
            "input_id": self.input_id,
            "original_sha256": self.original_sha256,
            "source_receipt_sha256": self.source_receipt_sha256,
            "target_receipt_id": self.target_receipt_id,
            "target_receipt_sha256": self.target_receipt_sha256,
            "checkpoint": asdict(self.checkpoint),
            "capture_sha256": self.capture.capture_hash,
            "fence_sha256": self.fence_sha256,
            "expires_at": self.expires_at.isoformat(),
            "attempt_namespace_sha256": self.attempt_namespace_sha256,
        }


def _exact_original(capture, delivery, item, target_generation, *, verified_original=None):
    from app.reference_trading.inbox import (
        _exact_legacy_capture,
        _exact_fusion_capture,
        _verified_input,
    )

    effective = SimpleNamespace(
        **{c.name: getattr(delivery, c.name) for c in delivery.__table__.columns}
    )
    effective.generation = target_generation
    original = verified_original if verified_original is not None else _verified_input(item)
    return _exact_legacy_capture(
        capture, effective, original
    ) or _exact_fusion_capture(capture, effective, original)


def _receipt_binding(session, delivery, stream, target):
    old = session.get(ReferenceActivationReceipt, delivery.activation_receipt_id)
    require(
        old is not None
        and old.stream_id == delivery.stream_id
        and old.revision_id == delivery.revision_id
        and old.generation == delivery.generation
        and old.plan_hash == delivery.activation_plan_hash
    )
    require(
        target is not None
        and target.stream_id == delivery.stream_id
        and target.revision_id == delivery.revision_id
        and target.disabled_at is None
    )
    if target.generation == delivery.generation:
        require(target.receipt_id == old.receipt_id)
    else:
        revision = session.get(
            ReferenceRevision, (stream.stream_id, stream.active_revision_id)
        )
        require(
            target.generation == delivery.generation + 1
            and target.budget.get("previous_receipt_sha256") == receipt_hash(old)
            and consumed_bound_receipt(session, target, revision),
            "REFERENCE_INBOX_RECOVERY_BRIDGE_UNPROVEN",
        )
    return old


def _verify_stored_bridge(
    delivery, item, old, target, row, gap_captures, gap_calculations, *, cache=None
):
    from app.reference_trading.inbox import _aware

    require(target.generation == delivery.generation + 1)
    cache_key = (old.receipt_id, target.receipt_id, row.stream_id, row.target_revision_id)
    if cache is not None and cache_key in cache:
        end, sequence = cache[cache_key]
        require(end < _aware(item.bar_end) and sequence < row.calculation_seq)
        return
    active_old = SimpleNamespace(
        **{c.name: getattr(old, c.name) for c in old.__table__.columns}
    )
    active_old.__table__ = old.__table__
    active_old.disabled_at = None
    require(
        target.recovery_policy == "interrupt_and_restart"
        and target.budget.get("previous_receipt_sha256") == receipt_hash(active_old)
    )
    additions = {
        "bounded_recovery_capture_sha256",
        "previous_receipt_sha256",
        "journal_proof_sha256",
    }
    require(
        {k: v for k, v in target.budget.items() if k not in additions}
        == {k: v for k, v in old.budget.items() if k not in additions}
    )
    bound = target.budget.get("bounded_recovery_capture_sha256")
    matches = [
        c
        for c in gap_captures
        if c.stream_id == row.stream_id
        and c.revision_id == row.target_revision_id
        and c.payload_hash == bound
    ]
    require(len(matches) == 1)
    capture = matches[0]
    calculation = gap_calculations.get(capture.consumed_by_batch_id)
    source = capture.source_evidence.get("forward_capture_v1", {})
    reconstructed = ForwardCapture(
        capture.stream_id,
        capture.revision_id,
        source["generation"],
        source["source_key"],
        datetime.fromisoformat(source["bar_end"]),
        datetime.fromisoformat(source["observed_at"]),
        source["source_kind"],
        source["input_payload"],
        source["source_proof"],
        source["eligibility"],
    )
    require(
        reconstructed.capture_hash == bound
        and source.get("hash") == bound
        and source.get("generation") == target.generation
        and source.get("eligibility") == "gap_recovery"
        and source.get("source_kind") == "observation_interruption"
        and reconstructed.bar_end < _aware(item.bar_end)
        and capture.outcome == "consumed"
        and calculation is not None
        and calculation.stream_id == row.stream_id
        and calculation.revision_id == row.target_revision_id
        and calculation.kind == "calculation"
        and calculation.outcome == "committed"
        and calculation.seq == capture.expected_seq + 1
        and calculation.seq < row.calculation_seq
        and calculation.source_evidence.get("forward_capture_v1")
        == {
            "capture_id": capture.batch_id,
            "hash": bound,
            "generation": target.generation,
        }
        and calculation.post_state_hash
        == sha256(calculation.checkpoint_text.encode()).hexdigest()
    )
    if cache is not None:
        cache[cache_key] = (reconstructed.bar_end, calculation.seq)


def verified_resolution_ids(session, *, stream_ids=None, check_cancelled=lambda: None):
    """One strict closure definition for ordering, health and native handover."""
    check_cancelled()
    query = select(ReferenceInboxRecoveryResult)
    if stream_ids is not None:
        query = query.where(ReferenceInboxRecoveryResult.stream_id.in_(stream_ids))
    rows = session.scalars(query.limit(MAX_RESULTS + 1)).all()
    require(len(rows) <= MAX_RESULTS)
    if not rows:
        return ()
    # Keep strong references: SQLAlchemy's identity map alone is weak and would
    # turn a set-based read into thousands of per-result reloads.
    deliveries = {
        r.delivery_id: r
        for r in session.scalars(
            select(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.delivery_id.in_([r.delivery_id for r in rows])
            )
        )
    }
    inputs = {
        r.input_id: r
        for r in session.scalars(
            select(ReferenceInboxInput).where(
                ReferenceInboxInput.input_id.in_([r.input_id for r in rows])
            )
        )
    }
    batch_ids = {r.capture_batch_id for r in rows} | {
        r.calculation_batch_id for r in rows
    }
    batches = {
        r.batch_id: r
        for r in session.scalars(
            select(ReferenceBatch).where(ReferenceBatch.batch_id.in_(batch_ids))
        )
    }
    receipt_ids = {r.target_receipt_id for r in rows} | {
        r.activation_receipt_id for r in deliveries.values()
    }
    receipts = {
        r.receipt_id: r
        for r in session.scalars(
            select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.receipt_id.in_(receipt_ids)
            )
        )
    }
    bridges = [
        r
        for r in rows
        if deliveries.get(r.delivery_id) is not None
        and r.target_generation != deliveries[r.delivery_id].generation
    ]
    gap_captures = []
    gap_calculations = {}
    if bridges:
        bounds = {
            receipts[r.target_receipt_id].budget.get("bounded_recovery_capture_sha256")
            for r in bridges
            if r.target_receipt_id in receipts
        }
        gap_captures = session.scalars(
            select(ReferenceBatch).where(
                ReferenceBatch.kind == "capture",
                ReferenceBatch.payload_hash.in_(bounds),
            )
        ).all()
        gap_calculations = {
            r.batch_id: r
            for r in session.scalars(
                select(ReferenceBatch).where(
                    ReferenceBatch.batch_id.in_(
                        [
                            r.consumed_by_batch_id
                            for r in gap_captures
                            if r.consumed_by_batch_id
                        ]
                    )
                )
            )
        }
    # Only this exact readback may reuse receipt hashes. Later transactions must
    # observe disablement/tampering and revalidate the entire closure again.
    receipt_hashes = {}
    def stable_hash(receipt):
        if receipt.receipt_id not in receipt_hashes:
            receipt_hashes[receipt.receipt_id] = stable_receipt_hash(receipt)
        return receipt_hashes[receipt.receipt_id]
    indexed_gaps = {}
    for capture in gap_captures:
        indexed_gaps.setdefault((capture.stream_id, capture.revision_id, capture.payload_hash), []).append(capture)
    originals, bridge_cache = {}, {}
    ids = []
    for row in rows:
        check_cancelled()
        delivery = deliveries.get(row.delivery_id)
        item = inputs.get(row.input_id)
        capture = batches.get(row.capture_batch_id)
        calc = batches.get(row.calculation_batch_id)
        receipt = receipts.get(row.target_receipt_id)
        require(
            delivery is not None
            and item is not None
            and delivery.input_id == row.input_id
            and delivery.status != "UNKNOWN"
        )
        if item.input_id not in originals:
            from app.reference_trading.inbox import _verified_input
            originals[item.input_id] = _verified_input(item)
        require(_original_content_digest(delivery, item) == row.original_sha256)
        proof = row.proof
        proof_hash = digest(proof)
        require(
            row.proof_sha256 == proof_hash
            and row.plan_hash == proof_hash
            and proof.get("policy") == POLICY
            and proof.get("delivery_id") == row.delivery_id
            and proof.get("input_id") == row.input_id
            and proof.get("original_sha256") == row.original_sha256
        )
        old = receipts.get(delivery.activation_receipt_id)
        require(
            old is not None
            and proof.get("source_receipt_sha256") == stable_hash(old)
            and receipt is not None
            and proof.get("target_receipt_sha256") == stable_hash(receipt)
            and receipt.receipt_id == proof.get("target_receipt_id")
            and receipt.stream_id == row.stream_id == delivery.stream_id
            and receipt.revision_id == row.target_revision_id == delivery.revision_id
            and receipt.generation == row.target_generation
        )
        require(
            capture is not None
            and calc is not None
            and row.outcome == "CALCULATED"
            and capture.consumed_by_batch_id == calc.batch_id
            and capture.outcome == "consumed"
            and calc.stream_id == capture.stream_id == row.stream_id
            and calc.revision_id == capture.revision_id == row.target_revision_id
            and calc.kind == "calculation"
            and calc.outcome == "committed"
            and calc.seq == row.calculation_seq
            and proof.get("capture_sha256") == capture.payload_hash
            and _exact_original(capture, delivery, item, row.target_generation,
                                verified_original=originals[item.input_id])
        )
        linked = calc.source_evidence.get("forward_capture_v1", {})
        require(
            linked
            == {
                "capture_id": capture.batch_id,
                "hash": capture.payload_hash,
                "generation": row.target_generation,
            }
            and calc.source_evidence.get("inbox_recovery_v1")
            == {"plan_hash": row.plan_hash, "delivery_id": row.delivery_id}
        )
        from app.reference_trading.inbox import _aware

        require(
            all(
                r.disabled_at is None
                or _aware(r.disabled_at) >= _aware(row.recorded_at)
                for r in (old, receipt)
            )
        )
        if row.target_generation != delivery.generation:
            _verify_stored_bridge(
                delivery, item, old, receipt, row,
                indexed_gaps.get((row.stream_id, row.target_revision_id,
                    receipt.budget.get("bounded_recovery_capture_sha256")), ()), gap_calculations,
                cache=bridge_cache,
            )
        checkpoint = proof.get("checkpoint", {})
        require(
            calc.expected_seq == checkpoint.get("seq")
            and calc.seq == checkpoint.get("seq") + 1
            and calc.pre_state_hash == checkpoint.get("state_hash")
            and calc.post_state_hash
            == sha256(calc.checkpoint_text.encode()).hexdigest()
        )
        ids.append(row.delivery_id)
    return tuple(ids)


class InboxRecovery:
    def __init__(
        self,
        session_factory,
        *,
        attempt_dir,
        verify_fence,
        verify_source,
        now=lambda: datetime.now(UTC),
    ):
        self.factory = session_factory
        self.verify_fence = verify_fence
        self.verify_source = verify_source
        self.now = now
        self.attempt_dir = Path(attempt_dir)
        require(
            self.attempt_dir.is_absolute()
            and self.attempt_dir.resolve() == self.attempt_dir,
            "REFERENCE_INBOX_RECOVERY_ATTEMPT_PATH_INVALID",
        )
        self.attempt_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.attempt_dir.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0,
            "REFERENCE_INBOX_RECOVERY_ATTEMPT_PATH_INVALID",
        )

    def plan(self, delivery_id, *, capture, expires_at):
        from app.reference_trading.inbox import _head_query, _aware
        from app.reference_trading.repository import ReferenceRepository

        now = self.now()
        require(
            expires_at.tzinfo is not None and now < expires_at,
            "REFERENCE_INBOX_RECOVERY_PLAN_EXPIRED",
        )
        require(capture.observed_at <= now, "REFERENCE_INBOX_RECOVERY_FUTURE_ORIGINAL")
        fence = self.verify_fence()
        require(
            fence.get("attempt_namespace_sha256") == digest(str(self.attempt_dir)),
            "REFERENCE_INBOX_RECOVERY_ATTEMPT_NAMESPACE_DRIFT",
        )
        require(
            isinstance(fence, dict) and bool(fence),
            "REFERENCE_INBOX_RECOVERY_FENCE_INVALID",
        )
        with self.factory() as session:
            delivery = session.get(ReferenceInboxDelivery, delivery_id)
            require(
                delivery is not None
                and delivery.status in {"PENDING", "WAITING_HISTORY", "BLOCKED"}
            )
            resolved = verified_resolution_ids(
                session, stream_ids=(delivery.stream_id,)
            )
            head = session.scalar(_head_query(delivery.stream_id, resolved))
            require(
                head is not None and head.delivery_id == delivery_id,
                "REFERENCE_INBOX_RECOVERY_ORDER_CONFLICT",
            )
            item = session.get(ReferenceInboxInput, delivery.input_id)
            stream = session.get(ReferenceStream, delivery.stream_id)
            require(
                stream is not None
                and stream.enabled
                and stream.active_revision_id == delivery.revision_id
            )
            require(_recoverable_delivery(delivery, stream))
            target = session.scalar(
                select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == stream.stream_id,
                    ReferenceActivationReceipt.generation
                    == stream.activation_generation,
                )
            )
            old = _receipt_binding(session, delivery, stream, target)
            require(
                target.plan_hash == stream.activation_plan_hash
                and _aware(target.recording_start) == _aware(delivery.recording_start)
            )
            require(
                capture.stream_id == delivery.stream_id
                and capture.revision_id == delivery.revision_id
                and capture.generation == target.generation
                and capture.source_proof.get("inbox_delivery_id") == delivery_id
            )
            raw = SimpleNamespace(
                kind="capture",
                stream_id=capture.stream_id,
                revision_id=capture.revision_id,
                source_evidence=capture.evidence(),
                payload_hash=capture.capture_hash,
            )
            require(
                _exact_original(raw, delivery, item, target.generation),
                "REFERENCE_INBOX_RECOVERY_ORIGINAL_CONFLICT",
            )
            token, _ = ReferenceRepository(self.factory).load_checkpoint(
                delivery.stream_id
            )
            require(
                not (self.attempt_dir / (delivery_id + ".json")).exists(),
                "REFERENCE_INBOX_RECOVERY_ATTEMPT_CONSUMED",
            )
            value = InboxRecoveryPlan(
                delivery_id,
                item.input_id,
                original_digest(delivery, item),
                stable_receipt_hash(old),
                target.receipt_id,
                stable_receipt_hash(target),
                token,
                capture,
                digest(fence),
                expires_at,
                digest(str(self.attempt_dir)),
                "",
            )
            plan = replace(value, plan_hash=digest(value.proof()))
        self.verify_source(plan)
        return plan

    def readback(self, plan):
        return self.readback_result(plan.delivery_id, expected_plan_hash=plan.plan_hash)

    def readback_result(self, delivery_id, *, expected_plan_hash):
        """Restart-safe exact readback needs only the durable intent's identity."""
        with self.factory() as session:
            row = session.get(ReferenceInboxRecoveryResult, delivery_id)
            if row is None:
                return None
            require(delivery_id in verified_resolution_ids(session, stream_ids=(row.stream_id,))
                    and row.plan_hash == expected_plan_hash,
                    "REFERENCE_INBOX_RECOVERY_READBACK_CONFLICT")
            return row.calculation_batch_id, row.calculation_seq

    def check_external(self, plan):
        require(
            digest(str(self.attempt_dir)) == plan.attempt_namespace_sha256,
            "REFERENCE_INBOX_RECOVERY_ATTEMPT_NAMESPACE_DRIFT",
        )
        require(self.now() <= plan.expires_at, "REFERENCE_INBOX_RECOVERY_PLAN_EXPIRED")
        require(
            digest(self.verify_fence()) == plan.fence_sha256,
            "REFERENCE_INBOX_RECOVERY_FENCE_DRIFT",
        )
        self.verify_source(plan)

    def _validate(self, session, plan):
        from app.reference_trading.inbox import _head_query

        require(
            plan.plan_hash == digest(plan.proof()),
            "REFERENCE_INBOX_RECOVERY_PLAN_HASH_CONFLICT",
        )
        self.check_external(plan)
        row = session.get(ReferenceInboxDelivery, plan.delivery_id)
        item = session.get(ReferenceInboxInput, plan.input_id)
        require(
            row is not None
            and item is not None
            and original_digest(row, item) == plan.original_sha256,
            "REFERENCE_INBOX_RECOVERY_PREIMAGE_DRIFT",
        )
        stream = session.get(ReferenceStream, row.stream_id)
        require(stream is not None and _recoverable_delivery(row, stream))
        target = session.get(ReferenceActivationReceipt, plan.target_receipt_id)
        old = _receipt_binding(session, row, stream, target)
        require(
            stable_receipt_hash(old) == plan.source_receipt_sha256
            and stable_receipt_hash(target) == plan.target_receipt_sha256
            and stream.activation_generation == target.generation
            and stream.active_revision_id == target.revision_id
            and stream.activation_plan_hash == target.plan_hash
            and stream.row_version == plan.checkpoint.row_version
        )
        head = session.scalar(
            _head_query(
                row.stream_id,
                verified_resolution_ids(session, stream_ids=(row.stream_id,)),
            )
        )
        require(
            head is not None and head.delivery_id == row.delivery_id,
            "REFERENCE_INBOX_RECOVERY_ORDER_CONFLICT",
        )
        return row, item

    def complete(self, session, plan, *, capture_row, calculation):
        row, item = self._validate(session, plan)
        require(
            capture_row.payload_hash == plan.capture.capture_hash
            and _exact_original(capture_row, row, item, plan.capture.generation)
            and calculation.expected_seq == plan.checkpoint.seq
        )
        proof = plan.proof()
        session.add(
            ReferenceInboxRecoveryResult(
                delivery_id=row.delivery_id,
                input_id=item.input_id,
                stream_id=row.stream_id,
                plan_hash=plan.plan_hash,
                original_sha256=plan.original_sha256,
                target_receipt_id=plan.target_receipt_id,
                target_revision_id=plan.capture.revision_id,
                target_generation=plan.capture.generation,
                capture_batch_id=capture_row.batch_id,
                calculation_batch_id=calculation.batch_id,
                calculation_seq=calculation.seq,
                outcome="CALCULATED",
                proof=_wire(proof),
                proof_sha256=digest(proof),
                recorded_at=self.now(),
            )
        )
        session.flush()

    def _claim(self, plan):
        require(
            plan.delivery_id
            and len(plan.delivery_id) == 64
            and all(c in "0123456789abcdef" for c in plan.delivery_id)
        )
        target = self.attempt_dir / (plan.delivery_id + ".json")
        try:
            fd = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except OSError:
            raise ValueError("REFERENCE_INBOX_RECOVERY_ATTEMPT_CONSUMED") from None
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(
                    json.dumps(
                        {
                            "policy": POLICY,
                            "delivery_id": plan.delivery_id,
                            "plan_hash": plan.plan_hash,
                            "state": "started",
                            "at": self.now().isoformat(),
                        },
                        sort_keys=True,
                    ).encode()
                )
                out.flush()
                os.fsync(out.fileno())
            directory_fd = os.open(
                self.attempt_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            raise ValueError(
                "REFERENCE_INBOX_RECOVERY_ATTEMPT_DURABILITY_UNKNOWN"
            ) from None

    def apply(self, plan, *, expected_plan_hash, evaluator, commit_guard=None, fault_injector=None):
        from app.reference_trading.repository import ReferenceRepository
        from app.reference_trading.forward_service import ForwardReferenceService

        require(
            expected_plan_hash == plan.plan_hash,
            "REFERENCE_INBOX_RECOVERY_PLAN_HASH_CONFLICT",
        )
        existing = self.readback(plan)
        if existing is not None:
            return existing
        with self.factory() as session:
            self._validate(session, plan)
        self._claim(plan)
        repository = ReferenceRepository(self.factory, fault_injector=fault_injector)
        try:
            repository.capture_forward(plan.capture)
            service = ForwardReferenceService(repository, evaluator, commit_guard=commit_guard)
            service.process_pending(plan.capture.stream_id, inbox_recovery=(self, plan))
        except Exception:
            result = self.readback(plan)
            if result is not None:
                return result
            raise ValueError("REFERENCE_INBOX_RECOVERY_OUTCOME_UNKNOWN") from None
        result = self.readback(plan)
        require(result is not None, "REFERENCE_INBOX_RECOVERY_READBACK_REQUIRED")
        return result


def validate_receiving_delivery(session, delivery, resolved):
    """Completed original facts outlive active generations; unresolved routes do not."""
    from app.reference_trading.inbox import (
        _validate_active,
        _legacy_calculation,
        InboxConflict,
    )

    if delivery.delivery_id in resolved:
        return
    try:
        _validate_active(session, delivery, lock=False)
        return
    except InboxConflict:
        if delivery.status != "COMPLETED":
            raise
    item = session.get(ReferenceInboxInput, delivery.input_id)
    calculation = session.get(ReferenceBatch, delivery.calculation_batch_id)
    source = (
        calculation.source_evidence.get("forward_capture_v1", {}) if calculation else {}
    )
    capture = (
        session.get(ReferenceBatch, source.get("capture_id"))
        if source.get("capture_id")
        else None
    )
    receipt = session.get(ReferenceActivationReceipt, delivery.activation_receipt_id)
    require(
        receipt is not None
        and receipt.stream_id == delivery.stream_id
        and receipt.revision_id == delivery.revision_id
        and receipt.generation == delivery.generation
        and receipt.plan_hash == delivery.activation_plan_hash
        and capture is not None
        and _exact_original(capture, delivery, item, delivery.generation)
        and _legacy_calculation(session, capture).batch_id
        == delivery.calculation_batch_id
    )
