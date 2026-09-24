"""Append-only comparison of captured observation and later Canonical evidence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation
from app.reference_trading.repository import RepositoryConflict


@dataclass(frozen=True, slots=True)
class CanonicalEvidence:
    source_revision: str
    source_sha256: str | None

    def __post_init__(self) -> None:
        if not self.source_revision or len(self.source_revision) > 128:
            raise ValueError("CANONICAL_REVISION_INVALID")
        if self.source_sha256 is not None and (
            len(self.source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.source_sha256)
        ):
            raise ValueError("CANONICAL_HASH_INVALID")


class ForwardReconciler:
    def __init__(
        self, session_factory,
        read_canonical: Callable[[dict[str, object]], CanonicalEvidence],
        *, read_guard: Callable[[], AbstractContextManager[object]] = nullcontext,
    ) -> None:
        self._factory = session_factory
        self._read_canonical = read_canonical
        self._read_guard = read_guard

    def reconcile(self, capture_id: str, *, now: datetime) -> str:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("RECONCILIATION_TIME_INVALID")
        with self._read_guard():
            with self._factory() as session:
                capture = session.get(ReferenceBatch, capture_id)
                if capture is None or capture.kind != "capture":
                    raise RepositoryConflict("CAPTURE_NOT_FOUND")
                evidence = capture.source_evidence.get("forward_capture_v1")
                if not isinstance(evidence, dict):
                    raise RepositoryConflict("CAPTURE_CORRUPT")
                source_proof = evidence.get("source_proof")
                if not isinstance(source_proof, dict):
                    raise RepositoryConflict("CAPTURE_SOURCE_PROOF_MISSING")
                captured_hash = source_proof.get("source_sha256") or source_proof.get("window_sha256")
                if not isinstance(captured_hash, str) or len(captured_hash) != 64:
                    raise RepositoryConflict("CAPTURE_SOURCE_PROOF_MISSING")
            authoritative = self._read_canonical(evidence)
        if not isinstance(authoritative, CanonicalEvidence):
            raise TypeError("read_canonical must return CanonicalEvidence")
        status = (
            "pending" if authoritative.source_sha256 is None else
            "matched" if authoritative.source_sha256 == captured_hash else "mismatch"
        )
        with self._factory() as session, session.begin():
            existing = session.scalar(select(ReferenceCaptureReconciliation).where(
                ReferenceCaptureReconciliation.capture_batch_id == capture_id,
                ReferenceCaptureReconciliation.source_revision == authoritative.source_revision,
            ))
            if existing is not None:
                if (
                    existing.status != status
                    or existing.captured_sha256 != captured_hash
                    or existing.canonical_sha256 != authoritative.source_sha256
                ):
                    raise RepositoryConflict("RECONCILIATION_REVISION_CONFLICT")
                return existing.status
            session.add(ReferenceCaptureReconciliation(
                reconciliation_id=uuid4().hex, capture_batch_id=capture_id,
                source_revision=authoritative.source_revision,
                status=status, captured_sha256=captured_hash,
                canonical_sha256=authoritative.source_sha256, checked_at=now,
            ))
        return status
