"""Task recovery for missing transient projections; journals remain immutable.

No Canonical input, provider download, consumer acknowledgment or day promotion is
performed here. The caller supplies read-only formal rank1 and Session authority,
parks all affected writers and consumers, and reviews the resulting exact plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
import json
import re
from typing import Any, Callable

from app.market_data.aggregation import SessionWindow, aggregate_from_1m, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from app.market_data.live_market import RedisLiveStore, _bar_from_payload, _bar_payload, _compact_json, _epoch_millis
from app.market_data.market_feed import _equivalent_bar_payload
from app.market_data.observation_stream import DAILY_LIMIT, TTL_SECONDS, ObservationEnvelope, ObservationStream

RESTORE = r"""-- observation-projection-restore-v1
local plan=cjson.decode(ARGV[1])
if tonumber(ARGV[2])~=259200 or #ARGV~=#KEYS+2 then return -4 end
for pattern,expected in pairs(plan.namespaces) do
 local known={}; local expected_count=0
 for _,key in ipairs(expected) do known[key]=true; expected_count=expected_count+1 end
 local seen={}; local count=0; local cursor='0'
 repeat
  local page=redis.call('SCAN',cursor,'MATCH',pattern,'COUNT',1000); cursor=page[1]
  for _,key in ipairs(page[2]) do
   if not known[key] then return -1 end
   if not seen[key] then seen[key]=true; count=count+1 end
  end
 until cursor=='0'
 if count~=expected_count then return -1 end
end
local hashes={}
for _,i in ipairs(plan.hash_keys) do hashes[i]=true end
for i,key in ipairs(KEYS) do
 if hashes[i] then
  if redis.call('TYPE',key).ok~='hash' then return -1 end
  local expected=cjson.decode(ARGV[i+2]); local count=0
  for field,value in pairs(expected) do
   count=count+1
   if redis.call('HGET',key,field)~=value then return -1 end
  end
  if redis.call('HLEN',key)~=count then return -1 end
 elseif (redis.call('DUMP',key) or '')~=ARGV[i+2] then return -1 end
end
-- Every destination was proven absent or an exact frozen zset during planning.
for _,item in ipairs(plan.bars) do
 local kind=redis.call('TYPE',KEYS[item.key_index]).ok
 if kind~='none' and kind~='zset' then return -4 end
 if #redis.call('ZRANGEBYSCORE',KEYS[item.key_index],item.score,item.score)~=0 then return -1 end
end
if plan.snapshot then
 if redis.call('TYPE',KEYS[plan.snapshot.key_index]).ok~='none' then return -1 end
end
if plan.snapshot then
 redis.call('SET',KEYS[plan.snapshot.key_index],plan.snapshot.payload,'EX',ARGV[2])
end
for _,item in ipairs(plan.bars) do
 redis.call('ZADD',KEYS[item.key_index],item.score,item.payload)
 redis.call('EXPIRE',KEYS[item.key_index],ARGV[2])
