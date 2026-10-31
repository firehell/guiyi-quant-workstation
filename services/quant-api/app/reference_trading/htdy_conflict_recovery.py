"""Stopped-writer, append-only HTDY conflict retirement and future flat restart.

Source verification is supplied by the authoritative MDS wrapper. This module
never edits observations, calculates historical signals or completes deliveries.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.htdy_activation import htdy_identity, SCHEMA, POLICY
from app.reference_trading.htdy_conflict_incidents import (
    ORIGINAL_VERSION as VERSION,
    OCT31_VERSION,
    OCT31_BINDINGS,
    OCT31_OPEN_STREAM,
)
from app.reference_trading.models import (
    ReferenceActivationReceipt,
    ReferenceBatch,
    ReferenceRevision,
    ReferenceStream,
    ReferenceInboxDelivery,
    ReferenceInboxInput,
    ReferenceTradeRow,
)
from app.reference_trading.newow_bootstrap import _BorrowedSession
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)

KEY = "htdy_conflict_boundary_v1"


def _wire(value):
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(v) for v in value]
    return value


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(value):
    return sha256(
        json.dumps(
            _wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _row(row):
    return {c.name: _wire(getattr(row, c.name)) for c in row.__table__.columns}


def _delivery(session, row):
    from app.reference_trading.inbox import _verified_input, _route_identity, _digest

    item = session.get(ReferenceInboxInput, row.input_id)
    if item is None or row.status == "UNKNOWN" or row.unknown_at is not None:
        raise RepositoryConflict("HTDY_CONFLICT_UNKNOWN_DELIVERY")
    _verified_input(item)
    routes = session.scalars(
        select(ReferenceInboxDelivery)
        .where(ReferenceInboxDelivery.input_id == item.input_id)
        .order_by(ReferenceInboxDelivery.stream_id)
    ).all()
    if (
        len(routes) != item.target_count
        or _digest([_route_identity(r) for r in routes]) != item.routing_sha256
    ):
        raise RepositoryConflict("HTDY_CONFLICT_ROUTING_INVALID")
    original = {"delivery": _row(row), "input": _row(item)}
    return {
        "delivery_id": row.delivery_id,
        "input_id": row.input_id,
        "status": row.status,
        "code": row.code,
        "envelope_sha256": item.envelope_sha256,
        "routing_sha256": item.routing_sha256,
        "original_digest": _hash(original),
        "original": original,
    }


def _receipt_hash(row):
    return _hash({k: v for k, v in _row(row).items() if k != "disabled_at"})


def _control_state(cp, end, day):
    from guiyi_quant.reference_trading import (
        ReferenceBoundary,
        BoundaryReason,
        reduce_reference,
    )

    boundary = ReferenceBoundary(
        cp.stream,
        BoundaryReason.DATA_INTERRUPTED,
        cp.physical_contract,
        cp.owner_segment_id,
        cp.calculation_segment_id,
        end,
        day,
    )
    return reduce_reference(cp.reference_state, boundaries=(boundary,)).state


def _presentation(identity, end, day):
    from app.reference_trading.presentation import envelope, presentation_point

    return envelope(
        [
            presentation_point(
                kind="boundary",
                trading_day=day,
                formula_versions=identity.formula_versions,
                value={
                    "version": KEY,
                    "reason": "DATA_CONFLICT",
                    "bar_end": _aware(end).isoformat(),
                    "control_transition": True,
                },
            )
        ]
    )


def _verify_proof(proof, binding, checkpoint):
    from app.reference_trading.htdy_conflict_source import (
        POLICY as SOURCE_POLICY,
        _bar,
        _fact,
        FIELDS,
    )
    from app.reference_trading.capture import ForwardCapture
    import re

    def require(value):
        if not value:
            raise RepositoryConflict("HTDY_CONFLICT_SOURCE_UNVERIFIED")

    require(
        isinstance(proof, dict)
        and proof.get("policy") == SOURCE_POLICY
        and proof.get("checkpoint_sha256") == binding["checkpoint_sha256"]
        and len(binding["captures"]) == 1
    )
    row = binding["captures"][0]
    wire = row["source_evidence"]["forward_capture_v1"]
    cap = ForwardCapture(
        binding["stream_id"],
        binding["revision_id"],
        wire["generation"],
        wire["source_key"],
        datetime.fromisoformat(wire["bar_end"]),
        datetime.fromisoformat(wire["observed_at"]),
        wire["source_kind"],
        wire["input_payload"],
        wire["source_proof"],
        wire["eligibility"],
    )
    require(
        proof.get("capture_sha256")
        == row["payload_hash"]
        == wire["hash"]
        == cap.capture_hash
        and proof.get("boundary_end") == wire["bar_end"]
        and proof.get("boundary_trading_day")
        == cap.input_payload["bars"][-1]["trading_day"]
    )
    members = {
        (b["bar_end"], c)
        for b, c in zip(
            cap.input_payload["bars"][:-1], cap.input_payload["bar_contracts"][:-1]
        )
    }
    conflicts = proof.get("conflicts")
    require(
        isinstance(conflicts, list)
        and bool(conflicts)
        and all(isinstance(c, dict) for c in conflicts)
    )
    old, raw, contracts = (
        checkpoint.strategy_state.window,
        cap.input_payload["bars"],
        cap.input_payload["bar_contracts"],
    )
    require(len(old) == len(raw) == len(contracts) == 32)
    bars = tuple(_bar(b) for b in raw)
    require(
        tuple((b.bar_end, b.trading_day, b.physical_contract) for b in old[1:])
        == tuple(
            (b.bar_end, b.trading_day, c) for b, c in zip(bars[:-1], contracts[:-1])
        )
    )
    expected = []
    for a, b, c in zip(old[1:], bars[:-1], contracts[:-1]):
        fields = {
            f: {"old": str(getattr(a, f)), "new": str(getattr(b, f))}
            for f in FIELDS
            if getattr(a, f) != getattr(b, f)
        }
        if fields:
            expected.append(
                {
                    "bar_end": b.bar_end.isoformat(),
                    "contract": c,
                    "old_sha256": manifest_sha256(_fact(a, c)),
                    "new_sha256": manifest_sha256(_fact(b, c)),
                    "fields": fields,
                }
            )
    require(
        sorted(conflicts, key=lambda c: (c.get("contract", ""), c.get("bar_end", "")))
        == sorted(expected, key=lambda c: (c["contract"], c["bar_end"]))
    )
    for c in conflicts:
        require(
            isinstance(c, dict)
            and (c.get("bar_end"), c.get("contract")) in members
            and all(
                isinstance(c.get(k), str) and re.fullmatch("[0-9a-f]{64}", c[k])
                for k in ("old_sha256", "new_sha256")
            )
            and c["old_sha256"] != c["new_sha256"]
            and isinstance(c.get("fields"), dict)
            and bool(c["fields"])
        )
    require(len({(c["bar_end"], c["contract"]) for c in conflicts}) == len(conflicts))
    sources = proof.get("sources")
    require(isinstance(sources, list) and bool(sources))
    coverage = set()
    for source in sources:
        require(isinstance(source, dict) and isinstance(source.get("evidence"), dict))
        e = source["evidence"]
        require(
            e.get("contract") in {c["contract"] for c in conflicts}
            and e.get("frequency") in {"1m", "60m"}
            and isinstance(e.get("partitions"), list)
            and bool(e["partitions"])
            and isinstance(source.get("publication_provenance"), list)
            and bool(source["publication_provenance"])
        )
        for part in e["partitions"]:
            require(
                isinstance(part.get("content_sha256"), str)
                and re.fullmatch("[0-9a-f]{64}", part["content_sha256"])
                and (
                    part.get("quality_sha256") is None
                    or re.fullmatch("[0-9a-f]{64}", part["quality_sha256"])
                )
            )
        for publication in source["publication_provenance"]:
            require(
                publication.get("version") == 1
                and publication.get("input_source")
                == ("rqdata" if e["frequency"] == "1m" else "canonical_1m")
                and isinstance(publication.get("input_sha256"), str)
                and re.fullmatch("[0-9a-f]{64}", publication["input_sha256"])
            )
        coverage.add((e["contract"], e["frequency"]))
    require(coverage == {(c["contract"], f) for c in conflicts for f in ("1m", "60m")})


class HtdyConflictRecovery:
    """Atomic domain transaction; caller owns durable one-shot attempt fencing."""

    def __init__(
        self, factory, *, verify_source, assert_fenced, clock=None, incident=VERSION
    ):
        if incident not in (VERSION, OCT31_VERSION):
            raise ValueError("HTDY_CONFLICT_INCIDENT_INVALID")
        if not callable(verify_source) or not callable(assert_fenced):
            raise ValueError("HTDY_CONFLICT_VERIFIER_REQUIRED")
        self.factory, self.verify_source, self.assert_fenced = (
            factory,
            verify_source,
            assert_fenced,
        )
        self.clock = clock
        self.incident = incident

    def _freeze(self, session, ids, start, *, lock=False):
        from app.reference_trading.inbox_recovery import (
            _verified_calculation_resolution_ids,
        )

        if (self.incident == VERSION and (len(ids) != 48 or len(set(ids)) != 48)) or (
            self.incident == OCT31_VERSION and sorted(ids) != sorted(OCT31_BINDINGS)
        ):
            raise RepositoryConflict("HTDY_CONFLICT_SCOPE_INVALID")
        resolved = set(_verified_calculation_resolution_ids(session, stream_ids=ids))
        items, records = [], []
        for sid in sorted(ids):
            query = select(ReferenceStream).where(ReferenceStream.stream_id == sid)
            stream = session.scalar(query.with_for_update() if lock else query)
            if (
                stream is None
                or not stream.enabled
                or htdy_identity(stream.product).stream_id != sid
            ):
                raise RepositoryConflict("HTDY_CONFLICT_IDENTITY_INVALID")
            rev = session.get(ReferenceRevision, (sid, stream.active_revision_id))
            receipt = session.scalar(
                select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == sid,
                    ReferenceActivationReceipt.generation
                    == stream.activation_generation,
                    ReferenceActivationReceipt.disabled_at.is_(None),
                )
            )
            old = (
                None
                if rev is None
                else session.get(ReferenceBatch, rev.checkpoint_batch_id)
            )
            if (
                rev is None
                or rev.status != "active"
                or receipt is None
                or old is None
                or old.seq != rev.last_seq
                or old.seq != stream.latest_seq
            ):
                raise RepositoryConflict("HTDY_CONFLICT_PREIMAGE_INVALID")
            identity = htdy_identity(stream.product)
            if sha256(old.checkpoint_text.encode()).hexdigest() != old.post_state_hash:
                raise RepositoryConflict("HTDY_CONFLICT_CHECKPOINT_HASH_INVALID")
            checkpoint = adapter_checkpoint_from_json(
                old.checkpoint_text,
                expected_stream=identity,
                expected_strategy_schema=SCHEMA,
            )
            if (
                checkpoint.computed_through is None
                or checkpoint.computed_through >= start
            ):
                raise RepositoryConflict("HTDY_CONFLICT_BOUNDARY_INVALID")
            ReferenceRepository._validate_open_projection(
                session, sid, rev.revision_id, checkpoint.reference_state.open_trade
            )
            batches = session.scalars(
                select(ReferenceBatch)
                .where(
                    ReferenceBatch.stream_id == sid,
                    ReferenceBatch.revision_id == rev.revision_id,
                )
                .order_by(ReferenceBatch.batch_id)
            ).all()
            rows = session.scalars(
                select(ReferenceInboxDelivery)
                .where(
                    ReferenceInboxDelivery.stream_id == sid,
                    ReferenceInboxDelivery.status != "COMPLETED",
                )
                .order_by(ReferenceInboxDelivery.delivery_id)
            ).all()
            if any(
                r.revision_id != rev.revision_id
                or r.generation != stream.activation_generation
                for r in rows
                if r.delivery_id not in resolved
            ):
                raise RepositoryConflict("HTDY_CONFLICT_DELIVERY_REVISION_INVALID")
            deliveries = [
                _delivery(session, r) for r in rows if r.delivery_id not in resolved
            ]
            for delivery in deliveries:
                route, original = (
                    delivery["original"]["delivery"],
                    delivery["original"]["input"],
                )
                if (
                    route["activation_receipt_id"] != receipt.receipt_id
                    or route["activation_plan_hash"] != receipt.plan_hash
                    or route["recording_start"]
                    != _aware(receipt.recording_start).isoformat()
                    or not datetime.fromisoformat(original["bar_end"])
                    <= datetime.fromisoformat(original["confirmed_at"])
                    <= datetime.fromisoformat(original["ingested_at"])
                    < start
                ):
                    raise RepositoryConflict("HTDY_CONFLICT_DELIVERY_BOUNDARY_INVALID")
            binding = {
                "stream_id": sid,
                "revision_id": rev.revision_id,
                "checkpoint_batch_id": old.batch_id,
                "checkpoint_sha256": old.post_state_hash,
                "checkpoint": json.loads(old.checkpoint_text),
                "captures": [
                    _row(b)
                    for b in batches
                    if b.kind == "capture" and b.consumed_by_batch_id is None
                ],
                "deliveries": deliveries,
                "batches_sha256": _hash([_row(b) for b in batches]),
                "receipts_sha256": _receipt_hash(receipt),
            }
            if self.incident == OCT31_VERSION:
                if (
                    stream.activation_generation != 1
                    or len(binding["captures"]) != 1
                    or (rev.revision_id, binding["captures"][0]["batch_id"])
                    != OCT31_BINDINGS[sid]
                    or (checkpoint.reference_state.open_trade is not None)
                    != (sid == OCT31_OPEN_STREAM)
                ):
                    raise RepositoryConflict("HTDY_CONFLICT_INCIDENT_PREIMAGE_DRIFT")
            proof = self.verify_source(identity, binding, old.dependency_manifest)
            _verify_proof(proof, binding, checkpoint)
            end = datetime.fromisoformat(proof["boundary_end"])
            if end.tzinfo is None:
                raise RepositoryConflict("HTDY_CONFLICT_BOUNDARY_INVALID")
            day = date.fromisoformat(proof["boundary_trading_day"])
            if not checkpoint.computed_through <= _aware(end) < start:
                raise RepositoryConflict("HTDY_CONFLICT_BOUNDARY_INVALID")
            trades = session.scalars(
                select(ReferenceTradeRow)
                .where(
                    ReferenceTradeRow.stream_id == sid,
                    ReferenceTradeRow.revision_id == rev.revision_id,
                )
                .order_by(ReferenceTradeRow.trade_id, ReferenceTradeRow.valid_from_seq)
            ).all()
            items.append(
                {
                    "binding": binding,
                    "source_proof": _wire(proof),
                    "manifest": old.dependency_manifest,
                    "stream_sha256": _hash(_row(stream)),
                    "trades_sha256": _hash([_row(t) for t in trades]),
                }
            )
            records.append((identity, stream, rev, receipt, old, checkpoint, end, day))
        return items, records

    def plan(self, stream_ids, *, recording_start, expires_at, now):
        start, expiry, current = map(_aware, (recording_start, expires_at, now))
        if not current < expiry <= start:
            raise RepositoryConflict("HTDY_CONFLICT_WINDOW_INVALID")
        self.assert_fenced()
        with self.factory() as session:
            items, _ = self._freeze(session, list(stream_ids), start)
        payload = {
            "version": self.incident,
            "items": items,
            "recording_start": start.isoformat(),
            "expires_at": expiry.isoformat(),
        }
        return {**payload, "plan_hash": _hash(payload)}

    def readback(self, plan):
        if plan.get("version") != self.incident or _hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        ) != plan.get("plan_hash"):
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        if self.incident == OCT31_VERSION and sorted(
            item["binding"]["stream_id"] for item in plan["items"]
        ) != sorted(OCT31_BINDINGS):
            raise RepositoryConflict("HTDY_CONFLICT_SCOPE_INVALID")
        with self.factory() as session:
            ids = [item["binding"]["stream_id"] for item in plan["items"]]
            receipts = session.scalars(
                select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id.in_(ids),
                    ReferenceActivationReceipt.plan_hash == plan["plan_hash"],
                )
            ).all()
            if not receipts:
                return None
            if {r.stream_id for r in receipts} != set(ids):
                raise RepositoryConflict("HTDY_CONFLICT_PARTIAL_COMMIT")
            boundaries = [
                b.source_evidence[KEY]
                for b in session.scalars(
                    select(ReferenceBatch).where(ReferenceBatch.stream_id.in_(ids))
                )
                if KEY in b.source_evidence
                and b.source_evidence[KEY].get("plan_hash") == plan["plan_hash"]
            ]
            if len(boundaries) != len(ids) or {
                b["stream_id"] for b in boundaries
            } != set(ids):
                raise RepositoryConflict("HTDY_CONFLICT_PARTIAL_COMMIT")
            expected = {i["binding"]["stream_id"]: i for i in plan["items"]}
            for b in boundaries:
                item = expected[b["stream_id"]]
                if (
                    b["old_revision_id"] != item["binding"]["revision_id"]
                    or b["retired_deliveries"] != item["binding"]["deliveries"]
                    or b["source_proof"] != item["source_proof"]
                ):
                    raise RepositoryConflict("HTDY_CONFLICT_READBACK_DRIFT")
            retired_delivery_ids(session, stream_ids=ids)
            for r in receipts:
                stream = session.get(ReferenceStream, r.stream_id)
                if (
                    r.disabled_at is not None
                    or stream.active_revision_id != r.revision_id
                ):
                    raise RepositoryConflict("HTDY_CONFLICT_RECEIPT_STALE")
            return {r.stream_id: r.revision_id for r in receipts}

    def apply(self, plan, *, expected_plan_hash, now):
        if (
            plan.get("version") != self.incident
            or expected_plan_hash != plan.get("plan_hash")
            or _hash({k: v for k, v in plan.items() if k != "plan_hash"})
            != expected_plan_hash
        ):
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        prior = self.readback(plan)
        if prior is not None:
            return prior
        started = monotonic()

        def current():
            return _aware(self.clock() if self.clock else now) + (
                timedelta(0) if self.clock else timedelta(seconds=monotonic() - started)
            )

        start, expiry = (
            datetime.fromisoformat(plan[k]) for k in ("recording_start", "expires_at")
        )
        self.assert_fenced()
        try:
            with self.factory() as session, session.begin():
                if session.bind.dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                else:
                    session.execute(text("SELECT pg_advisory_xact_lock(874326819)"))
                items, records = self._freeze(
                    session,
                    [i["binding"]["stream_id"] for i in plan["items"]],
                    start,
                    lock=True,
                )
                if items != plan["items"]:
                    raise RepositoryConflict("HTDY_CONFLICT_PREIMAGE_DRIFT")
                if not current() < expiry <= start:
                    raise RepositoryConflict("HTDY_CONFLICT_WINDOW_INVALID")
                repo = ReferenceRepository(lambda: _BorrowedSession(session))
                results = {}
                for item, record in zip(items, records):
                    identity, stream, old, receipt, batch, cp, end, day = record
                    sid = stream.stream_id
                    boundary_id = uuid4().hex
                    seq = old.last_seq + 1
                    opened = cp.reference_state.open_trade
                    if opened is not None:
                        row = session.scalar(
                            select(ReferenceTradeRow).where(
                                ReferenceTradeRow.stream_id == sid,
                                ReferenceTradeRow.revision_id == old.revision_id,
                                ReferenceTradeRow.trade_id == opened.reference_trade_id,
                                ReferenceTradeRow.valid_to_seq.is_(None),
                            )
                        )
                        data = {
                            c.name: getattr(row, c.name) for c in row.__table__.columns
                        }
                        row.valid_to_seq = seq
                        data.update(
                            valid_from_seq=seq,
                            valid_to_seq=None,
                            status="DATA_INTERRUPTED",
                            effective_bar_end=end,
                            observed_at=None,
                        )
                        session.flush()
                        session.add(ReferenceTradeRow(**data))
                    boundary_cp = replace(
                        cp, reference_state=_control_state(cp, end, day)
                    )
                    content = adapter_checkpoint_to_json(
                        boundary_cp, strategy_schema=SCHEMA
                    )
                    boundary = {
                        "version": KEY,
                        "reason": "DATA_CONFLICT",
                        "plan_hash": expected_plan_hash,
                        "stream_id": sid,
                        "old_revision_id": old.revision_id,
                        "future_start": start.isoformat(),
                        "old_checkpoint_sha256": batch.post_state_hash,
                        "old_batches_sha256": item["binding"]["batches_sha256"],
                        "old_trades_sha256": item["trades_sha256"],
                        "old_checkpoint_batch_id": batch.batch_id,
                        "boundary_batch_id": boundary_id,
                        "boundary_end": _aware(end).isoformat(),
                        "boundary_trading_day": day.isoformat(),
                        "retired_deliveries": item["binding"]["deliveries"],
                        "retired_deliveries_sha256": _hash(
                            item["binding"]["deliveries"]
                        ),
                        "source_proof": item["source_proof"],
                        "old_receipt_id": receipt.receipt_id,
                        "old_receipt_sha256": _receipt_hash(receipt),
                    }
                    manifest = {
                        **batch.dependency_manifest,
                        KEY: {
                            "plan_hash": expected_plan_hash,
                            "old_revision_id": old.revision_id,
                        },
                    }
                    revision_id = repo.create_revision(
                        sid, stream.row_version, manifest_sha256(manifest)
                    )
                    seed = replace(
                        cp,
                        strategy_state=HtdyForwardState(MODEL_VERSION, POLICY),
                        reference_state=ReferenceState.flat(
                            identity, recording_start=start
                        ),
                        computed_through=None,
                        last_fingerprint=None,
                        physical_contract=None,
                        owner_segment_id=None,
                        calculation_segment_id=None,
                    )
                    seed_text = adapter_checkpoint_to_json(seed, strategy_schema=SCHEMA)
                    repo.stage_seed_chunk(
                        revision_id,
                        SeedChunk(
                            "htdy-conflict:" + expected_plan_hash,
                            0,
                            1,
                            sha256(seed_text.encode()).hexdigest(),
                            seed_text,
                        ),
                    )
                    repo.seal_seed(revision_id, manifest, seed, SCHEMA)
                    new = session.get(ReferenceRevision, (sid, revision_id))
                    new_receipt_id = uuid4().hex
                    boundary.update(
                        new_revision_id=revision_id,
                        new_receipt_id=new_receipt_id,
                        new_seed_batch_id=new.checkpoint_batch_id,
                    )
                    session.add(
                        ReferenceBatch(
                            batch_id=boundary_id,
                            stream_id=sid,
                            revision_id=old.revision_id,
                            batch_key="htdy-conflict:" + expected_plan_hash,
                            payload_hash=_hash(boundary),
                            kind="calculation",
                            outcome="committed",
                            seq=seq,
                            expected_seq=old.last_seq,
                            pre_state_hash=batch.post_state_hash,
                            post_state_hash=sha256(content.encode()).hexdigest(),
                            checkpoint_text=content,
                            strategy_schema=SCHEMA,
                            computed_through=cp.computed_through,
                            last_event_bar_end=None
                            if boundary_cp.reference_state.last_event_key is None
                            else boundary_cp.reference_state.last_event_key[0],
                            last_event_kind=None
                            if boundary_cp.reference_state.last_event_key is None
                            else boundary_cp.reference_state.last_event_key[1],
                            last_event_sequence=None
                            if boundary_cp.reference_state.last_event_key is None
                            else boundary_cp.reference_state.last_event_key[2],
                            dependency_manifest=batch.dependency_manifest,
                            source_evidence={
                                KEY: boundary,
                                "presentation_v1": _presentation(identity, end, day),
                            },
                            projected_action_pks=[],
                            diagnostics=["DATA_CONFLICT"],
                            processed_at=current(),
                        )
                    )
                    session.flush()  # Insert control batch before advancing its revision FK.
                    (
                        old.status,
                        old.invalid_reason,
                        old.last_seq,
                        old.checkpoint_batch_id,
                    ) = "invalid", "DATA_CONFLICT", seq, boundary_id
                    new.status = "active"
                    receipt.disabled_at = current()
                    stream.active_revision_id, stream.latest_seq = (
                        revision_id,
                        new.last_seq,
                    )
                    stream.activation_generation += 1
                    stream.row_version += 1
                    (
                        stream.recording_start,
                        stream.activation_plan_hash,
                        stream.health,
                    ) = start, expected_plan_hash, "READY"
                    session.add(
                        ReferenceActivationReceipt(
                            receipt_id=new_receipt_id,
                            stream_id=sid,
                            revision_id=revision_id,
                            generation=stream.activation_generation,
                            plan_hash=expected_plan_hash,
                            recording_start=start,
                            activated_at=current(),
                            environment=receipt.environment,
                            host=receipt.host,
                            budget=receipt.budget,
                            recovery_policy="block",
                        )
                    )
                    results[sid] = revision_id
                session.flush()
                self.assert_fenced()
                if not current() < expiry:
                    raise RepositoryConflict("HTDY_CONFLICT_WINDOW_INVALID")
                return results
        except SQLAlchemyError as error:
            raise RepositoryConflict("HTDY_CONFLICT_COMMIT_OUTCOME_UNKNOWN") from error


def retired_delivery_ids(session, *, stream_ids=None, check_cancelled=lambda: None):
    """Verify append-only conflict retirement without pretending a calculation ACK."""
    query = select(ReferenceBatch.batch_id).where(
        ReferenceBatch.kind == "calculation",
        ReferenceBatch.batch_key.like("htdy-conflict:%"),
    )
    if stream_ids is not None:
        query = query.where(ReferenceBatch.stream_id.in_(stream_ids))
    result = []
    for identifier in session.scalars(query):
        check_cancelled()
        batch = session.get(ReferenceBatch, identifier)
        proof = batch.source_evidence.get(KEY)
        if proof is None:
            continue

        def require(ok):
            if not ok:
                raise RepositoryConflict("HTDY_CONFLICT_RETIREMENT_INVALID")

        require(
            proof.get("version") == KEY
            and proof.get("reason") == "DATA_CONFLICT"
            and proof.get("boundary_batch_id") == batch.batch_id
            and batch.payload_hash == _hash(proof)
            and batch.diagnostics == ["DATA_CONFLICT"]
            and not batch.projected_action_pks
        )
        sid, oldid, newid = (
            proof["stream_id"],
            proof["old_revision_id"],
            proof["new_revision_id"],
        )
        old, new = (
            session.get(ReferenceRevision, (sid, rid)) for rid in (oldid, newid)
        )
        original = session.get(ReferenceBatch, proof["old_checkpoint_batch_id"])
        receipt = session.get(ReferenceActivationReceipt, proof["new_receipt_id"])
        previous = session.get(ReferenceActivationReceipt, proof["old_receipt_id"])
        seed = session.get(ReferenceBatch, proof["new_seed_batch_id"])
        require(
            old is not None
            and old.status == "invalid"
            and old.invalid_reason == "DATA_CONFLICT"
            and old.checkpoint_batch_id == batch.batch_id
            and old.last_seq == batch.seq
            and new is not None
            and new.parent_revision_id == oldid
            and original is not None
            and original.post_state_hash == proof["old_checkpoint_sha256"]
            and receipt is not None
            and receipt.stream_id == sid
            and receipt.revision_id == newid
            and receipt.plan_hash == proof["plan_hash"]
            and _aware(receipt.recording_start).isoformat() == proof["future_start"]
            and previous is not None
            and previous.disabled_at is not None
            and _receipt_hash(previous) == proof["old_receipt_sha256"]
            and seed is not None
            and seed.revision_id == newid
            and seed.kind == "seed_seal"
        )
        require(
            batch.stream_id == sid
            and batch.revision_id == oldid
            and batch.expected_seq == original.seq
            and batch.seq == original.seq + 1
            and batch.pre_state_hash == original.post_state_hash
            and sha256(original.checkpoint_text.encode()).hexdigest()
            == original.post_state_hash
            and sha256(batch.checkpoint_text.encode()).hexdigest()
            == batch.post_state_hash
            and sha256(seed.checkpoint_text.encode()).hexdigest()
            == seed.post_state_hash
            and previous.stream_id == sid
            and previous.revision_id == oldid
            and receipt.generation == previous.generation + 1
            and seed.stream_id == sid
            and seed.seq == 1
            and seed.dependency_manifest.get(KEY)
            == {"plan_hash": proof["plan_hash"], "old_revision_id": oldid}
            and seed.payload_hash
            == sha256(
                (
                    manifest_sha256(seed.dependency_manifest) + seed.post_state_hash
                ).encode()
            ).hexdigest()
        )
        require(
            _aware(batch.processed_at)
            <= _aware(previous.disabled_at)
            <= _aware(receipt.activated_at)
            < datetime.fromisoformat(proof["future_start"])
            and (
                receipt.disabled_at is None
                or _aware(receipt.disabled_at) >= _aware(receipt.activated_at)
            )
        )
        identity = htdy_identity(session.get(ReferenceStream, sid).product)
        original_cp = adapter_checkpoint_from_json(
            original.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema=SCHEMA,
        )
        old_batches = session.scalars(
            select(ReferenceBatch)
            .where(
                ReferenceBatch.stream_id == sid,
                ReferenceBatch.revision_id == oldid,
                ReferenceBatch.batch_id != batch.batch_id,
            )
            .order_by(ReferenceBatch.batch_id)
        ).all()
        require(_hash([_row(b) for b in old_batches]) == proof["old_batches_sha256"])
        _verify_proof(
            proof["source_proof"],
            {
                "stream_id": sid,
                "revision_id": oldid,
                "checkpoint_sha256": original.post_state_hash,
                "captures": [
                    _row(b)
                    for b in old_batches
                    if b.kind == "capture" and b.consumed_by_batch_id is None
                ],
            },
            original_cp,
        )
        boundary_cp = adapter_checkpoint_from_json(
            batch.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema=SCHEMA,
        )
        require(
            boundary_cp
            == replace(
                original_cp,
                reference_state=_control_state(
                    original_cp,
                    datetime.fromisoformat(proof["boundary_end"]),
                    date.fromisoformat(proof["boundary_trading_day"]),
                ),
            )
        )
        require(
            batch.outcome == "committed"
            and batch.observed_at is None
            and batch.source_evidence.get("presentation_v1")
            == _presentation(
                identity,
                datetime.fromisoformat(proof["boundary_end"]),
                date.fromisoformat(proof["boundary_trading_day"]),
            )
        )
        opened = original_cp.reference_state.open_trade
        trades = session.scalars(
            select(ReferenceTradeRow)
            .where(
                ReferenceTradeRow.stream_id == sid,
                ReferenceTradeRow.revision_id == oldid,
            )
            .order_by(ReferenceTradeRow.trade_id, ReferenceTradeRow.valid_from_seq)
        ).all()
        originals = []
        appended = [t for t in trades if t.valid_from_seq == batch.seq]
        require(len(appended) == int(opened is not None))
        old_open = []
        for trade in trades:
            if trade.valid_from_seq == batch.seq:
                continue
            row = _row(trade)
            if (
                opened is not None
                and trade.trade_id == opened.reference_trade_id
                and trade.status == "OPEN"
                and trade.valid_to_seq == batch.seq
            ):
                old_open.append(row)
                row = {**row, "valid_to_seq": None}
            originals.append(row)
        require(_hash(originals) == proof["old_trades_sha256"])
        if opened is not None:
            require(len(old_open) == 1)
            expected = {
                **old_open[0],
                "valid_from_seq": batch.seq,
                "valid_to_seq": None,
                "status": "DATA_INTERRUPTED",
                "effective_bar_end": proof["boundary_end"],
                "observed_at": None,
            }
            require(_row(appended[0]) == expected)
        cp = adapter_checkpoint_from_json(
            seed.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema=SCHEMA,
        )
        require(
            cp.strategy_state == HtdyForwardState(MODEL_VERSION, POLICY)
            and cp.computed_through is None
            and cp.reference_state
            == ReferenceState.flat(
                identity, recording_start=datetime.fromisoformat(proof["future_start"])
            )
        )
        retired = proof["retired_deliveries"]
        require(_hash(retired) == proof["retired_deliveries_sha256"])
        for frozen in retired:
            check_cancelled()
            row = session.get(ReferenceInboxDelivery, frozen["delivery_id"])
            require(
                row is not None
                and row.stream_id == sid
                and row.revision_id == oldid
                and row.generation == previous.generation
                and row.activation_receipt_id == previous.receipt_id
                and row.status != "COMPLETED"
                and _delivery(session, row) == frozen
            )
            result.append(row.delivery_id)
    if len(result) != len(set(result)):
        raise RepositoryConflict("HTDY_CONFLICT_RETIREMENT_DUPLICATE")
    return tuple(sorted(result))
