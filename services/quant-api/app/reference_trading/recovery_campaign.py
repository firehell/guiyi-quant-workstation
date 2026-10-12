"""One-shot recovery campaign; progress is durable before every mutation."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path

from app.reference_trading.bounded_recovery import BoundedRecoveryPlan
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.journal_recovery import replay_expired_originals
from app.reference_trading.repository import RepositoryConflict


class RecoveryCampaignError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=lambda item:item.isoformat(), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def decode_plan(value):
    value = dict(value)
    capture = dict(value.pop('capture'))
    for key in ('bar_end', 'observed_at'):
        capture[key] = datetime.fromisoformat(capture[key])
    value['expires_at'] = datetime.fromisoformat(value['expires_at'])
    return BoundedRecoveryPlan(capture=ForwardCapture(**capture), **value)


def write_once(path: Path, value):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise RecoveryCampaignError('RECOVERY_OUTPUT_UNSAFE')
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(canonical(value)+'\n')
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class AttemptProgress:
    def __init__(self, path, *, plan_hash):
        self.path = Path(path)
        if self.path.is_symlink() or self.path.parent.resolve() != self.path.parent:
            raise RecoveryCampaignError('RECOVERY_ATTEMPT_UNSAFE')
        self.path.mkdir(mode=0o700)  # existing attempt is never reused
        parent_fd = os.open(self.path.parent, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        self.fd = os.open(self.path/'progress.jsonl', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        self.record('started', plan_hash=plan_hash)
        directory_fd = os.open(self.path, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def record(self, stage, **fields):
        data = (canonical({'stage':stage, **fields})+'\n').encode()
        while data:
            count = os.write(self.fd, data)
            data = data[count:]
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


def freeze_campaign(repository, recovery, journal_authority, *, products, day,
                    observed_at, expires_at, identity):
    journal = journal_authority.journal
    cursor, tail = journal.cursor('reference', day), journal.tail(day)
    groups = []
    codes = {'newow_trend','newow_oscillation','newow_main_rise','newow_dual_fusion'}
    for product in sorted(products):
        routes = repository.enabled_forward_routes(product, '60m')
        contexts = [repository.forward_source_context(route) for route in routes]
        if len(routes) != 4 or any(context is None for context in contexts) or {
                context[0].strategy_code for context in contexts} != codes:
            raise RecoveryCampaignError('RECOVERY_SCOPE_INVALID')
        plans, group_proof = [], None
        for route, context in zip(routes, contexts, strict=True):
            stream, _revision, _generation, _start, watermark, _policy, *_rest = context
            proof, missing = journal_authority.freeze(stream, watermark, day=day,
                                                      expected_cursor=cursor, tail_id=tail)
            if group_proof is not None and proof != group_proof:
                raise RecoveryCampaignError('RECOVERY_GROUP_WATERMARK_CONFLICT')
            group_proof = proof
            for original in journal_authority.replay_envelopes(proof):
                raw = original.raw_received_at or original.source_observed_at
                if (observed_at - raw).total_seconds() <= 30:
                    raise RecoveryCampaignError('RECOVERY_REPLAY_NOT_EXPIRED')
            plan = recovery.plan(route, endpoints=missing, trading_day=day,
                                 observed_at=observed_at, expires_at=expires_at,
                                 journal_proof=proof)
            plans.append(asdict(plan))
        groups.append({'product':product,'routes':list(routes),'proof':group_proof,'plans':plans})
    frozen = {'schema_version':1,'identity':identity,'day':day.isoformat(),
              'reference_cursor':cursor,'tail_id':tail,'groups':groups}
    # Normalize the datetime objects once; the frozen file is its sole preimage.
    frozen = json.loads(canonical(frozen))
    frozen['plan_hash'] = digest(frozen)
    return frozen


def validate_campaign(frozen, *, expected_hash):
    content = {key:value for key,value in frozen.items() if key != 'plan_hash'}
    if frozen.get('schema_version') != 1 or frozen.get('plan_hash') != expected_hash or digest(content) != expected_hash:
        raise RecoveryCampaignError('RECOVERY_CAMPAIGN_HASH_CONFLICT')
    groups = frozen.get('groups', [])
    if not groups or len({group['product'] for group in groups}) != len(groups):
        raise RecoveryCampaignError('RECOVERY_SCOPE_INVALID')
    return [decode_plan(value) for group in groups for value in group['plans']]


def apply_campaign(frozen, *, recovery, worker, wake, progress, now, assert_guard):
    plans = validate_campaign(frozen, expected_hash=frozen['plan_hash'])
    # Validate every unmodified preimage/source before the first write.
    for plan in plans:
        assert_guard()
        fresh = recovery.plan(plan.capture.stream_id,
            endpoints=tuple(datetime.fromisoformat(end) for end in plan.capture.source_proof['gap_endpoints']),
            trading_day=date.fromisoformat(plan.capture.input_payload['trading_day']),
            observed_at=plan.capture.observed_at, expires_at=plan.expires_at,
            journal_proof=plan.journal_proof)
        if fresh != plan:
            raise RecoveryCampaignError('RECOVERY_PREIMAGE_DRIFT')
    try:
        for plan in plans:
            assert_guard()
            progress.record('activation_started', stream_id=plan.capture.stream_id, plan_hash=plan.plan_hash)
            result = recovery.apply(plan, expected_plan_hash=plan.plan_hash, now=now())
            if recovery.readback(plan) != result:
                raise RepositoryConflict('RECOVERY_READBACK_CONFLICT')
            progress.record('activation_committed', stream_id=plan.capture.stream_id,
                            receipt_id=result[0], capture_id=result[1])
        # Every route's explicit gap is committed before any surviving Bar.
        for plan in plans:
            assert_guard()
            progress.record('gap_started', stream_id=plan.capture.stream_id)
            worker._service_for(plan.capture.stream_id).process_pending(plan.capture.stream_id)
            if (worker._repository.read_pending_capture(plan.capture.stream_id) is not None
                    or recovery.consumed_calculation(plan) is None):
                raise RecoveryCampaignError('RECOVERY_GAP_PENDING')
            progress.record('gap_committed', stream_id=plan.capture.stream_id,
                            calculation=recovery.consumed_calculation(plan))
        for group in frozen['groups']:
            assert_guard()
            progress.record('replay_started', product=group['product'], replay_sha256=group['proof']['replay_sha256'])
            replay_expired_originals(worker, tuple(group['routes']), group['proof'], now=now())
            progress.record('replay_committed', product=group['product'])
        # The regular consumer performs CAS ack; no cursor SET/rewind/skip exists here.
        for _ in range(1000):
            assert_guard()
            more = wake.poll()
            if not more and not wake._last_poll_count:
                break
        else:
            raise RecoveryCampaignError('RECOVERY_ACK_BUDGET_EXCEEDED')
        if wake._stream.cursor('reference', date.fromisoformat(frozen['day'])) != frozen['tail_id']:
            raise RecoveryCampaignError('RECOVERY_ACK_BLOCKED')
        progress.record('finished', cursor=frozen['tail_id'])
    except Exception:
        # Fixed terminal marker, no sensitive error text. Existing attempt cannot
        # be reused; exact readback is a separate read-only command.
        progress.record('stopped_no_retry')
        raise
