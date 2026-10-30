"""Explicit immutable HTDY 60m display snapshots; readers never replay or write."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from app.core.env import PROJECT_ROOT
from app.market_data.market_home_projection import _open_projection_parent

MAX_BYTES = 32 * 1024 * 1024
MAX_TRADES = 10000
MAX_SIGNALS = 40000
_ID = re.compile(r'[0-9a-f]{64}\Z')
_SYMBOL = re.compile(r'[a-z]{1,4}\Z')
MODEL = 'htdy_historical_window32_reverse_close_v1'


class SnapshotError(ValueError):
    def __init__(self, code='HTDY_SNAPSHOT_CORRUPT'):
        self.code = code
        super().__init__(code)


def snapshot_root():
    return Path(os.environ.get('GUIYI_HTDY_SNAPSHOT_ROOT', str(PROJECT_ROOT / '.run/htdy-snapshots')))


def _encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(payload):
    return sha256(_encode({key: value for key, value in payload.items()
                           if key not in {'generated_at', 'snapshot_id'}})).hexdigest()


def _scope(symbol, identifier=None):
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) or (identifier is not None and
            (not isinstance(identifier, str) or not _ID.fullmatch(identifier))):
        raise SnapshotError('HTDY_SNAPSHOT_INVALID_QUERY')


def _decimal(value, *, positive=False):
    if not isinstance(value, str):
        raise SnapshotError()
    try:
        result = Decimal(value)
    except Exception:
        raise SnapshotError() from None
    if not result.is_finite() or positive and result <= 0:
        raise SnapshotError()
    return result


def _instant(value):
    if not isinstance(value, str):
        raise SnapshotError()
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise SnapshotError()
    return result


def _stream_identity(payload):
    from guiyi_quant.reference_trading import StreamIdentity
    identity = StreamIdentity(strategy_code='htdy', formula_versions=tuple(payload['formula_versions']),
        profile_id='htdy_historical_window32_v1', reference_model_version=MODEL,
        futures_adaptation_version='htdy_physical_quality_prefix_v1', product=payload['product'].upper(),
        frequency='60m', series_kind='actual_dominant', recording_mode='historical_replay',
        observation_policy_version=None)
    if payload['stream_id'] != identity.stream_id:
        raise SnapshotError()
    return identity


def _expected_records(payload):
    from fastapi.encoders import jsonable_encoder
    from app.reference_trading.signal_window import _reference_actions
    from guiyi_quant.reference_trading import StreamIdentity
    stream = _stream_identity(payload)
    cutoff = _instant(payload['computed_through'])
    ids, closed, observed = set(), [], {}
    counts = dict(total=0, closed=0, open=0, interrupted=0, wins=0, losses=0, flat=0)
    for trade in payload['trades']:
        if not isinstance(trade.get('stream'), dict) or StreamIdentity(**trade['stream']) != stream:
            raise SnapshotError()
        identifier = trade['reference_trade_id']
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise SnapshotError()
        ids.add(identifier)
        if trade['status'] not in {'CLOSED', 'OPEN', 'ROLLOVER_INTERRUPTED', 'DATA_INTERRUPTED'} or trade['side'] not in {'LONG', 'SHORT'}:
            raise SnapshotError()
        if not re.fullmatch(re.escape(payload['product'].upper()) + r'[0-9]{3,4}', trade['physical_contract']):
            raise SnapshotError()
        for key in ('owner_segment_id', 'calculation_segment_id', 'entry_action_id'):
            if not isinstance(trade[key], str) or not trade[key]:
                raise SnapshotError()
        entry = _instant(trade['entry_bar_end'])
        day = date.fromisoformat(trade['entry_trading_day'])
        if entry > cutoff or not date.fromisoformat(payload['since']) <= day <= date.fromisoformat(payload['through']):
            raise SnapshotError()
        _decimal(trade['entry_reference_price'], positive=True)
        counts['total'] += 1
        if trade['status'] == 'CLOSED':
            if not entry <= _instant(trade['exit_bar_end']) <= cutoff:
                raise SnapshotError()
            exit_day = date.fromisoformat(trade['exit_trading_day'])
            if not day <= exit_day <= date.fromisoformat(payload['through']):
                raise SnapshotError()
            _decimal(trade['exit_reference_price'], positive=True)
            result = _decimal(trade['reference_return'])
            counts['closed'] += 1
            counts['wins' if result > 0 else 'losses' if result < 0 else 'flat'] += 1
            closed.append(trade)
        else:
            if trade.get('reference_return') is not None or trade.get('exit_bar_end') is not None:
                raise SnapshotError()
            counts['open' if trade['status'] == 'OPEN' else 'interrupted'] += 1
        if trade.get('mark_reference_price') is not None:
            _decimal(trade['mark_reference_price'], positive=True)
        if trade.get('mark_return') is not None:
            _decimal(trade['mark_return'])
    for signal in payload['signals']:
        instant = _instant(signal['bar_end'])
        signal_day = date.fromisoformat(signal['trading_day'])
        if not date.fromisoformat(payload['since']) <= signal_day <= date.fromisoformat(payload['through']):
            raise SnapshotError()
        owner = (instant, signal['physical_contract'], signal['segment_id'], signal['calculation_segment_id'])
        if owner in observed or instant > cutoff or not isinstance(signal['observation_types'], list) or len(signal['observation_types']) != 1 or signal['observation_types'][0] not in {'buy', 'sell'}:
            raise SnapshotError()
        observed[owner] = signal
        _decimal(signal['reference_price'], positive=True)
    earliest = min((_instant(item['entry_bar_end']) for item in payload['trades']), default=cutoff)
    actions = _reference_actions(payload['trades'], payload['signals'], stream_id=payload['stream_id'], from_time=earliest, to_time=cutoff)
    if len(actions) != len(payload['trades']) + counts['closed']:
        raise SnapshotError()
    for action in actions:
        owner = (_instant(action['bar_end'].isoformat()), action['physical_contract'], action['segment_id'], action['calculation_segment_id'])
        signal = observed.get(owner)
        expected = 'buy' if (action['role'] == 'BUILD') == (action['side'] == 'LONG') else 'sell'
        if signal is None or signal['observation_types'] != [expected] or signal['trading_day'] != action['trading_day']:
            raise SnapshotError()
    curve, cumulative = [], Decimal(0)
    version = payload.get('display_projection_version', 'htdy_snapshot_display_v1')
    if version not in {'htdy_snapshot_display_v1', 'htdy_snapshot_display_v2'}:
        raise SnapshotError()
    for trade in sorted(closed, key=lambda item: (item['exit_bar_end'], item['reference_trade_id'])):
        cumulative += _decimal(trade['reference_return'])
        point = dict(bar_end=trade['exit_bar_end'], value=str(cumulative), reference_trade_id=trade['reference_trade_id'])
        if version == 'htdy_snapshot_display_v2':
            point.update(date=trade['exit_trading_day'], segment=':'.join((trade['physical_contract'], trade['owner_segment_id'], trade['calculation_segment_id'])))
        curve.append(point)
    summary = payload['summary']
    for key, count in counts.items():
        if type(summary.get(key)) is not int or summary[key] != count:
            raise SnapshotError()
    if _decimal(summary['sum_return_percentage_points']) != cumulative:
        raise SnapshotError()
    expected_mean = cumulative / Decimal(len(closed)) if closed else None
    expected_win = Decimal(counts['wins']) / Decimal(len(closed)) * 100 if closed else None
    for key, expected in (('mean_return_pct', expected_mean), ('win_rate_pct', expected_win)):
        if (summary.get(key) is not None if expected is None else summary.get(key) is None or _decimal(summary[key]) != expected):
            raise SnapshotError()
    return jsonable_encoder(actions, custom_encoder={Decimal: str}), curve


def _validate(payload):
    if (not isinstance(payload, dict) or payload.get('schema_version') != 'htdy_historical_reference_v1'
            or payload.get('recording_mode') != 'historical_replay' or payload.get('frequency') != '60m'
            or payload.get('source') != 'canonical' or payload.get('reference_model_version') != MODEL
            or payload.get('page_parity') is not True or payload.get('executable') is not False
            or payload.get('auto_order') is not False or not _ID.fullmatch(str(payload.get('source_token', '')))
            or not isinstance(payload.get('formula_versions'), list) or not payload['formula_versions']
            or any(not isinstance(value, str) or not value.strip() for value in payload['formula_versions'])
            or not isinstance(payload.get('stream_id'), str) or not payload['stream_id']):
        raise SnapshotError()
    _scope(payload.get('product'))
    if (not isinstance(payload.get('trades'), list) or len(payload['trades']) > MAX_TRADES
            or not isinstance(payload.get('signals'), list) or len(payload['signals']) > MAX_SIGNALS
            or not isinstance(payload.get('actions'), list) or len(payload['actions']) > 2 * MAX_TRADES
            or not isinstance(payload.get('curve'), list) or len(payload['curve']) > MAX_TRADES
            or not isinstance(payload.get('summary'), dict)):
        raise SnapshotError()
    try:
        since, through = date.fromisoformat(payload['since']), date.fromisoformat(payload['through'])
        cutoff = datetime.fromisoformat(payload['computed_through'])
        if since > through or cutoff.tzinfo is None:
            raise ValueError
        actions, curve = _expected_records(payload)
        if actions != payload['actions'] or curve != payload['curve']:
            raise SnapshotError()
    except Exception:
        raise SnapshotError() from None


def _read(parent, name, *, allow_linked=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES or info.st_uid != os.getuid() or info.st_nlink != (2 if allow_linked else 1) or info.st_mode & 0o077:
            raise SnapshotError()
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise SnapshotError()
        if size != info.st_size:
            raise SnapshotError()
        return json.loads(b''.join(chunks))
    finally:
        os.close(fd)


def _write_temp(parent, payload):
    encoded = _encode(payload)
    if len(encoded) > MAX_BYTES:
        raise SnapshotError('HTDY_SNAPSHOT_BUDGET_EXCEEDED')
    name = f'.htdy-{uuid4().hex}.tmp'
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise SnapshotError()
            remaining = remaining[written:]
        os.fsync(fd)
    except BaseException:
        os.unlink(name, dir_fd=parent)
        raise
    finally:
        os.close(fd)
    return name


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root != self.root.resolve():
            raise SnapshotError('HTDY_SNAPSHOT_INVALID_QUERY')

    def _load(self, parent, identifier, *, allow_linked=False):
        value = _read(parent, f'{identifier}.json', allow_linked=allow_linked)
        payload = value['payload']
        _validate(payload)
        if (value['sha256'] != sha256(_encode(payload)).hexdigest()
                or payload.get('snapshot_id') != identifier or _digest(payload) != identifier):
            raise SnapshotError()
        generated = datetime.fromisoformat(payload['generated_at'])
        if generated.tzinfo is None:
            raise SnapshotError()
        return payload

    def _recover_linked_temp(self, parent, identifier):
        """Only an explicit publisher under its product lock may finish a crash link."""
        name = f'{identifier}.json'
        try:
            target = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if target.st_nlink == 1:
            return
        if (not stat.S_ISREG(target.st_mode) or target.st_nlink != 2
                or target.st_uid != os.getuid() or target.st_mode & 0o077):
            raise SnapshotError()
        candidates = []
        for candidate in os.listdir(parent):
            if not re.fullmatch(r'\.htdy-[0-9a-f]{32}\.tmp', candidate):
                continue
            info = os.stat(candidate, dir_fd=parent, follow_symlinks=False)
            if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 2:
                    raise SnapshotError()
                candidates.append(candidate)
        if len(candidates) != 1:
            raise SnapshotError()
        # Validate all bytes, content hash, scope, identity and semantic facts
        # before removing the sole root-local temporary alias of the same inode.
        self._load(parent, identifier, allow_linked=True)
        info = os.stat(candidates[0], dir_fd=parent, follow_symlinks=False)
        if (info.st_dev, info.st_ino, info.st_nlink) != (target.st_dev, target.st_ino, 2):
            raise SnapshotError()
        os.unlink(candidates[0], dir_fd=parent)
        os.fsync(parent)

    def read(self, symbol, *, snapshot_id=None, before=None, limit=50):
        _scope(symbol, snapshot_id)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise SnapshotError('HTDY_SNAPSHOT_INVALID_QUERY')
        parent = None
        try:
            parent = _open_projection_parent(self.root, create=False)
            if parent is None:
                raise SnapshotError('HTDY_SNAPSHOT_NOT_BUILT')
            identifier = snapshot_id
            if identifier is None:
                index = _read(parent, f'{symbol}-latest.json')
                identifier = index['snapshot_id']
                _scope(symbol, identifier)
            payload = self._load(parent, identifier)
            if payload['product'] != symbol:
                raise SnapshotError('HTDY_SNAPSHOT_SCOPE_MISMATCH')
            offset = 0
            if before is not None:
                match = re.fullmatch(r'([0-9a-f]{64}):([0-9]{1,5})', before)
                if match is None or match[1] != identifier:
                    raise SnapshotError('HTDY_SNAPSHOT_CURSOR_CONFLICT')
                offset = int(match[2])
                if offset > len(payload['trades']):
                    raise SnapshotError('HTDY_SNAPSHOT_CURSOR_CONFLICT')
            result = deepcopy(payload)
            result['trades'] = payload['trades'][offset:offset + limit]
            result['next_cursor'] = f'{identifier}:{offset + limit}' if offset + limit < len(payload['trades']) else None
            return result
        except FileNotFoundError:
            raise SnapshotError('HTDY_SNAPSHOT_NOT_BUILT') from None
        except SnapshotError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise SnapshotError() from None
        finally:
            if parent is not None:
                os.close(parent)

    def publish(self, payload, *, now=None):
        payload = deepcopy(payload)
        payload.pop('next_cursor', None)
        _validate(payload)
        identifier = _digest(payload)
        payload.update(snapshot_id=identifier, generated_at=(now or datetime.now(UTC)).isoformat())
        parent, lock_fd = None, None
        temp = None
        try:
            parent = _open_projection_parent(self.root, create=True)
            lock_fd = os.open(f"{payload['product']}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise SnapshotError()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SnapshotError('HTDY_SNAPSHOT_BUILD_BUSY') from None
            self._recover_linked_temp(parent, identifier)
            try:
                payload = self._load(parent, identifier)
            except FileNotFoundError:
                temp = _write_temp(parent, {'payload': payload, 'sha256': sha256(_encode(payload)).hexdigest()})
                os.link(temp, f'{identifier}.json', src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                os.unlink(temp, dir_fd=parent)
                temp = None
                os.fsync(parent)
            name = f"{payload['product']}-latest.json"
            try:
                if not stat.S_ISREG(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
                    raise SnapshotError()
            except FileNotFoundError:
                pass
            temp = _write_temp(parent, {'snapshot_id': identifier})
            os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
            temp = None
            os.fsync(parent)
            return deepcopy(payload)
        except SnapshotError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise SnapshotError() from None
        finally:
            try:
                if temp is not None and parent is not None:
                    try:
                        os.unlink(temp, dir_fd=parent)
                    except OSError:
                        # A root-local temporary alias can be recovered only by
                        # the next explicit publisher, never by a GET reader.
                        pass
            finally:
                try:
                    if lock_fd is not None:
                        os.close(lock_fd)
                finally:
                    if parent is not None:
                        os.close(parent)


def build_snapshot(service, query, *, store=None, query_history=None):
    """Explicit builder only. Freeze a complete independently paginated replay."""
    from fastapi.encoders import jsonable_encoder
    from app.reference_trading.htdy_history import query_htdy_history
    from app.reference_trading.signal_window import _reference_actions
    read = query_history or query_htdy_history
    if query.frequency != '60m' or query.before is not None:
        raise SnapshotError('HTDY_SNAPSHOT_INVALID_QUERY')
    query = replace(query, limit=200, as_of=query.as_of or service.now())
    first = jsonable_encoder(read(service, query), custom_encoder={Decimal: str})
    if first['summary']['total'] > MAX_TRADES or len(first['signals']) > MAX_SIGNALS:
        raise SnapshotError('HTDY_SNAPSHOT_BUDGET_EXCEEDED')
    trades = list(first['trades'])
    cursor = first['next_cursor']
    seen_cursors = set()
    while cursor:
        service.check_cancelled()
        if cursor in seen_cursors or len(trades) >= MAX_TRADES:
            raise SnapshotError('HTDY_SNAPSHOT_BUDGET_EXCEEDED')
        seen_cursors.add(cursor)
        page = jsonable_encoder(read(service, replace(query, before=cursor)), custom_encoder={Decimal: str})
        if (page['source_token'] != first['source_token'] or page['summary'] != first['summary']
                or page['stream_id'] != first['stream_id'] or page['computed_through'] != first['computed_through']):
            raise SnapshotError('HTDY_SNAPSHOT_SOURCE_CHANGED')
        trades.extend(page['trades'])
        cursor = page['next_cursor']
    if len(trades) != first['summary']['total'] or len({row['reference_trade_id'] for row in trades}) != len(trades):
        raise SnapshotError('HTDY_SNAPSHOT_SOURCE_CHANGED')
    signals = first['signals']
    earliest = min((datetime.fromisoformat(item['entry_bar_end']) for item in trades), default=datetime.fromisoformat(first['computed_through']))
    actions = _reference_actions(trades, signals, stream_id=first['stream_id'], from_time=earliest,
                                 to_time=datetime.fromisoformat(first['computed_through']))
    cumulative, curve = Decimal(0), []
    for trade in sorted((item for item in trades if item['status'] == 'CLOSED'),
                        key=lambda item: (item['exit_bar_end'], item['reference_trade_id'])):
        result = Decimal(trade['reference_return'])
        if not result.is_finite():
            raise SnapshotError()
        cumulative += result
        curve.append(dict(bar_end=trade['exit_bar_end'], value=str(cumulative), reference_trade_id=trade['reference_trade_id']))
    if first['summary']['closed'] != len(curve) or Decimal(first['summary']['sum_return_percentage_points']) != cumulative:
        raise SnapshotError('HTDY_SNAPSHOT_SOURCE_CHANGED')
    payload = {**first, 'trades': trades, 'actions': actions, 'curve': curve, 'display_projection_version': 'htdy_snapshot_display_v2'}
    for point, trade in zip(curve, sorted((item for item in trades if item['status'] == 'CLOSED'), key=lambda item: (item['exit_bar_end'], item['reference_trade_id'])), strict=True):
        point.update(date=trade['exit_trading_day'], segment=':'.join((trade['physical_contract'], trade['owner_segment_id'], trade['calculation_segment_id'])))
    payload.pop('next_cursor', None)
    payload = jsonable_encoder(payload, custom_encoder={Decimal: str})
    return (store or SnapshotStore(snapshot_root())).publish(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build',))
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--since', type=date.fromisoformat)
    parser.add_argument('--through', type=date.fromisoformat)
    parser.add_argument('--as-of', type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        _scope(args.symbol)
        from app.private_settings import load_private_readonly_settings
        settings, _ = load_private_readonly_settings(Path.home() / 'Library/Application Support/GuiyiQuant/project.env')
        os.environ.update({key: settings[key] for key in ('DATABASE_URL', 'GUIYI_CANONICAL_DATA_ROOT')})
        from app.api.market_subing_reference import _build_service
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.subing_reference import SubingReferenceQuery
        from time import monotonic
        deadline = monotonic() + 600
        def check_cancelled():
            if monotonic() > deadline:
                raise SnapshotError('HTDY_SNAPSHOT_BUDGET_EXCEEDED')
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=600):
            service = _build_service(session, check_cancelled)
            result = build_snapshot(service, SubingReferenceQuery(args.symbol, args.since, args.through,
                                    args.as_of, frequency='60m'))
        print(json.dumps({'status': 'built', 'snapshot_id': result['snapshot_id'],
                          'product': result['product'], 'summary': result['summary']}))
    except Exception as exc:
        code = exc.code if isinstance(exc, SnapshotError) else 'HTDY_SNAPSHOT_BUILD_FAILED'
        raise SystemExit(code) from None


if __name__ == '__main__':
    main()
