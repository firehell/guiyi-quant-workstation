"""Explicit AL-only continuation of a proven rolled-back fenced recovery.

The original claim is immutable. A second exclusive marker in the SAME namespace
permits exactly one continuation; neither normal apply nor polling grants it.
"""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
import os
import stat
from sqlalchemy import select
from app.reference_trading.inbox_recovery import POLICY, digest, require
from app.reference_trading.models import (
    ReferenceBatch as B,
    ReferenceRevision as R,
    ReferenceStream as S,
    ReferenceInboxRecoveryResult as Result,
)


def _claim_bytes(recovery, delivery_id):
    require(
        len(delivery_id) == 64 and all(c in "0123456789abcdef" for c in delivery_id)
    )
    return _private_bytes(recovery.attempt_dir / (delivery_id + ".json"))


def _private_bytes(path):
    directory_fd = _directory_fd(path.parent)
    try:
        fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        try:
            st = os.fstat(fd)
            require(
                stat.S_ISREG(st.st_mode)
                and st.st_uid == os.getuid()
                and st.st_nlink == 1
                and stat.S_IMODE(st.st_mode) == 0o600
                and st.st_size <= 4096
            )
            return os.read(fd, 4097)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def _directory_fd(path):
    require(
        path.is_absolute() and path.resolve() == path,
        "REFERENCE_ROLLBACK_NAMESPACE_DRIFT",
    )
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if not (
        stat.S_ISDIR(st.st_mode)
        and st.st_uid == os.getuid()
        and st.st_mode & 0o077 == 0
    ):
        os.close(fd)
        raise ValueError("REFERENCE_ROLLBACK_NAMESPACE_DRIFT")
    return fd


def _marker(recovery, delivery_id):
    return recovery.attempt_dir / (delivery_id + ".rollback-continuation.json")


def verify_link(proof, capture_id):
    try:
        _verify_link(proof, capture_id)
    except (KeyError, TypeError, ValueError):
        raise ValueError("REFERENCE_ROLLBACK_LINK_INVALID") from None


def _verify_link(proof, capture_id):
    link = proof["rollback_continuation"]
    require(
        isinstance(link, dict)
        and set(link)
        == {
            "version",
            "parent_proof",
            "parent_plan_hash",
            "parent_claim",
            "parent_claim_sha256",
            "capture_id",
            "rollback_proof_sha256",
        }
    )
    parent = link["parent_proof"]
    claim = link["parent_claim"]
    require(
        link["version"] == "al_proven_rollback_v1"
        and isinstance(parent, dict)
        and "rollback_continuation" not in parent
    )
    require(
        digest(parent) == link["parent_plan_hash"]
        and claim["policy"] == POLICY
        and claim["delivery_id"] == proof["delivery_id"]
        and claim["plan_hash"] == link["parent_plan_hash"]
        and claim["state"] == "started"
    )
    require(set(claim) == {"policy", "delivery_id", "plan_hash", "state", "at"})
    require(
        sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()
        == link["parent_claim_sha256"]
    )
    require(datetime.fromisoformat(claim["at"]).tzinfo is not None)
    for key in (
        "policy",
        "delivery_id",
        "input_id",
        "original_sha256",
        "source_receipt_sha256",
        "target_receipt_id",
        "target_receipt_sha256",
        "checkpoint",
        "capture_sha256",
        "attempt_namespace_sha256",
    ):
        require(parent.get(key) == proof.get(key))
    require(link["capture_id"] == capture_id)
    for key in ("parent_claim_sha256", "rollback_proof_sha256"):
        require(
            isinstance(link[key], str)
            and len(link[key]) == 64
            and all(c in "0123456789abcdef" for c in link[key])
        )


def check_marker(recovery, plan):
    expected = {
        "version": "al_proven_rollback_v1",
        "plan_hash": plan.plan_hash,
        "parent_plan_hash": plan.rollback_continuation["parent_plan_hash"],
        "state": "started",
    }
    require(
        json.loads(_private_bytes(_marker(recovery, plan.delivery_id))) == expected,
        "REFERENCE_ROLLBACK_CLAIM_REQUIRED",
    )