end
return 1
"""


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def _preimage(redis, key):
    # Redis hash DUMP byte ordering changes during internal rehash even without mutation.
    if _text(redis.type(key)) == 'hash':
        values = {_text(k): _text(v) for k, v in redis.hgetall(key).items()}
        return json.dumps(values, sort_keys=True, separators=(',', ':')).encode()
    return redis.dump(key) or b''


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


@dataclass(frozen=True)
class ProjectionRestorePlan:
    trading_day: date
    keys: tuple[str, ...]
    preimages: tuple[bytes, ...]
    changes_json: str
    source_tail: str
    source_cursor: str
    source_count: int
    completed_count: int

    @property
    def sha256(self):
        identity = _hash({'day': str(self.trading_day), 'keys': self.keys, 'source_tail': self.source_tail,
                          'source_cursor': self.source_cursor, 'source_count': self.source_count,
                          'completed_count': self.completed_count})
        witness = identity.encode() + self.changes_json.encode() + b''.join(sha256(raw).digest() for raw in self.preimages)
        return sha256(witness).hexdigest()


def _read_rows(redis, stream, day):
    rows = redis.xrange(stream.key(day))
    if not rows or len(rows) > DAILY_LIMIT:
        raise ValueError('RESTORE_JOURNAL_BOUNDS_INVALID')
    result = []
    for identifier, fields in rows:
        fields = {_text(k): _text(v) for k, v in fields.items()}
        if set(fields) != {'envelope'}:
            raise ValueError('RESTORE_JOURNAL_SCHEMA_INVALID')
        raw = fields['envelope']
        event = ObservationEnvelope.from_json(raw, stream_id=_text(identifier))
        if event.trading_day != day or not event.notification_eligible:
            raise ValueError('RESTORE_JOURNAL_IDENTITY_INVALID')
        record = redis.hget(stream.identity_key(day), event.observation_id)
        if record is None:
            raise ValueError('RESTORE_JOURNAL_IDENTITY_MISSING')
        record = json.loads(record)
        if record['id'] != event.stream_id or record['payload'] != raw:
            raise ValueError('RESTORE_JOURNAL_IDENTITY_CONFLICT')
        if stream.kind == 'source':
            fingerprint = json.loads(event.to_json())
            fingerprint.pop('source_observed_at')
            fingerprint.pop('raw_received_at')
            if record.get('content') != json.dumps(fingerprint, sort_keys=True, separators=(',', ':'), allow_nan=False):
                raise ValueError('RESTORE_SOURCE_FINGERPRINT_CONFLICT')
        result.append((event, raw))
    return result


def build_projection_restore_plan(
    redis: Any, *, day: date, products: tuple[str, ...], formal_rank1: dict[str, str],
    natural_live_evidence: dict, session_for_bar: Callable[[str, CanonicalBar], SessionWindow],
) -> ProjectionRestorePlan:
    """Read-only proof of exact source facts and missing completed projections."""
    if not products or len(products) != len(set(products)) or set(formal_rank1) != set(products):
        raise ValueError('RESTORE_SCOPE_INVALID')
    for symbol, contract in formal_rank1.items():
        if normalize_contract_for_symbol(symbol, contract) != contract:
            raise ValueError('RESTORE_RANK1_INVALID')
    evidence = natural_live_evidence
    if (evidence.get('trading_day') != day.isoformat() or evidence.get('rank1_matches_snapshot') is not True
            or evidence.get('scope_sha256') != _hash(list(products))
            or evidence.get('snapshot_sha256') != _hash(formal_rank1)
            or evidence.get('formal_rank1_sha256') != _hash(formal_rank1)
            or evidence.get('cleanup_verified') is not True):
        raise ValueError('RESTORE_NATURAL_EVIDENCE_CONFLICT')
    source = ObservationStream(redis, kind='source')
    completed = ObservationStream(redis, kind='completed')
    if source.registered_day('live') != day:
        raise ValueError('RESTORE_REGISTERED_DAY_CONFLICT')
    cursor = source.cursor('live', day)
    journal_keys = (source.key(day), source.identity_key(day), completed.key(day), completed.identity_key(day),
                    source.cursor_key('live', day), source.registration_key('live'))
    journal_preimages = tuple(_preimage(redis, key) for key in journal_keys)
    source_rows = _read_rows(redis, source, day)
    completed_rows = _read_rows(redis, completed, day)
    latest = {}
    for event, _ in source_rows:
        data = dict(event.data)
        if data.pop('subscription_snapshot', None) != formal_rank1:
            raise ValueError('RESTORE_SOURCE_SNAPSHOT_CONFLICT')
        channel = event.channel.split(':')
        if len(channel) != 4 or channel[:2] != ['live', 'bar'] or channel[2] not in formal_rank1 or channel[3] != '1m':
            raise ValueError('RESTORE_SOURCE_CHANNEL_INVALID')
        symbol = channel[2]
        bar = _bar_from_payload(_compact_json(data))
        if (not _equivalent_bar_payload(data, _bar_payload(bar, contract=formal_rank1[symbol]))
                or bar.trading_day != day
                or re.fullmatch(r'[0-9a-f]{64}', event.observation_id) is None):
            raise ValueError('RESTORE_SOURCE_FACT_CONFLICT')
        session = session_for_bar(symbol, bar)
        if not session.start < bar.bar_end <= session.end or bar.bar_end.second or bar.bar_end.microsecond:
            raise ValueError('RESTORE_SESSION_CONFLICT')
        latest[(symbol, bar.bar_end)] = (bar, event, session)
    if {symbol for symbol, _ in latest} != set(products):
        raise ValueError('RESTORE_SOURCE_SCOPE_INCOMPLETE')
    store = RedisLiveStore(redis)
    projected = {}
    for event, _ in completed_rows:
        channel = event.channel.split(':')
        if len(channel) != 4 or channel[:2] != ['live', 'bar'] or channel[2] not in formal_rank1:
            raise ValueError('RESTORE_COMPLETED_CHANNEL_INVALID')
        symbol, frequency = channel[2], BarFrequency(channel[3])
        if frequency not in (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1):
            raise ValueError('RESTORE_COMPLETED_FREQUENCY_INVALID')
        bar = _bar_from_payload(_compact_json(event.data))
        identity = f'{day}:{formal_rank1[symbol]}:{frequency.value}:{bar.bar_end.isoformat()}'
        endpoint = latest.get((symbol, bar.bar_end))
        if (event.observation_id != identity or bar.trading_day != day or endpoint is None
                or event.source_observed_at != endpoint[1].source_observed_at
                or event.raw_received_at != event.source_observed_at or event.confirmed_at is None
                or event.confirmed_at < event.source_observed_at
                or event.confirmed_at < bar.bar_end + timedelta(seconds=2)):
            raise ValueError('RESTORE_COMPLETED_TIME_IDENTITY_CONFLICT')
        expected = endpoint[0]
        if frequency != BarFrequency.M1:
            bucket = bucket_window_for_bar(endpoint[2], frequency, bar.bar_end)
            if bucket.end != bar.bar_end:
                raise ValueError('RESTORE_DERIVED_ENDPOINT_INVALID')
            ends = tuple(bucket.start + timedelta(minutes=i) for i in range(
                1, int((bucket.end-bucket.start).total_seconds()//60)+1))
            try:
                bars = tuple(latest[(symbol, end)][0] for end in ends)
            except KeyError:
                raise ValueError('RESTORE_DERIVED_SOURCE_INCOMPLETE') from None
            expected = aggregate_from_1m(bars, target_frequency=frequency, sessions=(bucket,))[0]
        if not _equivalent_bar_payload(event.data, _bar_payload(expected, contract=formal_rank1[symbol])):
            raise ValueError('RESTORE_COMPLETED_FACT_CONFLICT')
        key = store._bars_key(day, symbol, frequency)
        score = _epoch_millis(bar.bar_end)
        if (key, score) in projected:
            raise ValueError('RESTORE_COMPLETED_DUPLICATE')
        projected[(key, score)] = _compact_json(event.data)
    # Never preserve an acknowledged source prefix whose completion fact is missing.
    completed_identities = {event.observation_id for event, _ in completed_rows}
    frontier = tuple(map(int, cursor.split('-')))
    for event, _ in source_rows:
        if tuple(map(int, event.stream_id.split('-'))) <= frontier:
            data = event.data
            identity = f"{day}:{data['contract']}:1m:{data['bar_end']}"
            if identity not in completed_identities:
                raise ValueError('RESTORE_ACKNOWLEDGED_PREFIX_UNPROVEN')
    # Freeze entire journals, identity hashes, consumer registrations/cursors, recovery attempts/watermarks.
    keys = {source.key(day), source.identity_key(day), completed.key(day), completed.identity_key(day)}
    namespaces = {}
    for pattern in (f'live:observations:cursor:*:{day}', 'live:observations:registered:*',
                    f'live:recovery:{day}:*', f'live:recovery:circuit:{day}', f'live:bars:{day}:*'):
        namespaces[pattern] = sorted(_text(key) for key in redis.scan_iter(match=pattern))
        keys.update(namespaces[pattern])
    projected_keys = {key for key, _ in projected}
    if {_text(key) for key in redis.scan_iter(match=f'live:bars:{day}:*')} - projected_keys:
        raise ValueError('RESTORE_EXISTING_PROJECTION_UNKNOWN')
    snapshot_key = store._subscription_key(day)
    keys.add(snapshot_key)
    keys.update(key for key, _ in projected)
    frozen_keys = tuple(sorted(keys))
    preimages = tuple(_preimage(redis, key) for key in frozen_keys)
    additions = []
    for key in {key for key, _ in projected}:
        for payload, score in redis.zrange(key, 0, -1, withscores=True):
            expected = projected.get((key, int(score)))
            if score != int(score) or expected is None or not _equivalent_bar_payload(json.loads(payload), json.loads(expected)):
                raise ValueError('RESTORE_EXISTING_PROJECTION_CONFLICT')
    for (key, score), payload in projected.items():
        existing = redis.zrangebyscore(key, score, score)
        if len(existing) > 1:
            raise ValueError('RESTORE_EXISTING_PROJECTION_CONFLICT')
        if not existing:
            additions.append({'key_index': frozen_keys.index(key)+1, 'score': score, 'payload': payload})
    snapshot = redis.get(snapshot_key)
    if snapshot is not None and json.loads(snapshot) != formal_rank1:
        raise ValueError('RESTORE_EXISTING_SNAPSHOT_CONFLICT')
    changes = {'namespaces': namespaces, 'hash_keys': [i+1 for i, key in enumerate(frozen_keys) if _text(redis.type(key)) == 'hash'],
               'bars': additions, 'snapshot': None if snapshot is not None else {
        'key_index': frozen_keys.index(snapshot_key)+1, 'payload': _compact_json(formal_rank1)}}
    # No source/identity/consumer fact may change while this read-only proof is assembled.
    if (tuple(_preimage(redis, key) for key in frozen_keys) != preimages
            or tuple(_preimage(redis, key) for key in journal_keys) != journal_preimages
            or any(sorted(_text(key) for key in redis.scan_iter(match=pattern)) != values
                   for pattern, values in namespaces.items())):
        raise ValueError('RESTORE_READBACK_DRIFT')
    return ProjectionRestorePlan(day, frozen_keys, preimages, _compact_json(changes),
        source_rows[-1][0].stream_id, cursor, len(source_rows), len(completed_rows))


def restore_missing_projections(redis, plan: ProjectionRestorePlan, *, expected_sha256: str,
                                assert_owned: Callable[[], None]):
    """Atomic exact-preimage apply. No retry on drift; build a new read-only proof."""
    if expected_sha256 != plan.sha256:
        raise ValueError('RESTORE_PLAN_HASH_CONFLICT')
    assert_owned()
    result = redis.eval(RESTORE, len(plan.keys), *plan.keys, plan.changes_json, TTL_SECONDS, *plan.preimages)
    if result != 1:
        raise ValueError('RESTORE_PREIMAGE_DRIFT' if result == -1 else 'RESTORE_COMMIT_UNKNOWN')
