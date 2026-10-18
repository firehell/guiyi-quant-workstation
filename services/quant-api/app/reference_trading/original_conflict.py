"""Typed terminal transfer of sealed original observations, never a capture/reconciliation.

The maintenance caller owns both stopped writers and the immutable journal seal.
All four existing routes retire the explicitly frozen interval together. A matched
original may be transferred at this boundary, but is never labelled a mismatch.
"""
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.newow_bootstrap import _aware, _hash
from app.reference_trading.repository import RepositoryConflict

VERSION = 'original_observation_conflict_v1'
CONFLICT = 'ORIGINAL_OBSERVATION_CANONICAL_CONFLICT'
TERMINAL = 'ORIGINAL_OBSERVATION_TERMINAL_FOR_CONFLICT_BOUNDARY'
PREFIX = 'original-conflict:'
FIELDS = frozenset(('bar_end', 'trading_day', 'open', 'high', 'low', 'close', 'volume', 'turnover', 'open_interest'))


def require(value, code='ORIGINAL_CONFLICT_PROOF_INVALID'):
    if not value:
        raise RepositoryConflict(code)


def numeric_diff(original, canonical):
    require(set(original) == set(canonical) == FIELDS)
    require(all(original[k] == canonical[k] for k in ('bar_end', 'trading_day')))
    result = {}
    for field in sorted(FIELDS - {'bar_end', 'trading_day'}):
        left, right = original[field], canonical[field]
        if left is None or right is None:
            require(left is None and right is None)  # Unknown never proves a conflict.
            continue
        try:
            a, b = Decimal(left), Decimal(right)
            require(a.is_finite() and b.is_finite())
        except (TypeError, ValueError, ArithmeticError) as error:
            raise RepositoryConflict('ORIGINAL_CONFLICT_PROOF_INVALID') from error
        if a != b:
            result[field] = {'original': left, 'canonical': right}
    return result


class CanonicalObservationVerifier:
    """Fresh MDS bytes, quality, physical owner and endpoint; no provider or writes."""
    def __init__(self, market, owner_segments, *, assert_sealed):
        self.market, self.owner_segments, self.assert_sealed = market, owner_segments, assert_sealed

    def __call__(self, observation):
        from app.market_data.domain import BarFrequency
        from app.reference_trading.forward_inputs import _bar_wire
        from app.reference_trading.scheduled_reconciliation import CompletedCanonicalReader

        self.assert_sealed(observation)
        require(isinstance(observation, ObservationEnvelope) and observation.stream_id
                and observation.confirmed_at is not None and observation.notification_eligible)
        pieces = observation.channel.split(':')
        require(len(pieces) == 4 and pieces[:2] == ['live', 'bar'] and pieces[3] == '60m')
        product, frequency = pieces[2:]
        raw = {key: value for key, value in observation.data.items() if key != 'contract'}
        require(set(raw) == FIELDS)
        end = _aware(datetime.fromisoformat(raw['bar_end']))
        require(raw['trading_day'] == observation.trading_day.isoformat() and end <= observation.confirmed_at)
        contract = observation.data['contract']
        identity = SimpleNamespace(product=product, frequency=frequency, strategy_code='newow_trend')
        owner, calculation = self.owner_segments(identity, contract, observation.trading_day, end)
        captured = manifest_sha256(raw)
        source = self.market.contract_source_evidence(symbol=product, contract=contract,
            frequency=BarFrequency.H1, before=end)
        require(source.get('partitions') and all(p.get('content_sha256') and 'quality_sha256' in p for p in source['partitions']))
        class ObservedMarket:
            def __getattr__(_, key):
                return getattr(self.market, key)
            def query_page_inclusive(_, request):
                result = self.market.query_page_inclusive(request)
                _.bar = result.bars[0] if result.bars else None
                return result
        observed = ObservedMarket()
        evidence = CompletedCanonicalReader(observed, self.owner_segments)({
            'source_kind': 'completed_live', 'bar_end': end.isoformat(),
            'input_payload': {'bar': raw, 'product': product, 'contract': contract, 'source_bar_sha256': captured},
            'source_proof': {'source_sha256': captured, 'frequency': frequency,
                'owner_segment_id': owner, 'calculation_segment_id': calculation}})
        require(evidence.source_sha256 is not None and evidence.source_revision == 'canonical:' + manifest_sha256(source))
        canonical = _bar_wire(observed.bar)
        diff = numeric_diff(raw, canonical)
        self.assert_sealed(observation)
        return {'kind': CONFLICT if diff else 'ORIGINAL_OBSERVATION_CANONICAL_MATCH',
            'product': product, 'frequency': frequency, 'contract': contract,
            'owner_segment_id': owner, 'calculation_segment_id': calculation,
            'bar_end': end.isoformat(), 'original_bar': raw, 'canonical_bar': canonical,
            'differences': diff, 'quality_validation': 'MDS_PHYSICAL_READ_PASSED', 'canonical_source': source, 'source_revision': evidence.source_revision,
            'source_manifest_sha256': manifest_sha256(source), 'canonical_bar_sha256': manifest_sha256(canonical)}


