"""Select one committed page generation; never construct an asset on GET."""
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.fingerprint_proof import fingerprint_count
from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.page_material_storage import validate_page_material
from app.reference_trading.query import QueryConflict, _encode, POLICY_VERSION
from guiyi_quant.newow.page_performance import PAGE_PERFORMANCE_VERSION, PAGE_SOURCE_SHA256


@dataclass(frozen=True, slots=True)
class PageMaterialSnapshot:
    stream_id: str
    revision_id: str
    seq: int
    cutoff: datetime
    through: date
    field: dict

    def token(self, manifest, *, since: date, through: date, cutoff: datetime) -> str:
        return _encode({
            'kind': 'snapshot', 'stream': self.stream_id,
            'revision': self.revision_id, 'seq': self.seq,
            'since': since.isoformat(), 'through': through.isoformat(),
            'cutoff': cutoff.isoformat(), 'policy': POLICY_VERSION,
            'dependency': manifest_sha256(manifest),
        })

    def envelope(self, manifest, identity):
        """Rebuild all externally anchored fields before validating the body."""
        binding = self.field.get('binding')
        if not isinstance(binding, dict):
            raise QueryConflict('PRESENTATION_CORRUPT')
        request = binding.get('request')
        if (not isinstance(request, dict)
                or request.get('product') != identity.product.lower()
                or request.get('frequency') != identity.frequency
                or request.get('since') != manifest.get('query_since')
                or not isinstance(request.get('through'), str)
                or not isinstance(request.get('as_of'), str)):
            raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
        try:
            scope_end = date.fromisoformat(request['through'])
            scope_asof = datetime.fromisoformat(request['as_of'])
            if scope_end < self.through or scope_asof.tzinfo is None or scope_asof < self.cutoff:
                raise ValueError('invalid projection source window')
        except (TypeError, ValueError) as error:
            raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED') from error
        if not isinstance(request.get('since'), str):
            raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
        input_sha = binding.get('input_sha256')
        integrity = binding.get('source_integrity')
        if (not isinstance(input_sha, str) or len(input_sha) != 64
                or any(char not in '0123456789abcdef' for char in input_sha)
                or not isinstance(integrity, dict) or integrity.get('request') != request):
            raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
        expected = {
            'input_sha256': input_sha, 'source_integrity': integrity,
            'schema': 'reference_page_material_binding_v1',
            'stream_id': self.stream_id, 'revision_id': self.revision_id, 'seq': self.seq,
            'manifest_sha256': manifest_sha256(manifest),
            'source_token': manifest_sha256(manifest),
            'end_input_index': fingerprint_count(manifest.get('input_fingerprints')),
            'input_count': fingerprint_count(manifest.get('input_fingerprints')),
            'request': {'product': identity.product.lower(), 'frequency': identity.frequency,
                        'since': manifest['query_since'], 'through': request['through'],
                        'as_of': request['as_of']},
            'cutoff': self.cutoff.isoformat(), 'result_trading_day': self.through.isoformat(),
            'page_version': PAGE_PERFORMANCE_VERSION,
            'page_source_sha256': PAGE_SOURCE_SHA256,
            'fusion_source_dependencies': manifest.get('source_dependencies'),
        }
        if set(binding) != set(expected):
            raise QueryConflict('PRESENTATION_CORRUPT')
        try:
            return validate_page_material(self.field, expected_binding=expected)
        except (TypeError, ValueError, KeyError) as error:
            raise QueryConflict('PRESENTATION_CORRUPT') from error


