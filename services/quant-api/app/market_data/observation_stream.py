"""Bounded transient observation journal; never a historical market authority."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

TTL_SECONDS = 259200
DAILY_LIMIT = 120000
_ID = re.compile(r'^[0-9]+-[0-9]+$')
_NAME = re.compile(r'^[a-zA-Z0-9_.:-]{1,128}$')

APPEND = r"""-- observation-append-v1
for i,k in ipairs(KEYS) do
 local t=redis.call('TYPE',k).ok
 local expected=i==1 and 'stream' or 'hash'
 if t~='none' and t~=expected then return {-4} end
end
local old=redis.call('HGET',KEYS[2],ARGV[1])
if old then
 local item=cjson.decode(old)
 if (item.content or item.payload)~=ARGV[5] then return {-1} end
 return {0,item.id}
end
if redis.call('XLEN',KEYS[1])>=tonumber(ARGV[4]) then return {-2} end
local id=redis.call('XADD',KEYS[1],'*','envelope',ARGV[2])
redis.call('HSET',KEYS[2],ARGV[1],cjson.encode({id=id,payload=ARGV[2],content=ARGV[5]}))
redis.call('EXPIRE',KEYS[1],ARGV[3]); redis.call('EXPIRE',KEYS[2],ARGV[3])
return {1,id}
"""
INITIALIZE = r"""-- observation-initialize-v1
for i,k in ipairs(KEYS) do
 local t=redis.call('TYPE',k).ok
 local expected=i==2 and 'stream' or 'string'
 if t~='none' and t~=expected then return -4 end
end
if redis.call('EXISTS',KEYS[1])~=0 or redis.call('EXISTS',KEYS[3])~=0 then return -1 end
if ARGV[1]~='0-0' and #redis.call('XRANGE',KEYS[2],ARGV[1],ARGV[1])~=1 then return -2 end
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2])
redis.call('SET',KEYS[3],ARGV[3]); return 1
"""
NEW_DAY = r"""-- observation-new-day-v1
for i,k in ipairs(KEYS) do
 local t=redis.call('TYPE',k).ok
 local expected=(i==3 or i==5) and 'stream' or 'string'
 if t~='none' and t~=expected then return -4 end
