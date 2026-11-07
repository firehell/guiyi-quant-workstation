"""Fenced, atomic old-formula retirement and verified new-formula activation.

Original checkpoints/actions are immutable. OPEN references acquire an appended
OBSERVATION_INTERRUPTED version, with no exit action, price or return.
"""

from datetime import datetime, date
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.reference_trading.models import (
    ReferenceStream,
    ReferenceRevision,
    ReferenceBatch,
    ReferenceActivationReceipt,
    ReferenceTradeRow,
)
from app.reference_trading.newow_bootstrap import (
    NewowForwardBootstrap,
    _BorrowedSession,
    _aware,
    _hash,
)
from app.reference_trading.repository import (
    ReferenceRepository,
    RepositoryConflict,
    _identity_from_row,
    _aware as _db_aware,
)
from app.reference_trading.presentation import envelope, presentation_point
from guiyi_quant.reference_trading import (
    RecordingMode,
    ReferenceBoundary,
    BoundaryReason,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    retirement_reference_from_json,
    adapter_checkpoint_to_json,
)

VERSION = "newow_formula_transition_v1"
SCHEMA = "reference_formula_retired_v1"
CODES = {"newow_oscillation", "newow_dual_fusion"}


def require(value, code="FORMULA_TRANSITION_INVALID"):
    if not value:
        raise RepositoryConflict(code)


def _row(row):
    return {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}