def _proof(proof, observation):
    require(isinstance(proof, dict))
    require(proof.get('original_bar') == {k: v for k, v in observation.data.items() if k != 'contract'})
    diff = numeric_diff(proof['original_bar'], proof['canonical_bar'])
    require(proof.get('differences') == diff and proof.get('contract') == observation.data['contract']
            and proof.get('bar_end') == observation.data['bar_end']
            and observation.channel == f"live:bar:{proof.get('product')}:{proof.get('frequency')}"
            and proof.get('owner_segment_id') and proof.get('calculation_segment_id')
            and proof.get('source_manifest_sha256') == manifest_sha256(proof['canonical_source'])
            and proof.get('source_revision') == 'canonical:' + proof['source_manifest_sha256']
            and proof.get('canonical_bar_sha256') == manifest_sha256(proof['canonical_bar'])
            and proof.get('kind') == (CONFLICT if diff else 'ORIGINAL_OBSERVATION_CANONICAL_MATCH'))
    return diff


class OriginalObservationTransfer:
    def __init__(self, factory, *, verify_observation, assert_fenced):
        self.factory, self.verify_observation, self.assert_fenced = factory, verify_observation, assert_fenced

    def _freeze(self, session, routes, observations, *, lock=False):
        require(len(routes) == len(set(routes)) == 4 and 1 <= len(observations) <= 256, 'ORIGINAL_CONFLICT_SCOPE_INVALID')
        query = select(ReferenceStream).where(ReferenceStream.stream_id.in_(routes)).order_by(ReferenceStream.stream_id)
        streams = session.scalars(query.with_for_update() if lock else query).all()
        require(len(streams) == 4 and all(s.enabled and s.active_revision_id and s.recording_mode == 'forward_observation' for s in streams))
        require(len({(s.product, s.frequency) for s in streams}) == 1 and streams[0].frequency == '60m')
        current = set(session.scalars(select(ReferenceStream.stream_id).where(ReferenceStream.enabled.is_(True),
            ReferenceStream.recording_mode == 'forward_observation', ReferenceStream.product == streams[0].product,
            ReferenceStream.frequency == streams[0].frequency)))
        require(current == set(routes), 'ORIGINAL_CONFLICT_SCOPE_INVALID')
        bindings = [{c.name: str(getattr(s, c.name)) for c in s.__table__.columns} for s in streams]
        items = []
        for observation in observations:
            require(isinstance(observation, ObservationEnvelope) and observation.stream_id and observation.confirmed_at is not None
                    and observation.notification_eligible and observation.channel == f'live:bar:{streams[0].product}:60m')
            require(all(_aware(s.recording_start.replace(tzinfo=UTC) if s.recording_start.tzinfo is None else s.recording_start) <= observation.confirmed_at for s in streams), 'ORIGINAL_CONFLICT_ALREADY_FUTURE_BOUNDARY')
            proof = self.verify_observation(observation)
            _proof(proof, observation)
            raw = observation.to_json()
            items.append({'stream_id': observation.stream_id, 'day': observation.trading_day.isoformat(),
                'raw': raw, 'raw_sha256': sha256(raw.encode()).hexdigest(), 'proof': proof})
        require(len({(i['day'], i['stream_id']) for i in items}) == len(items))
        anchors = [i['raw_sha256'] for i in items if i['proof']['differences']]
        require(anchors, 'ORIGINAL_CONFLICT_NUMERIC_MISMATCH_REQUIRED')
        return {'version': VERSION, 'bindings': bindings, 'items': items, 'conflict_anchors': anchors}, streams

    def plan(self, routes, observations):
        self.assert_fenced()
        with self.factory() as session:
            payload, _ = self._freeze(session, routes, observations)
        return {**payload, 'plan_hash': _hash(payload)}

    def apply(self, plan, *, expected_plan_hash, now):
        current = _aware(now)
        payload = {k: v for k, v in plan.items() if k != 'plan_hash'}
        require(expected_plan_hash == plan.get('plan_hash') == _hash(payload), 'PLAN_HASH_CONFLICT')
        require(plan.get('version') == VERSION)
        observations = tuple(ObservationEnvelope.from_json(i['raw'], stream_id=i['stream_id']) for i in plan['items'])
        require(all(o.confirmed_at <= current for o in observations))
        self.assert_fenced()
        try:
            with self.factory() as session, session.begin():
                fresh, streams = self._freeze(session, [b['stream_id'] for b in plan['bindings']], observations, lock=True)
                require(fresh == payload, 'ORIGINAL_CONFLICT_PREIMAGE_DRIFT')
                keys = [PREFIX + _hash([i['day'], i['stream_id']]) for i in plan['items']]
                require(not session.scalar(select(ReferenceBatch.batch_id).where(ReferenceBatch.stream_id.in_([s.stream_id for s in streams]),
                    ReferenceBatch.batch_key.in_(keys)).limit(1)), 'ORIGINAL_CONFLICT_ATTEMPT_ALREADY_EXISTS')
                ids = []
                for item, key in zip(plan['items'], keys):
                    evidence = {VERSION: {'version': VERSION, 'plan_hash': expected_plan_hash,
                        'kind': CONFLICT if item['proof']['differences'] else TERMINAL,
                        'item': item, 'bindings': plan['bindings'], 'conflict_anchors': plan['conflict_anchors'],
                        'interval': [{k: i[k] for k in ('day', 'stream_id', 'raw_sha256')} for i in plan['items']],
                        'natural_capture': False, 'notification_eligible': False}}
                    for stream in streams:
                        batch_id = uuid4().hex
                        session.add(ReferenceBatch(batch_id=batch_id, stream_id=stream.stream_id,
                            revision_id=stream.active_revision_id, batch_key=key, payload_hash=_hash(evidence),
                            kind='diagnostic', outcome='diagnostic', seq=None, expected_seq=stream.latest_seq,
                            dependency_manifest={}, source_evidence=evidence, projected_action_pks=[],
                            diagnostics=[evidence[VERSION]['kind']], observed_at=None, processed_at=current))
                        ids.append(batch_id)
                session.flush()
                self.assert_fenced()
                return ids
        except SQLAlchemyError as error:
            raise RepositoryConflict('ORIGINAL_CONFLICT_COMMIT_OUTCOME_UNKNOWN') from error