def check_external(recovery, plan):
    link = plan.rollback_continuation
    require(isinstance(link, dict), "REFERENCE_ROLLBACK_LINK_REQUIRED")
    verify_link(plan.proof(), link["capture_id"])
    raw = _claim_bytes(recovery, plan.delivery_id)
    require(
        sha256(raw).hexdigest() == link["parent_claim_sha256"]
        and json.loads(raw) == link["parent_claim"],
        "REFERENCE_ROLLBACK_PARENT_CLAIM_DRIFT",
    )
    require(callable(recovery.verify_rollback), "REFERENCE_ROLLBACK_PROOF_REQUIRED")
    proof = recovery.verify_rollback()
    require(
        isinstance(proof, dict)
        and proof.get("old_transactions_ended") is True
        and digest(proof) == link["rollback_proof_sha256"],
        "REFERENCE_ROLLBACK_NOT_PROVEN",
    )


def _db_proof(recovery, session, plan):
    from app.reference_trading.htdy_activation import htdy_identity
    from app.reference_trading.repository import _identity_from_row

    row, _ = recovery._validate(session, plan)
    stream = session.scalar(
        select(S).where(S.stream_id == row.stream_id).with_for_update()
    )
    require(
        _identity_from_row(stream) == htdy_identity("al")
        and row.status == "BLOCKED"
        and row.code == "HTDY_WINDOW_UNAVAILABLE",
        "REFERENCE_ROLLBACK_SCOPE_INVALID",
    )
    require(
        row.generation == plan.capture.generation,
        "REFERENCE_ROLLBACK_GENERATION_CHANGED",
    )
    require(
        session.get(Result, plan.delivery_id) is None,
        "REFERENCE_ROLLBACK_ALREADY_CLOSED",
    )
    revision = session.get(R, (row.stream_id, row.revision_id))
    require(
        revision.last_seq == plan.checkpoint.seq
        and revision.checkpoint_batch_id is not None,
        "REFERENCE_ROLLBACK_CHECKPOINT_DRIFT",
    )
    checkpoint = session.get(B, revision.checkpoint_batch_id)
    require(
        checkpoint.post_state_hash == plan.checkpoint.state_hash
        and sha256(checkpoint.checkpoint_text.encode()).hexdigest()
        == plan.checkpoint.state_hash,
        "REFERENCE_ROLLBACK_CHECKPOINT_DRIFT",
    )
    require(
        session.scalar(
            select(B.batch_id)
            .where(
                B.stream_id == row.stream_id,
                B.revision_id == row.revision_id,
                B.kind == "calculation",
                B.seq > plan.checkpoint.seq,
            )
            .limit(1)
        )
        is None,
        "REFERENCE_ROLLBACK_CALCULATION_EXISTS",
    )
    pending = session.scalars(
        select(B).where(
            B.stream_id == row.stream_id,
            B.revision_id == row.revision_id,
            B.kind == "capture",
            B.consumed_by_batch_id.is_(None),
        )
    ).all()
    require(
        len(pending) == 1
        and pending[0].batch_id == plan.rollback_continuation["capture_id"]
        and pending[0].outcome == "pending"
        and pending[0].payload_hash == plan.capture.capture_hash
        and pending[0].source_evidence == plan.capture.evidence(),
        "REFERENCE_ROLLBACK_CAPTURE_DRIFT",
    )