class NewowFormulaTransition:
    def __init__(self, factory, *, assert_fenced):
        self.factory, self.assert_fenced = factory, assert_fenced

    def _old(self, db, stream_id, *, lock=False):
        query = select(ReferenceStream).where(ReferenceStream.stream_id == stream_id)
        row = db.scalar(query.with_for_update() if lock else query)
        require(
            row is not None
            and row.enabled
            and row.active_revision_id
            and row.strategy_code in CODES
            and row.frequency in {"1d", "1w", "60m"}
            and row.recording_mode == RecordingMode.FORWARD_OBSERVATION.value
        )
        rev = db.get(ReferenceRevision, (stream_id, row.active_revision_id))
        batch = db.get(ReferenceBatch, rev.checkpoint_batch_id) if rev else None
        receipt = db.scalar(
            select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == stream_id,
                ReferenceActivationReceipt.generation == row.activation_generation,
                ReferenceActivationReceipt.disabled_at.is_(None),
            )
        )
        require(
            rev is not None
            and rev.status == "active"
            and batch is not None
            and receipt is not None
            and batch.seq == row.latest_seq == rev.last_seq
            and batch.checkpoint_text
            and sha256(batch.checkpoint_text.encode()).hexdigest()
            == batch.post_state_hash
        )
        identity = _identity_from_row(row)
        reference = retirement_reference_from_json(
            batch.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema=batch.strategy_schema,
        )
        repo = ReferenceRepository(lambda: _BorrowedSession(db))
        require(
            repo.read_pending_capture(stream_id) is None,
            "FORMULA_TRANSITION_PENDING_CAPTURE",
        )
        trades = list(
            db.scalars(
                select(ReferenceTradeRow).where(
                    ReferenceTradeRow.stream_id == stream_id,
                    ReferenceTradeRow.revision_id == rev.revision_id,
                    ReferenceTradeRow.valid_to_seq.is_(None),
                    ReferenceTradeRow.status == "OPEN",
                )
            )
        )
        require(len(trades) == int(reference.open_trade is not None))
        if trades:
            domain = repo._trade_domain(db, identity, trades[0])
            require(
                all(
                    getattr(domain, field) == getattr(reference.open_trade, field)
                    for field in (
                        "reference_trade_id",
                        "stream",
                        "side",
                        "physical_contract",
                        "owner_segment_id",
                        "calculation_segment_id",
                        "entry_action_id",
                        "entry_bar_end",
                        "entry_trading_day",
                        "entry_reference_price",
                        "status",
                        "exit_action_id",
                        "exit_reference_price",
                        "reference_return",
                    )
                )
            )
        batches = db.execute(
            select(
                ReferenceBatch.batch_id,
                ReferenceBatch.payload_hash,
                ReferenceBatch.post_state_hash,
                ReferenceBatch.consumed_by_batch_id,
            )
            .where(ReferenceBatch.stream_id == stream_id)
            .order_by(ReferenceBatch.batch_id)
        ).all()
        frozen = dict(
            stream=_row(row),
            revision=_row(rev),
            receipt=_row(receipt),
            checkpoint_sha256=batch.post_state_hash,
            batches_sha256=_hash([list(x) for x in batches]),
            open_sha256=_hash([_row(t) for t in trades]),
        )
        return frozen, (row, rev, batch, receipt, identity, reference)

    def plan(self, pairs, *, recording_start, expires_at, now):
        self.assert_fenced()
        start, expiry, at = map(_aware, (recording_start, expires_at, now))
        with self.factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
            return self._freeze(db, pairs, start=start, expiry=expiry, at=at)

    def _freeze(self, db, pairs, *, start, expiry, at):
        require(at < expiry <= start)
        require(len(pairs) == 2 and len({p[0] for p in pairs}) == 2)
        items = []
        for old_id, historical_id in sorted(pairs):
            frozen, data = self._old(db, old_id)
            row, _, _, receipt, old, _ = data
            history, _, _, _, _ = NewowForwardBootstrap(
                lambda: _BorrowedSession(db)
            )._source(db, historical_id)
            require(
                (history.strategy_code, history.product, history.frequency)
                == (old.strategy_code, old.product, old.frequency)
            )
            require(
                history.formula_versions != old.formula_versions,
                "FORMULA_TRANSITION_FORMULA_UNCHANGED",
            )
            warmup = seed_warmup(db, historical_id)
            bootstrap = NewowForwardBootstrap(lambda: _BorrowedSession(db)).plan(
                historical_id,
                recording_start=start,
                expires_at=expiry,
                host=receipt.host,
                environment=receipt.environment,
                now=at,
                recovery_policy=receipt.recovery_policy,
                formula_warmup=warmup,
            )
            require(bootstrap["target_stream_id"] != old_id)
            items.append(dict(old=frozen, bootstrap=bootstrap))
        require({i["old"]["stream"]["strategy_code"] for i in items} == CODES)
        require(
            len(
                {
                    (i["old"]["stream"]["product"], i["old"]["stream"]["frequency"])
                    for i in items
                }
            )
            == 1
        )
        body = dict(
            version=VERSION,
            items=items,
            recording_start=start.isoformat(),
            expires_at=expiry.isoformat(),
        )
        return {**body, "plan_hash": _hash(body)}

    def status(self, plan):
        require(
            plan.get("plan_hash")
            == _hash({k: v for k, v in plan.items() if k != "plan_hash"}),
            "PLAN_HASH_CONFLICT",
        )
        with self.factory() as db:
            return self._status(db, plan)

    def _status(self, db, plan):
        rows = list(
            db.scalars(
                select(ReferenceBatch).where(
                    ReferenceBatch.batch_key
                    == "formula-transition:" + plan["plan_hash"]
                )
            )
        )
        if not rows:
            return None
        expected = {i["old"]["stream"]["stream_id"] for i in plan["items"]}
        require(
            {b.stream_id for b in rows} == expected, "FORMULA_TRANSITION_PARTIAL_COMMIT"
        )
        indexed = {b.stream_id: b for b in rows}
        for item in plan["items"]:
            frozen = item["old"]
            sid = frozen["stream"]["stream_id"]
            batch = indexed[sid]
            row = db.get(ReferenceStream, sid)
            proof = retired_proof(db, row)
            require(
                proof is not None
                and proof["plan_hash"] == plan["plan_hash"]
                and batch.seq == int(frozen["stream"]["latest_seq"]) + 1
                and row.active_revision_id == frozen["stream"]["active_revision_id"]
                and row.activation_generation
                == int(frozen["stream"]["activation_generation"]) + 1,
                "FORMULA_TRANSITION_READBACK_DRIFT",
            )
            original = db.get(ReferenceBatch, frozen["revision"]["checkpoint_batch_id"])
            require(
                original is not None
                and original.post_state_hash == frozen["checkpoint_sha256"]
                and sha256(original.checkpoint_text.encode()).hexdigest()
                == original.post_state_hash
            )
            old_trades = list(
                db.scalars(
                    select(ReferenceTradeRow).where(
                        ReferenceTradeRow.stream_id == sid,
                        ReferenceTradeRow.revision_id == batch.revision_id,
                        ReferenceTradeRow.status == "OPEN",
                        ReferenceTradeRow.valid_to_seq == batch.seq,
                    )
                )
            )
            before = [{**_row(t), "valid_to_seq": "None"} for t in old_trades]
            require(
                _hash(before) == frozen["open_sha256"],
                "FORMULA_TRANSITION_READBACK_DRIFT",
            )
            interrupted = list(
                db.scalars(
                    select(ReferenceTradeRow).where(
                        ReferenceTradeRow.stream_id == sid,
                        ReferenceTradeRow.revision_id == batch.revision_id,
                        ReferenceTradeRow.valid_from_seq == batch.seq,
                    )
                )
            )
            require(
                {t.trade_id for t in interrupted} == {t.trade_id for t in old_trades}
                and all(
                    t.status == "OBSERVATION_INTERRUPTED"
                    and t.exit_action_pk is None
                    and t.exit_reference_price is None
                    and t.reference_return is None
                    for t in interrupted
                ),
                "FORMULA_TRANSITION_READBACK_DRIFT",
            )
            bootstrap = item["bootstrap"]
            target = db.get(ReferenceStream, bootstrap["target_stream_id"])
            require(
                target is not None
                and target.enabled
                and target.activation_generation == 1
            )
            receipt = db.scalar(
                select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == target.stream_id,
                    ReferenceActivationReceipt.revision_id == target.active_revision_id,
                    ReferenceActivationReceipt.generation == 1,
                    ReferenceActivationReceipt.disabled_at.is_(None),
                )
            )
            seed = db.scalar(
                select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == target.stream_id,
                    ReferenceBatch.revision_id == target.active_revision_id,
                    ReferenceBatch.kind == "seed_seal",
                )
            )
            require(
                receipt is not None
                and seed is not None
                and seed.dependency_manifest.get("forward_bootstrap_v1", {}).get(
                    "plan_hash"
                )
                == bootstrap["plan_hash"],
                "FORMULA_TRANSITION_TARGET_RECEIPT_MISSING",
            )
        return dict(
            status="COMMITTED", plan_hash=plan["plan_hash"], retired=sorted(expected)
        )

    def apply(self, plan, *, expected_plan_hash, now):
        require(
            plan.get("version") == VERSION
            and plan.get("plan_hash") == expected_plan_hash
            and _hash({k: v for k, v in plan.items() if k != "plan_hash"})
            == expected_plan_hash,
            "PLAN_HASH_CONFLICT",
        )
        self.assert_fenced()
        at = _aware(now)
        try:
            with self.factory() as db, db.begin():
                if db.get_bind().dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                else:
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    key = int.from_bytes(
                        sha256(expected_plan_hash.encode()).digest()[:8],
                        "big",
                        signed=True,
                    )
                    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
                prior = self._status(db, plan)
                if prior:
                    return prior
                require(
                    at < _aware(datetime.fromisoformat(plan["expires_at"])),
                    "FORMULA_TRANSITION_EXPIRED",
                )
                fresh = self._freeze(
                    db,
                    [
                        (
                            i["old"]["stream"]["stream_id"],
                            i["bootstrap"]["source"]["stream_id"],
                        )
                        for i in plan["items"]
                    ],
                    start=datetime.fromisoformat(plan["recording_start"]),
                    expiry=datetime.fromisoformat(plan["expires_at"]),
                    at=at,
                )
                require(fresh == plan, "FORMULA_TRANSITION_PREIMAGE_DRIFT")
                data = []
                for item in plan["items"]:
                    frozen, old = self._old(
                        db, item["old"]["stream"]["stream_id"], lock=True
                    )
                    require(frozen == item["old"], "FORMULA_TRANSITION_PREIMAGE_DRIFT")
                    data.append((item, old))

                def factory():
                    return _BorrowedSession(db)

                repo = ReferenceRepository(factory)
                for item, old in data:
                    row, rev, batch, receipt, identity, reference = old
                    result = NewowForwardBootstrap(factory).apply(
                        item["bootstrap"],
                        expected_plan_hash=item["bootstrap"]["plan_hash"],
                        now=at,
                    )
                    require(at > _db_aware(batch.computed_through))
                    original = json.loads(batch.checkpoint_text)
                    owner = tuple(
                        original[k]
                        for k in (
                            "physical_contract",
                            "owner_segment_id",
                            "calculation_segment_id",
                        )
                    )
                    require(
                        all(isinstance(v, str) and v for v in owner),
                        "FORMULA_TRANSITION_OWNER_MISSING",
                    )
                    day_wire = batch.source_evidence.get("presentation_v1", {}).get(
                        "last_day"
                    )
                    if day_wire is None and reference.open_trade is not None:
                        day_wire = (
                            reference.open_trade.mark_trading_day
                            or reference.open_trade.entry_trading_day
                        ).isoformat()
                    require(day_wire is not None, "FORMULA_TRANSITION_DAY_MISSING")
                    boundary = ReferenceBoundary(
                        identity,
                        BoundaryReason.OBSERVATION_INTERRUPTED,
                        *owner,
                        at,
                        date.fromisoformat(day_wire),
                    )
                    transition = reduce_reference(reference, boundaries=(boundary,))
                    checkpoint = AdapterCheckpoint(
                        transition.state,
                        at,
                        "formula-transition:" + expected_plan_hash,
                        boundary.physical_contract,
                        boundary.owner_segment_id,
                        boundary.calculation_segment_id,
                        identity,
                        transition.state,
                    )
                    content = adapter_checkpoint_to_json(
                        checkpoint, strategy_schema=SCHEMA
                    )
                    seq, batch_id = rev.last_seq + 1, uuid4().hex
                    proof = dict(
                        plan_hash=expected_plan_hash,
                        reason="FORMULA_VERSION_CHANGED",
                        old_stream_id=row.stream_id,
                        old_generation=receipt.generation,
                        new_stream_id=result["target_stream_id"],
                        previous_checkpoint_sha256=batch.post_state_hash,
                        last_market_computed_through=_db_aware(
                            batch.computed_through
                        ).isoformat(),
                        boundary_at=at.isoformat(),
                        recording_start=plan["recording_start"],
                    )
                    db.add(
                        ReferenceBatch(
                            batch_id=batch_id,
                            stream_id=row.stream_id,
                            revision_id=rev.revision_id,
                            batch_key="formula-transition:" + expected_plan_hash,
                            payload_hash=_hash(proof),
                            kind="calculation",
                            outcome="committed",
                            seq=seq,
                            expected_seq=rev.last_seq,
                            pre_state_hash=batch.post_state_hash,
                            post_state_hash=sha256(content.encode()).hexdigest(),
                            checkpoint_text=content,
                            strategy_schema=SCHEMA,
                            computed_through=at,
                            dependency_manifest={},
                            source_evidence={
                                VERSION: proof,
                                "presentation_v1": envelope(
                                    [
                                        presentation_point(
                                            kind="boundary",
                                            value=boundary,
                                            trading_day=boundary.trading_day,
                                            formula_versions=identity.formula_versions,
                                        )
                                    ]
                                ),
                            },
                            projected_action_pks=[],
                            diagnostics=["FORMULA_VERSION_CHANGED"],
                            observed_at=at,
                            processed_at=at,
                        )
                    )
                    prepared = SimpleNamespace(
                        stream_id=row.stream_id,
                        revision_id=rev.revision_id,
                        checkpoint=checkpoint,
                        transitions=(transition,),
                        input_observed_at=at,
                    )
                    repo._apply_trade_changes(db, prepared, action_pks={}, seq=seq)
                    db.flush()
                    rev.last_seq, rev.checkpoint_batch_id = seq, batch_id
                    row.latest_seq, row.enabled, row.health = (
                        seq,
                        False,
                        "FORMULA_RETIRED",
                    )
                    row.activation_generation += 1
                    row.row_version += 1
                    receipt.disabled_at = at
                db.flush()
                self.assert_fenced()
                return self._status(db, plan)
        except SQLAlchemyError as error:
            raise RepositoryConflict(
                "FORMULA_TRANSITION_COMMIT_OUTCOME_UNKNOWN"
            ) from error


