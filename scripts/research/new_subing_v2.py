"""Frozen V1-matched input replay for V2; 100k main and 1m diagnostic accounts."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
from typing import Any, cast

from app.market_data.new_subing_research import (
    NewSubingInputError, PRODUCTS, SINCE, THROUGH, load_execution_facts,
    load_new_subing_inputs, safe_diagnostic,
)
from app.new_subing_research.store import list_results, read_result
from guiyi_quant.new_subing_v2 import Profile, prepare_research, run_research
from scripts.research.new_subing import DIAGNOSTIC_WINDOWS, read_facts

CAPITALS = (Decimal('100000'), Decimal('1000000'))
SCENARIOS = ('baseline', 'double_commission', 'double_slippage')


def reference_hashes(root: Path) -> dict[str, tuple[str, str]]:
    """Only indexed, content-verified completed V1 baseline results are references."""
    hashes: dict[str, tuple[str, str]] = {}
    for meta in list_results(root):
        if meta['strategy_code'] != 'new_subing_v1' or meta['scenario'] != 'baseline':
            continue
        packet = read_result(root, meta['run_id'])
        if (meta['status'] != 'COMPLETED' or meta['requested_since'] != SINCE.isoformat()
                or meta['requested_through'] != THROUGH.isoformat()
                or packet['summary'].get('initial_cash') != '100000'):
            raise NewSubingInputError('REFERENCE_IDENTITY_MISMATCH')
        product = meta['product'].lower()
        if product in hashes:
            raise NewSubingInputError('REFERENCE_IDENTITY_AMBIGUOUS')
        hashes[product] = (meta['input_snapshot_hash'], meta['execution_facts_hash'])
    if set(hashes) != set(PRODUCTS):
        raise NewSubingInputError('REFERENCE_INCOMPLETE')
    return hashes


def build_packet(*, product: str, scenario: str, profile: Profile, code_revision: str,
                 status: str, source=None, facts_hash: str | None = None,
                 result: dict | None = None, diagnostic: dict | None = None) -> dict:
    result = result or {'summary': {'status': status, 'initial_cash': str(profile.initial_cash)},
                       'decisions': [], 'trades': [], 'equity': [], 'diagnostics': {}}
    diagnostics = {**result.get('diagnostics', {}),
                   **(dict(source.diagnostics) if source else {}),
                   'case_parity': 'PENDING', 'original_case_fixture': False,
                   'oos_status': 'NOT_PROVEN', 'independent_account_per_window': True,
                   'capital_role': 'main' if profile.initial_cash == CAPITALS[0] else 'diagnostic'}
    if diagnostic:
        diagnostics['gap'] = diagnostic
    return {'schema_version': 1, 'metadata': {
        'product': product.upper(), 'scenario': scenario, 'status': status,
        'strategy_code': profile.strategy_code, 'formula_version': profile.formula_version,
        'profile_id': profile.profile_id, 'initial_cash': str(profile.initial_cash),
        'risk_profile_version': profile.risk_profile_version,
        'execution_profile_version': profile.execution_profile_version,
        'account_model_version': profile.account_model_version, 'code_revision': code_revision,
        'requested_since': SINCE.isoformat(), 'requested_through': THROUGH.isoformat(),
        'input_snapshot_hash': source.input_snapshot_hash if source else None,
        'execution_facts_hash': facts_hash, 'source': 'historical_replay', 'auto_order': False,
        'case_parity': 'PENDING', 'oos_status': 'NOT_PROVEN'},
        'summary': result['summary'], 'decisions': result.get('decisions', []),
        'trades': result.get('trades', []), 'equity': result.get('equity', []),
        'fills': result.get('fills', []), 'diagnostics': diagnostics,
        'stages': result.get('stages', []), 'layers': result.get('layers', []),
        'projection': result.get('projection', {})}


def progress(**values: Any) -> None:
    print(json.dumps(values, ensure_ascii=False), flush=True)


def run_source(source, executions, *, facts_hash: str, code_revision: str) -> list[dict]:
    """Prepare once; each capital/scenario/window starts an independent account."""
    progress(product=source.product, stage='prepare')
    prepared = prepare_research(source.bars_by_frequency, Profile())
    packets = []
    for cash in CAPITALS:
        profile = Profile(initial_cash=cash)
        for scenario in SCENARIOS:
            progress(product=source.product, cash=str(cash), scenario=scenario, window='full', stage='start')
            result = cast(dict[str, Any], run_research(source.bars_by_frequency, executions, profile=profile,
                                  scenario=scenario, since=SINCE, through=THROUGH, prepared=prepared))
            windows = []
            for name, since, through in DIAGNOSTIC_WINDOWS:
                progress(product=source.product, cash=str(cash), scenario=scenario, window=name, stage='start')
                selected = tuple(b for b in executions if since <= b.bar.trading_day <= through)
                diagnostic = run_research(source.bars_by_frequency, selected, profile=profile,
                                          scenario=scenario, since=since, through=through, prepared=prepared)
                windows.append({'name': name, 'since': since.isoformat(), 'through': through.isoformat(),
                                'input_snapshot_hash': source.input_snapshot_hash,
                                'summary': diagnostic['summary'], 'independent_initial_cash': str(cash),
                                'oos_status': 'NOT_PROVEN'})
                progress(product=source.product, cash=str(cash), scenario=scenario, window=name,
                         stage='end', summary=diagnostic['summary'])
            result.setdefault('diagnostics', {})['independent_windows'] = windows
            packets.append(build_packet(product=source.product, scenario=scenario, profile=profile,
                                        code_revision=code_revision, status=result['summary']['status'],
                                        source=source, facts_hash=facts_hash, result=result))
    return packets


def verify_inputs(source, facts_hash: str, expected: tuple[str, str]) -> None:
    if source.input_snapshot_hash != expected[0]:
        raise NewSubingInputError('COMPARISON_INPUT_HASH_MISMATCH')
    if facts_hash != expected[1]:
        raise NewSubingInputError('COMPARISON_FACTS_HASH_MISMATCH')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', nargs='+', choices=PRODUCTS, default=list(PRODUCTS))
    parser.add_argument('--project-env', type=Path, required=True)
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if len(args.symbols) != len(set(args.symbols)) or not args.out.is_absolute():
        parser.error('exact unique symbols and absolute task output root required')
    expected = reference_hashes(args.reference_root)
    if args.out.exists():
        raise NewSubingInputError('OUTPUT_ATTEMPT_EXISTS')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.new_subing_research.store import publish_result
    from app.private_settings import load_private_readonly_settings

    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    changed = subprocess.run(['git', '-c', 'core.fsmonitor=false', 'status', '--porcelain', '--',
                              'packages/quant-core/guiyi_quant/new_subing',
                              'packages/quant-core/guiyi_quant/new_subing_v2',
                              'services/quant-api/app/market_data/new_subing_research.py',
                              'services/quant-api/app/new_subing_research/store.py',
                              'scripts/research/new_subing_v2.py'],
                             check=True, capture_output=True, text=True).stdout
    if changed.strip():
        raise NewSubingInputError('CODE_IDENTITY_UNCOMMITTED')
    settings, _ = load_private_readonly_settings(args.project_env)
    canonical = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), connect_args={'connect_timeout': 5})
    statuses = []
    try:
        for product in args.symbols:
            source = None
            try:
                progress(product=product, stage='readonly_input')
                with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=900):
                    market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
                    source = load_new_subing_inputs(market, product=product)
                executions, facts_hash = load_execution_facts(read_facts(args.facts_dir / f'{product}.json'),
                                                              product=product, bars=source.minute_bars)
                verify_inputs(source, facts_hash, expected[product])
                progress(product=product, stage='input_verified', input_snapshot_hash=source.input_snapshot_hash,
                         execution_facts_hash=facts_hash)
                packets = run_source(source, executions, facts_hash=facts_hash, code_revision=revision)
            except NewSubingInputError as exc:
                status = 'EXECUTION_FACTS_MISSING' if exc.code == 'EXECUTION_FACTS_MISSING' else 'DATA_INSUFFICIENT'
                packets = [build_packet(product=product, scenario='baseline', profile=Profile(initial_cash=cash),
                                        code_revision=revision, status=status, source=source,
                                        diagnostic={'code': exc.code, **exc.diagnostic}) for cash in CAPITALS]
            except Exception as exc:
                packets = [build_packet(product=product, scenario='baseline', profile=Profile(initial_cash=cash),
                                        code_revision=revision, status='DATA_INSUFFICIENT', source=source,
                                        diagnostic=safe_diagnostic(exc, product=product, stage='readonly_replay'))
                           for cash in CAPITALS]
            for packet in packets:
                frozen = publish_result(args.out, packet)
                meta = frozen['metadata']
                statuses.append(meta['status'])
                progress(product=meta['product'], cash=meta['initial_cash'], scenario=meta['scenario'],
                         status=meta['status'], run_id=meta['run_id'], gap=frozen['diagnostics'].get('gap'))
    finally:
        engine.dispose()
    return 0 if statuses and all(s in ('COMPLETED', 'ROLLOVER_INTERRUPTED') for s in statuses) else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}', code):
            code = 'NEW_SUBING_V2_RESEARCH_FAILED'
        progress(status='BLOCKED', code=code)
        raise SystemExit(1) from None
