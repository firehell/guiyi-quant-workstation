"""One offline engineering replay of the phase-A verified JM window, no promotion."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from scripts.research.newow_futures_execution_facts import read_json, safe_path
from guiyi_quant.subing_jm_daily import DailyModel, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-env', type=Path, required=True)
    parser.add_argument('--phase-a', type=Path, required=True)
    parser.add_argument('--facts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for path in (args.project_env, args.phase_a, args.facts, args.output):
        safe_path(path)
    if not args.output.is_relative_to(args.phase_a.parent) or args.output.exists() or args.output.suffix != '.json':
        raise ValueError('JM_OUTPUT_INVALID')
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in (args.phase_a, args.facts)}
    phase_a, facts = read_json(args.phase_a), read_json(args.facts)
    if any(sha256(Path(p).read_bytes()).hexdigest() != h for p, h in before.items()):
        raise ValueError('JM_INPUT_CHANGED_DURING_READ')
    if before[str(args.facts)] not in {s['hash'] for s in phase_a['snapshots']}:
        raise ValueError('JM_FACTS_NOT_PHASE_A_VERIFIED')
    if phase_a['kind'] != 'PHASE_A_INPUT_AUDIT_NOT_BACKTEST':
        raise ValueError('JM_PHASE_A_IDENTITY_INVALID')
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
            market = MarketDataService(MarketCatalog(session, Path(settings['GUIYI_CANONICAL_DATA_ROOT'])),
                                       CanonicalMonthlyStore(Path(settings['GUIYI_CANONICAL_DATA_ROOT'])))
            source = load_inputs(market, facts, phase_a=phase_a)
    finally:
        engine.dispose()
    print(json.dumps({'stage': 'INPUTS_LOADED', 'events': len(source.events), 'input_hash': source.input_hash}), flush=True)
    model = DailyModel()
    processed = 0
    for event in source.events:
        model.apply(event)
        processed += 1
        if model.status == 'ROLLOVER_INTERRUPTED':
            break
    result = model.result()
    checkpoint = model.checkpoint()
    if DailyModel.restore(checkpoint).result() != result:
        raise ValueError('JM_RESTART_PARITY_FAILED')
    diagnostics = []
    for contract in dict.fromkeys(e.bar.physical_contract for e in source.events):
        independent = DailyModel()
        resumed = None
        owner_events = tuple(e for e in source.events if e.bar.physical_contract == contract)
        for i, event in enumerate(owner_events):
            independent.apply(event)
            if resumed is not None:
                resumed.apply(event)
            elif independent.pending or i == len(owner_events)//2:
                resumed = DailyModel.restore(independent.checkpoint())
        independent.reconcile()
        value = independent.result()
        if resumed is None or resumed.result() != value:
            raise ValueError('JM_OWNER_RESTART_PARITY_FAILED')
        diagnostics.append({'contract': contract, 'independent_initial_cash': '100000',
            'not_continuous_account': True, 'restart_parity': True,
            'summary': value['summary'], 'fills': value['fills'],
            'trades': value['trades'], 'position': value['position'], 'pending': value['pending'],
            'decisions': value['decisions']})
    result['owner_engineering_diagnostics'] = diagnostics
    if any(sha256(Path(p).read_bytes()).hexdigest() != h for p, h in before.items()):
        raise ValueError('JM_FROZEN_INPUT_CHANGED')
    root = Path(__file__).resolve().parents[2]
    code_paths = ['packages/quant-core/guiyi_quant/subing_jm_daily.py',
        'services/quant-api/app/market_data/subing_jm_daily.py', 'scripts/research/subing_jm_daily.py',
        'services/quant-api/app/private_settings.py']
    result['metadata'] = {'kind': 'PHASE_B_OFFLINE_ENGINEERING_REPLAY_NOT_OOS',
        'requested_since': '2024-10-14', 'requested_through': '2026-10-19',
        'input_hash': source.input_hash, 'facts_hash': source.facts_hash, 'input_file_hashes': before,
        'source_hashes': source.sources, 'processed_events': processed, 'input_events': len(source.events),
        'checkpoint_hash': checkpoint['hash'], 'restart_parity': True, 'input_files_unchanged': True,
        'time_model': 'retrospective_completed_bar_reconstruction',
        'code_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
            check=True, capture_output=True, text=True).stdout.strip(),
        'code_hashes': {p: sha256((root/p).read_bytes()).hexdigest() for p in code_paths},
        'provider_calls': 0, 'data_mutations': 0}
    result['result_hash'] = digest(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
    print(json.dumps(result['summary'], ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from app.market_data.new_subing_research import safe_diagnostic
        print(json.dumps({'status': 'OFFLINE_REPLAY_FAILED',
            'error': safe_diagnostic(exc, product='jm', stage='phase_b')}))
        raise SystemExit(2) from None