def original_conflict_evidence(session, routes, *, rows=None):
    """Only complete typed active-revision groups count; no generic diagnostic inference."""
    rows = rows if rows is not None else session.scalars(select(ReferenceBatch).join(ReferenceStream, (ReferenceStream.stream_id == ReferenceBatch.stream_id)
        & (ReferenceStream.active_revision_id == ReferenceBatch.revision_id)).where(ReferenceBatch.stream_id.in_(routes),
        ReferenceBatch.kind == 'diagnostic', ReferenceBatch.batch_key.like(PREFIX + '%')).order_by(ReferenceBatch.batch_id)).all()
    if not rows:
        return []
    grouped = {}
    for row in rows:
        evidence = row.source_evidence.get(VERSION)
        require(isinstance(evidence, dict) and evidence.get('version') == VERSION
                and evidence.get('kind') in (CONFLICT, TERMINAL) and row.payload_hash == _hash(row.source_evidence))
        grouped.setdefault(row.batch_key, []).append(row)
    result = []
    for key, group in grouped.items():
        first = group[0].source_evidence[VERSION]
        required = {b['stream_id'] for b in first['bindings']}
        require(len(required) == 4 and {r.stream_id for r in group} == required
                and len(group) == 4 and all(r.source_evidence[VERSION] == first for r in group))
        require(first['conflict_anchors'] and first.get('natural_capture') is False and first.get('notification_eligible') is False)
        result.append({'batch_key': key, 'evidence': first, 'receipt_ids': sorted(r.batch_id for r in group)})
    by_plan = {}
    for record in result:
        evidence = record['evidence']
        item = evidence['item']
        observation = ObservationEnvelope.from_json(item['raw'], stream_id=item['stream_id'])
        require(item['raw_sha256'] == sha256(item['raw'].encode()).hexdigest()
                and item['day'] == observation.trading_day.isoformat())
        different = bool(_proof(item['proof'], observation))
        require(evidence['kind'] == (CONFLICT if different else TERMINAL))
        by_plan.setdefault(evidence['plan_hash'], []).append(record)
    for records in by_plan.values():
        first = records[0]['evidence']
        require(all(r['evidence']['interval'] == first['interval']
                    and r['evidence']['bindings'] == first['bindings']
                    and r['evidence']['conflict_anchors'] == first['conflict_anchors'] for r in records))
        actual = sorted((r['evidence']['item']['day'], r['evidence']['item']['stream_id'], r['evidence']['item']['raw_sha256']) for r in records)
        expected = sorted((i['day'], i['stream_id'], i['raw_sha256']) for i in first['interval'])
        require(actual == expected and len(actual) == len(set(actual)), 'ORIGINAL_CONFLICT_PARTIAL_TERMINAL_PROOF')
        require(sorted(r['evidence']['item']['raw_sha256'] for r in records if r['evidence']['kind'] == CONFLICT)
                == sorted(first['conflict_anchors']))
    return sorted(result, key=lambda r: r['batch_key'])