end
if redis.call('TYPE',KEYS[1]).ok~='string' or redis.call('GET',KEYS[1])~=ARGV[1] then return -1 end
if redis.call('GET',KEYS[2])~=ARGV[2] then return -2 end
local last=redis.call('XREVRANGE',KEYS[3],'+','-','COUNT',1)
local tail=#last==0 and '0-0' or last[1][1]
if tail~=ARGV[2] then return -2 end
if redis.call('EXISTS',KEYS[4])~=0 or redis.call('XLEN',KEYS[5])~=0 then return -3 end
redis.call('SET',KEYS[4],'0-0','EX',ARGV[3])
redis.call('SET',KEYS[1],ARGV[4]); return 1
"""
ACK = r"""-- observation-ack-v1
if redis.call('GET',KEYS[1])~=ARGV[1] then return -1 end
if #redis.call('XRANGE',KEYS[2],ARGV[2],ARGV[2])~=1 then return -2 end
redis.call('SET',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1
"""


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    observation_id: str
    trading_day: date
    source_observed_at: datetime
    channel: str
    data: dict[str, Any]
    notification_eligible: bool
    stream_id: str = ''
    raw_received_at: datetime | None = None
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.source_observed_at.tzinfo is None or self.source_observed_at.utcoffset() is None:
            raise ValueError('OBSERVATION_TIME_INVALID')
        for timestamp in (self.raw_received_at, self.confirmed_at):
            if timestamp is not None and (timestamp.tzinfo is None or timestamp.utcoffset() is None):
                raise ValueError('OBSERVATION_TIME_INVALID')
        if not self.observation_id or not _NAME.fullmatch(self.channel) or type(self.data) is not dict:
            raise ValueError('OBSERVATION_ENVELOPE_INVALID')
        if type(self.notification_eligible) is not bool:
            raise ValueError('OBSERVATION_ENVELOPE_INVALID')

    def to_json(self) -> str:
        return json.dumps({'observation_id': self.observation_id, 'trading_day': self.trading_day.isoformat(),
                           'source_observed_at': self.source_observed_at.isoformat(), 'channel': self.channel,
                           'data': self.data, 'notification_eligible': self.notification_eligible,
                           'raw_received_at': self.raw_received_at.isoformat() if self.raw_received_at else None,
                           'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None},
                          sort_keys=True, separators=(',', ':'), allow_nan=False)

    @classmethod
    def from_json(cls, raw: str | bytes, *, stream_id: str = '') -> ObservationEnvelope:
        item = json.loads(raw)
        return cls(item['observation_id'], date.fromisoformat(item['trading_day']),
                   datetime.fromisoformat(item['source_observed_at']), item['channel'], item['data'],
                   item['notification_eligible'], stream_id,
                   datetime.fromisoformat(item['raw_received_at']) if item.get('raw_received_at') else None,
                   datetime.fromisoformat(item['confirmed_at']) if item.get('confirmed_at') else None)


class ObservationStream:
    def __init__(self, redis: Any, *, kind: Literal['source', 'completed']) -> None:
        if kind not in ('source', 'completed'):
            raise ValueError('OBSERVATION_KIND_INVALID')
        self.redis = redis
        self.kind = kind

    def key(self, day: date) -> str:
        return f'live:observations:{self.kind}:{day.isoformat()}'

    def identity_key(self, day: date) -> str:
        return self.key(day) + ':identities'

    def cursor_key(self, consumer: str, day: date) -> str:
        if not _NAME.fullmatch(consumer):
            raise ValueError('OBSERVATION_CONSUMER_INVALID')
        return f'live:observations:cursor:{self.kind}:{consumer}:{day.isoformat()}'

    def days(self) -> tuple[date, ...]:
        """Journal partitions only; this is not a market fact resolver."""
        prefix = f'live:observations:{self.kind}:'
        days = set()
        for raw in self.redis.scan_iter(match=prefix + '*'):
            suffix = _text(raw)[len(prefix):]
            try:
                day = date.fromisoformat(suffix)
            except ValueError:
                continue
            if suffix == day.isoformat():
                days.add(day)
        # Registered empty/new partitions and expired partitions remain visible;
        # consumers must prove their cursor, rather than silently skipping gaps.
        for raw in self.redis.scan_iter(match=f'live:observations:registered:{self.kind}:*'):
            value = self.redis.get(_text(raw))
            if value is None:
                raise ValueError('OBSERVATION_REGISTRATION_MISSING')
            days.add(date.fromisoformat(_text(value)))
        return tuple(sorted(days))

    def tail(self, day: date) -> str:
        rows = self.redis.xrevrange(self.key(day), count=1)
        return _text(rows[0][0]) if rows else '0-0'

    def initialize(self, consumer: str, day: date, *, cursor: str) -> None:
        """Explicit migration baseline only; callers must freeze the supplied cutoff."""
        if not _ID.fullmatch(cursor):
            raise ValueError('OBSERVATION_CURSOR_INVALID')
        result = self.redis.eval(INITIALIZE, 3, self.cursor_key(consumer, day), self.key(day),
                                 self.registration_key(consumer), cursor, TTL_SECONDS, day.isoformat())
        if result != 1:
            raise ValueError({-1: 'OBSERVATION_CURSOR_ALREADY_EXISTS', -2: 'OBSERVATION_CURSOR_EXPIRED',
                              -4: 'OBSERVATION_KEY_TYPE_INVALID'}.get(result, 'OBSERVATION_COMMIT_UNKNOWN'))

    def registration_key(self, consumer: str) -> str:
        self.cursor_key(consumer, date.min)  # validate identity
        return f'live:observations:registered:{self.kind}:{consumer}'

    def registered_day(self, consumer: str) -> date:
        value = self.redis.get(self.registration_key(consumer))
        if value is None:
            raise ValueError('OBSERVATION_CONSUMER_UNREGISTERED')
        return date.fromisoformat(_text(value))

    def initialize_new_day(self, consumer: str, day: date) -> None:
        previous = self.registered_day(consumer)
        if previous >= day:
            raise ValueError('OBSERVATION_DAY_REGRESSION')
        old = self.cursor(consumer, previous)
        result = self.redis.eval(NEW_DAY, 5, self.registration_key(consumer),
            self.cursor_key(consumer, previous), self.key(previous), self.cursor_key(consumer, day),
            self.key(day), previous.isoformat(), old, TTL_SECONDS, day.isoformat())
        if result != 1:
            raise ValueError('OBSERVATION_DAY_BASELINE_UNPROVEN')

    def prepare_registered_day(self, day: date) -> None:
        prefix = f'live:observations:registered:{self.kind}:'
        for raw in self.redis.scan_iter(match=prefix + '*'):
            consumer = _text(raw)[len(prefix):]
            registered = _text(self.redis.get(_text(raw)))
            if registered == day.isoformat():
                self.cursor(consumer, day)  # missing cursor cannot recreate itself
            else:
                self.initialize_new_day(consumer, day)

    def cursor(self, consumer: str, day: date) -> str:
        value = self.redis.get(self.cursor_key(consumer, day))
        if value is None:
            raise ValueError('OBSERVATION_CURSOR_MISSING')
        cursor = _text(value)
        if not _ID.fullmatch(cursor):
            raise ValueError('OBSERVATION_CURSOR_INVALID')
        if cursor != '0-0' and not self.redis.xrange(self.key(day), min=cursor, max=cursor, count=1):
            raise ValueError('OBSERVATION_CURSOR_EXPIRED')
        return cursor

    def read(self, consumer: str, day: date, *, count: int = 128, after: str | None = None, through: str = '+') -> tuple[ObservationEnvelope, ...]:
        persisted = self.cursor(consumer, day)
        if not 1 <= count <= 1024 or (after is not None and not _ID.fullmatch(after)):
            raise ValueError('OBSERVATION_READ_INVALID')
        if through != '+' and not _ID.fullmatch(through):
            raise ValueError('OBSERVATION_READ_INVALID')
        rows = self.redis.xrange(self.key(day), min='(' + (after or persisted), max=through, count=count)
        result = []
        for identifier, fields in rows:
            raw = fields.get('envelope', fields.get(b'envelope'))
            event = ObservationEnvelope.from_json(raw, stream_id=_text(identifier))
            if event.trading_day != day:
                raise ValueError('OBSERVATION_DAY_CONFLICT')
            result.append(event)
        return tuple(result)

    def append(self, event: ObservationEnvelope) -> str:
        content = json.loads(event.to_json())
        if self.kind == 'source':
            content.pop('source_observed_at')
            content.pop('raw_received_at')
        fingerprint = json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False)
        result = self.redis.eval(APPEND, 2, self.key(event.trading_day), self.identity_key(event.trading_day),
                                 event.observation_id, event.to_json(), TTL_SECONDS, DAILY_LIMIT, fingerprint)
        code = int(result[0])
        if code < 0:
            raise ValueError({-1: 'OBSERVATION_CONTENT_CONFLICT', -2: 'OBSERVATION_CAPACITY_EXCEEDED',
                              -4: 'OBSERVATION_KEY_TYPE_INVALID'}[code])
        return _text(result[1])

    def ack(self, consumer: str, day: date, *, expected_cursor: str, next_id: str) -> None:
        if not _ID.fullmatch(expected_cursor) or not _ID.fullmatch(next_id):
            raise ValueError('OBSERVATION_CURSOR_INVALID')
        if tuple(map(int, next_id.split('-'))) <= tuple(map(int, expected_cursor.split('-'))):
            raise ValueError('OBSERVATION_CURSOR_REGRESSION')
        result = self.redis.eval(ACK, 2, self.cursor_key(consumer, day), self.key(day),
                                 expected_cursor, next_id, TTL_SECONDS)
        if result != 1:
            raise ValueError('OBSERVATION_CURSOR_DRIFT' if result == -1 else 'OBSERVATION_CURSOR_EXPIRED')
