"""Versioned persistence for the P2 decision prefix, without a Reference stream."""

from datetime import datetime
from hashlib import sha256
import json

from ..reference_trading.adapters import AdapterCheckpoint
from ..reference_trading.strategy_checkpoint import _canonical, _pairs, _restore, _wire
from .decision_adapter import DECISION_VERSION, DecisionState, MarketSource, V2Strategy, _DecisionState
from .product_adapters import ProductReplayState
from .product_contracts import ProductFrequency
from .product_identity import InputQualityPolicy

_SCHEMA = 'newow_v2_decision_checkpoint_v1'


def encode_decision_checkpoint(checkpoint: DecisionState) -> str:
    state = checkpoint.strategy_state
    binding = []
    if state.binding:
        scope, revision, strategies, selected, product, frequency, quality = state.binding
        binding = [scope, revision, list(strategies), selected, product, frequency, quality]
    body = {
        'schema': _SCHEMA, 'version': DECISION_VERSION,
        'through': _wire(checkpoint.computed_through), 'fingerprint': checkpoint.last_fingerprint,
        'contract': checkpoint.physical_contract, 'owner_segment': checkpoint.owner_segment_id,
        'calculation_segment': checkpoint.calculation_segment_id, 'binding': binding,
        'source': list(state.source or ()), 'available': _wire(state.available_through),
        'reference': state.reference, 'trend': _wire(state.trend), 'oscillation': _wire(state.oscillation),
        'fusion_long': state.fusion_long, 'eligible_started': state.eligible_started,
    }
    return _canonical({'payload': body, 'sha256': sha256(_canonical(body).encode()).hexdigest()})


def decode_decision_checkpoint(raw: str) -> DecisionState:
    try:
        envelope = json.loads(raw, object_pairs_hook=_pairs)
        body = envelope['payload']
        if (set(envelope) != {'payload', 'sha256'} or body['schema'] != _SCHEMA
                or body['version'] != DECISION_VERSION
                or envelope['sha256'] != sha256(_canonical(body).encode()).hexdigest()):
            raise ValueError
        binding = ()
        if body['binding']:
            scope, revision, rules, selected, product, frequency, quality = body['binding']
            binding = (scope, revision, tuple(map(V2Strategy, rules)), V2Strategy(selected) if selected else None,
                       product, ProductFrequency(frequency), InputQualityPolicy(quality))
        source = (MarketSource(body['source'][0]), body['source'][1]) if body['source'] else None
        trend, oscillation = _restore(body['trend']), _restore(body['oscillation'])
        through, available = _restore(body['through']), _restore(body['available'])
        if (type(body['fusion_long']) is not bool or type(body['eligible_started']) is not bool
                or not isinstance(trend, ProductReplayState) or not isinstance(oscillation, ProductReplayState)):
            raise ValueError
        if (through is not None and (
            not isinstance(through, datetime) or not isinstance(available, datetime) or available < through
            or not binding or not source or not all(isinstance(body[key], str) and body[key] for key in (
                'fingerprint', 'contract', 'owner_segment', 'calculation_segment', 'reference',
            ))
        )):
            raise ValueError
        checkpoint = AdapterCheckpoint(
            _DecisionState(binding, body['reference'], trend, oscillation,
                           body['fusion_long'], body['eligible_started'], source, available),
            through, body['fingerprint'], body['contract'], body['owner_segment'], body['calculation_segment'],
        )
        if json.loads(encode_decision_checkpoint(checkpoint)) != envelope:
            raise ValueError
        return checkpoint
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ValueError('P5_DECISION_CHECKPOINT_INVALID') from None
