"""Exact, atomic HTDY 60m first-seen forward scope activation.

Planning and readback are read-only. Applying creates only empty forward seeds;
it never captures historical observations or changes the accepted model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from time import monotonic

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision, ReferenceStream,
)
from app.reference_trading.newow_bootstrap import _BorrowedSession
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from guiyi_quant.reference_trading import RecordingMode, ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.htdy import HtdyForwardState, MODEL_VERSION
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json, adapter_checkpoint_to_json,
)


VERSION = "htdy60m_first_seen_reference_v1"
POLICY = "latest_only_32_v1"
SCHEMA = "htdy_first_seen_v1"
ACCEPTANCE_ID = VERSION
BUDGET = {"max_pending_keys": 360, "max_units_per_round": 32}
START_COMMIT_MARGIN = timedelta(seconds=10)
_SYMBOL = re.compile(r"[a-z]{1,8}")


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("HTDY_ACTIVATION_TIME_INVALID")
    return value.astimezone(UTC)


def _stored_aware(value: datetime) -> datetime:
    # SQLite's DateTime fixture discards tzinfo; repository readback uses UTC there.
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC))


def _products(values) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("HTDY_ACTIVATION_SCOPE_INVALID")
    try:
        raw = tuple(values)
    except TypeError as error:
        raise ValueError("HTDY_ACTIVATION_SCOPE_INVALID") from error
    if not 1 <= len(raw) <= 60 or any(
        not isinstance(item, str) or _SYMBOL.fullmatch(item.lower()) is None for item in raw
    ):
        raise ValueError("HTDY_ACTIVATION_SCOPE_INVALID")
    normalized = tuple(sorted(item.lower() for item in raw))
    if len(normalized) != len(set(normalized)):
        raise ValueError("HTDY_ACTIVATION_SCOPE_INVALID")
    return normalized


def htdy_identity(product: str) -> StreamIdentity:
    symbol, = _products((product,))
    return StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", symbol.upper(), "60m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, POLICY,
    )


def plan_htdy_activation(*, operational, recording_start: datetime,
                         expires_at: datetime, now: datetime,
                         host: str, environment: str) -> dict:
    products = _products(operational)
    start, expiry, current = map(_aware, (recording_start, expires_at, now))
    if not current < expiry <= start - START_COMMIT_MARGIN or not isinstance(host, str) or not host.strip() \
            or not isinstance(environment, str) or not environment.strip():
        raise ValueError("HTDY_ACTIVATION_PLAN_INVALID")
    payload = {
        "version": VERSION, "acceptance_id": ACCEPTANCE_ID,
        "strategy_code": "htdy", "formula_version": "huotian_dayou_original_v0",
        "reference_model_version": MODEL_VERSION, "observation_policy_version": POLICY,
        "frequency": "60m", "series_kind": "actual_dominant",
        "products": list(products),
        "stream_ids": [htdy_identity(item).stream_id for item in products],
        "recording_start": start.isoformat(), "expires_at": expiry.isoformat(),
        "host": host, "environment": environment,
        "recovery_policy": "block", "budget": dict(BUDGET),
    }
    return {**payload, "plan_hash": manifest_sha256(payload)}


def _validate(plan: dict, expected_plan_hash: str, operational, now: datetime):
    if not isinstance(plan, dict) or not isinstance(expected_plan_hash, str):
        raise RepositoryConflict("PLAN_HASH_CONFLICT")
    try:
        frozen = {key: value for key, value in plan.items() if key != "plan_hash"}
        if set(plan) != {"version", "acceptance_id", "strategy_code", "formula_version",
                         "reference_model_version", "observation_policy_version",
                         "frequency", "series_kind", "products", "stream_ids",
                         "recording_start", "expires_at", "host", "environment",
                         "recovery_policy", "budget", "plan_hash"} \
                or manifest_sha256(frozen) != expected_plan_hash \
                or plan["plan_hash"] != expected_plan_hash:
            raise RepositoryConflict("PLAN_HASH_CONFLICT")
        products = _products(plan["products"])
        if (list(products) != plan["products"] or products != _products(operational)
                or plan["version"] != VERSION or plan["acceptance_id"] != ACCEPTANCE_ID
                or plan["strategy_code"] != "htdy"
                or plan["formula_version"] != "huotian_dayou_original_v0"
                or plan["reference_model_version"] != MODEL_VERSION
                or plan["observation_policy_version"] != POLICY
                or plan["frequency"] != "60m" or plan["series_kind"] != "actual_dominant"
                or plan["stream_ids"] != [htdy_identity(p).stream_id for p in products]
                or plan["recovery_policy"] != "block" or plan["budget"] != BUDGET
                or not isinstance(plan["host"], str) or not plan["host"].strip()
                or not isinstance(plan["environment"], str) or not plan["environment"].strip()):
            raise RepositoryConflict("HTDY_ACTIVATION_SCOPE_DRIFT")
        start = _aware(datetime.fromisoformat(plan["recording_start"]))
        expiry = _aware(datetime.fromisoformat(plan["expires_at"]))
        current = _aware(now)
        if expiry > start - START_COMMIT_MARGIN:
            raise RepositoryConflict("HTDY_ACTIVATION_START_MARGIN_INVALID")
    except (KeyError, TypeError, ValueError) as error:
        raise RepositoryConflict("HTDY_ACTIVATION_PLAN_INVALID") from error
    return products, start, expiry, current, frozen


def plan_operational_htdy_activation(*, operational, **kwargs) -> dict:
    """Production entry: the frozen operational set must contain all 60 products."""
    products = _products(operational)
    if len(products) != 60:
        raise ValueError("HTDY_OPERATIONAL_SCOPE_NOT_60")
    return plan_htdy_activation(operational=products, **kwargs)


def apply_operational_htdy_activation(factory, plan: dict, *, expected_plan_hash: str,
                                      operational, now: datetime) -> dict:
    products = _products(operational)
    if len(products) != 60:
        raise RepositoryConflict("HTDY_OPERATIONAL_SCOPE_NOT_60")
    return apply_htdy_activation(factory, plan, expected_plan_hash=expected_plan_hash,
                                 operational=products, now=now)


def readback_htdy_activation(factory, plan: dict, *, expected_plan_hash: str,
                             operational) -> dict:
    """Prove a possibly committed scope without modifying or retrying it."""
    products, start, expiry, _current, frozen = _validate(
        plan, expected_plan_hash, operational, datetime.now(UTC))
    result = []
    with factory() as session:
        for product in products:
            identity = htdy_identity(product)
            stream = session.get(ReferenceStream, identity.stream_id)
            if (stream is None or not stream.enabled or stream.activation_generation != 1
                    or stream.recording_mode != RecordingMode.FORWARD_OBSERVATION.value
                    or stream.observation_policy_version != POLICY
                    or stream.latest_seq != 1 or stream.recording_start is None
                    or _stored_aware(stream.recording_start) != start or stream.active_revision_id is None):
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            revision = session.get(ReferenceRevision, (identity.stream_id, stream.active_revision_id))
            if (revision is None or revision.status != "active" or revision.last_seq != 1
                    or revision.checkpoint_batch_id is None):
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            receipt = session.scalar(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == identity.stream_id,
                ReferenceActivationReceipt.generation == 1))
            if (batch is None or batch.kind != "seed_seal" or batch.strategy_schema != SCHEMA
                    or batch.seq != 1 or batch.expected_seq != 0
                    or batch.computed_through is not None or batch.projected_action_pks
                    or not batch.checkpoint_text or batch.dependency_manifest != {
                        VERSION: frozen, "scope_plan_hash": expected_plan_hash}
                    or receipt is None or receipt.disabled_at is not None
                    or receipt.plan_hash != stream.activation_plan_hash
                    or receipt.revision_id != revision.revision_id
                    or receipt.recovery_policy != "block" or receipt.budget != BUDGET
                    or receipt.host != plan["host"] or receipt.environment != plan["environment"]
                    or _stored_aware(receipt.recording_start) != start
                    or _stored_aware(receipt.activated_at) > expiry
                    or _stored_aware(receipt.activated_at) > start - START_COMMIT_MARGIN):
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            activation_payload = {
                "stream_id": identity.stream_id, "revision_id": revision.revision_id,
                "row_version": stream.row_version - 1,
                "checkpoint_hash": batch.post_state_hash,
                "dependency_digest": revision.dependency_digest,
                "host": plan["host"], "environment": plan["environment"],
                "recording_start": start.isoformat(),
                "expires_at": plan["expires_at"], "budget": BUDGET,
                "model_acceptance_id": ACCEPTANCE_ID, "recovery_policy": "block",
            }
            activation_hash = sha256(json.dumps(
                activation_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if receipt.plan_hash != activation_hash:
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            checkpoint = adapter_checkpoint_from_json(
                batch.checkpoint_text, expected_stream=identity, expected_strategy_schema=SCHEMA)
            if (checkpoint.strategy_state != HtdyForwardState(MODEL_VERSION, POLICY)
                    or checkpoint.reference_state != ReferenceState.flat(identity, recording_start=start)
                    or checkpoint.computed_through is not None
                    or batch.post_state_hash != sha256(batch.checkpoint_text.encode()).hexdigest()
                    or revision.dependency_digest != manifest_sha256(batch.dependency_manifest)):
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            extras = session.scalar(select(ReferenceBatch.batch_id).where(
                ReferenceBatch.stream_id == identity.stream_id,
                ReferenceBatch.kind.in_(("capture", "calculation"))).limit(1))
            if extras is not None:
                raise RepositoryConflict("HTDY_ACTIVATION_READBACK_INCOMPLETE")
            result.append({"product": product, "stream_id": identity.stream_id,
                           "revision_id": revision.revision_id, "receipt_id": receipt.receipt_id,
                           "activation_plan_hash": receipt.plan_hash})
        enabled = session.scalars(select(ReferenceStream).where(
            func.replace(func.lower(ReferenceStream.strategy_code), "-", "_").like("htdy%"),
            ReferenceStream.frequency == "60m",
            ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
            ReferenceStream.enabled.is_(True))).all()
        if any(row.product.lower() in products and row.stream_id not in plan["stream_ids"] for row in enabled):
            raise RepositoryConflict("HTDY_ACTIVATION_DUPLICATE_ROUTE")
    return {"plan_hash": expected_plan_hash, "acceptance_id": ACCEPTANCE_ID,
            "routes": result}


def apply_htdy_activation(factory, plan: dict, *, expected_plan_hash: str,
                          operational, now: datetime) -> dict:
    products, start, expiry, current, frozen = _validate(plan, expected_plan_hash, operational, now)
    monotonic_start = monotonic()

    def checked_now() -> datetime:
        elapsed = max(0.0, monotonic() - monotonic_start)
        observed = current + timedelta(seconds=elapsed)
        if observed > expiry or observed > start - START_COMMIT_MARGIN:
            raise RepositoryConflict("PLAN_EXPIRED")
        return observed

    checked_now()
    try:
        with factory() as session, session.begin():
            dialect = session.get_bind().dialect.name
            if dialect == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            elif dialect == "postgresql":
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '5s'"))
                key = int.from_bytes(sha256(VERSION.encode()).digest()[:8], "big", signed=True)
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            else:
                raise RepositoryConflict("HTDY_ACTIVATION_BACKEND_UNSUPPORTED")
            checked_now()
            for product in products:
                identity = htdy_identity(product)
                if session.get(ReferenceStream, identity.stream_id) is not None:
                    raise RepositoryConflict("HTDY_ACTIVATION_ALREADY_EXISTS_READBACK_REQUIRED")
                duplicate = session.scalar(select(ReferenceStream.stream_id).where(
                    func.lower(ReferenceStream.product) == product,
                    ReferenceStream.frequency == "60m",
                    func.replace(func.lower(ReferenceStream.strategy_code), "-", "_").like("htdy%"),
                    ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
                    ReferenceStream.enabled.is_(True)).limit(1))
                if duplicate is not None:
                    raise RepositoryConflict("HTDY_ACTIVATION_DUPLICATE_ROUTE")
            def borrowed():
                return _BorrowedSession(session)
            repository = ReferenceRepository(borrowed)
            accepted = frozenset((
                (ACCEPTANCE_ID, MODEL_VERSION, POLICY, product.upper(), "60m")
                for product in products
            ))
            activation = ForwardActivation(borrowed, accepted_models=accepted)
            routes = []
            manifest = {VERSION: frozen, "scope_plan_hash": expected_plan_hash}
            digest = manifest_sha256(manifest)
            for product in products:
                checked_now()
                identity = htdy_identity(product)
                stored = repository.ensure_stream(identity)
                revision = repository.create_revision(identity.stream_id, stored.row_version, digest)
                checkpoint = AdapterCheckpoint(
                    HtdyForwardState(MODEL_VERSION, POLICY), stream=identity,
                    reference_state=ReferenceState.flat(identity, recording_start=start))
                encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema=SCHEMA)
                repository.stage_seed_chunk(revision, SeedChunk(
                    "seed:" + expected_plan_hash, 0, 1, sha256(encoded.encode()).hexdigest(), encoded))
                repository.seal_seed(revision, manifest, checkpoint, SCHEMA)
                ready = activation.plan(
                    identity.stream_id, revision, host=plan["host"],
                    environment=plan["environment"], recording_start=start,
                    expires_at=expiry, budget=BUDGET, model_acceptance_id=ACCEPTANCE_ID,
                    recovery_policy="block")
                receipt = activation.apply(ready, expected_plan_hash=ready.plan_hash,
                                           now=checked_now())
                routes.append({"product": product, "stream_id": identity.stream_id,
                               "revision_id": revision, "receipt_id": receipt,
                               "activation_plan_hash": ready.plan_hash})
            session.flush()
            checked_now()  # Last check before the outer transaction commits all routes.
            return {"plan_hash": expected_plan_hash, "acceptance_id": ACCEPTANCE_ID,
                    "routes": routes}
    except SQLAlchemyError as error:
        raise RepositoryConflict("HTDY_ACTIVATION_OUTCOME_UNKNOWN_READBACK_REQUIRED") from error
