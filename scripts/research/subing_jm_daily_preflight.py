"""Local-only phase A audit. No strategy trades, provider, repairs or account writes."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.new_subing_research import (
    _wire, load_execution_facts, payload_hash, safe_diagnostic, validate_series,
)
from guiyi_quant.indicators.subing_ths import SubingThs15mKernel
from scripts.research.newow_futures_execution_facts import read_json, safe_path


def compare_endpoints(expected, bars):
    actual = [(b.bar_end, b.trading_day) for b in bars]
    wanted = set(expected)
    found = set(actual)
    return {
        'expected_count': len(expected), 'actual_count': len(actual),
        'missing': _wire(sorted(wanted - found)),
        'unexpected': _wire(sorted(found - wanted)),
        'duplicate_count': len(actual) - len(found),
        'ordered': all(a[0] < b[0] for a, b in zip(actual, actual[1:])),
    }


def execution_day(raw, contract, day):
    """Use the existing strict dated-facts validator, without constructing a fill."""
    body = raw.get('contracts', {}).get(contract)
    if body is None:
        raise ValueError('EXECUTION_FACTS_MISSING')
    selected = {**body,
        'parameters': [r for r in body['parameters'] if r['date'] == day.isoformat()],
        'daily': [r for r in body['daily'] if r['date'] == day.isoformat()]}
    subset = {**raw, 'contracts': {contract: selected}}
    probe = SimpleNamespace(frequency='1m', physical_contract=contract, trading_day=day)
    rows, _ = load_execution_facts(subset, product='jm', bars=(probe,))
    facts = asdict(rows[0].facts)
    facts.pop('source_id')
    facts['fees'].pop('source_id')
    return _wire(facts)


def audit_series(market, contract, frequency, since, through, cutoff):
    context = {'contract': contract, 'frequency': frequency.value,
               'since': since.isoformat() if since else None, 'through': through.isoformat()}
    try:
        before = market.contract_source_evidence(
            symbol='jm', contract=contract, frequency=frequency, before=cutoff)
        expected = market.expected_contract_replay_endpoints(
            symbol='jm', contract=contract, frequency=frequency,
            trading_day=through, cutoff=cutoff, since=since)
        if not expected:
            raise ValueError('EMPTY_EXPECTED_ENDPOINTS')
        result = market.query_contract_trading_days(ContractTradingDayQuery(
            'jm', contract, frequency, expected[0][1], through))
        endpoints = compare_endpoints(expected, result.bars)
        try:
            validate_series(result, product='jm', contract=contract,
                            frequency=frequency, expected=expected)
        except Exception as exc:
            return {**context, 'status': 'DATA_INSUFFICIENT', **endpoints,
                    'error': safe_diagnostic(exc, product='jm', stage='endpoints')}, ()
        after = market.contract_source_evidence(
            symbol='jm', contract=contract, frequency=frequency, before=cutoff)
        if before != after:
            return {**context, 'status': 'INPUT_CHANGED_DURING_AUDIT'}, ()
        return {**context, 'status': 'PASS', **endpoints,
                'input_hash': payload_hash([asdict(b) for b in result.bars]),
                'source_hash': payload_hash(before), 'source': before,
                'source_unchanged': True}, result.bars
    except Exception as exc:
        return {**context, 'status': 'DATA_INSUFFICIENT',
                'error': safe_diagnostic(exc, product='jm', stage='physical_input')}, ()


def windows_from_days(rows):
    """Merge adjacent audited trading-day rows only, never across an owner or failure."""
    windows = []
    for row in rows:
        key = (row['contract'], row['status'])
        if windows and tuple(windows[-1]['key']) == key:
            windows[-1]['through'] = row['day']
            windows[-1]['days'] += 1
        else:
            windows.append({'key': key, 'since': row['day'], 'through': row['day'], 'days': 1})
    return _wire(windows)


def daily_readiness(bars):
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    ready = {}
    for bar in bars:
        had_previous = state.previous_dif is not None and state.previous_dea is not None
        state, frame = kernel.step(state, float(bar.close), bar_end=bar.bar_end.isoformat())
        ready[bar.trading_day] = bool(frame.valid and frame.ready and had_previous)
    return ready


def include_session_failures(rows, errors):
    failures = [{**e, 'market': {'session': e['error']}, 'facts': [],
                 'facts_status': 'NOT_EVALUATED_SESSION_ERROR',
                 'daily_kernel_ready': False, 'signal_inputs_verified': False} for e in errors]
    result = sorted([*rows, *failures], key=lambda r: r['day'])
    if len({r['day'] for r in result}) != len(result):
        raise ValueError('DUPLICATE_AUDIT_DAY')
    return result


def run(session, market, *, facts_paths, as_of):
    from sqlalchemy import select
    from app.models.market_tables import MainContractMap
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader

    mappings = session.execute(select(MainContractMap).where(
        MainContractMap.symbol == 'jm', MainContractMap.rank == 1
    ).order_by(MainContractMap.trade_date)).scalars().all()
    if not mappings:
        raise ValueError('MAIN_CONTRACT_MAP_MISSING')
    snapshots, inputs = [], []
    for path in facts_paths:
        raw_bytes = path.read_bytes()
        raw = read_json(path)
        if path.read_bytes() != raw_bytes:
            raise ValueError('FACTS_CHANGED_DURING_READ')
        inputs.append((path, sha256(raw_bytes).hexdigest()))
        snapshots.append({'path': str(path), 'hash': inputs[-1][1],
                          'captured_at': raw.get('captured_at'), 'raw': raw})
    sessions, eligible, excluded, session_errors = {}, [], [], []
    for m in mappings:
        try:
            values = market.session_windows(symbol='jm', trading_day=m.trade_date)
            if not values:
                raise ValueError('TRADING_SESSION_MISSING')
            sessions[m.trade_date] = max(s.end for s in values)
            if sessions[m.trade_date] <= as_of:
                eligible.append(m)
            else:
                excluded.append({'day': m.trade_date.isoformat(), 'reason': 'NOT_COMPLETED'})
        except Exception as exc:
            session_errors.append({'day': m.trade_date.isoformat(), 'contract': m.contract_code,
                'status': 'DATA_INSUFFICIENT',
                'error': safe_diagnostic(exc, product='jm', stage='session')})
    if not eligible:
        raise ValueError('NO_COMPLETED_TRADING_DAY')
    since, through = eligible[0].trade_date, eligible[-1].trade_date
    authority = ActualDominantResearchSegmentLoader(market).owner_segments(
        symbol='jm', since=since, through=through)
    segments, days = [], []
    for owner in authority:
        owned = [m for m in eligible if m.contract_code == owner.contract
                 and owner.start_trading_day <= m.trade_date <= owner.end_trading_day]
        if not owned:
            continue
        start, end = owned[0].trade_date, owned[-1].trade_date
        print(json.dumps({'stage': 'owner', 'contract': owner.contract,
                          'since': str(start), 'through': str(end)}), flush=True)
        by_day = {m.trade_date: {'day': m.trade_date.isoformat(), 'contract': owner.contract,
                                'market': {}, 'facts': []} for m in owned}
        scans = []
        for f in (BarFrequency.D1, BarFrequency.M15, BarFrequency.M1):
            report, bars = audit_series(market, owner.contract, f, start, end, sessions[end])
            scans.append(report)
            if report['status'] == 'PASS':
                for row in by_day.values():
                    row['market'][f.value] = 'PASS'
            else:
                # Preserve full-owner failure and locate every affected exact trading day.
                for d, row in by_day.items():
                    check, _ = audit_series(market, owner.contract, f, d, d, sessions[d])
                    row['market'][f.value] = check
        warm, prefix = audit_series(market, owner.contract, BarFrequency.D1,
                                    None, end, sessions[end])
        ready = {}
        if warm['status'] == 'PASS':
            ready = daily_readiness(prefix)
        for d, row in by_day.items():
            row['daily_kernel_ready'] = ready.get(d, False)
            for snap in snapshots:
                try:
                    validated = execution_day(snap['raw'], owner.contract, d)
                    row['facts'].append({'snapshot_hash': snap['hash'], 'status': 'PASS',
                                         'normalized_hash': payload_hash(validated)})
                except Exception:
                    row['facts'].append({'snapshot_hash': snap['hash'], 'status': 'EXECUTION_FACTS_MISSING'})
            hashes = {x['normalized_hash'] for x in row['facts'] if x['status'] == 'PASS'}
            market_ok = all(v == 'PASS' or isinstance(v, dict) and v['status'] == 'PASS'
                            for v in row['market'].values())
            row['status'] = ('DATA_INSUFFICIENT' if not market_ok or not row['daily_kernel_ready'] else
                             'EXECUTION_FACTS_CONFLICT' if len(hashes) > 1 else
                             'EXECUTION_FACTS_MISSING' if not hashes else 'INPUTS_VERIFIED')
            row['signal_inputs_verified'] = market_ok and row['daily_kernel_ready']
            days.append(row)
        segments.append({'contract': owner.contract, 'since': str(start), 'through': str(end),
                         'scans': scans, 'daily_warmup': warm})
    if len(days) != len(eligible):
        raise ValueError('OWNER_DAY_ACCOUNTING_MISMATCH')
    days = include_session_failures(days, session_errors)
    if len(days) + len(excluded) != len(mappings):
        raise ValueError('MAPPING_DAY_ACCOUNTING_MISMATCH')
    seams = []
    for previous, current in zip(segments, segments[1:]):
        day = datetime.strptime(current['since'], '%Y-%m-%d').date()
        check, _ = audit_series(market, previous['contract'], BarFrequency.M1,
                                day, day, sessions[day])
        facts_available = []
        for snap in snapshots:
            try:
                execution_day(snap['raw'], previous['contract'], day)
                facts_available.append(snap['hash'])
            except Exception:
                pass
        seams.append({'old_contract': previous['contract'], 'new_contract': current['contract'],
            'new_owner_first_day': str(day), 'old_contract_execution': check,
            'old_contract_facts_hashes': facts_available,
            'status': 'OLD_CONTRACT_INPUTS_AVAILABLE' if check['status'] == 'PASS' and facts_available
                      else 'ROLLOVER_EXIT_INPUTS_MISSING'})
    # A later scan must not invalidate an earlier physical-source proof.
    source_scans = [scan for segment in segments
                    for scan in [*segment['scans'], segment['daily_warmup']]]
    source_scans.extend(s['old_contract_execution'] for s in seams)
    for scan in source_scans:
        if scan['status'] == 'PASS':
            cutoff = sessions[datetime.strptime(scan['through'], '%Y-%m-%d').date()]
            final = market.contract_source_evidence(symbol='jm', contract=scan['contract'],
                frequency=BarFrequency(scan['frequency']), before=cutoff)
            if payload_hash(final) != scan['source_hash']:
                raise ValueError('SOURCE_CHANGED_DURING_FULL_AUDIT')
    unchanged = all(sha256(path.read_bytes()).hexdigest() == digest for path, digest in inputs)
    if not unchanged:
        raise ValueError('FACTS_CHANGED_DURING_AUDIT')
    return {'schema_version': 1, 'kind': 'PHASE_A_INPUT_AUDIT_NOT_BACKTEST',
        'as_of': as_of.isoformat(), 'since': str(since), 'through': str(through),
        'mapping_hash': payload_hash([(m.trade_date, m.contract_code) for m in mappings]),
        'mapped_days': len(mappings), 'audited_days': len(days),
        'excluded_incomplete_days': excluded, 'session_errors': session_errors,
        'snapshots': [{k: v for k, v in s.items() if k != 'raw'} for s in snapshots],
        'facts_unchanged': unchanged, 'physical_sources_unchanged_at_end': True,
        'segments': segments, 'days': days, 'rollover_seams': seams,
        'status_counts': dict(Counter(r['status'] for r in days)),
        'windows': windows_from_days(days), 'provider_calls': 0, 'data_mutations': 0,
        'account_simulation_run': False, 'retrospective_execution_facts': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    from dotenv import load_dotenv
    load_dotenv(root / '.env', override=False)
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service

    target = safe_path(args.output)
    if not target.is_relative_to(root / 'output'):
        raise ValueError('OUTPUT_OUTSIDE_RESEARCH_ROOT')
    paths = [safe_path(p) for p in args.facts]
    as_of = datetime.now(UTC)
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
        report = run(session, build_market_data_service(session), facts_paths=paths, as_of=as_of)
    report['code_revision'] = subprocess.run(['git', 'rev-parse', 'HEAD'],
        check=True, capture_output=True, text=True).stdout.strip()
    report['audit_script_hash'] = sha256(Path(__file__).read_bytes()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ('since', 'through', 'audited_days', 'status_counts')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'AUDIT_FAILED',
            'error': safe_diagnostic(exc, product='jm', stage='preflight')}))
        raise SystemExit(2) from None