def retired_proof(db, row):
    """Only terminal, disabled formula records are eligible for historical reads."""
    if (
        row is None
        or row.enabled
        or row.health != "FORMULA_RETIRED"
        or row.strategy_code not in CODES
    ):
        return None
    revision = db.get(ReferenceRevision, (row.stream_id, row.active_revision_id))
    batch = db.get(ReferenceBatch, revision.checkpoint_batch_id) if revision else None
    require(
        batch is not None
        and batch.strategy_schema == SCHEMA
        and batch.seq == row.latest_seq == revision.last_seq
        and batch.checkpoint_text
        and sha256(batch.checkpoint_text.encode()).hexdigest() == batch.post_state_hash
    )
    proof = batch.source_evidence.get(VERSION, {})
    require(
        proof.get("old_stream_id") == row.stream_id
        and batch.batch_key == "formula-transition:" + proof.get("plan_hash", "")
        and batch.payload_hash == _hash(proof)
    )
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_from_json,
    )

    cp = adapter_checkpoint_from_json(
        batch.checkpoint_text,
        expected_stream=_identity_from_row(row),
        expected_strategy_schema=SCHEMA,
    )
    require(cp.reference_state.open_trade is None)
    receipt = db.scalar(
        select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == row.stream_id,
            ReferenceActivationReceipt.generation == proof["old_generation"],
        )
    )
    require(
        receipt is not None
        and receipt.disabled_at is not None
        and row.activation_generation == receipt.generation + 1
    )
    return {**proof, "retired_seq": batch.seq}