def select_page_material(factory, stream_id: str, *, cutoff: datetime,
                         generation: tuple[str, int] | None = None):
    """Choose the last complete material, excluding partially advanced batches."""
    with factory() as session, readonly_transaction(session, timeout_seconds=30):
        stream = session.get(ReferenceStream, stream_id)
        if stream is None or stream.recording_mode != 'historical_replay':
            raise QueryConflict('NOT_BUILT')
        revision_id = stream.active_revision_id if generation is None else generation[0]
        revision = session.get(ReferenceRevision, (stream_id, revision_id))
        if revision is None or revision.status not in ('active', 'superseded'):
            raise QueryConflict('STALE_INVALID')
        stmt = select(ReferenceBatch).options(defer(ReferenceBatch.dependency_manifest)).where(
            ReferenceBatch.stream_id == stream_id, ReferenceBatch.revision_id == revision_id,
            ReferenceBatch.kind == 'calculation', ReferenceBatch.outcome == 'committed',
            ReferenceBatch.seq <= stream.latest_seq if generation is None else ReferenceBatch.seq == generation[1],
            ReferenceBatch.computed_through <= cutoff,
            ReferenceBatch.source_evidence['page_material_v1'].as_string().is_not(None),
        ).order_by(ReferenceBatch.seq.desc()).limit(1)
        batch = session.scalar(stmt)
        if batch is None:
            return None
        field = batch.source_evidence.get('page_material_v1')
        try:
            binding = field['binding']
            end = datetime.fromisoformat(binding['cutoff'])
            day = date.fromisoformat(binding['result_trading_day'])
            actual = batch.computed_through
            if actual is not None and actual.tzinfo is None:
                actual = actual.replace(tzinfo=UTC)
            if (end.tzinfo is None or end > cutoff or end != actual
                    or binding['stream_id'] != stream_id
                    or binding['revision_id'] != revision_id or binding['seq'] != batch.seq):
                raise ValueError('invalid material generation')
        except (TypeError, ValueError, KeyError) as error:
            raise QueryConflict('PRESENTATION_CORRUPT') from error
        return PageMaterialSnapshot(stream_id, revision_id, batch.seq, end, day, field)


def material_interruptions(envelope, identity, cutoff):
    """Decode the quality facts frozen with the selected page generation."""
    from guiyi_quant.newow.product_contracts import DataInterruption, ProductFrequency
    try:
        coverage = envelope['coverage']
        if not isinstance(coverage, dict) or set(coverage) != {'data_interruptions'}:
            raise ValueError('invalid material coverage')
        rows = coverage['data_interruptions']
        if not isinstance(rows, list) or len(rows) > 200_000:
            raise ValueError('invalid material coverage')
        gaps = []
        for item in rows:
            if not isinstance(item, dict) or set(item) != {
                'product', 'frequency', 'physical_contract', 'segment_id',
                'trading_day', 'effective_at', 'source_identity',
            }:
                raise ValueError('invalid material coverage')
            gap = DataInterruption(item['product'], ProductFrequency(item['frequency']),
                item['physical_contract'], item['segment_id'], date.fromisoformat(item['trading_day']),
                datetime.fromisoformat(item['effective_at']), item['source_identity'])
            if gap.product != identity.product.lower() or gap.frequency.value != identity.frequency:
                raise ValueError('invalid material coverage')
            if gap.effective_at <= cutoff:
                gaps.append(gap)
        return tuple(gaps)
    except (TypeError, ValueError, KeyError) as error:
        raise QueryConflict('PRESENTATION_CORRUPT') from error


def latest_input_integrity(session, batch):
    """Use the latest CAS-ordered verification for this exact calculation seq."""
    code = 'CANONICAL_INPUTS_REVERIFIED'
    diagnostic = session.scalar(select(ReferenceBatch).options(defer(ReferenceBatch.dependency_manifest)).where(
        ReferenceBatch.stream_id == batch.stream_id,
        ReferenceBatch.revision_id == batch.revision_id,
        ReferenceBatch.kind == 'diagnostic', ReferenceBatch.outcome == 'diagnostic',
        ReferenceBatch.seq.is_(None), ReferenceBatch.expected_seq == batch.seq,
        ReferenceBatch.diagnostics[0].as_string() == code,
    ).order_by(
        ReferenceBatch.source_evidence['source_verification_row_version'].as_integer().desc(),
    ).limit(1))
    if diagnostic is None:
        evidence = batch.source_evidence
        return evidence.get('input_integrity_v1') if isinstance(evidence, dict) else None
    from app.reference_trading.repository import _digest
    evidence = diagnostic.source_evidence
    stream = session.get(ReferenceStream, batch.stream_id)
    if (not isinstance(evidence, dict)
            or set(evidence) != {'input_integrity_v1', 'source_verification_row_version'}
            or type(evidence.get('source_verification_row_version')) is not int
            or stream is None
            or not 0 < evidence['source_verification_row_version'] <= stream.row_version
            or diagnostic.diagnostics != [code]
            or diagnostic.payload_hash != _digest({'evidence': evidence, 'code': code})):
        raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
    return evidence['input_integrity_v1']
