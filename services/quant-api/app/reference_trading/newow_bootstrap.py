"""Exact, atomic Newow forward warm-up from a published historical checkpoint.

Planning is read-only. Applying uses the existing repository and activation
protocol inside one locked transaction; historical reference positions never carry.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json

from sqlalchemy import select, text

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.planning import _canonical_identity
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict, _identity_from_row
from guiyi_quant.newow.product_adapters import ProductReplayState
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json, adapter_checkpoint_to_json

POLICY = "completed_observation_v1"
SCHEMAS = {"trend": "newow_product_replay_v1", "oscillation": "newow_product_replay_v1",
           "main_rise": "newow_product_replay_v1", "dual_fusion": "newow_dual_fusion_reference_v1"}
FREQUENCIES = ("1w", "1d", "60m")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return sha256(_json(value).encode()).hexdigest()


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("BOOTSTRAP_TIME_INVALID")
    return value.astimezone(UTC)


class _BorrowedSession:
    """Existing protocols retain their transaction scopes as nested savepoints."""
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __getattr__(self, name):
        return getattr(self.session, name)

    def begin(self):
        return self.session.begin_nested()


def _terminal_boundary_proven(batch, checkpoint):
    """A reference boundary advances its cursor without inventing a strategy Bar."""
    from app.reference_trading.inputs import _canonical
    from app.reference_trading.presentation import require_envelope
    from guiyi_quant.reference_trading import BoundaryReason

    progress = tuple(checkpoint.strategy_state.input_progress.values())
    if not progress:
        return False
    latest_input = max(item[0] for item in progress)
    if latest_input >= checkpoint.computed_through or checkpoint.reference_state.open_trade is not None:
        return False
    points = require_envelope(batch.source_evidence.get("presentation_v1"))
    trailing = []
    for point in points:
        if not isinstance(point["value"], dict):
            if point["kind"] not in {"hint", "diagnostic"}:
                return False
            continue
        end_wire = point["value"].get("bar_end")
        if not isinstance(end_wire, str):
            if point["kind"] not in {"hint", "diagnostic"}:
                return False
            continue  # Diagnostics/hints can have no independently timed Bar.
        if datetime.fromisoformat(end_wire) > latest_input:
            trailing.append(point)
    if not trailing or any(point["kind"] != "boundary" for point in trailing):
        return False
    hashes = []
    previous = latest_input
    for point in trailing:
        value = point["value"]
        end = datetime.fromisoformat(value["bar_end"])
        if (end <= previous or end > checkpoint.computed_through
                or value.get("reason") not in {BoundaryReason.ROLLOVER.value, BoundaryReason.DATA_INTERRUPTED.value}
                or (value.get("physical_contract"), value.get("owner_segment_id"), value.get("calculation_segment_id"))
                != (checkpoint.physical_contract, checkpoint.owner_segment_id, checkpoint.calculation_segment_id)):
            return False
        hashes.append(sha256(_canonical({
            "kind": "reference_boundary", "stream": checkpoint.stream.stream_id,
            "reason": value["reason"], "physical_contract": value["physical_contract"],
            "owner_segment_id": value["owner_segment_id"],
            "calculation_segment_id": value["calculation_segment_id"],
            "bar_end": end, "trading_day": datetime.fromisoformat(point["trading_day"]).date(),
        }).encode()).hexdigest())
        previous = end
    fingerprints = batch.dependency_manifest.get("input_fingerprints", [])
    return (previous == checkpoint.computed_through
            and hashes[-1] == checkpoint.last_fingerprint
            and batch.source_evidence.get("last_fingerprint") == checkpoint.last_fingerprint
            and fingerprints[-len(hashes):] == hashes)


class NewowForwardBootstrap:
    def __init__(self, session_factory):
        self._factory = session_factory

    def _source(self, session, stream_id, *, lock=False):
        query = select(ReferenceStream).where(ReferenceStream.stream_id == stream_id)
        row = session.scalar(query.with_for_update(read=True) if lock else query)
        if row is None:
            raise RepositoryConflict("BOOTSTRAP_HISTORY_MISSING")
        identity = _identity_from_row(row)
        strategy = identity.strategy_code.replace("-", "_").removeprefix("newow_")
        if (identity.recording_mode is not RecordingMode.HISTORICAL_REPLAY
                or strategy not in SCHEMAS or identity.frequency not in FREQUENCIES
                or not _canonical_identity(identity)):
            raise RepositoryConflict("BOOTSTRAP_HISTORY_IDENTITY_INVALID")
        if row.active_revision_id is None:
            raise RepositoryConflict("BOOTSTRAP_HISTORY_NOT_PUBLISHED")
        if row.health != "READY":
            raise RepositoryConflict("BOOTSTRAP_HISTORY_NOT_READY")
        query = select(ReferenceRevision).where(
            ReferenceRevision.stream_id == stream_id,
            ReferenceRevision.revision_id == row.active_revision_id,
        )
        revision = session.scalar(query.with_for_update(read=True) if lock else query)
        if revision is None or revision.status != "active" or revision.checkpoint_batch_id is None:
            raise RepositoryConflict("BOOTSTRAP_HISTORY_NOT_PUBLISHED")
        query = select(ReferenceBatch).where(ReferenceBatch.batch_id == revision.checkpoint_batch_id)
        batch = session.scalar(query.with_for_update(read=True) if lock else query)
        if (batch is None or not batch.checkpoint_text or batch.strategy_schema != SCHEMAS[strategy]
                or batch.seq != revision.last_seq or row.latest_seq != revision.last_seq
                or batch.post_state_hash != sha256(batch.checkpoint_text.encode()).hexdigest()
                or manifest_sha256(batch.dependency_manifest) != revision.dependency_digest):
            raise RepositoryConflict("BOOTSTRAP_HISTORY_CHECKPOINT_INVALID")
        if identity.frequency == "1d":
            from app.reference_trading.inputs import NEWOW_D1_REFERENCE_BOUNDARY_POLICY
            if batch.dependency_manifest.get("reference_boundary_policy_version") != NEWOW_D1_REFERENCE_BOUNDARY_POLICY:
                raise RepositoryConflict("BOOTSTRAP_HISTORY_BOUNDARY_POLICY_CONFLICT")
        checkpoint = adapter_checkpoint_from_json(batch.checkpoint_text, expected_stream=identity,
            expected_strategy_schema=batch.strategy_schema)
        if (checkpoint.computed_through is None or checkpoint.reference_state is None
                or not checkpoint.last_fingerprint or not checkpoint.physical_contract
                or not checkpoint.owner_segment_id or not checkpoint.calculation_segment_id):
            raise RepositoryConflict("BOOTSTRAP_WARMUP_NOT_PROVEN")
        if strategy != "dual_fusion" and (
            not isinstance(checkpoint.strategy_state, ProductReplayState)
            or checkpoint.strategy_state.calculation_segment_id != checkpoint.calculation_segment_id
            or (not any(progress[0] == checkpoint.computed_through
                        for progress in checkpoint.strategy_state.input_progress.values())
                and not _terminal_boundary_proven(batch, checkpoint))
        ):
            raise RepositoryConflict("BOOTSTRAP_WARMUP_NOT_PROVEN")
        binding = {"stream_id": stream_id, "revision_id": revision.revision_id,
            "seq": revision.last_seq, "checkpoint_hash": batch.post_state_hash,
            "dependency_digest": revision.dependency_digest,
            "computed_through": checkpoint.computed_through.isoformat()}
        return identity, checkpoint, batch.strategy_schema, dict(batch.dependency_manifest), binding

    def plan(self, historical_stream_id: str, *, recording_start: datetime, expires_at: datetime,
             host: str, environment: str, now: datetime, recovery_policy: str = "block") -> dict:
        start, expiry, current = map(_aware, (recording_start, expires_at, now))
        if start <= current or expiry <= current or expiry > start or not host or not environment:
            raise ValueError("BOOTSTRAP_PLAN_WINDOW_INVALID")
        if recovery_policy not in {"block", "interrupt_and_restart"}:
            raise ValueError("RECOVERY_POLICY_INVALID")
        with self._factory() as session:
            identity, checkpoint, schema, _, binding = self._source(session, historical_stream_id)
            if checkpoint.computed_through > current:
                raise RepositoryConflict("BOOTSTRAP_HISTORY_FUTURE_INPUT")
            if checkpoint.computed_through >= start:
                raise RepositoryConflict("BOOTSTRAP_WARMUP_AFTER_START")
            target_identity = replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION,
                observation_policy_version=POLICY)
            target = session.get(ReferenceStream, target_identity.stream_id)
            if target is not None and (target.enabled or target.activation_generation != 0 or target.active_revision_id is not None):
                raise RepositoryConflict("BOOTSTRAP_ACTIVATION_ALREADY_USED")
            payload = {"version": "newow_forward_bootstrap_v1", "source": binding,
                "product": identity.product,
                "strategy": identity.strategy_code.replace("-", "_").removeprefix("newow_"),
                "frequency": identity.frequency,
                "target_stream_id": target_identity.stream_id,
                "target_row_version": None if target is None else target.row_version,
                "strategy_schema": schema, "recording_start": start.isoformat(),
                "expires_at": expiry.isoformat(), "host": host, "environment": environment,
                "budget": {"max_pending_keys": 180, "max_units_per_round": 32},
                "recovery_policy": recovery_policy}
            return {**payload, "plan_hash": _hash(payload)}

    def plan_scope(self, operational, active, *, selected_products=None, **options) -> dict:
        products = validate_product_scope(operational, active)
        selected = tuple(product.lower() for product in (selected_products or products))
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(products):
            raise ValueError("BOOTSTRAP_PRODUCT_SCOPE_INVALID")
        with self._factory() as session:
            rows = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == RecordingMode.HISTORICAL_REPLAY.value,
                ReferenceStream.product.in_(selected),
                ReferenceStream.frequency.in_(FREQUENCIES),
            )).all()
            routes, invalid = {}, set()
            for row in rows:
                identity = _identity_from_row(row)
                strategy = identity.strategy_code.replace("-", "_").removeprefix("newow_")
                key = (identity.product, strategy, identity.frequency)
                if strategy in SCHEMAS:
                    if _canonical_identity(identity):
                        routes.setdefault(key, []).append(identity.stream_id)
                    else:
                        invalid.add(key)
        items = []
        for product in selected:
            for frequency in FREQUENCIES:
                for strategy in SCHEMAS:
                    item = {"product": product, "strategy": strategy, "frequency": frequency}
                    sources = routes.get((product, strategy, frequency), ())
                    if len(sources) != 1:
                        items.append({**item, "status": "blocked", "reason": (
                                      "BOOTSTRAP_HISTORY_IDENTITY_INVALID" if not sources and (product, strategy, frequency) in invalid
                                      else "BOOTSTRAP_HISTORY_MISSING" if not sources else "BOOTSTRAP_HISTORY_AMBIGUOUS"), "plan": None})
                        continue
                    try:
                        plan = self.plan(sources[0], **options)
                    except (RepositoryConflict, ValueError) as error:
                        reason = str(error) if isinstance(error, RepositoryConflict) else "BOOTSTRAP_PLAN_INVALID"
                        items.append({**item, "status": "blocked", "reason": reason, "plan": None})
                    else:
                        items.append({**item, "status": "ready", "reason": None, "plan": plan})
        result = {"version": "newow_forward_bootstrap_scope_v1", "products": list(products),
                  "selected_products": list(selected), "expected_count": len(items), "items": items}
        return {**result, "plan_hash": _hash(result)}

    @staticmethod
    def _prior_receipt(session, plan):
        target = session.scalar(select(ReferenceStream).where(
            ReferenceStream.stream_id == plan["target_stream_id"]
        ).with_for_update().execution_options(populate_existing=True))
        if target is None or not target.enabled or target.activation_generation != 1:
            return None
        seed = session.scalar(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == target.stream_id,
            ReferenceBatch.revision_id == target.active_revision_id,
            ReferenceBatch.kind == "seed_seal",
        ))
        if seed is None or seed.dependency_manifest.get("forward_bootstrap_v1", {}).get("plan_hash") != plan["plan_hash"]:
            return None
        receipt = session.scalar(select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == target.stream_id,
            ReferenceActivationReceipt.plan_hash == target.activation_plan_hash,
            ReferenceActivationReceipt.revision_id == target.active_revision_id,
            ReferenceActivationReceipt.generation == 1,
            ReferenceActivationReceipt.disabled_at.is_(None),
        ))
        if receipt is None:
            raise RepositoryConflict("BOOTSTRAP_ACTIVATION_RECEIPT_MISSING")
        return {"target_stream_id": target.stream_id, "revision_id": receipt.revision_id,
                "activation_plan_hash": receipt.plan_hash, "receipt_id": receipt.receipt_id,
                "bootstrap_plan_hash": plan["plan_hash"]}

    def apply(self, plan: dict, *, expected_plan_hash: str, now: datetime) -> dict:
        current = _aware(now)
        payload = {key: value for key, value in plan.items() if key != "plan_hash"}
        if (plan.get("version") != "newow_forward_bootstrap_v1" or plan.get("plan_hash") != _hash(payload)
                or expected_plan_hash != plan.get("plan_hash")):
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        with self._factory() as session, session.begin():
            if session.get_bind().dialect.name == "sqlite":
                # sqlite legacy mode otherwise commits the first SAVEPOINT outside BEGIN.
                session.execute(text("BEGIN IMMEDIATE"))
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '30s'"))
                lock_key = int.from_bytes(sha256(plan["target_stream_id"].encode()).digest()[:8], "big", signed=True)
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
            prior = self._prior_receipt(session, plan)
            if prior is not None:
                return prior
            start = _aware(datetime.fromisoformat(plan["recording_start"]))
            expiry = _aware(datetime.fromisoformat(plan["expires_at"]))
            if current > expiry or current >= start:
                raise RepositoryConflict("PLAN_EXPIRED_OR_START_IN_PAST")
            try:
                identity, source, schema, historical_manifest, binding = self._source(session, plan["source"]["stream_id"], lock=True)
            except (RepositoryConflict, ValueError) as error:
                if str(error) == "BOOTSTRAP_HISTORY_BOUNDARY_POLICY_CONFLICT":
                    raise
                raise RepositoryConflict("BOOTSTRAP_SOURCE_DRIFT") from error
            if (plan.get("product"), plan.get("strategy"), plan.get("frequency")) != (
                identity.product, identity.strategy_code.replace("-", "_").removeprefix("newow_"), identity.frequency
            ):
                raise RepositoryConflict("BOOTSTRAP_PLAN_IDENTITY_CONFLICT")
            if binding != plan["source"] or schema != plan["strategy_schema"]:
                raise RepositoryConflict("BOOTSTRAP_SOURCE_DRIFT")
            target_identity = replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION,
                observation_policy_version=POLICY)
            if target_identity.stream_id != plan["target_stream_id"]:
                raise RepositoryConflict("BOOTSTRAP_TARGET_IDENTITY_CONFLICT")
            target = session.scalar(select(ReferenceStream).where(
                ReferenceStream.stream_id == target_identity.stream_id).with_for_update().execution_options(populate_existing=True))
            if (target is not None and (target.enabled or target.activation_generation != 0
                    or target.active_revision_id is not None or target.row_version != (plan["target_row_version"] or 0))):
                raise RepositoryConflict("BOOTSTRAP_TARGET_DRIFT")
            if target is None and plan["target_row_version"] is not None:
                raise RepositoryConflict("BOOTSTRAP_TARGET_DRIFT")
            def factory():
                return _BorrowedSession(session)
            repository = ReferenceRepository(factory)
            stored = repository.ensure_stream(target_identity)
            manifest = {**historical_manifest, "forward_bootstrap_v1": {
                "plan_hash": plan["plan_hash"], "source": binding,
                "recording_start": plan["recording_start"], "policy": POLICY}}
            digest = manifest_sha256(manifest)
            candidates = list(session.scalars(select(ReferenceRevision).where(
                ReferenceRevision.stream_id == target_identity.stream_id,
                ReferenceRevision.status == "candidate")))
            if len(candidates) > 1 or candidates and candidates[0].dependency_digest != digest:
                raise RepositoryConflict("BOOTSTRAP_CANDIDATE_CONFLICT")
            revision_id = candidates[0].revision_id if candidates else repository.create_revision(target_identity.stream_id, stored.row_version, digest)
            checkpoint = replace(source, stream=target_identity,
                reference_state=ReferenceState.flat(target_identity, recording_start=start))
            checkpoint_text = adapter_checkpoint_to_json(checkpoint, strategy_schema=schema)
            sealed = candidates and candidates[0].checkpoint_batch_id is not None
            if not sealed:
                repository.stage_seed_chunk(revision_id, SeedChunk(
                    "bootstrap:" + plan["plan_hash"], 0, 1,
                    sha256(checkpoint_text.encode()).hexdigest(), checkpoint_text))
            repository.seal_seed(revision_id, manifest, checkpoint, schema)
            activation = ForwardActivation(factory)
            activation_plan = activation.plan(target_identity.stream_id, revision_id,
                host=plan["host"], environment=plan["environment"], recording_start=start,
                expires_at=expiry, budget=plan["budget"], recovery_policy=plan["recovery_policy"])
            receipt_id = activation.apply(activation_plan, expected_plan_hash=activation_plan.plan_hash, now=current)
            return {"target_stream_id": target_identity.stream_id, "revision_id": revision_id,
                "activation_plan_hash": activation_plan.plan_hash, "receipt_id": receipt_id,
                "bootstrap_plan_hash": plan["plan_hash"]}


def validate_product_scope(operational, active) -> tuple[str, ...]:
    def normalize(values):
        values = tuple(values)
        if any(not isinstance(value, str) or not value.isascii() or not value.isalpha()
               or not 1 <= len(value) <= 8 for value in values):
            raise ValueError("BOOTSTRAP_PRODUCT_SCOPE_INVALID")
        result = tuple(value.lower() for value in values)
        if len(set(result)) != len(result):
            raise ValueError("BOOTSTRAP_PRODUCT_SCOPE_INVALID")
        return set(result)
    operational, active = normalize(operational), normalize(active)
    if len(operational) != 60 or operational != active:
        raise ValueError("BOOTSTRAP_PRODUCT_SCOPE_INVALID")
    return tuple(sorted(operational))
