"""Read-only observation proof; never an account command or trading authority."""

from datetime import timedelta

from ..htdy_account_execution.codec import digest
from .inventory import at

VERSION = 'simnow_observe_reconciliation_v1'
FIELDS = {'schema', 'run_id', 'account_id', 'products', 'native_source_id',
          'ledger_hash', 'native_at', 'checked_at', 'valid_until', 'verified'}


def build_proof(state, native, reconciled, run_id, now):
    """Called only after native evidence is durable and a.apply has succeeded."""
    rb = reconciled.readback
    if not (reconciled.readback_valid and reconciled.phase == 'READY'
            and not reconciled.unresolved_fill_ids and rb.complete
            and state.account_id == native.account_id == reconciled.account_id
            and rb.source_id == native.source_id and rb.snapshot.at == native.at):
        return None
    until = min(rb.valid_until, native.at + timedelta(seconds=30))
    if not native.at <= now < until:
        return None
    proof = dict(schema=VERSION, run_id=run_id, account_id=state.account_id,
                 products=sorted(p.product for p in state.products),
                 native_source_id=native.source_id, ledger_hash=digest(state),
                 native_at=native.at.isoformat(), checked_at=now.isoformat(),
                 valid_until=until.isoformat(), verified=True)
    return {**proof, 'proof_sha256': digest(proof)}


def verify_proof(proof, index, state, native, now):
    """Bad bindings fail closed. Expiry is a stale observation, not fresh proof."""
    if proof is None:
        return None
    if not isinstance(proof, dict) or set(proof) != FIELDS | {'proof_sha256'}:
        raise ValueError('OBSERVE_RECONCILIATION_PROOF_INVALID')
    body = {k: v for k, v in proof.items() if k != 'proof_sha256'}
    valid = (proof['schema'] == VERSION and proof['verified'] is True
             and proof['proof_sha256'] == digest(body)
             and index.get('mode') == 'observe'
             and proof['run_id'] == index['run_id']
             and proof['account_id'] == index['account_id'] == state.account_id == native.account_id
             and proof['products'] == sorted(p.product for p in state.products)
             and proof['native_source_id'] == index['native_source_id'] == native.source_id
             and proof['ledger_hash'] == index['ledger_hash'] == digest(state)
             and proof['native_at'] == native.at.isoformat())
    if not valid:
        raise ValueError('OBSERVE_RECONCILIATION_PROOF_INVALID')
    checked, until = at(proof['checked_at']), at(proof['valid_until'])
    if not native.at <= checked < until <= native.at + timedelta(seconds=30) or not checked <= at(index['published_at']) <= now:
        raise ValueError('OBSERVE_RECONCILIATION_PROOF_INVALID')
    return dict(checked_at=checked.isoformat(), valid_until=until.isoformat(), fresh=now < until)
