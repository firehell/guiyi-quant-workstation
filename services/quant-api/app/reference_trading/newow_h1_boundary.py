"""Replace the four Newow H1 routes at a new observation boundary."""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.formula_transition import (
    H1_VERSION, RETIREMENTS, NewowFormulaTransition, require,
)
from app.reference_trading.models import ReferenceStream
from app.reference_trading.newow_bootstrap import SCHEMAS, _hash
from app.reference_trading.planning import _canonical_identity
from app.reference_trading.recording_scope import H1_BOUNDARY_POLICY
from app.reference_trading.repository import ReferenceRepository, _aware, _identity_from_row
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json


class NewowH1Boundary(NewowFormulaTransition):
    retired_health = "OBSERVATION_RETIRED"
    version, batch_prefix, reason, codes = RETIREMENTS[retired_health]
    seed_manifest_key = H1_VERSION

    def _plan_members(self, plan):
        return [item["old"]["stream"]["stream_id"] for item in plan["items"]]

    def _freeze(self, db, stream_ids, *, start, expiry, at):
        require(at < expiry <= start, "NEWOW_H1_BOUNDARY_EXPIRED")
        require(len(stream_ids) == len(set(stream_ids)) == 4, "NEWOW_H1_BOUNDARY_SCOPE")
        items = []
        products, codes = set(), set()
        for stream_id in sorted(stream_ids):
            frozen, (_, _, batch, receipt, old, _) = self._old(db, stream_id)
            require(old.frequency == "60m" and old.observation_policy_version != H1_BOUNDARY_POLICY
                    and batch.computed_through is not None and _aware(batch.computed_through) < at,
                    "NEWOW_H1_BOUNDARY_SCOPE")
            require(_canonical_identity(replace(old, recording_mode=RecordingMode.HISTORICAL_REPLAY,
                                                observation_policy_version=None)),
                    "NEWOW_H1_BOUNDARY_FORMULA_IDENTITY")
            products.add(old.product)
            codes.add(old.strategy_code)
            target = replace(old, observation_policy_version=H1_BOUNDARY_POLICY)
            require(db.get(ReferenceStream, target.stream_id) is None, "NEWOW_H1_BOUNDARY_TARGET_EXISTS")
            bootstrap = {
                "old_stream_id": old.stream_id,
                "target_stream_id": target.stream_id,
                "expected_first_bar_end": start.isoformat(),
                "expires_at": expiry.isoformat(),
                "host": receipt.host,
                "environment": receipt.environment,
                "budget": dict(receipt.budget),
            }
            items.append({"old": frozen, "bootstrap": {**bootstrap, "plan_hash": _hash(bootstrap)}})
        require(len(products) == 1 and codes == self.codes, "NEWOW_H1_BOUNDARY_SCOPE")
        enabled = set(db.scalars(select(ReferenceStream.stream_id).where(
            ReferenceStream.enabled.is_(True), ReferenceStream.product.in_(products),
            ReferenceStream.frequency == "60m", ReferenceStream.strategy_code.in_(self.codes),
            ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
        )))
        require(enabled == set(stream_ids), "NEWOW_H1_BOUNDARY_DUPLICATE_ROUTE")
        body = {
            "version": self.version, "items": items,
            "recording_start": start.isoformat(), "expires_at": expiry.isoformat(),
        }
        return {**body, "plan_hash": _hash(body)}

    def _activate_target(self, factory, bootstrap, at):
        start = datetime.fromisoformat(bootstrap["expected_first_bar_end"])
        expiry = datetime.fromisoformat(bootstrap["expires_at"])
        with factory() as session:
            old = _identity_from_row(session.get(ReferenceStream, bootstrap["old_stream_id"]))
        target = replace(old, observation_policy_version=H1_BOUNDARY_POLICY)
        require(target.stream_id == bootstrap["target_stream_id"], "NEWOW_H1_BOUNDARY_TARGET_DRIFT")
        strategy = target.strategy_code.removeprefix("newow_")
        state = FusionReferenceReplayState() if strategy == "dual_fusion" else seed_replay_state()
        checkpoint = AdapterCheckpoint(state, stream=target,
                                       reference_state=ReferenceState.flat(target, recording_start=start))
        schema = SCHEMAS[strategy]
        encoded = adapter_checkpoint_to_json(checkpoint, strategy_schema=schema)
        repository = ReferenceRepository(factory)
        stream = repository.ensure_stream(target)
        manifest = {self.seed_manifest_key: bootstrap}
        revision = repository.create_revision(target.stream_id, stream.row_version, manifest_sha256(manifest))
        repository.stage_seed_chunk(revision, SeedChunk(
            "seed:" + bootstrap["plan_hash"], 0, 1, sha256(encoded.encode()).hexdigest(), encoded,
        ))
        repository.seal_seed(revision, manifest, checkpoint, schema)
        activation = ForwardActivation(factory)
        plan = activation.plan(target.stream_id, revision, host=bootstrap["host"],
                               environment=bootstrap["environment"], recording_start=start,
                               expires_at=expiry, budget=bootstrap["budget"], recovery_policy="block")
        activation.apply(plan, expected_plan_hash=plan.plan_hash, now=at)
        with factory() as session:
            session.get(ReferenceStream, target.stream_id).health = "FORMULA_WARMING"
        return {"target_stream_id": target.stream_id}
