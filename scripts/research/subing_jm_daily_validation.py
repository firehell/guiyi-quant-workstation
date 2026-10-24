"""Stage D: frozen-model causal checks on exposed local history, never OOS promotion."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from guiyi_quant.subing_jm_daily import DailyModel, daily_frames, digest
from scripts.research.newow_futures_execution_facts import read_json, safe_path

EXPOSED_THROUGH = date(2026, 10, 22)
CORE_KEYS = ('summary', 'position', 'pending', 'decisions', 'fills', 'trades', 'equity_curve')


def exposure_status(day):
    return 'EXPOSED_HISTORY' if date.fromisoformat(day) <= EXPOSED_THROUGH else 'FUTURE_ELIGIBLE_NOT_VALIDATED'


def validate_daily(bars, *, compute=daily_frames):
    """Recompute actual physical prefixes and alter only their later OHLC inputs."""
    bars = tuple(bars)
    full = compute(bars)
    cuts = sorted({min(len(bars), n) for n in (1, 21, 34, 35, len(bars)//2, len(bars)) if n > 0})
    perturbed = 0
    for n in cuts:
        if compute(bars[:n]) != full[:n]:
            raise ValueError('JM_DAILY_PREFIX_FAILED')
        if n < len(bars):
            future = tuple(replace(b, open=b.open*2, high=b.high*2,
                                   low=b.low*2, close=b.close*2) for b in bars[n:])
            if compute(bars[:n]+future)[:n] != full[:n]:
                raise ValueError('JM_DAILY_FUTURE_LEAK_FAILED')
            perturbed += 1
    return {'bars': len(bars), 'prefix_checks': len(cuts), 'future_perturbation_checks': perturbed}


def _state(model):
    if model.status == 'ROLLOVER_INTERRUPTED':
        return 'ROLLOVER_INTERRUPTED'
    if model.pending:
        return 'PENDING_'+model.pending.action
    if model.position:
        return 'POSITION_OPEN'
    return 'FLAT_AFTER_CLOSE' if model.trades else 'FLAT'


def _replay(events, factory):
    model = factory(len(events))
    for e in events:
        model.apply(e)
        if model.status == 'ROLLOVER_INTERRUPTED':
            break
    return model


def validate_account(events, *, expected=None, factory=lambda size: DailyModel()):
    """No new account reset at a chronological split; each physical owner stays independent."""
    events = tuple(events)
    if not events:
        raise ValueError('JM_VALIDATION_EMPTY_ACCOUNT')
    model = factory(len(events))
    cuts, states = {}, set()
    fixed = {1, max(1, len(events)//2), len(events)}
    processed = 0
    for n, e in enumerate(events, 1):
        model.apply(e)
        processed = n
        state = _state(model)
        if state not in states or n in fixed:
            cuts[n] = digest(model.result())
            states.add(state)
        if model.status == 'ROLLOVER_INTERRUPTED':
            break
    cuts[processed] = digest(model.result())
    result = model.result()
    if expected is not None and any(result[k] != expected[k] for k in CORE_KEYS):
        raise ValueError('JM_FROZEN_RESULT_MISMATCH')
    # Fresh prefix construction deliberately receives the shorter batch length.
    # Negative-control tests prove a batch-size-dependent future leak is caught.
    for n, expected_hash in cuts.items():
        if digest(_replay(events[:n], factory).result()) != expected_hash:
            raise ValueError('JM_ACCOUNT_PREFIX_FAILED')
    stream, restores, duplicates = factory(len(events)), 0, 0
    for n, e in enumerate(events[:processed], 1):
        stream.apply(e)
        if n in cuts:
            if digest(stream.result()) != cuts[n]:
                raise ValueError('JM_INCREMENTAL_PARITY_FAILED')
            before = stream.checkpoint()
            stream.apply(e)
            if stream.checkpoint() != before:
                raise ValueError('JM_DUPLICATE_PARITY_FAILED')
            duplicates += 1
            stream = type(stream).restore(json.loads(json.dumps(before)))
            if stream.checkpoint() != before or digest(stream.result()) != cuts[n]:
                raise ValueError('JM_RESTART_PARITY_FAILED')
            stream.apply(e)
            if stream.checkpoint() != before:
                raise ValueError('JM_RESTART_DUPLICATE_PARITY_FAILED')
            restores += 1
    if stream.result() != result:
        raise ValueError('JM_RESTART_SUFFIX_PARITY_FAILED')
    return {'processed_events': processed, 'prefix_checks': len(cuts), 'restart_checks': restores,
            'duplicate_checks': duplicates, 'states_checked': sorted(states),
            'final_hash': digest(result), 'result': result}


def validate_fills(events, result):
    bars = {(e.bar.physical_contract, e.bar.confirmed_at.isoformat()): e
            for e in events if e.kind == '1m'}
    for f in result['fills']:
        e = bars.get((f['contract'], f['recorded_at']))
        if e is None:
            raise ValueError('JM_FILL_SOURCE_MISSING')
        b, facts = e.bar, e.facts
        start = b.bar_end-timedelta(minutes=1)
        direction = f['side'] if f['action'] == 'OPEN' else -f['side']
        price = b.open+direction*facts.tick_size
        if (not start > datetime.fromisoformat(f['decision_at']) or
                start != datetime.fromisoformat(f['fill_at']) or D(f['price']) != price or
                f['qty'] != 1 or b.volume <= 0 or price % facts.tick_size != 0 or
                not facts.limit_down <= price <= facts.limit_up or
                f['trading_day'] != b.trading_day.isoformat()):
            raise ValueError('JM_FILL_CAUSALITY_FAILED')
    return len(result['fills'])


def load_daily_checks(market, source):
    """Read the same MDS-selected full physical D1 prefix, including warm-up."""
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.new_subing_research import validate_series
    rows = []
    eligible = {(e.bar.physical_contract, e.bar.bar_end): e for e in source.events if e.kind == '1d'}
    for s in source.sources:
        if s['frequency'] != '1d':
            continue
        day = date.fromisoformat(s['through'])
        cutoff = max(w.end for w in market.session_windows(symbol='jm', trading_day=day))
        def unchanged():
            evidence = market.contract_source_evidence(symbol='jm', contract=s['contract'],
                frequency=BarFrequency.D1, before=cutoff)
            if digest(evidence) != s['source_hash']:
                raise ValueError('JM_DAILY_VALIDATION_SOURCE_CHANGED')
        unchanged()
        expected = market.expected_contract_replay_endpoints(symbol='jm', contract=s['contract'],
            frequency=BarFrequency.D1, trading_day=day, cutoff=cutoff, since=None)
        series = market.query_contract_trading_days(ContractTradingDayQuery(
            'jm', s['contract'], BarFrequency.D1, expected[0][1], day))
        validate_series(series, product='jm', contract=s['contract'], frequency=BarFrequency.D1, expected=expected)
        # Bar payloads came through MDS validation above. Reuse the existing B
        # adapter's StrategyBar identity/Session construction for exact parity.
        from dataclasses import asdict
        from guiyi_quant.new_subing import StrategyBar
        frames = []
        for b in series.bars:
            windows = market.session_windows(symbol='jm', trading_day=b.trading_day)
            session = next(w for w in windows if w.start < b.bar_end <= w.end)
            frames.append(StrategyBar(product='jm', physical_contract=s['contract'], frequency='1d',
                source_identity='validation:'+digest(asdict(b)), confirmed_at=b.bar_end,
                session_open_at=session.start, session_close_at=max(w.end for w in windows),
                **{k: v for k, v in asdict(b).items() if k != 'turnover'}))
        actual = daily_frames(frames)
        matched = 0
        for f in actual:
            original = eligible.get((s['contract'], f.bar.bar_end))
            if original:
                if (f.ema, f.cross) != (original.ema, original.cross):
                    raise ValueError('JM_DAILY_PHYSICAL_PREFIX_PARITY_FAILED')
                matched += 1
        rows.append({'contract': s['contract'], **validate_daily(frames), 'eligible_daily_parity': matched})
        unchanged()
    if sum(r['eligible_daily_parity'] for r in rows) != 489:
        raise ValueError('JM_DAILY_VALIDATION_MEMBERSHIP_FAILED')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project-env', 'phase-a', 'phase-c', 'facts', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    for p in vars(args).values():
        safe_path(p)
    if args.output.exists() or not args.output.is_relative_to(args.phase_a.parent):
        raise ValueError('JM_VALIDATION_OUTPUT_INVALID')
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in (args.phase_a, args.phase_c, args.facts)}
    phase_a, phase_c, facts = (read_json(p) for p in (args.phase_a, args.phase_c, args.facts))
    if phase_c['result_hash'] != digest({k: v for k, v in phase_c.items() if k != 'result_hash'}):
        raise ValueError('JM_PHASE_C_HASH_INVALID')
    for p, h in phase_c['metadata']['input_file_hashes'].items():
        if sha256(Path(p).read_bytes()).hexdigest() != h:
            raise ValueError('JM_PHASE_C_INPUT_CHANGED')
    root = Path(__file__).resolve().parents[2]
    for p, h in phase_c['metadata']['code_hashes'].items():
        if sha256((root/p).read_bytes()).hexdigest() != h:
            raise ValueError('JM_FROZEN_CODE_CHANGED')
    if before[str(args.phase_a)] != phase_c['metadata']['input_file_hashes'].get(str(args.phase_a)) or before[str(args.facts)] != phase_c['metadata']['input_file_hashes'].get(str(args.facts)):
        raise ValueError('JM_VALIDATION_INPUT_NOT_FROZEN')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.subing_jm_daily import load_inputs
    from app.private_settings import load_private_readonly_settings
    settings, _ = load_private_readonly_settings(args.project_env)
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), connect_args={'connect_timeout': 5})
    try:
        with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=900):
            data_root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            market = MarketDataService(MarketCatalog(session, data_root), CanonicalMonthlyStore(data_root))
            source = load_inputs(market, facts, phase_a=phase_a)
            def selected(ss):
                return [(s['contract'], s['frequency'], s['bar_hash']) for s in ss]
            if selected(source.sources) != selected(phase_c['metadata']['source_hashes']) or source.facts_hash != phase_c['metadata']['facts_hash']:
                raise ValueError('JM_VALIDATION_NUMERICAL_INPUT_CHANGED')
            daily = load_daily_checks(market, source)
    finally:
        engine.dispose()
    baseline = phase_c['scenarios'][0]
    if baseline['scenario'] != 'baseline':
        raise ValueError('JM_VALIDATION_BASELINE_MISSING')
    continuous = validate_account(source.events, expected=baseline['continuous_account'])
    validate_fills(source.events, continuous['result'])
    owners = []
    for old in baseline['independent_owners']:
        events = tuple(e for e in source.events if e.bar.physical_contract == old['contract'])
        value = validate_account(events, expected=old['result'])
        value['fills_verified'] = validate_fills(events, value['result'])
        # Keep full diagnostic account results in C; D records their exact hash.
        value.pop('result')
        owners.append({'contract': old['contract'], 'not_continuous_account': True, **value})
        print(json.dumps({'contract': old['contract'], 'prefix_checks': value['prefix_checks'], 'status': 'PASS'}), flush=True)
    continuous.pop('result')
    if any(sha256(Path(p).read_bytes()).hexdigest() != h for p, h in before.items()):
        raise ValueError('JM_VALIDATION_INPUT_CHANGED_DURING_RUN')
    code = ['scripts/research/subing_jm_daily_validation.py', *phase_c['metadata']['code_hashes']]
    report = {'kind': 'PHASE_D_EXPOSED_HISTORY_CAUSAL_VALIDATION_NOT_OOS',
        'continuous_account': continuous, 'independent_owners': owners, 'physical_daily_checks': daily,
        'all_engineering_checks_passed': True, 'oos_status': 'OOS_NOT_PROVEN',
        'parameter_stability': 'NOT_ESTABLISHED_NO_PARAMETER_SEARCH',
        'prospective_boundary': {'exposed_through': str(EXPOSED_THROUGH), 'first_eligible_trading_day_after': str(EXPOSED_THROUGH),
            'requires_new_completed_local_inputs_and_fact_audit': True, 'automatic_resume_after_rollover': False,
            'automatic_collection_or_execution': False},
        'metadata': {'code_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
            capture_output=True, text=True).stdout.strip(), 'input_file_hashes': before,
            'code_hashes': {p: sha256((root/p).read_bytes()).hexdigest() for p in code},
            'input_hash': source.input_hash, 'facts_hash': source.facts_hash,
            'selected_bar_identity_matches_phase_c': True, 'provider_calls': 0, 'data_mutations': 0,
            'auto_order': False, 'continuous_paper': False}}
    report['result_hash'] = digest(report)
    with args.output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from app.market_data.new_subing_research import safe_diagnostic
        print(json.dumps({'status': 'VALIDATION_FAILED', 'error': safe_diagnostic(exc, product='jm', stage='phase_d')}))
        raise SystemExit(2) from None
