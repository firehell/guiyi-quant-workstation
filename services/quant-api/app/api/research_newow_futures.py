"""Read-only, bounded views of SHA-verified historical research; GET never runs research."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from bisect import bisect_left
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from guiyi_quant.newow_futures.contracts import FREQUENCIES, MODEL, PRODUCTS, Profile, Variant, profile_payload
from app.newow_futures_research.store import (
    PARTS, ResultStoreError, latest_packet, list_result_page, read_packet,
)

router = APIRouter(prefix='/api/v1/research/newow-futures', tags=['newow-futures-research'])
PROJECT_ROOT = Path(__file__).resolve().parents[4]
Hash = Annotated[str | None, Query(pattern=r'^[0-9a-f]{64}$')]


def _root() -> Path:
    value = os.getenv('GUIYI_NEWOW_FUTURES_RESULTS_ROOT')
    return Path(value) if value else PROJECT_ROOT / 'output' / 'newow-futures-bidir-v1-20261021'


def _fail(exc: ResultStoreError) -> HTTPException:
    code = str(exc)
    status = 404 if code == 'RESULT_NOT_FOUND' else 422 if code in {'RUN_ID_INVALID', 'PAGE_INVALID'} else 409
    return HTTPException(status_code=status, detail={'code': code})


def _packet(run_id: str, sha256: str | None = None) -> dict:
    try:
        packet = read_packet(_root(), run_id)
        if sha256 is not None and packet['sha256'] != sha256:
            raise ResultStoreError('RESULT_HASH_MISMATCH')
        return packet
    except ResultStoreError as exc:
        raise _fail(exc) from exc


def _preview(rows: list) -> list:
    return rows if len(rows) <= 100 else rows[:50] + rows[-50:]


def _bounded(value):
    """Bound ancillary diagnostics, preserving exact scalars and explicit frozen summaries."""
    if isinstance(value, list):
        return [_bounded(item) for item in _preview(value)]
    if isinstance(value, dict):
        return {key: _bounded(item) for key, item in value.items()}
    return value


def _time(row: dict) -> datetime | None:
    value = row.get('bar_end', row.get('at'))
    try:
        at = datetime.fromisoformat(value)
        return at if at.tzinfo is not None and at.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def _detail(packet: dict) -> dict:
    chart, ref = packet['chart'], packet['reference']
    bars = chart['bars'][-2000:]
    times = {_time(row) for row in bars} - {None}
    frames = [row for row in chart['frames'] if _time(row) in times][-2000:]
    by_contract: dict[str, list] = {}
    bar_owners = {}
    for bar in bars:
        at = _time(bar)
        if at is not None and isinstance(bar.get('physical_contract'), str):
            by_contract.setdefault(bar['physical_contract'], []).append(at)
            bar_owners[(bar['physical_contract'], at)] = bar.get('owner_segment_id')
    actions = []
    for row in ref['actions']:
        at = _time(row)
        if not times or at is None or not min(times) <= at <= max(times):
            continue
        candidates = by_contract.get(row.get('physical_contract'), [])
        index = bisect_left(candidates, at)
        projected = row
        if index < len(candidates) and (candidates[index] == at or index > 0):
            target_owner = bar_owners[(row.get('physical_contract'), candidates[index])]
            source_owner = row.get('owner_segment_id')
            prior_owner = bar_owners.get((row.get('physical_contract'), candidates[index - 1])) if index else target_owner
            if (source_owner is None or source_owner == target_owner) and (
                    candidates[index] == at or prior_owner == target_owner):
                projected = {**row, 'display_bar_end': candidates[index].isoformat()}
        actions.append(projected)
    actions = actions[-2000:]
    return {'schema_version': packet['schema_version'], 'run_id': packet['run_id'], 'sha256': packet['sha256'],
            'metadata': packet['metadata'], 'summary': packet['summary'],
            'reference': {'summary': ref['summary'], 'snapshot': ref['snapshot'],
                          'actions': actions, 'trades': _preview(ref['trades']),
                          'equity': _preview(ref['equity'])},
            'chart': {'bars': bars, 'frames': frames}, 'diagnostics': _bounded(packet['diagnostics']),
            'preview': {'chart_total': len(chart['bars']), 'chart_frames_total': len(chart['frames']),
                        'reference_actions_total': len(ref['actions']),
                        'reference_trades_total': len(ref['trades']),
                        'reference_equity_total': len(ref['equity']),
                        **{f'{key}_total': len(packet[key]) for key in ('decisions', 'fills', 'trades', 'equity')}}}


@router.get('/profiles')
def profiles() -> dict:
    return {'strategy_model': MODEL, 'products': [product.upper() for product in PRODUCTS],
            'frequencies': list(FREQUENCIES), 'strategies': [item.value for item in Variant],
            'scenarios': ['baseline', 'double_commission', 'double_slippage'],
            'profiles': [profile_payload(Profile(variant, frequency))
                         for variant in Variant for frequency in FREQUENCIES]}


@router.get('/runs')
def runs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=4096)) -> dict:
    try:
        return list_result_page(_root(), limit=limit, offset=offset)
    except ResultStoreError as exc:
        raise _fail(exc) from exc


@router.get('/snapshot')
def snapshot(product: str = Query(max_length=10), strategy: str = Query(max_length=30),
             frequency: str = Query(max_length=4), scenario: str = Query('baseline', max_length=30),
             sha256: Hash = None) -> dict:
    product = product.upper()
    if product.lower() not in PRODUCTS:
        raise HTTPException(status_code=404, detail={'code': 'RESEARCH_NOT_COVERED'})
    if strategy not in {item.value for item in Variant} or frequency not in FREQUENCIES or scenario not in {
            'baseline', 'double_commission', 'double_slippage'}:
        raise HTTPException(status_code=422, detail={'code': 'RESEARCH_QUERY_INVALID'})
    try:
        packet = latest_packet(_root(), product=product, strategy=strategy, frequency=frequency,
                               scenario=scenario, expected_sha256=sha256)
        return _detail(packet)
    except ResultStoreError as exc:
        raise _fail(exc) from exc


@router.get('/runs/{run_id}')
def run_detail(run_id: str, sha256: Hash = None) -> dict:
    return _detail(_packet(run_id, sha256))


@router.get('/runs/{run_id}/equity-curve')
def equity_curve(run_id: str, kind: str = Query('equity', pattern='^(equity|reference-equity)$'),
                 max_points: int = Query(2000, ge=4, le=2000), sha256: Hash = None) -> dict:
    packet = _packet(run_id, sha256)
    rows = packet['equity'] if kind == 'equity' else packet['reference']['equity']
    points = [{'at': row['at'], 'value': row.get('value', row.get('equity')),
               **({'physical_contract': row['physical_contract']} if 'physical_contract' in row else {})}
              for row in rows]
    protected = {0, len(points) - 1} if points else set()
    for index in range(1, len(points)):
        left, right = points[index - 1], points[index]
        if (left.get('physical_contract') != right.get('physical_contract')
                or (left['value'] is None) != (right['value'] is None)):
            protected.update((index - 1, index))
    numeric = [i for i, point in enumerate(points) if point['value'] is not None]
    if numeric:
        protected.update((min(numeric, key=lambda i: Decimal(points[i]['value'])),
                          max(numeric, key=lambda i: Decimal(points[i]['value']))))
    if len(protected) > max_points:
        raise HTTPException(status_code=409, detail={'code': 'CURVE_BOUNDARY_BUDGET_EXCEEDED'})
    chosen = set(range(len(points))) if len(points) <= max_points else protected.copy()
    if len(points) > max_points:
        buckets = max(1, (max_points - len(chosen)) // 2)
        for bucket in range(buckets):
            indices = [i for i in range(bucket * len(points) // buckets, (bucket + 1) * len(points) // buckets)
                       if points[i]['value'] is not None]
            if indices:
                chosen.update((min(indices, key=lambda i: Decimal(points[i]['value'])),
                               max(indices, key=lambda i: Decimal(points[i]['value']))))
        # Preserve mandatory boundaries even when a nearly full budget has one slot.
        if len(chosen) > max_points:
            chosen = protected | set(sorted(chosen - protected)[:max_points - len(protected)])
    return {'run_id': packet['run_id'], 'sha256': packet['sha256'], 'kind': kind,
            'points': [points[i] for i in sorted(chosen)], 'total_points': len(points),
            'status': 'COMPLETED', 'sampled': len(chosen) < len(points)}


@router.get('/runs/{run_id}/{part}')
def part_page(run_id: str, part: str, limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0, le=10000000), sha256: Hash = None) -> dict:
    if part not in PARTS:
        raise HTTPException(status_code=422, detail={'code': 'PAGE_INVALID'})
    packet = _packet(run_id, sha256)
    rows = packet['reference']['trades'] if part == 'reference-trades' else packet[part]
    if offset > len(rows):
        raise HTTPException(status_code=422, detail={'code': 'PAGE_INVALID'})
    items = rows[offset:offset + limit]
    end = offset + len(items)
    return {'run_id': run_id, 'sha256': packet['sha256'], 'part': part, 'items': items,
            'total': len(rows), 'offset': offset, 'limit': limit,
            'next_offset': end if end < len(rows) else None}
