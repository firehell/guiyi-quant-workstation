"""L H1 conflict retirement with an explicit sealed-day interruption, no warm claim."""
from datetime import UTC, datetime
from hashlib import sha256

from app.reference_trading.conflict_recovery import ConflictRevisionRecovery
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.repository import RepositoryConflict, _identity_from_row
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json


class RetiredDayConflictReset(ConflictRevisionRecovery):
    plan_version = "reference_retired_day_conflict_reset_v1"
    boundary_key = "retired_day_conflict_boundary_v1"
    manifest_key = "retired_day_conflict_reset_v1"
    new_health = "OBSERVATION_LAGGING"

    def __init__(self, factory, *, absence_authority, recording_start, assert_fenced):
        self.absence_authority = absence_authority
        self.recording_start = recording_start
        super().__init__(factory, verify_source=self._verify, assert_fenced=assert_fenced)

    @staticmethod
    def _verify(identity, binding, manifest):
        return {"kind": "sealed_day_empty_reset", "binding_sha256": manifest_sha256(binding),
                "manifest_sha256": manifest_sha256(manifest)}

    def _source(self, session, source_id, *, lock):
        self.assert_fenced()
        stream = session.get(ReferenceStream, source_id)
        if (stream is None or stream.product != "l" or stream.frequency != "60m"
                or stream.recording_mode != "forward_observation" or not stream.enabled):
            raise RepositoryConflict("RETIRED_CONFLICT_SCOPE_INVALID")
        identity = _identity_from_row(stream)
        revision = session.get(ReferenceRevision, (source_id, stream.active_revision_id))
        batch = session.get(ReferenceBatch, revision.checkpoint_batch_id) if revision else None
        if (batch is None or not batch.checkpoint_text
                or sha256(batch.checkpoint_text.encode()).hexdigest() != batch.post_state_hash):
            raise RepositoryConflict("RETIRED_CONFLICT_CHECKPOINT_INVALID")
        old = adapter_checkpoint_from_json(batch.checkpoint_text, expected_stream=identity,
                                          expected_strategy_schema=batch.strategy_schema)
        proof, endpoints = self.absence_authority.freeze(identity, old.computed_through)
        code = identity.strategy_code.replace("-", "_")
        if code == "newow_dual_fusion":
            state, schema = FusionReferenceReplayState(), "newow_dual_fusion_reference_v1"
        elif code in {"newow_trend", "newow_oscillation", "newow_main_rise"}:
            state, schema = seed_replay_state(), "newow_product_replay_v1"
        else:
            raise RepositoryConflict("RETIRED_CONFLICT_SCOPE_INVALID")
        binding = {"stream_id": source_id, "kind": "retired_day_empty_reset_v1",
                   "previous_revision_id": revision.revision_id,
                   "previous_checkpoint_id": batch.batch_id, "previous_checkpoint_hash": batch.post_state_hash,
                   "absence_proof_sha256": manifest_sha256(proof)}
        manifest = {"kind": "retired_day_empty_reset_v1", "source_binding": binding,
                    "observation_interruption_v1": {"reason": "OBSERVATION_INTERRUPTED",
                        "interruption_end": endpoints[-1].isoformat(), "proof": proof},
                    "warm_state": "EMPTY_REQUIRES_NATURAL_WARMUP"}
        checkpoint = AdapterCheckpoint(state, endpoints[-1],
            "observation-gap:"+manifest_sha256(proof), None, None, None, identity,
            ReferenceState.flat(identity, recording_start=self.recording_start))
        return identity, checkpoint, schema, manifest, binding

    def _freeze(self, session, source_ids, *, start, expiry, lock=False):
        if (len(source_ids) != 4 or start != self.recording_start
                or start <= datetime.now(UTC)):
            raise RepositoryConflict("RETIRED_CONFLICT_SCOPE_INVALID")
        plan, data = super()._freeze(session, source_ids, start=start, expiry=expiry, lock=lock)
        if {item[0].strategy_code for item in data} != {
                "newow_trend", "newow_oscillation", "newow_main_rise", "newow_dual_fusion"}:
            raise RepositoryConflict("RETIRED_CONFLICT_SCOPE_INVALID")
        return plan, data
