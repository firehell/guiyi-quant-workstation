"""Frozen cost-only JM diagnostics. Separate accounts; no optimization or promotion."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Context, Decimal as D, localcontext
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from guiyi_quant.subing_jm_daily import DailyModel, VERSIONS, entry_risk, wire, digest
from scripts.research.newow_futures_execution_facts import read_json, safe_path

SCENARIOS = ('baseline', 'double_commission', 'double_slippage')


class ResearchModel(DailyModel):
    scenario = 'baseline'

    def __init__(self):
        super().__init__()
        self.risk_checks = []
        self.signal_events = []

    def _apply(self, event):
        identity = digest([event.kind, event.bar.source_identity])
        existed = identity in self.seen
        held = self.position.side if self.position else 0
        pending = self.pending.action if self.pending else None
        super()._apply(event)
        if not existed and identity in self.seen and event.kind == '1d' and event.cross:
            self.signal_events.append(wire({'at': event.bar.confirmed_at, 'side': event.cross,
                'contract': event.bar.physical_contract, 'close': event.bar.close, 'ema': event.ema,
                'holding_before': held, 'pending_before': pending}))

    def _risk_reason(self, side, price, stop, facts):
        detail = entry_risk(side, price, stop, facts, self.equity, slippage_ticks=self.slippage_ticks)
        self.risk_checks.append(wire({**detail, 'at': self.last_clock[0], 'side': side,
            'contract': facts.physical_contract, 'stage': 'SIGNAL' if self.last_clock[1] == 1 else 'FILL'}))
        return detail['reason']

    @classmethod
    def cost_profile(cls):
        return {'cost_profile_version': f'subing_jm_d1_cost_{cls.scenario}_v1',
                'scenario': cls.scenario, 'fee_multiplier': 2 if cls.scenario == 'double_commission' else 1,
                'slippage_ticks_per_fill': cls.slippage_ticks, 'model_assumption': True}

    def checkpoint(self):
        packet = super().checkpoint()
        packet['cost_profile'] = self.cost_profile()
        packet['versions'] = {**packet['versions'], 'cost_profile_version': self.cost_profile()['cost_profile_version']}
        return packet

    @classmethod
    def restore(cls, packet):
        expected = {**VERSIONS, 'cost_profile_version': cls.cost_profile()['cost_profile_version']}
        if packet.get('cost_profile') != cls.cost_profile() or packet.get('versions') != expected:
            raise ValueError('JM_COST_CHECKPOINT_MISMATCH')
        return super().restore({**packet, 'versions': dict(VERSIONS)})

    def result(self):
        result = super().result()
        result.update(cost_profile=self.cost_profile(), risk_checks=wire(self.risk_checks),
                      signal_events=wire(self.signal_events))
        return result


class DoubleCommissionModel(ResearchModel):
    scenario = 'double_commission'


class DoubleSlippageModel(ResearchModel):
    scenario = 'double_slippage'
    slippage_ticks = 2


def make_model(scenario):
    if scenario not in SCENARIOS:
        raise ValueError('JM_COST_PROFILE_INVALID')
    return {'baseline': ResearchModel, 'double_commission': DoubleCommissionModel,
            'double_slippage': DoubleSlippageModel}[scenario]()


@lru_cache(maxsize=2048)
def doubled_facts(facts):
    fees = facts.fees
    keys = ('open_rate', 'open_per_contract', 'close_rate', 'close_per_contract',
            'close_today_rate', 'close_today_per_contract')
    with localcontext(Context(prec=28)):
        fees = replace(fees, **{k: getattr(fees, k)*2 for k in keys},
                       source_id=digest(['double_commission_model', fees.source_id]))
    return replace(facts, fees=fees, source_id=digest(['double_commission_model', facts.source_id]))


def cost_event(event, scenario):
    if scenario not in SCENARIOS:
        raise ValueError('JM_COST_PROFILE_INVALID')
    if scenario == 'double_commission' and event.facts is not None:
        return replace(event, facts=doubled_facts(event.facts))
    return event


def run_account(events, scenario):
    model = make_model(scenario)
    resumed = None
    for i, raw in enumerate(events):
        event = cost_event(raw, scenario)
        model.apply(event)
        if resumed is not None:
            resumed.apply(event)
        elif model.pending or i == len(events)//2:
            resumed = type(model).restore(model.checkpoint())
        if model.status == 'ROLLOVER_INTERRUPTED':
            break
    result = model.result()
    mode = 'in_stream' if resumed is not None else 'terminal_checkpoint_only'
    if resumed is None:
        resumed = type(model).restore(model.checkpoint())
    if result != resumed.result():
        raise ValueError('JM_COST_RESTART_PARITY_FAILED')
    result['processed_events'] = i+1 if events else 0
    result['restart_parity'] = True
    result['restart_validation_mode'] = mode
    return result


def analyze(result):
    """Descriptive arithmetic only; exit groups are not causal attribution."""
    signals = [r for r in result['risk_checks'] if r['stage'] == 'SIGNAL']
    rejected = [r for r in signals if r['reason']]
    fills = [r for r in result['risk_checks'] if r['stage'] == 'FILL']
    fill_rejected = [r for r in fills if r['reason']]
    trades = result['trades']
    return wire({'signal_admission_checks': len(signals), 'signal_rejections': len(rejected),
        'observed_macd_ema_crosses': len(result['signal_events']),
        'crosses_while_holding': sum(r['holding_before'] != 0 for r in result['signal_events']),
        'fill_admission_checks': len(fills), 'fill_rejections': len(fill_rejected),
        'fill_rejections_by_reason': dict(Counter(r['reason'] for r in fill_rejected)),
        'rejections_by_reason': dict(Counter(r['reason'] for r in rejected)),
        'risk_rejected_checks': rejected, 'exit_reason_counts': dict(Counter(t['reason'] for t in trades)),
        'closed_trade_count': len(trades), 'winning_closed_trades': sum(D(t['net_pnl']) > 0 for t in trades),
        'closed_trade_details': [{**t, 'holding_seconds': int((datetime.fromisoformat(t['exit_at'])-
            datetime.fromisoformat(t['entry_at'])).total_seconds())} for t in trades],
        'complete_account_return_eligible': result['summary']['status'] == 'COMPLETED',
        'causal_attribution_proven': False, 'inference_scope': 'historical_descriptive_only'})


def assert_baseline(result, phase_b):
    for key in ('summary', 'fills', 'trades', 'decisions', 'position', 'pending', 'equity_curve'):
        if result[key] != phase_b[key]:
            raise ValueError('JM_PHASE_B_BASELINE_PARITY_FAILED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project-env', 'phase-a', 'phase-b', 'facts', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    for path in vars(args).values():
        safe_path(path)
    if not args.output.is_relative_to(args.phase_a.parent) or args.output.exists():
        raise ValueError('JM_COST_OUTPUT_INVALID')
    paths = (args.phase_a, args.phase_b, args.facts)
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in paths}
    phase_a, phase_b, facts = (read_json(p) for p in paths)
    if phase_b.get('result_hash') != digest({k: v for k, v in phase_b.items() if k != 'result_hash'}):
        raise ValueError('JM_PHASE_B_HASH_INVALID')
    if any(sha256(Path(p).read_bytes()).hexdigest() != h for p, h in before.items()):
        raise ValueError('JM_COST_SOURCE_CHANGED')
    if before[str(args.facts)] not in {s['hash'] for s in phase_a['snapshots']}:
        raise ValueError('JM_COST_FACTS_NOT_FROZEN')
    if any(before.get(p) != h for p, h in phase_b['metadata']['input_file_hashes'].items()):
        raise ValueError('JM_PHASE_B_INPUT_IDENTITY_CHANGED')
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
            root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            source = load_inputs(MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root)),
                                 facts, phase_a=phase_a)
    finally:
        engine.dispose()
    def selected(sources):
        return [(s['contract'], s['frequency'], s['bar_hash']) for s in sources]
    if selected(source.sources) != selected(phase_b['metadata']['source_hashes']) or source.facts_hash != phase_b['metadata']['facts_hash']:
        raise ValueError('JM_PHASE_B_NUMERICAL_INPUT_CHANGED')
    owners = {c: tuple(e for e in source.events if e.bar.physical_contract == c)
              for c in dict.fromkeys(e.bar.physical_contract for e in source.events)}
    packets = []
    for scenario in SCENARIOS:
        continuous = run_account(source.events, scenario)
        groups = []
        for contract, events in owners.items():
            value = run_account(events, scenario)
            if scenario == 'baseline':
                old = next(g for g in phase_b['owner_engineering_diagnostics'] if g['contract'] == contract)
                for key in ('summary', 'fills', 'trades', 'decisions', 'position', 'pending'):
                    if value[key] != old[key]:
                        raise ValueError('JM_OWNER_BASELINE_PARITY_FAILED')
            groups.append({'contract': contract, 'not_continuous_account': True,
                           'initial_cash': '100000', 'analysis': analyze(value), 'result': value})
        if scenario == 'baseline':
            assert_baseline(continuous, phase_b)
        packets.append({'scenario': scenario, 'continuous_account': continuous,
                        'continuous_analysis': analyze(continuous), 'independent_owners': groups})
        print(json.dumps({'scenario': scenario, 'continuous_status': continuous['summary']['status'],
                          'owner_trade_counts': [len(g['result']['trades']) for g in groups]}), flush=True)
    if any(sha256(Path(p).read_bytes()).hexdigest() != h for p, h in before.items()):
        raise ValueError('JM_COST_SOURCE_CHANGED')
    root = Path(__file__).resolve().parents[2]
    code = ('packages/quant-core/guiyi_quant/subing_jm_daily.py',
            'services/quant-api/app/market_data/subing_jm_daily.py',
            'scripts/research/subing_jm_daily_stress.py', 'services/quant-api/app/private_settings.py')
    output = {'kind': 'PHASE_C_FROZEN_COST_STRESS_NOT_OOS', 'scenarios': packets,
        'metadata': {'requested_since': '2024-10-14', 'requested_through': '2026-10-19',
            'code_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                capture_output=True, text=True).stdout.strip(),
            'code_hashes': {p: sha256((root/p).read_bytes()).hexdigest() for p in code},
            'input_file_hashes': before, 'source_hashes': source.sources,
            'input_hash': source.input_hash, 'facts_hash': source.facts_hash,
            'input_events': len(source.events), 'selected_bar_identity_matches_phase_b': True,
            'baseline_matches_phase_b': True, 'provider_calls': 0, 'data_mutations': 0,
            'auto_order': False, 'oos_status': 'OOS_NOT_PROVEN', 'parameter_search': False}}
    output['result_hash'] = digest(output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from app.market_data.new_subing_research import safe_diagnostic
        print(json.dumps({'status': 'COST_STRESS_FAILED',
                          'error': safe_diagnostic(exc, product='jm', stage='phase_c')}))
        raise SystemExit(2) from None