def seed_warmup(db, stream_id):
    """Report existing kernel readiness; never borrow an old contract's history."""
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_from_json,
    )
    from app.reference_trading.planning import _canonical_identity

    row = db.get(ReferenceStream, stream_id)
    require(row is not None and _canonical_identity(_identity_from_row(row)))
    rev = db.get(ReferenceRevision, (stream_id, row.active_revision_id))
    batch = db.get(ReferenceBatch, rev.checkpoint_batch_id) if rev else None
    require(batch is not None and batch.checkpoint_text)
    checkpoint = adapter_checkpoint_from_json(
        batch.checkpoint_text,
        expected_stream=_identity_from_row(row),
        expected_strategy_schema=batch.strategy_schema,
    )
    from app.reference_trading.manifest_storage import resolve_manifest

    if row.strategy_code == "newow_dual_fusion":
        manifest = resolve_manifest(db, batch)
        dependencies = manifest.get("source_dependencies", [])
        require(len(dependencies) == 2, "FORMULA_FUSION_DEPENDENCIES_MISSING")
        sources = []
        for dep in dependencies:
            base = db.get(ReferenceStream, dep["stream_id"])
            require(
                base is not None
                and (base.product, base.frequency) == (row.product, row.frequency)
                and base.active_revision_id == dep["revision_id"]
            )
            source = seed_warmup(db, base.stream_id)
            require(
                source["checkpoint_seq"] == dep["seq"]
                and source["computed_through"]
                == checkpoint.computed_through.isoformat(),
                "FORMULA_FUSION_DEPENDENCIES_DRIFT",
            )
            sources.append(source)
        require(
            {s["strategy_code"] for s in sources}
            == {"newow_trend", "newow_oscillation"}
        )
        return dict(ready=all(s["ready"] for s in sources), sources=sources)
    points = batch.source_evidence.get("presentation_v1", {}).get("points", [])
    availability = [p["value"] for p in points if p.get("kind") == "availability"]
    ready = bool(
        availability and str(availability[-1].get("status")).lower() == "ready"
    )
    count = None
    if row.strategy_code == "newow_oscillation":
        from guiyi_quant.newow.oscillation_trueup import TrueupState

        state = checkpoint.strategy_state.oscillation_state
        require(type(state) is TrueupState)
        count = state.history_count
        ready = (
            ready
            and count >= 10
            and state.physical_contract == checkpoint.physical_contract
        )
    return dict(
        stream_id=stream_id,
        strategy_code=row.strategy_code,
        checkpoint_seq=batch.seq,
        checkpoint_sha256=batch.post_state_hash,
        computed_through=checkpoint.computed_through.isoformat(),
        physical_contract=checkpoint.physical_contract,
        calculation_segment_id=checkpoint.calculation_segment_id,
        history_count=count,
        required=10 if count is not None else None,
        ready=ready,
    )


def finish_formula_warmup(stream, prepared):
    """Only clear this explicit observation warmup, using verified emitted facts."""
    if stream.health != "FORMULA_WARMING":
        return
    points = prepared.source_evidence.get("presentation_v1", {}).get("points", [])
    availability = [p["value"] for p in points if p.get("kind") == "availability"]
    if availability and str(availability[-1].get("status")).lower() == "ready":
        stream.health = "READY"