def plan_continuation(recovery, parent, *, capture_id, expires_at):
    require(
        parent.rollback_continuation is None, "REFERENCE_ROLLBACK_RECURSION_FORBIDDEN"
    )
    require(
        parent.plan_hash == digest(parent.proof()),
        "REFERENCE_ROLLBACK_PARENT_PLAN_INVALID",
    )
    require(
        parent.attempt_namespace_sha256 == digest(str(recovery.attempt_dir)),
        "REFERENCE_ROLLBACK_NAMESPACE_DRIFT",
    )
    require(
        not _marker(recovery, parent.delivery_id).exists(),
        "REFERENCE_ROLLBACK_ATTEMPT_CONSUMED",
    )
    require(
        expires_at.tzinfo is not None and recovery.now() < expires_at,
        "REFERENCE_ROLLBACK_PLAN_EXPIRED",
    )
    raw = _claim_bytes(recovery, parent.delivery_id)
    require(callable(recovery.verify_rollback), "REFERENCE_ROLLBACK_PROOF_REQUIRED")
    rollback = recovery.verify_rollback()
    require(
        isinstance(rollback, dict) and rollback.get("old_transactions_ended") is True,
        "REFERENCE_ROLLBACK_NOT_PROVEN",
    )
    link = {
        "version": "al_proven_rollback_v1",
        "parent_proof": parent.proof(),
        "parent_plan_hash": parent.plan_hash,
        "parent_claim": json.loads(raw),
        "parent_claim_sha256": sha256(raw).hexdigest(),
        "capture_id": capture_id,
        "rollback_proof_sha256": digest(rollback),
    }
    plan = replace(
        parent,
        fence_sha256=digest(recovery.verify_fence()),
        expires_at=expires_at,
        rollback_continuation=link,
        plan_hash="",
    )
    plan = replace(plan, plan_hash=digest(plan.proof()))
    with recovery.factory() as db, db.begin():
        _db_proof(recovery, db, plan)
    return plan


def _claim_continuation(recovery, plan):
    target = _marker(recovery, plan.delivery_id)
    directory_fd = _directory_fd(recovery.attempt_dir)
    try:
        try:
            fd = os.open(
                target.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        except OSError:
            raise ValueError("REFERENCE_ROLLBACK_ATTEMPT_CONSUMED") from None
        _write_claim(fd, plan, directory_fd)
    finally:
        os.close(directory_fd)


def _write_claim(fd, plan, directory_fd):
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(
                {
                    "version": "al_proven_rollback_v1",
                    "plan_hash": plan.plan_hash,
                    "parent_plan_hash": plan.rollback_continuation["parent_plan_hash"],
                    "state": "started",
                },
                f,
                sort_keys=True,
            )
            f.flush()
            os.fsync(f.fileno())
        os.fsync(directory_fd)
    except Exception:
        raise ValueError("REFERENCE_ROLLBACK_CLAIM_DURABILITY_UNKNOWN") from None


def apply_continuation(
    recovery,
    plan,
    *,
    expected_plan_hash,
    evaluator,
    commit_guard=None,
    fault_injector=None,
):
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.forward_service import ForwardReferenceService

    require(
        plan.rollback_continuation is not None
        and expected_plan_hash == plan.plan_hash
        and plan.plan_hash == digest(plan.proof()),
        "REFERENCE_ROLLBACK_PLAN_HASH_INVALID",
    )
    existing = recovery.readback(plan)
    if existing is not None:
        return existing
    with recovery.factory() as db, db.begin():
        _db_proof(recovery, db, plan)
    _claim_continuation(recovery, plan)
    repo = ReferenceRepository(recovery.factory, fault_injector=fault_injector)

    def guard(db, stream_id):
        _db_proof(recovery, db, plan)
        if commit_guard is not None:
            commit_guard(db, stream_id)

    try:
        ForwardReferenceService(repo, evaluator, commit_guard=guard).process_pending(
            plan.capture.stream_id, inbox_recovery=(recovery, plan)
        )
    except Exception:
        existing = recovery.readback(plan)
        if existing is not None:
            return existing
        raise ValueError("REFERENCE_ROLLBACK_OUTCOME_UNKNOWN") from None
    result = recovery.readback(plan)
    require(result is not None, "REFERENCE_ROLLBACK_READBACK_REQUIRED")
    return result
