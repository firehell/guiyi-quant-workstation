"""Explicit-root immutable packets with verified SHA index; no historical data I/O."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from typing import Any, Iterator

from guiyi_quant.newow_futures.contracts import MODEL, PRODUCTS, VERSIONS, Profile, Variant

MAX_BYTES = 128 * 1024 * 1024
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_RUNS = 4096
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
STATUSES = {'COMPLETED', 'DATA_INSUFFICIENT', 'EXECUTION_FACTS_MISSING', 'DATA_INTERRUPTED',
            'ROLLOVER_INTERRUPTED', 'PENDING_UNFILLED', 'INSUFFICIENT_CAPITAL', 'NOT_APPLICABLE'}
NULLABLE_HASH_STATUSES = {'DATA_INSUFFICIENT', 'EXECUTION_FACTS_MISSING', 'DATA_INTERRUPTED', 'NOT_APPLICABLE'}
PARTS = {'decisions', 'fills', 'trades', 'equity', 'reference-trades'}
TIME_FIELDS = {'at', 'bar_end', 'entry_at', 'exit_at', 'entry_bar_end', 'exit_bar_end',
               'observed_at', 'confirmed_at', 'effective_after', 'fill_at', 'valuation_at', 'decision_at'}
MONEY_FIELDS = {'open', 'high', 'low', 'close', 'volume', 'price', 'entry_price', 'exit_price',
                'net_pnl', 'gross_pnl', 'pnl', 'fees', 'fee', 'equity', 'value', 'initial_cash',
                'final_equity', 'reference_return', 'entry_reference_price', 'exit_reference_price',
                'stop_reference_price', 'target_reference_price'}


class ResultStoreError(ValueError):
    """A stable public code, with no filesystem path or underlying secret."""


@contextmanager
def _directory(root: Path, *, create: bool = False) -> Iterator[int]:
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise ResultStoreError('RESULT_ROOT_UNSAFE')
    descriptors = []
    try:
        descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(descriptor)
        for component in root.parts[1:]:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=descriptor)
            descriptors.append(descriptor)
        yield descriptor
    except ResultStoreError:
        raise
    except FileNotFoundError as exc:
        raise ResultStoreError('RESULT_NOT_FOUND') from exc
    except OSError as exc:
        raise ResultStoreError('RESULT_PATH_UNSAFE') from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _encode(value: Any, maximum: int = MAX_BYTES) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ResultStoreError('RESULT_SCHEMA_INVALID') from exc
    if len(raw) > maximum:
        raise ResultStoreError('RESULT_TOO_LARGE')
    return raw


def _parse(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ResultStoreError('RESULT_CORRUPT') from exc


def _read(directory: int, name: str, maximum: int = MAX_BYTES) -> bytes:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError as exc:
        raise ResultStoreError('RESULT_NOT_FOUND') from exc
    except OSError as exc:
        raise ResultStoreError('RESULT_PATH_UNSAFE') from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ResultStoreError('RESULT_PATH_UNSAFE')
        if info.st_size > maximum:
            raise ResultStoreError('RESULT_TOO_LARGE')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ResultStoreError('RESULT_TOO_LARGE')
        return raw
    finally:
        os.close(descriptor)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _aware(value: Any) -> bool:
    try:
        time = datetime.fromisoformat(value)
        return time.tzinfo is not None and time.utcoffset() is not None
    except (ValueError, TypeError):
        return False


def _rows(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(row, dict) for row in value)


def _curve_valid(rows: list) -> bool:
    previous = None
    for row in rows:
        if not isinstance(row, dict) or not _aware(row.get('at')) or not ('value' in row or 'equity' in row):
            return False
        at = datetime.fromisoformat(row['at'])
        if previous is not None and at <= previous:
            return False
        previous = at
        value = row.get('value', row.get('equity'))
        if value is not None and (not isinstance(value, str) or not Decimal(value).is_finite()):
            return False
    return True


def _no_float(value: Any) -> None:
    if isinstance(value, float):
        raise ResultStoreError('RESULT_SCHEMA_INVALID')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ResultStoreError('RESULT_SCHEMA_INVALID')
            if key in TIME_FIELDS and item is not None and not _aware(item):
                raise ResultStoreError('RESULT_SCHEMA_INVALID')
            if key in MONEY_FIELDS and item is not None and not isinstance(item, (dict, list)):
                try:
                    if not isinstance(item, str) or not Decimal(item).is_finite():
                        raise ValueError()
                except (InvalidOperation, ValueError) as exc:
                    raise ResultStoreError('RESULT_SCHEMA_INVALID') from exc
            _no_float(item)
    elif isinstance(value, list):
        for item in value:
            _no_float(item)


def _validate_metadata(meta: Any, *, published: bool = False) -> None:
    if not isinstance(meta, dict):
        raise ResultStoreError('RESULT_SCHEMA_INVALID')
    try:
        profile = Profile(Variant(meta['strategy']), meta['frequency'])
        valid = (meta['strategy_model'] == MODEL and meta['product'] in tuple(p.upper() for p in PRODUCTS)
                 and meta['scenario'] in {'baseline', 'double_commission', 'double_slippage'}
                 and meta['status'] in STATUSES and meta['profile_id'] == profile.profile_id
                 and meta['versions'] == VERSIONS and meta['initial_cash'] == '100000'
                 and meta['requested_since'] == '2024-10-14' and meta['requested_through'] == '2026-10-19'
                 and meta['source'] == 'historical_replay' and meta['auto_order'] is False
                 and meta['oos_status'] == 'OOS_NOT_PROVEN' and _aware(meta['as_of'])
                 and isinstance(meta['code_revision'], str) and bool(meta['code_revision']))
        for key in ('input_snapshot_hash', 'execution_facts_hash'):
            valid = valid and (_sha(meta[key]) or
                              (meta[key] is None and meta['status'] in NULLABLE_HASH_STATUSES))
        if published:
            valid = valid and _sha(meta['run_id'])
        if 'generated_at' in meta:
            valid = valid and _aware(meta['generated_at'])
        if not valid:
            raise ValueError()
        _no_float(meta)
    except (KeyError, ValueError, TypeError, InvalidOperation, RecursionError) as exc:
        raise ResultStoreError('RESULT_SCHEMA_INVALID') from exc


def _validate(packet: dict, *, published: bool = False) -> None:
    if type(packet.get('schema_version')) is not int or packet['schema_version'] != 1:
        raise ResultStoreError('RESULT_SCHEMA_INVALID')
    meta = packet.get('metadata')
    _validate_metadata(meta, published=published)
    try:
        valid = True
        summary, reference, chart = packet['summary'], packet['reference'], packet['chart']
        valid = valid and isinstance(summary, dict) and summary.get('status') == meta['status']
        valid = valid and isinstance(reference, dict) and isinstance(reference['summary'], dict)
        valid = valid and isinstance(reference['snapshot'], dict)
        valid = valid and all(_rows(reference[key]) for key in ('actions', 'trades', 'equity'))
        valid = valid and isinstance(chart, dict) and all(_rows(chart[key]) for key in ('bars', 'frames'))
        valid = valid and all(_rows(packet[key]) for key in ('decisions', 'fills', 'trades', 'equity'))
        valid = valid and isinstance(packet['diagnostics'], dict)
        valid = valid and _curve_valid(packet['equity']) and _curve_valid(reference['equity'])
        if reference['summary'].get('executable', False) is not False:
            valid = False
        if summary.get('initial_cash', '100000') != '100000':
            valid = False
        for key in ('initial_cash', 'final_equity', 'account_return_pct', 'max_drawdown_pct', 'total_fees'):
            value = summary.get(key)
            if value is not None and (not isinstance(value, str) or not Decimal(value).is_finite()):
                valid = False
        if meta['status'] in NULLABLE_HASH_STATUSES | {'ROLLOVER_INTERRUPTED'}:
            valid = valid and all(summary.get(key) is None for key in ('final_equity', 'account_return_pct'))
            valid = valid and summary.get('annual_eligible', False) is False
        if not valid:
            raise ValueError()
        _no_float(packet)
        _encode(packet)
    except (KeyError, ValueError, TypeError, InvalidOperation, RecursionError) as exc:
        raise ResultStoreError('RESULT_SCHEMA_INVALID') from exc


def _identity(packet: dict) -> str:
    meta = {key: value for key, value in packet['metadata'].items() if key != 'run_id'}
    return hashlib.sha256(_encode(meta)).hexdigest()


def _index(directory: int) -> dict:
    try:
        raw = _read(directory, 'index.json', MAX_INDEX_BYTES)
    except ResultStoreError as exc:
        if str(exc) == 'RESULT_NOT_FOUND':
            return {'schema_version': 1, 'runs': []}
        raise
    index = _parse(raw)
    if type(index.get('schema_version')) is not int or index['schema_version'] != 1:
        raise ResultStoreError('INDEX_CORRUPT')
    entries = index.get('runs')
    if not isinstance(entries, list) or len(entries) > MAX_RUNS:
        raise ResultStoreError('INDEX_CORRUPT')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('metadata'), dict):
            raise ResultStoreError('INDEX_CORRUPT')
        run_id = entry.get('run_id')
        if (not _sha(run_id) or run_id in seen or not _sha(entry.get('sha256'))
                or entry.get('file') != f'{run_id}.json' or entry['metadata'].get('run_id') != run_id):
            raise ResultStoreError('INDEX_CORRUPT')
        try:
            _validate_metadata(entry['metadata'], published=True)
            if _identity({'metadata': entry['metadata']}) != run_id:
                raise ResultStoreError('RESULT_ID_MISMATCH')
        except ResultStoreError as exc:
            raise ResultStoreError('INDEX_CORRUPT') from exc
        seen.add(run_id)
    return index


def _verified(directory: int, entry: dict) -> dict:
    raw = _read(directory, entry['file'])
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ResultStoreError('RESULT_HASH_MISMATCH')
    packet = _parse(raw)
    _validate(packet, published=True)
    if packet['metadata'] != entry['metadata'] or _identity(packet) != entry['run_id']:
        raise ResultStoreError('RESULT_ID_MISMATCH')
    return {**packet, 'run_id': entry['run_id'], 'sha256': entry['sha256']}


def _atomic(directory: int, name: str, raw: bytes, *, exclusive: bool = False) -> None:
    temporary = f'.packet-{uuid.uuid4().hex}'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode=0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def publish_packet(root: Path, packet: dict) -> dict:
    """Publish task output atomically, serializing writers and never replacing a run."""
    if not isinstance(packet, dict):
        raise ResultStoreError('RESULT_SCHEMA_INVALID')
    _validate(packet)
    run_id = _identity(packet)
    if packet['metadata'].get('run_id') not in (None, run_id):
        raise ResultStoreError('RESULT_ID_MISMATCH')
    frozen = {**packet, 'metadata': {**packet['metadata'], 'run_id': run_id}}
    raw = _encode(frozen)
    sha = hashlib.sha256(raw).hexdigest()
    with _directory(root, create=True) as directory:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            # Separate atomic first creation from opening an existing lock. Concurrent
            # O_CREAT without O_EXCL can report ENOENT on this macOS filesystem even
            # while the directory and newly created file still exist.
            lock = os.open('.index.lock', flags | os.O_CREAT | os.O_EXCL,
                           mode=0o600, dir_fd=directory)
        except FileExistsError:
            lock = os.open('.index.lock', flags, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise ResultStoreError('RESULT_PATH_UNSAFE')
            fcntl.flock(lock, fcntl.LOCK_EX)
            index = _index(directory)
            existing = next((entry for entry in index['runs'] if entry['run_id'] == run_id), None)
            if existing is not None:
                _verified(directory, existing)
                if existing['sha256'] != sha:
                    raise ResultStoreError('RESULT_CONFLICT')
                return {'run_id': run_id, 'sha256': sha, 'metadata': frozen['metadata']}
            if len(index['runs']) >= MAX_RUNS:
                raise ResultStoreError('INDEX_TOO_LARGE')
            entry = {'run_id': run_id, 'sha256': sha, 'file': f'{run_id}.json',
                     'metadata': frozen['metadata']}
            index['runs'].append(entry)
            index_raw = _encode(index, MAX_INDEX_BYTES)
            # A crash before index publication may leave an orphan; safe exact retry verifies it.
            try:
                _atomic(directory, entry['file'], raw, exclusive=True)
            except FileExistsError:
                if _read(directory, entry['file']) != raw:
                    raise ResultStoreError('RESULT_CONFLICT')
            _atomic(directory, 'index.json', index_raw)
        finally:
            os.close(lock)
    return {'run_id': run_id, 'sha256': sha, 'metadata': frozen['metadata']}


def read_packet(root: Path, run_id: str) -> dict:
    if not _sha(run_id):
        raise ResultStoreError('RUN_ID_INVALID')
    with _directory(root) as directory:
        entry = next((item for item in _index(directory)['runs'] if item['run_id'] == run_id), None)
        if entry is None:
            raise ResultStoreError('RESULT_NOT_FOUND')
        return _verified(directory, entry)


def list_results(root: Path) -> list[dict]:
    try:
        with _directory(root) as directory:
            return [{'run_id': packet['run_id'], 'sha256': packet['sha256'],
                     'metadata': packet['metadata'], 'summary': packet['summary']}
                    for packet in (_verified(directory, entry) for entry in _index(directory)['runs'])]
    except ResultStoreError as exc:
        if str(exc) == 'RESULT_NOT_FOUND' and not Path(root).exists():
            return []
        raise


def _recency(entry: dict) -> tuple:
    meta = entry['metadata']
    return (datetime.fromisoformat(meta.get('generated_at', meta['as_of'])),
            datetime.fromisoformat(meta['as_of']), entry['run_id'])


def latest_packet(root: Path, *, product: str, strategy: str, frequency: str,
                  scenario: str, expected_sha256: str | None = None) -> dict:
    """Select an exact cell from the validated index, then verify only its full packet."""
    with _directory(root) as directory:
        matches = [entry for entry in _index(directory)['runs']
                   if all(entry['metadata'][key] == value for key, value in (
                       ('product', product), ('strategy', strategy), ('frequency', frequency),
                       ('scenario', scenario))) ]
        if not matches:
            raise ResultStoreError('RESULT_NOT_FOUND')
        selected = max(matches, key=_recency)
        if expected_sha256 is not None and selected['sha256'] != expected_sha256:
            raise ResultStoreError('RESULT_HASH_MISMATCH')
        return _verified(directory, selected)


def list_result_page(root: Path, *, offset: int = 0, limit: int = 50) -> dict:
    """Validate the index and the requested page; unrequested packet bodies are untouched."""
    if type(offset) is not int or type(limit) is not int or not 0 <= offset <= MAX_RUNS or not 1 <= limit <= 200:
        raise ResultStoreError('PAGE_INVALID')
    try:
        with _directory(root) as directory:
            entries = sorted(_index(directory)['runs'], key=_recency, reverse=True)
            packets = [_verified(directory, entry) for entry in entries[offset:offset + limit]]
            return {'runs': [{'run_id': packet['run_id'], 'sha256': packet['sha256'],
                              'metadata': packet['metadata'], 'summary': packet['summary']}
                             for packet in packets],
                    'total': len(entries), 'offset': offset, 'limit': limit}
    except ResultStoreError as exc:
        if str(exc) == 'RESULT_NOT_FOUND' and not Path(root).exists():
            return {'runs': [], 'total': 0, 'offset': offset, 'limit': limit}
        raise