from app.reference_trading.conflict_recovery import ConflictRevisionRecovery  # noqa: E402


class OriginalObservationRevisionRecovery(ConflictRevisionRecovery):
    """Separate typed admission; reuse the existing atomic flat-revision primitive."""
    plan_version = 'reference_original_observation_recovery_v1'
    boundary_key = 'original_conflict_boundary_v1'

    def __init__(self, factory, *, verify_source, assert_fenced, verify_observation, source_loader=None):
        super().__init__(factory, verify_source=verify_source, assert_fenced=assert_fenced)
        self.verify_observation = verify_observation
        self.source_loader = source_loader

    def _source(self, session, source_id, *, lock):
        if self.source_loader is None:
            return super()._source(session, source_id, lock=lock)
        from app.reference_trading.original_conflict_warm_seed import load_verified_warm_source
        return load_verified_warm_source(self.source_loader, session, source_id,
            lock=lock, new_health=self.new_health)

    def _freeze(self, session, source_ids, *, start, expiry, lock=False):
        plan, data = super()._freeze(session, source_ids, start=start, expiry=expiry, lock=lock)
        if self.source_loader is not None:
            for _, checkpoint, _, manifest, *_ in data:
                require(manifest['proof'].get('recording_start') == start.isoformat()
                        and checkpoint.reference_state.recording_start == start,
                        'ORIGINAL_CONFLICT_WARM_SEED_START_MISMATCH')
        return plan, data

    def _conflicts(self, session, targets):
        require(len(targets) == 4, 'ORIGINAL_CONFLICT_SCOPE_INVALID')
        records = original_conflict_evidence(session, targets)
        require(records, 'ORIGINAL_CONFLICT_TERMINAL_PROOF_MISSING')
        for record in records:
            item = record['evidence']['item']
            original = ObservationEnvelope.from_json(item['raw'], stream_id=item['stream_id'])
            require(self.verify_observation(original) == item['proof'], 'ORIGINAL_CONFLICT_CANONICAL_DRIFT')
        return records


PENDING_MANIFEST = 'original_conflict_pending_warmup_v1'


