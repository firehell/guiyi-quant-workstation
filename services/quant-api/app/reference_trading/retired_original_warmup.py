"""One-shot finalization of pristine Oct-22 L empty seeds with real originals."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select

from app.reference_trading.conflict_recovery import ConflictRevisionRecovery
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.forward_authority import ForwardMarketAuthority
from app.reference_trading.forward_inputs import capture_newow_envelope
from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.newow_forward import _whole_number
from app.reference_trading.repository import RepositoryConflict, _identity_from_row
from app.reference_trading.retained_observation_authority import read_retained_interval
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity, replay_step, seed_replay_state
from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.reference_trading import ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint, strategy_input_fingerprint
from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json


def require(value, code="RETIRED_ORIGINAL_WARMUP_INVALID"):
    if not value:
        raise RepositoryConflict(code)


class FinalizeRetiredDayOriginalWarmup(ConflictRevisionRecovery):
    plan_version = "reference_retired_original_warmup_v1"
    boundary_key = "retired_original_warmup_boundary_v1"
    manifest_key = "retired_original_warmup_v1"
    retirement_reason = "PREACTIVATION_WARMUP_FINALIZED"
    new_health = "OBSERVATION_LAGGING"

    def __init__(self, factory, *, journal, market, recording_start, knowledge_at,
                 assert_fenced, capability_ready):
        require(knowledge_at.tzinfo is not None and recording_start.tzinfo is not None
                and datetime(2026, 10, 22, 15, tzinfo=UTC) <= knowledge_at <= datetime.now(UTC) < recording_start
                and recording_start <= datetime(2026, 10, 22, 16, tzinfo=UTC))
        self.journal, self.market = journal, market
        self.start, self.known = recording_start, knowledge_at
        self.authority = ForwardMarketAuthority(market)
        self.capability_ready = capability_ready
        super().__init__(factory, verify_source=lambda identity, binding, manifest: {
            "kind": self.plan_version, "binding_sha256": manifest_sha256(binding),
            "manifest_sha256": manifest_sha256(manifest)}, assert_fenced=assert_fenced)

    def _pristine(self, session, source_id):
        stream = session.get(ReferenceStream, source_id)
        require(stream is not None and stream.enabled and stream.product == "l"
                and stream.frequency == "60m" and stream.recording_mode == "forward_observation"
                and stream.health == "OBSERVATION_LAGGING")
        revision = session.get(ReferenceRevision, (source_id, stream.active_revision_id))
        batch = session.get(ReferenceBatch, revision.checkpoint_batch_id) if revision else None
        require(revision is not None and revision.status == "active" and revision.last_seq == 1
                and stream.latest_seq == 1 and batch is not None and batch.kind == "seed_seal"
                and batch.seq == 1 and batch.checkpoint_text
                and sha256(batch.checkpoint_text.encode()).hexdigest() == batch.post_state_hash
                and manifest_sha256(batch.dependency_manifest) == revision.dependency_digest)
        identity = _identity_from_row(stream)
        cp = adapter_checkpoint_from_json(batch.checkpoint_text, expected_stream=identity,
                                         expected_strategy_schema=batch.strategy_schema)
        empty = FusionReferenceReplayState() if identity.strategy_code == "newow_dual_fusion" else seed_replay_state()
        require(batch.dependency_manifest.get("kind") == "retired_day_empty_reset_v1"
                and batch.dependency_manifest.get("warm_state") == "EMPTY_REQUIRES_NATURAL_WARMUP"
                and cp.computed_through == datetime(2026, 10, 22, 7, tzinfo=UTC)
                and cp.strategy_state == empty and cp.physical_contract is None
                and cp.reference_state == ReferenceState.flat(identity, recording_start=datetime(2026, 10, 22, 14, 55, tzinfo=UTC)))
        interruption = batch.dependency_manifest.get("observation_interruption_v1", {})
        require(interruption.get("reason") == "OBSERVATION_INTERRUPTED"
                and interruption.get("interruption_end") == cp.computed_through.isoformat()
                and interruption.get("proof", {}).get("kind") == "RETIRED_DAY_ABSENCE_V1"
                and cp.last_fingerprint == "observation-gap:" + manifest_sha256(interruption["proof"]))
        kinds = list(session.scalars(select(ReferenceBatch.kind).where(
            ReferenceBatch.stream_id == source_id, ReferenceBatch.revision_id == revision.revision_id)))
        require(sorted(kinds) == ["seed_chunk", "seed_seal"], "RETIRED_ORIGINAL_WARMUP_NOT_PRISTINE")
        return identity, cp, batch.strategy_schema, batch.dependency_manifest, {
            "stream_id": source_id, "revision_id": revision.revision_id,
            "checkpoint_id": batch.batch_id, "checkpoint_hash": batch.post_state_hash,
            "dependency_digest": revision.dependency_digest}

    def _conflicts(self, session, targets):
        # Dedicated admission evidence, never fabricated reconciliation mismatch.
        return [self._pristine(session, sid)[4] for sid in sorted(targets)]

    def _warm(self, identity, cp, binding):
        day = date(2026, 10, 23)
        metadata = self.market.historical_metadata_evidence(symbol="l", since=date(2026, 10, 22), through=day)
        contract = self.market.dominant_segment_for_day("l", day).contract
        ends = self.authority.expected_endpoints(identity, contract, day, cp.computed_through,
                                                self.start - timedelta(microseconds=1))
        require(ends == (datetime(2026, 10, 22, 14, tzinfo=UTC),
                         datetime(2026, 10, 22, 15, tzinfo=UTC)), "RETIRED_ORIGINAL_WARMUP_FRONTIER_INVALID")
        originals = read_retained_interval(self.journal, product="l", day=day,
            after=cp.computed_through, before=self.start, expected_endpoints=ends, knowledge_at=self.known)
        records, previous, owner, state = [], cp.computed_through, None, seed_replay_state()
        product_identity = None
        for original, proof in originals:
            capture = capture_newow_envelope(original, identity, revision_id=binding["revision_id"],
                generation=1, after=previous, now=original.confirmed_at,
                owner_segments=self.authority.owner_segments,
                expected_endpoints=self.authority.expected_endpoints, capability_ready=self.capability_ready)
            require(capture is not None)
            payload, source = capture.input_payload, capture.source_proof
            current_owner = (payload["contract"], source["owner_segment_id"], source["calculation_segment_id"])
            require(owner is None or current_owner == owner, "RETIRED_ORIGINAL_WARMUP_OWNER_CHANGED")
            owner = current_owner
            raw = payload["bar"]
            bar = ProductBar(NewowDailyBar("l", owner[0], owner[1], day, capture.bar_end,
                Decimal(raw["open"]), Decimal(raw["high"]), Decimal(raw["low"]), Decimal(raw["close"]),
                _whole_number(raw["volume"]), None if raw["open_interest"] is None else _whole_number(raw["open_interest"]),
                payload["source_identity"], True, True), "60m", calculation_segment_id=owner[2],
                source_bar_sha256=payload["source_bar_sha256"])
            if product_identity is None:
                product_identity = build_product_identity("l", identity.strategy_code.removeprefix("newow_"),
                    "60m", input_quality_policy=payload["input_quality_policy"])
                require(product_identity.formula_versions == identity.formula_versions
                        and product_identity.profile_id == identity.profile_id)
            state, frame, _ = replay_step(product_identity, state, bar)
            require(frame is not None)
            fingerprint = strategy_input_fingerprint({"source_bar_sha256": payload["source_bar_sha256"],
                "bar": raw, "physical_contract": owner[0], "owner_segment_id": owner[1],
                "calculation_segment_id": owner[2], "input_quality_policy": product_identity.input_quality_policy,
                "source_identity": payload["source_identity"]})
            records.append({"original": proof, "bar_end": capture.bar_end.isoformat(),
                            "source_sha256": payload["source_bar_sha256"], "owner": list(owner)})
            previous = capture.bar_end
        checkpoint = AdapterCheckpoint(state, previous, fingerprint, *owner, identity,
                                      ReferenceState.flat(identity, recording_start=self.start))
        self.assert_fenced()
        require(self.market.dominant_segment_for_day("l", day).contract == contract
                and self.authority.expected_endpoints(identity, contract, day, cp.computed_through,
                    self.start - timedelta(microseconds=1)) == ends
                and read_retained_interval(self.journal, product="l", day=day,
                    after=cp.computed_through, before=self.start, expected_endpoints=ends,
                    knowledge_at=self.known) == originals
                and self.market.historical_metadata_evidence(symbol="l", since=date(2026, 10, 22), through=day) == metadata,
                "RETIRED_ORIGINAL_WARMUP_SOURCE_DRIFT")
        return checkpoint, records, metadata

    def _source(self, session, source_id, *, lock):
        self.assert_fenced()
        identity, cp, schema, old_manifest, binding = self._pristine(session, source_id)
        if identity.strategy_code == "newow_dual_fusion":
            ids = list(session.scalars(select(ReferenceStream.stream_id).where(
                ReferenceStream.enabled.is_(True), ReferenceStream.product == "l", ReferenceStream.frequency == "60m",
                ReferenceStream.recording_mode == "forward_observation",
                ReferenceStream.strategy_code.in_(("newow_trend", "newow_oscillation", "newow_main_rise")))))
            require(len(ids) == 3)
            bases = [self._source(session, sid, lock=lock) for sid in sorted(ids)]
            require(len({manifest_sha256(base[3]["originals"]) for base in bases}) == 1)
            require(len({manifest_sha256(base[3]["metadata"]) for base in bases}) == 1)
            checkpoint = replace(bases[0][1], strategy_state=FusionReferenceReplayState(), stream=identity,
                                reference_state=ReferenceState.flat(identity, recording_start=self.start))
            records = bases[0][3]["originals"]
            metadata = bases[0][3]["metadata"]
        else:
            require(identity.strategy_code in ("newow_trend", "newow_oscillation", "newow_main_rise"))
            checkpoint, records, metadata = self._warm(identity, cp, binding)
        manifest = {"kind": self.plan_version, "pristine_empty_source": binding,
                    "prior_manifest_sha256": manifest_sha256(old_manifest), "originals": records,
                    "metadata": metadata,
                    "knowledge_at": self.known.isoformat(), "recording_start": self.start.isoformat(),
                    "reference_reset": "FLAT", "natural_capture": False, "first_seen": False}
        self.assert_fenced()
        require(self.market.historical_metadata_evidence(symbol="l", since=date(2026, 10, 22), through=date(2026, 10, 23)) == metadata,
                "RETIRED_ORIGINAL_WARMUP_SOURCE_DRIFT")
        return identity, checkpoint, schema, manifest, binding

    def _freeze(self, session, source_ids, *, start, expiry, lock=False):
        require(len(source_ids) == 4 and start == self.start and datetime.now(UTC) < start)
        plan, data = super()._freeze(session, source_ids, start=start, expiry=expiry, lock=lock)
        require({item[0].strategy_code for item in data} == {
            "newow_trend", "newow_oscillation", "newow_main_rise", "newow_dual_fusion"})
        return plan, data
