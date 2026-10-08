"""Bounded Canonical readback inside the existing observation worker lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import exists, select

from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
from app.market_data.market_data_service import MarketDataError
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.forward_inputs import ForwardInputUnavailable, _bar_wire
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceCaptureReconciliation,
    ReferenceStream,
)
from app.reference_trading.newow_forward import _timestamp
from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
from app.reference_trading.repository import RepositoryConflict


class CompletedCanonicalReader:
    """Read exact physical completed content through MDS, with owner evidence."""

    def __init__(self, market_data, owner_segments):
        self._market = market_data
        self._owner_segments = owner_segments

    def __call__(self, evidence):
        payload, proof = evidence["input_payload"], evidence["source_proof"]
        if (
            evidence.get("source_kind") != "completed_live"
            or proof.get("frequency") != "60m"
        ):
            raise RepositoryConflict("RECONCILIATION_SOURCE_UNSUPPORTED")
        raw = payload["bar"]
        end = _timestamp(evidence["bar_end"])
        from datetime import date

        if raw.get("bar_end") != end.isoformat() or payload.get(
            "source_bar_sha256"
        ) != proof.get("source_sha256"):
            raise RepositoryConflict("RECONCILIATION_CAPTURE_IDENTITY_CONFLICT")
        day = date.fromisoformat(raw["trading_day"])
        product, contract = payload["product"].lower(), payload["contract"]
        identity = SimpleNamespace(
            product=product, frequency="60m", strategy_code="newow_trend"
        )
        if self._owner_segments(identity, contract, day, end) != (
            proof["owner_segment_id"],
            proof["calculation_segment_id"],
        ):
            raise RepositoryConflict("RECONCILIATION_OWNER_CONFLICT")
        try:
            source = self._market.contract_source_evidence(
                symbol=product, contract=contract, frequency=BarFrequency.H1, before=end
            )
        except MarketDataError as error:
            if error.code != "PHYSICAL_DATA_MISSING":
                raise
            return CanonicalEvidence(
                "unpublished:"
                + manifest_sha256([product, contract, "60m", end.isoformat()]),
                None,
            )
        revision = "canonical:" + manifest_sha256(source)
        coverage = [
            _timestamp(part.get("source_coverage_end") or part["coverage_end"])
            for part in source["partitions"]
            if part.get("source_coverage_end") or part.get("coverage_end")
        ]
        if not coverage or max(coverage) < end:
            return CanonicalEvidence(revision, None)
        result = self._market.query_page_inclusive(
            SeriesPageQuery(
                SeriesKind.CONTRACT,
                product,
                BarFrequency.H1,
                limit=1,
                contract=contract,
                before=end,
            )
        )
        if (
            len(result.bars) != 1
            or result.bars[0].bar_end != end
            or result.bars[0].trading_day != day
        ):
            raise RepositoryConflict("RECONCILIATION_CANONICAL_ENDPOINT_CONFLICT")
        canonical = _bar_wire(result.bars[0])
        # Capture scale is presentation, not market semantics. Reuse its lexical
        # scale only after Decimal equality has independently proved the value.
        comparable = {}
        for key, value in raw.items():
            authoritative = canonical[key]
            if (
                key in {"bar_end", "trading_day"}
                or value is None
                or authoritative is None
            ):
                comparable[key] = authoritative
            elif Decimal(value) == Decimal(authoritative):
                comparable[key] = value
            else:
                comparable[key] = authoritative
        return CanonicalEvidence(revision, manifest_sha256(comparable))


@dataclass(frozen=True, slots=True)
class ReconciliationRound:
    statuses: tuple[tuple[str, str], ...]
    errors: tuple[tuple[str, str], ...]


def capture_reconciliation_statuses(session, capture_ids):
    """Bulk derive statuses from exact base records without synthetic evidence."""
    ids = tuple(dict.fromkeys(capture_ids))
    if not ids:
        return {}
    if len(ids) > 4096:
        raise ValueError("RECONCILIATION_QUERY_BUDGET_INVALID")
    roots = {
        row.batch_id: row
        for row in session.scalars(
            select(ReferenceBatch).where(ReferenceBatch.batch_id.in_(ids))
        )
    }
    if len(roots) != len(ids) or any(row.kind != "capture" for row in roots.values()):
        raise RepositoryConflict("CAPTURE_NOT_FOUND")
    dependency_ids = set()
    fusion = {}
    for capture_id, row in roots.items():
        capture = row.source_evidence["forward_capture_v1"]
        if capture.get("source_kind") == "completed_fusion_sources":
            sources = capture["input_payload"].get("sources")
            if not isinstance(sources, list) or len(sources) != 2:
                raise RepositoryConflict("RECONCILIATION_DEPENDENCY_CONFLICT")
            fusion[capture_id] = sources
            dependency_ids.update(dep["capture_id"] for dep in sources)
    bases = (
        {
            row.batch_id: row
            for row in session.scalars(
                select(ReferenceBatch).where(
                    ReferenceBatch.batch_id.in_(dependency_ids)
                )
            )
        }
        if dependency_ids
        else {}
    )
    all_rows = {**roots, **bases}
    states = {
        capture_id: "pending"
        if row.source_evidence["forward_capture_v1"].get("source_kind")
        == "completed_live"
        else "not_applicable"
        for capture_id, row in all_rows.items()
    }
    for record in session.scalars(
        select(ReferenceCaptureReconciliation).where(
            ReferenceCaptureReconciliation.capture_batch_id.in_(tuple(all_rows))
        )
    ):
        current = states[record.capture_batch_id]
        if (
            record.status == "mismatch"
            or record.status == "matched"
            and current != "mismatch"
        ):
            states[record.capture_batch_id] = record.status
    for capture_id, sources in fusion.items():
        source_states = []
        for dep in sources:
            base = bases.get(dep["capture_id"])
            if (
                base is None
                or base.stream_id != dep["stream_id"]
                or base.revision_id != dep["revision_id"]
                or base.payload_hash != dep["capture"]["hash"]
                or base.kind != "capture"
                or base.source_evidence.get("forward_capture_v1") != dep["capture"]
                or dep["capture"].get("source_kind")
                not in {"completed_live", "canonical_completed"}
            ):
                raise RepositoryConflict("RECONCILIATION_DEPENDENCY_CONFLICT")
            source_states.append(states[base.batch_id])
        states[capture_id] = (
            "mismatch"
            if "mismatch" in source_states
            else "matched"
            if source_states == ["matched", "matched"]
            else "not_applicable"
            if source_states == ["not_applicable", "not_applicable"]
            else "pending"
        )
    return {capture_id: states[capture_id] for capture_id in ids}


def capture_reconciliation_status(session, capture_id):
    return capture_reconciliation_statuses(session, (capture_id,))[capture_id]


class ScheduledCanonicalReconciliation:
    """Round-robin pending readback with no notifications, replay or new task."""

    def __init__(
        self,
        session_factory,
        read_canonical,
        *,
        read_guard,
        limit=8,
        interval_seconds=60,
    ):
        if not 1 <= limit <= 64 or interval_seconds < 1:
            raise ValueError("RECONCILIATION_BUDGET_INVALID")
        self._factory = session_factory
        self._reconciler = ForwardReconciler(
            session_factory,
            read_canonical,
            read_guard=read_guard,
            scope_guard=self._scope_guard,
        )
        self._limit, self._interval = limit, interval_seconds
        self._after = None
        self._last = None

    @staticmethod
    def _scope_guard(session, capture):
        if capture is None:
            raise RepositoryConflict("CAPTURE_NOT_FOUND")
        stream = session.scalar(
            select(ReferenceStream)
            .where(ReferenceStream.stream_id == capture.stream_id)
            .with_for_update()
        )
        proof = capture.source_evidence.get("forward_capture_v1", {})
        if (
            stream is None
            or not stream.enabled
            or stream.active_revision_id != capture.revision_id
            or stream.activation_generation != proof.get("generation")
            or stream.frequency != proof.get("source_proof", {}).get("frequency")
            or stream.product.lower()
            != str(proof.get("input_payload", {}).get("product")).lower()
        ):
            raise RepositoryConflict("RECONCILIATION_SCOPE_CONFLICT")

    def tick(self, *, now):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("RECONCILIATION_TIME_INVALID")
        if (
            self._last is not None
            and (now - self._last).total_seconds() < self._interval
        ):
            return ReconciliationRound((), ())
        self._last = now
        with self._factory() as session:
            query = (
                select(ReferenceBatch)
                .join(
                    ReferenceStream,
                    ReferenceStream.stream_id == ReferenceBatch.stream_id,
                )
                .where(
                    ReferenceStream.enabled.is_(True),
                    ReferenceStream.recording_mode == "forward_observation",
                    ReferenceStream.frequency == "60m",
                    ReferenceStream.strategy_code.in_(
                        ("newow_trend", "newow_oscillation", "newow_main_rise")
                    ),
                    ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
                    ReferenceBatch.kind == "capture",
                    ReferenceBatch.outcome == "consumed",
                    ReferenceBatch.source_evidence["forward_capture_v1"][
                        "source_kind"
                    ].as_string()
                    == "completed_live",
                    ~exists(
                        select(ReferenceCaptureReconciliation.reconciliation_id).where(
                            ReferenceCaptureReconciliation.capture_batch_id
                            == ReferenceBatch.batch_id,
                            ReferenceCaptureReconciliation.status.in_(
                                ("matched", "mismatch")
                            ),
                        )
                    ),
                )
            )
            if self._after is not None:
                query = query.where(ReferenceBatch.batch_id > self._after)
            rows = session.scalars(
                query.order_by(ReferenceBatch.batch_id).limit(self._limit)
            ).all()
            if not rows and self._after is not None:
                self._after = None
                return self.tick_reset(now=now)
            captures = []
            for row in rows:
                stream = session.get(ReferenceStream, row.stream_id)
                evidence = row.source_evidence["forward_capture_v1"]
                if evidence.get("generation") == stream.activation_generation:
                    captures.append(row.batch_id)
            if rows:
                self._after = rows[-1].batch_id
        statuses, errors = [], []
        for capture_id in captures:
            try:
                statuses.append(
                    (capture_id, self._reconciler.reconcile(capture_id, now=now))
                )
            except Exception as error:  # noqa: BLE001 - preserve other scopes, never manufacture evidence
                errors.append((capture_id, type(error).__name__))
        return ReconciliationRound(tuple(statuses), tuple(errors))

    def tick_reset(self, *, now):
        self._last = None
        return self.tick(now=now)

    def assert_source_allowed(self, stream_id, *, session=None):
        from contextlib import nullcontext
        with (self._factory() if session is None else nullcontext(session)) as session:
            stream = session.execute(select(ReferenceStream).where(
                ReferenceStream.stream_id == stream_id,
            ).with_for_update()).scalar_one_or_none()
            mismatch = session.scalar(
                select(ReferenceCaptureReconciliation.reconciliation_id)
                .join(
                    ReferenceBatch,
                    ReferenceBatch.batch_id
                    == ReferenceCaptureReconciliation.capture_batch_id,
                )
                .join(
                    ReferenceStream,
                    ReferenceStream.stream_id == ReferenceBatch.stream_id,
                )
                .where(
                    ReferenceBatch.stream_id == stream_id,
                    ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
                    ReferenceCaptureReconciliation.status == "mismatch",
                )
                .limit(1)
            )
            if mismatch is not None:
                raise ForwardInputUnavailable("REFERENCE_CANONICAL_MISMATCH")
            if stream is not None and stream.strategy_code == "newow_dual_fusion":
                for code in ("newow_trend", "newow_oscillation"):
                    ids = session.scalars(
                        select(ReferenceStream.stream_id).where(
                            ReferenceStream.strategy_code == code,
                            ReferenceStream.product == stream.product,
                            ReferenceStream.frequency == stream.frequency,
                            ReferenceStream.recording_mode == "forward_observation",
                            ReferenceStream.enabled.is_(True),
                        )
                    ).all()
                    for base_id in sorted(ids):
                        self.assert_source_allowed(base_id, session=session)

    def commit_guard(self, session, stream_id):
        try:
            self.assert_source_allowed(stream_id, session=session)
        except ForwardInputUnavailable as error:
            raise RepositoryConflict("REFERENCE_CANONICAL_MISMATCH") from error