class PendingOriginalObservationRecovery(OriginalObservationRevisionRecovery):
    """An explicit incomplete warm-up boundary, never business READY."""
    plan_version = 'reference_original_observation_pending_warmup_v1'
    boundary_key = 'original_conflict_pending_boundary_v1'
    manifest_key = PENDING_MANIFEST
    new_health = 'PENDING_WARMUP'


class FinalizeOriginalObservationWarmup(OriginalObservationRevisionRecovery):
    """Final warm-up admits only a pristine pending revision, never fake conflicts."""
    plan_version = 'reference_original_observation_finalize_warmup_v1'
    boundary_key = 'original_conflict_warmup_completed_v1'
    manifest_key = 'original_conflict_final_warmup_v1'
    retirement_reason = 'WARMUP_COMPLETED'

    def _source(self, session, source_id, *, lock):
        require(self.source_loader is not None, 'ORIGINAL_CONFLICT_FINAL_WARM_LOADER_REQUIRED')
        return super()._source(session, source_id, lock=lock)

    def _conflicts(self, session, targets):
        from sqlalchemy import or_
        from app.reference_trading.models import (ReferenceRevision, ReferenceActivationReceipt,
            ReferenceActionRow, ReferenceTradeRow, ReferenceMarkRow)

        require(len(targets) == 4, 'ORIGINAL_CONFLICT_SCOPE_INVALID')
        result = []
        for target in sorted(targets):
            stream = session.get(ReferenceStream, target)
            require(stream is not None and stream.health == 'PENDING_WARMUP', 'PENDING_WARMUP_REQUIRED')
            revision = session.get(ReferenceRevision, (target, stream.active_revision_id))
            require(revision is not None and revision.status == 'active', 'PENDING_WARMUP_REQUIRED')
            batches = session.scalars(select(ReferenceBatch).where(ReferenceBatch.stream_id == target,
                ReferenceBatch.revision_id == revision.revision_id)).all()
            seals = [b for b in batches if b.kind == 'seed_seal']
            require(len(seals) == 1 and all(b.kind in ('seed_chunk', 'seed_seal') for b in batches)
                    and seals[0].batch_id == revision.checkpoint_batch_id
                    and seals[0].seq == stream.latest_seq == revision.last_seq, 'PENDING_WARMUP_HAS_OBSERVATIONS')
            seal = seals[0]
            boundary = seal.dependency_manifest.get(PENDING_MANIFEST)
            require(isinstance(boundary, dict) and boundary.get('plan_hash') == stream.activation_plan_hash
                    and boundary.get('recording_start') == _aware(stream.recording_start.replace(tzinfo=UTC)
                        if stream.recording_start.tzinfo is None else stream.recording_start).isoformat(), 'PENDING_WARMUP_LINEAGE_INVALID')
            receipt = session.scalar(select(ReferenceActivationReceipt).where(ReferenceActivationReceipt.stream_id == target,
                ReferenceActivationReceipt.revision_id == revision.revision_id, ReferenceActivationReceipt.generation == stream.activation_generation,
                ReferenceActivationReceipt.disabled_at.is_(None)))
            require(receipt is not None and receipt.plan_hash == boundary['plan_hash'], 'PENDING_WARMUP_LINEAGE_INVALID')
            action = session.scalar(select(ReferenceActionRow.action_pk).where(ReferenceActionRow.stream_id == target,
                or_(ReferenceActionRow.origin_revision_id == revision.revision_id, ReferenceActionRow.batch_revision_id == revision.revision_id)).limit(1))
            require(action is None, 'PENDING_WARMUP_HAS_OBSERVATIONS')
            for model in (ReferenceTradeRow, ReferenceMarkRow):
                require(session.scalar(select(model.stream_id).where(model.stream_id == target,
                    model.revision_id == revision.revision_id).limit(1)) is None, 'PENDING_WARMUP_HAS_OBSERVATIONS')
            result.append({'stream_id': target, 'pending_revision_id': revision.revision_id,
                'seed_hash': seal.post_state_hash, 'pending_boundary': boundary,
                'receipt_hash': _hash({c.name: str(getattr(receipt, c.name)) for c in receipt.__table__.columns}),
                'batch_hashes': sorted([b.batch_id, b.payload_hash] for b in batches)})
        return result
