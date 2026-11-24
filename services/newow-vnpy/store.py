"""Isolated PostgreSQL journal for the offline Newow trading host."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
import re
from threading import RLock

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

SOURCE = 'offline_fixture'
SCHEMA = 'newow_p5'
KINDS = frozenset({'decisions', 'orders', 'fills'})


def wire(value):
    if is_dataclass(value):
        return wire(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('P5_NONFINITE_DECIMAL')
        if value.is_zero():
            return '0'
        fixed = format(value, 'f')
        return fixed.rstrip('0').rstrip('.') if '.' in fixed else fixed
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value


def digest(value) -> str:
    payload = json.dumps(wire(value), sort_keys=True, separators=(',', ':'), allow_nan=False)
    return sha256(payload.encode()).hexdigest()


def isolated_connection(dsn: str):
    if any(key.startswith('PG') for key in os.environ):
        raise ValueError('P5_AMBIENT_PG_SETTINGS_FORBIDDEN')
    try:
        facts = conninfo_to_dict(dsn)
        valid = (
            set(facts) == {'host', 'port', 'dbname', 'user'}
            and facts['host'] == '127.0.0.1'
            and facts['dbname'] == 'guiyi_p5_test'
            and facts['user'] == 'postgres'
            and 1024 <= int(facts['port']) <= 65535
            and int(facts['port']) != 5432
        )
    except (ValueError, psycopg.Error):
        valid = False
    if not valid:
        raise ValueError('P5_ISOLATED_DATABASE_REQUIRED')
    try:
        # Explicitly override libpq environment, service and password-file fallbacks.
        return psycopg.connect(
            '', host='127.0.0.1', hostaddr='127.0.0.1', port=facts['port'],
            user='postgres', dbname='guiyi_p5_test',
            passfile='/dev/null', sslmode='disable', gssencmode='disable',
            options='', application_name='guiyi-v2-p5-offline', connect_timeout=3, autocommit=True,
        )
    except psycopg.Error:
        raise RuntimeError('P5_DATABASE_UNAVAILABLE') from None


def account_key(alias: str) -> str:
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', alias):
        raise ValueError('P5_ACCOUNT_ALIAS_INVALID')
    return f'{SOURCE}:{alias}'


class Journal:
    def __init__(self, connection, account: str):
        self.connection = connection
        self.account = account

    def record(self, kind: str, key: str, payload: dict) -> int:
        payload = wire(payload)
        row = self.connection.execute(
            'INSERT INTO newow_p5.record (account, kind, key, payload) VALUES (%s, %s, %s, %s) '
            'ON CONFLICT (account, kind, key) DO NOTHING RETURNING sequence',
            (self.account, kind, key, Jsonb(payload)),
        ).fetchone()
        if row:
            return row[0]
        sequence, previous = self.connection.execute(
            'SELECT sequence, payload FROM newow_p5.record WHERE account = %s AND kind = %s AND key = %s',
            (self.account, kind, key),
        ).fetchone()
        if previous != payload:
            raise ValueError('P5_RECORD_CONFLICT')
        return sequence

    def input_result(self, key: str):
        return self.get('inputs', key)

    def get(self, kind: str, key: str):
        row = self.connection.execute(
            'SELECT payload FROM newow_p5.record WHERE account = %s AND kind = %s AND key = %s',
            (self.account, kind, key),
        ).fetchone()
        return row[0] if row else None


class TradingStore:
    def __init__(self, dsn: str, alias: str):
        self.account = account_key(alias)
        self.dsn = dsn
        self._mutex = RLock()
        self._connection = None

    def __enter__(self):
        connection = isolated_connection(self.dsn)
        try:
            if not connection.execute(
                'SELECT pg_try_advisory_lock(hashtextextended(%s, 0))', (self.account,),
            ).fetchone()[0]:
                raise RuntimeError('P5_WRITER_BUSY')
            with connection.transaction():
                # Different isolated fixture aliases may bootstrap the same test schema.
                connection.execute('SELECT pg_advisory_xact_lock(2026112405)')
                connection.execute('CREATE SCHEMA IF NOT EXISTS newow_p5')
                connection.execute('''CREATE TABLE IF NOT EXISTS newow_p5.account_state (
                    account text PRIMARY KEY, sequence bigint NOT NULL,
                    payload jsonb NOT NULL
                )''')
                connection.execute('''CREATE TABLE IF NOT EXISTS newow_p5.record (
                    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    account text NOT NULL REFERENCES newow_p5.account_state(account),
                    kind text NOT NULL, key text NOT NULL, payload jsonb NOT NULL,
                    UNIQUE (account, kind, key)
                )''')
                connection.execute('CREATE INDEX IF NOT EXISTS p5_record_list '
                                   'ON newow_p5.record (account, kind, sequence)')
                connection.execute(
                    'INSERT INTO newow_p5.account_state VALUES (%s, 0, %s) ON CONFLICT DO NOTHING',
                    (self.account, Jsonb({})),
                )
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        return self

    def __exit__(self, *_):
        with self._mutex:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @contextmanager
    def dispatch_fence(self):
        """Serialize a single fixture dispatch with native and config state changes."""
        with self._mutex:
            yield

    @contextmanager
    def transaction(self) -> Iterator[tuple[dict, Journal]]:
        with self._mutex:
            connection = self._connection
            if connection is None or connection.closed:
                raise RuntimeError('P5_WRITER_UNAVAILABLE')
            try:
                with connection.transaction():
                    sequence, state = connection.execute(
                        'SELECT sequence, payload FROM newow_p5.account_state WHERE account = %s FOR UPDATE',
                        (self.account,),
                    ).fetchone()
                    before = digest(state)
                    yield state, Journal(connection, self.account)
                    if digest(state) != before:
                        connection.execute(
                            'UPDATE newow_p5.account_state SET sequence = %s, payload = %s WHERE account = %s',
                            (sequence + 1, Jsonb(wire(state)), self.account),
                        )
            except psycopg.Error:
                # A COMMIT error is ambiguous. Keep this instance fenced until restart/readback.
                connection.close()
                raise RuntimeError('P5_DATABASE_OUTCOME_UNKNOWN') from None

    def projection(self, resource: str, *, limit: int = 100, after: int = 0, through: int | None = None):
        return read_projection(self.dsn, self.account.partition(':')[2], resource,
                               limit=limit, after=after, through=through)


def read_projection(dsn: str, alias: str, resource: str, *, limit: int = 100,
                    after: int = 0, through: int | None = None) -> dict:
    account = account_key(alias)
    if (resource not in KINDS | {'status', 'account', 'positions'}
            or not 1 <= limit <= 200 or after < 0 or through is not None and through < after):
        raise ValueError('P5_QUERY_INVALID')
    result = {'source': SOURCE, 'account_alias': alias, 'revision': None,
              'snapshot_seq': 0, 'as_of': None, 'status': 'NOT_AVAILABLE',
              'auto_order': False, 'data': None}
    try:
        with isolated_connection(dsn) as connection, connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row = connection.execute(
                'SELECT sequence, payload FROM newow_p5.account_state WHERE account = %s', (account,),
            ).fetchone()
            if not row or not row[1]:
                return result
            sequence, state = row
            native = state.get('native') or {}
            status = state.get('status', 'RECONCILING')
            until = state.get('verified_until')
            if status == 'READY' and until and datetime.fromisoformat(until) < datetime.now().astimezone():
                status = 'STALE'
            result.update(snapshot_seq=sequence, revision=state['revision'], status=status,
                          as_of=native.get('as_of'))
            if resource == 'status':
                result['data'] = {'reason': state.get('reason'), 'owners': state['owners']}
            if resource in ('account', 'positions'):
                result['data'] = native.get(resource)
            if resource in KINDS:
                current = connection.execute(
                    'SELECT COALESCE(max(sequence), 0) FROM newow_p5.record WHERE account = %s AND kind = %s',
                    (account, resource),
                ).fetchone()[0]
                if through is not None and through > current:
                    raise ValueError('P5_QUERY_INVALID')
                ceiling = current if through is None else through
                rows = connection.execute(
                    'SELECT sequence, payload FROM newow_p5.record '
                    'WHERE account = %s AND kind = %s AND sequence > %s AND sequence <= %s '
                    'ORDER BY sequence LIMIT %s', (account, resource, after, ceiling, limit + 1),
                ).fetchall()
                result.update(data=[dict(payload, sequence=seq) for seq, payload in rows[:limit]],
                              through=ceiling, next_after=rows[limit - 1][0] if len(rows) > limit else None)
    except psycopg.errors.UndefinedTable:
        return result
    except psycopg.Error:
        raise RuntimeError('P5_DATABASE_UNAVAILABLE') from None
    return result
