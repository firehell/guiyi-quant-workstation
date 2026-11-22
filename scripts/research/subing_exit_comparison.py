"""Offline SuBing A/B comparison over registered historical research inputs."""

import argparse
from collections import Counter
from dataclasses import replace
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import gzip
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.aggregation import expected_intraday_ends
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import NewSubingInputError, payload_hash, validate_series
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.product_taxonomy import load_product_taxonomy
from app.private_settings import load_private_readonly_settings
from app.subing_model.account import decode_execution
from guiyi_quant.subing_decision import REGIME_PROFILE, _wire, direction_sign
from guiyi_quant.subing_one_lot import (
    EXPANDED_PORTFOLIO_PRODUCTS, HOUR_EXIT, RANGE_EXIT, THREE_PRODUCT_RESEARCH, build_engine,
)
from guiyi_quant.subing_one_lot.portfolio import INITIAL_CASH, replay
from scripts.research.subing_one_lot_stress import dump, hashes, sha, stressed
from scripts.research.subing_portfolio_replay import load_hourly, load_segments


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8') as source:
        return json.load(source)


def market_engine():
    settings, _ = load_private_readonly_settings(
        Path.home() / 'Library/Application Support/GuiyiQuant/project.env'
    )
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']),
                           connect_args={'connect_timeout': 5})
    return engine, Path(settings['GUIYI_CANONICAL_DATA_ROOT'])


def legacy_hours(archive):
    index = json.loads((archive / 'prepared/index.json').read_text())['prepared']
    engine, root = market_engine()
    result = {}
    try:
        for contract, entry in sorted(index.items()):
            prepared = archive / 'prepared' / entry['file']
            prepared_hash = sha(prepared)
            if prepared_hash != entry['sha256']:
                raise ValueError('LEGACY_PREPARED_INPUT_CHANGED')
            bundle = read_gzip(prepared)
            cutoff = datetime.fromisoformat(bundle['executions'][-1]['bar']['bar_end'])
            with Session(engine, autoflush=False) as db, readonly_transaction(db, timeout_seconds=90):
                market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
                hourly, source = load_hourly(
                    market, contract[:-4].lower(), contract,
                    date.fromisoformat(bundle['through']), cutoff,
                )
            if _wire(source) != bundle['hourly_source']:
                raise ValueError(f'LEGACY_H1_SOURCE_CHANGED:{contract}')
            hours = {at.isoformat(): row for at, row in hourly.items()}
            for stamp, context in bundle['structures'].items():
                old = context.get('hourly')
                if old and (
                    old['direction'] != hours[old['at']]['direction'] or
                    datetime.fromisoformat(old['at']) > datetime.fromisoformat(stamp)
                ):
                    raise ValueError(f'LEGACY_H1_DIRECTION_CHANGED:{contract}')
            result[contract] = {'hours': hours, 'prepared_sha256': prepared_hash}
            print(contract, 'H1 verified', len(hours), flush=True)
    finally:
        engine.dispose()
    return result


def compact_prefix(account):
    """Discard diagnostics after consuming a unique, ordered prefix offline."""
    account.inputs.clear()
    account.seen_inputs.clear()
    account.trace.clear()
    model = account.model
    model.events.clear()
    model.results.clear()
    model.fingerprints.clear()
    model.chain.clear()
    model.observer.seen.clear()


def fork(source, destination):
    # No prefix history is edited or copied. Only the current projection and
    # its mutable fields travel to the counterfactual branch.
    compact_prefix(source)
    destination.__dict__.update(deepcopy({
        name: value for name, value in vars(source).items() if name != 'model'
    }))
    version = destination.model.version
    destination.model.__dict__.update(deepcopy(vars(source.model)))
    destination.model.version = version


def open_key(fill):
    return tuple(str(fill.get(key)) for key in (
        'contract', 'side', 'decision_at', 'fill_at', 'price', 'fee', 'quantity',
    ))


def follow_open(account, executions, observations):
    top_net = None
    handoff = None
    opening = len(account.fills)
    session_opens = set()
    last_day = None
    for i, x in enumerate(executions):
        account.step(x, observations[x.bar.bar_end])
        new_fills = account.fills[opening:]
        if new_fills and new_fills[-1]['action'] == 'CLOSE':
            fill = _wire(new_fills[-1])
            net = D(account.closed_rounds[-1]['net_pnl'])
            high = net if top_net is None else max(net, top_net)
            start = new_fills[0]
            return dict(
                opening=_wire(start), exit=fill, net=net, peak_net=high,
                giveback=high - net, handoff=handoff,
                holding_minutes=(new_fills[-1]['fill_at'] - start['fill_at']).total_seconds() / 60,
                crossed_trading_day=start['trading_day'] != last_day or last_day != x.bar.trading_day,
                crossed_session=len(session_opens | {x.bar.session_open_at}) > 1,
            )
        if new_fills:
            last_day = x.bar.trading_day
            session_opens.add(x.bar.session_open_at)
            mark = account.finance(x.bar.close, x.facts, account.model.side)['remaining_net']
            top_net = mark if top_net is None else max(top_net, mark)
            handoff = account.model.hour_exit_since
        if i % 256 == 255:
            compact_prefix(account)
    return dict(opening=_wire(account.fills[opening]) if len(account.fills) > opening else None,
                exit=None, handoff=handoff, peak_net=top_net)


def legacy_pair(archive, registered, contract, fee, slip):
    index = json.loads((archive / 'prepared/index.json').read_text())['prepared']
    entry = index[contract]
    prepared = archive / 'prepared' / entry['file']
    if sha(prepared) != entry['sha256'] or sha(prepared) != registered['prepared_sha256']:
        raise ValueError('LEGACY_PREPARED_INPUT_CHANGED')
    bundle = read_gzip(prepared)
    scenario = archive / 'scenarios' / f'{contract}-one_lot-fee{fee}-slip{slip}.json.gz'
    archived = read_gzip(scenario)
    if archived['prepared_sha256'] != entry['sha256']:
        raise ValueError('LEGACY_SCENARIO_INPUT_CHANGED')
    result = archived['result']
    fills = {row['fill_id']: row for row in result['fills']}
    closed = {
        datetime.fromisoformat(fills[row['fills'][0]]['fill_at']) + timedelta(minutes=1):
        (fills[row['fills'][0]], fills[row['fills'][-1]])
        for row in result['closed_rounds']
    }
    xs = stressed([decode_execution(row) for row in bundle['executions']], fee)
    obs = {x.bar.bar_end: row for x, row in zip(xs, bundle['observations'], strict=True)}
    if any(at.isoformat() != row['at'] for at, row in obs.items()):
        raise ValueError('LEGACY_UNORDERED_OBSERVATION')
    directions = bundle['structures']
    structures = {
        at: dict(row, hourly=registered['hours'][(row['hourly']['at'])] if row.get('hourly') else None)
        for at, row in directions.items()
    }
    factories = [
        build_engine(xs, bundle['schedule'], structures=structures, exit_profile=profile,
                     legacy_close_witness=witness)[0].AccountEngine
        for witness, profile in ((False, None), (True, None), (True, HOUR_EXIT))
    ]

    def account(factory):
        return factory(contract, contract[:-4].lower(), xs[0].facts.multiplier,
                       result['run_id'], slip, 'theoretical_open',
                       regime_research_profile=REGIME_PROFILE)

    baseline = account(factories[0])
    pairs, opportunities = [], Counter()
    for i, x in enumerate(xs):
        at = x.bar.bar_end
        if at in closed:
            expected_open, expected_close = closed[at]
            pending = baseline.model.pending
            if not pending or pending['kind'] != 'OPEN':
                raise ValueError(f'LEGACY_OPEN_INTENT_UNREPRODUCED:{contract}:{at}')
            risk = abs(D(expected_open['price']) - pending['initial_stop']) * x.facts.multiplier
            outcomes = {}
            for label, factory in zip(('A', 'B'), factories[1:], strict=True):
                branch = account(factory)
                fork(baseline, branch)
                outcome = follow_open(branch, xs[i:], obs)
                if outcome['opening'] is None or open_key(outcome['opening']) != open_key(expected_open):
                    raise ValueError(f'LEGACY_OPEN_UNREPRODUCED:{contract}:{at}')
                outcomes[label] = outcome
            pairs.append(pair_result(contract, risk, outcomes) | dict(
                archived_exit=expected_close, entry_volume_tier=pending.get('entry_volume_tier'),
            ))
        baseline.step(x, obs[at])
        for action in baseline.model.chain[-1]['actions']:
            if action['kind'] == 'OPEN' or action.get('opportunity') == 'OPEN':
                opportunities.update([action['kind']])
                opportunities.update(action.get('reasons', []) if action['kind'] == 'REJECT' else [])
        if i % 256 == 255:
            compact_prefix(baseline)
    if _wire(baseline.fills) != result['fills']:
        raise ValueError(f'LEGACY_BASELINE_FILLS_CHANGED:{contract}')
    return dict(contract=contract, fee=fee, slip=slip, pairs=pairs,
                opportunities=dict(opportunities), archived_fill_count=len(baseline.fills),
                prepared_sha256=entry['sha256'], archived_sha256=sha(scenario))


def pair_result(contract, risk, outcomes):
    a, b = outcomes['A'], outcomes['B']
    paired = a['exit'] is not None and b['exit'] is not None
    delta = b['net'] - a['net'] if paired else None
    for result in outcomes.values():
        if result['exit'] is not None:
            result['net_r'] = result['net'] / risk
    return dict(
        contract=contract, technical_risk=risk, **outcomes, net_delta=delta,
        r_delta=delta / risk if paired else None,
        changed=paired and (a['exit']['fill_at'], a['exit']['price']) !=
        (b['exit']['fill_at'], b['exit']['price']),
        winner_to_loss=paired and a['net'] > 0 > b['net'],
        tier1_exit=bool(a['exit'] and any(r.endswith('_TIER1_CLEAR') for r in a['exit']['reasons'])),
    )


def summarize_pairs(pairs):
    complete = [p for p in pairs if p['net_delta'] is not None]
    return dict(
        entries=len(pairs), closed_pairs=len(complete),
        tier1_exits=sum(p['tier1_exit'] for p in pairs),
        transfers=sum(p['B']['handoff'] is not None for p in pairs),
        differences=sum(p['changed'] for p in pairs),
        winners_to_losses=sum(p['winner_to_loss'] for p in pairs),
        net_delta=sum((p['net_delta'] for p in complete), D(0)),
        r_delta=sum((p['r_delta'] for p in complete), D(0)),
    )


def portfolio_comparison(segments, products, fee, slip, profile, input_id):
    archive = {
        segment.executions[0].bar.physical_contract: {x.bar.bar_end: x for x in segment.executions}
        for segment in segments
    }
    sectors = load_product_taxonomy()
    if fee > 1:
        segments = [replace(s, executions=tuple(stressed(s.executions, fee))) for s in segments]
    runs, entries = {}, {}
    for label, exit_profile in (('A', None), ('B', profile)):
        peak = INITIAL_CASH
        drawdown = D(0)
        margin = D(0)
        exposure = Counter()
        observed_range = Counter()
        held = {}
        position_marks = {}
        sparse_actions = {}
        shanghai = ZoneInfo('Asia/Shanghai')

        def batch(book):
            nonlocal peak, drawdown, margin
            equity = book.equity()
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            margin = max(margin, book.reserved_finance()[0])
            positions = Counter()
            for contract, account in book.accounts.items():
                mark = book.marks.get(contract)
                if not account.layers or not mark:
                    continue
                sector = sectors[contract[:-4].lower()].sector
                positions[f'{sector}:{account.model.side}'] += 1
                if mark.bar.bar_end != book.last_at:
                    continue
                if account.model.regime == 'RANGE':
                    observed_range[contract[:-4].lower()] += 1
                layer = next(iter(account.layers.values()))
                key = (contract, layer['layer_id'])
                stats = position_marks.setdefault(key, dict(peak=None, handoff=None, sessions=set()))
                if account.model.hour_exit_since is not None:
                    stats['handoff'] = account.model.hour_exit_since
                net = (direction_sign(layer['side']) * (mark.bar.close - layer['price']) *
                       account.multiplier - layer['open_fee'] -
                       account.close_fee(layer, mark.bar.close, mark.facts)[0])
                stats['peak'] = net if stats['peak'] is None else max(net, stats['peak'])
                stats['sessions'].add((mark.bar.trading_day, mark.bar.session_open_at))
            for side, count in positions.items():
                exposure[side] = max(exposure[side], count)
            occupied = {
                c for c, a in book.accounts.items() if a.layers or a.model.pending
            }
            if occupied:
                held[book.last_at.isoformat()] = occupied
            if products == THREE_PRODUCT_RESEARCH:
                for contract, account in book.accounts.items():
                    chain = account.model.chain
                    if len(chain) < 256:
                        continue
                    sparse_actions.setdefault(contract, []).extend(
                        {'actions': row['actions']} for row in chain[:-1] if row['actions']
                    )
                    latest = chain[-1]
                    compact_prefix(account)
                    chain.append(latest)

        variant = exit_profile or 'baseline'
        result = replay(segments, f'subing-research:{input_id}:{variant}:f{fee}:s{slip}',
                        products=products, on_batch=batch, exit_profile=exit_profile,
                        slippage_ticks=slip, research_scope=products == THREE_PRODUCT_RESEARCH)
        entry_rows, by_product, by_session, opportunities, intents = {}, {}, {}, Counter(), []
        execution_rejections = Counter()
        for contract, account in result['accounts'].items():
            fills = {f['fill_id']: f for f in account['fills']}
            execution_rejections.update(event['reason'] for event in account['execution_events'])
            decision_rows = sparse_actions.get(contract, []) + account['decisions_with_actions']
            initial = {
                action['decision_id']: action for row in decision_rows
                for action in row['actions'] if action['kind'] == 'OPEN'
            }
            closed = {r['fills'][0]: r for r in account['closed_rounds']}
            for row in decision_rows:
                for action in row['actions']:
                    if action['kind'] == 'OPEN':
                        opportunities['OPEN_INTENT'] += 1
                        intents.append((contract, action['side'], action['at']))
                    elif action.get('opportunity') == 'OPEN':
                        opportunities['REJECTED_OPEN'] += 1
                        opportunities.update(f"REJECT:{reason}" for reason in action.get('reasons', []))
            for opening in (f for f in fills.values() if f['action'] == 'OPEN'):
                fact = archive[contract][datetime.fromisoformat(opening['fill_bar_end'])]
                action = initial[opening['decision_id']]
                risk = (direction_sign(opening['side']) *
                        (D(opening['price']) - D(action['initial_stop'])) * fact.facts.multiplier)
                stats = position_marks.get((contract, opening['decision_id']), {})
                round_ = closed.get(opening['fill_id'])
                close = fills[round_['fills'][-1]] if round_ else None
                net = D(round_['net_pnl']) if round_ else None
                peak_net = stats.get('peak')
                if net is not None:
                    peak_net = net if peak_net is None else max(net, peak_net)
                    exit_fact = archive[contract][datetime.fromisoformat(close['fill_bar_end'])]
                    sessions = stats.get('sessions', set()) | {
                        (fact.bar.trading_day, fact.bar.session_open_at),
                        (exit_fact.bar.trading_day, exit_fact.bar.session_open_at),
                    }
                    scope = ('CROSS_TRADING_DAY' if fact.bar.trading_day != exit_fact.bar.trading_day
                             else 'CROSS_SESSION' if len(sessions) > 1 else 'INTRASESSION')
                    opening_hour = fact.bar.session_open_at.astimezone(shanghai).hour
                    contribution = by_session.setdefault(
                        f"{'NIGHT' if opening_hour >= 18 else 'DAY'}:{scope}",
                        dict(rounds=0, net=D(0), fees=D(0)),
                    )
                    contribution['rounds'] += 1
                    contribution['net'] += net
                    contribution['fees'] += D(opening['fee']) + D(close['fee'])
                entry_rows[open_key(opening)] = dict(
                    opening=opening, exit=close, net=net, risk=risk,
                    peak_net=peak_net, handoff=stats.get('handoff'),
                    giveback=peak_net - net if net is not None else None,
                    holding_minutes=(datetime.fromisoformat(close['fill_at']) -
                                     datetime.fromisoformat(opening['fill_at'])).total_seconds() / 60
                    if close else None,
                    crossed_trading_day=bool(close and scope == 'CROSS_TRADING_DAY'),
                    crossed_session=bool(close and scope != 'INTRASESSION'),
                )
            product = contract[:-4].lower()
            row = by_product.setdefault(product, dict(net=D(0), fees=D(0), slippage_cny=D(0), fills=0))
            row['net'] += D(account['net_pnl'])
            row['fees'] += D(account['fees'])
            for fill in fills.values():
                fact = archive[contract][datetime.fromisoformat(fill['fill_bar_end'])]
                row['slippage_cny'] += (abs(D(fill['price']) - fact.bar.close) *
                                         fact.facts.multiplier * fill['quantity'])
            row['fills'] += len(fills)
        runs[label] = dict(
            policy=result['policy'], ending_equity=result['equity'],
            net_pnl=D(result['equity']) - INITIAL_CASH,
            drawdown=drawdown, peak_margin=margin, peak_sector_side_lots=exposure,
            minutes_holding_in_m30_range=observed_range,
            fees=sum((r['fees'] for r in by_product.values()), D(0)),
            slippage_cny=sum((r['slippage_cny'] for r in by_product.values()), D(0)),
            by_product=by_product,
            closed_rounds_by_session=by_session, opportunities=opportunities,
            open_fills=len(entry_rows), execution_rejections=execution_rejections,
            risk_records=result['risk_records'],
            pending_exit_contracts=result['pending_exit_contracts'],
            valuation_unproven=result['valuation_unproven'],
        )
        entries[label] = entry_rows, held, intents
    for label, other in (('A', 'B'), ('B', 'A')):
        _, _, intents = entries[label]
        _, held, other_intents = entries[other]
        other_keys = set(other_intents)
        runs[other]['other_open_intent_while_occupied'] = [
            (contract, side, at) for contract, side, at in intents
            if (contract, side, at) not in other_keys and contract in held.get(at, set())
        ]
    a_entries, b_entries = (entries[label][0] for label in ('A', 'B'))
    pairs = [pair_result(key[0], a_entries[key]['risk'], {'A': a_entries[key], 'B': b_entries[key]})
             for key in sorted(a_entries.keys() & b_entries.keys())]
    return dict(
        kind=('THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH' if products == THREE_PRODUCT_RESEARCH
              else 'SEEN_14_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH'),
        fee_multiplier=fee, slippage_ticks=slip, exit_profile=profile, input_id=input_id,
        portfolio_runs=runs, common_entries=summarize_pairs(pairs),
        matched_entries=pairs,
        unmatched_entries={label: [rows[k] for k in sorted(rows.keys() - other.keys())]
                           for label, rows, other in (('A', a_entries, b_entries),
                                                       ('B', b_entries, a_entries))},
    )



def current_coverage(registry, day):
    from datetime import UTC
    from redis.exceptions import RedisError
    from app.market_data.observation_stream import ObservationStream
    from app.subing_model.worker import settings_and_redis
    from app.subing_portfolio_worker import prepare_day, read_completed, registered_facts

    engine, root = market_engine()
    now = datetime.now(UTC)
    rows, contexts = {}, {}
    try:
        for product in EXPANDED_PORTFOLIO_PRODUCTS:
            row = rows[product] = {}
            try:
                context, _ = prepare_day(
                    {'GUIYI_CANONICAL_DATA_ROOT': str(root)}, engine, day, (product,),
                )
            except NewSubingInputError as exc:
                row['physical_warmup'] = exc.code
                continue
            except ValueError as exc:
                row['physical_warmup'] = str(exc)
                continue
            context = context[product]
            contexts[product] = context
            contract = context['contract']
            row.update(contract=contract, physical_warmup='VERIFIED')
            facts = None
            try:
                facts = registered_facts(registry, day, {product: context}, now)[product]
            except (OSError, ValueError) as exc:
                row['facts_status'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            if facts:
                captured = datetime.fromisoformat(facts['captured_at'])
                row.update(
                    facts_status='VERIFIED',
                    facts_captured_at=captured,
                    facts_payload_sha256=payload_hash(facts),
                    fee_assumption=facts['fee_assumption'],
                    minutes_not_strictly_after_facts=sum(
                        datetime.fromisoformat(t) <= captured for t in context['expected_1m']
                    ),
                )
            row['canonical'] = {}
            with Session(engine, autoflush=False) as db, readonly_transaction(db, timeout_seconds=90):
                market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
                sessions = market.session_windows(symbol=product, trading_day=day)
                for freq in (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15,
                             BarFrequency.M30, BarFrequency.H1):
                    expected = tuple((at, day) for at in expected_intraday_ends(sessions, freq.value))
                    try:
                        series = market.query_contract_trading_days(
                            ContractTradingDayQuery(product, contract, freq, day, day)
                        )
                        validate_series(series, product=product, contract=contract, frequency=freq,
                                        expected=expected)
                    except NewSubingInputError as exc:
                        row['canonical'][freq.value] = dict(status=exc.code, expected=len(expected))
                    else:
                        row['canonical'][freq.value] = dict(status='VERIFIED', count=len(expected))
    finally:
        engine.dispose()
    stream_status = 'VERIFIED'
    try:
        _, redis = settings_and_redis()
        observations, _ = read_completed(ObservationStream(redis, kind='completed'),
                                         day, contexts, '0-0')
    except (ValueError, OSError, RedisError) as exc:
        stream_status = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    else:
        for product, context in contexts.items():
            rows[product]['completed_stream'] = {}
            for freq in ('1m', '30m', '60m'):
                expected = [datetime.fromisoformat(at) for at in context['expected_' + freq]]
                missing = [at for at in expected if (at, product, freq) not in observations]
                rows[product]['completed_stream'][freq] = dict(
                    expected=len(expected), missing=len(missing),
                    first_missing=missing[0] if missing else None,
                    last_missing=missing[-1] if missing else None,
                )
    return dict(kind='CURRENT_16_READ_ONLY_COVERAGE', trading_day=day,
                stream_status=stream_status, products=rows)



def registered_day(archive):
    prepared = archive / 'input.json.gz'
    raw = prepared.read_bytes()
    digest = sha256(raw).hexdigest()
    identity = json.loads((archive / 'input-identity.json').read_text())
    if digest != identity['sha256']:
        raise ValueError('REGISTERED_DAY_INPUT_CHANGED')
    bundle = json.loads(gzip.decompress(raw))
    xs = [decode_execution(row) for row in bundle['executions']]
    if len(xs) != identity['minutes']:
        raise ValueError('REGISTERED_DAY_MINUTES_CHANGED')
    obs = {x.bar.bar_end: row for x, row in zip(xs, bundle['observations'], strict=True)}
    contract = bundle['contract']
    product = contract[:-4].lower()
    cutoff = xs[-1].bar.bar_end
    engine, root = market_engine()
    try:
        with Session(engine, autoflush=False) as db, readonly_transaction(db, timeout_seconds=90):
            market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
            hourly, source = load_hourly(market, product, contract, xs[-1].bar.trading_day, cutoff)
    finally:
        engine.dispose()
    old_source = bundle['hourly_source']
    if _wire(source) != old_source or len(hourly) != identity['hourly_bars']:
        def partitions(evidence):
            return {(row['year'], row['month']): row['content_sha256']
                    for row in evidence['partitions']}

        before, after = partitions(old_source), partitions(source)
        return dict(
            kind='PREVIOUSLY_REPORTED_POST_LOCK_SINGLE_JM_DAY',
            input_sha256=digest, execution_status='REGISTERED_DAY_H1_SOURCE_CHANGED',
            original_h1_count=identity['hourly_bars'], current_h1_count=len(hourly),
            changed_months=sorted(month for month in before.keys() | after.keys()
                                  if before.get(month) != after.get(month)),
        )
    hours = {at.isoformat(): row for at, row in hourly.items()}
    structures = {}
    for stamp, context in bundle['structures'].items():
        original = context.get('hourly')
        hour = hours[original['at']] if original else None
        if original and original['direction'] != hour['direction']:
            raise ValueError('REGISTERED_DAY_H1_DIRECTION_CHANGED')
        structures[stamp] = dict(context, hourly=hour)
    runs = {}
    for label, profile in (('A', None), ('B', HOUR_EXIT)):
        module, _, _ = build_engine(xs, bundle['schedule'], structures=structures, exit_profile=profile)
        account = module.AccountEngine(contract, product, xs[0].facts.multiplier, f'day:{label}',
                                       execution_model='theoretical_open',
                                       regime_research_profile=REGIME_PROFILE)
        prefix_checks = []
        last_window = None
        for i, x in enumerate(xs):
            if last_window is not None and last_window != x.bar.session_open_at:
                restored = module.AccountEngine.restore(account.checkpoint())
                prefix_checks.append(dict(minutes=i, restored=restored.snapshot() == account.snapshot()))
                if prefix_checks[-1]['restored'] is not True:
                    raise ValueError('REGISTERED_DAY_RESTART_CONFLICT')
                account = restored
            last_window = x.bar.session_open_at
            account.step(x, obs[x.bar.bar_end])
        result = account.snapshot(include_journal=False)
        runs[label] = dict(summary=result['summary'], fills=result['fills'], prefix_checks=prefix_checks,
                           entry_rejects=[a for row in account.model.chain for a in row['actions']
                                          if a.get('opportunity') == 'OPEN'])
    return dict(kind='PREVIOUSLY_REPORTED_POST_LOCK_SINGLE_JM_DAY', input_sha256=digest,
                eligibility=bundle['eligibility'], runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=(
        'legacy-hours', 'legacy-pairs', 'portfolio', 'three-product',
        'current-coverage', 'diagnostics', 'registered-day',
    ))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hours', type=Path)
    parser.add_argument('--contract')
    parser.add_argument('--day', type=date.fromisoformat)
    parser.add_argument('--fee', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--range-exit', action='store_true')
    parser.add_argument('--slip', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    def code_hashes():
        runners = (Path(__file__), *(Path(__file__).with_name(n) for n in
                    ('subing_portfolio_replay.py', 'subing_research_diagnostics.py')))
        return {**hashes(), **{path.name: sha(path) for path in runners}}

    code = code_hashes()
    if args.mode == 'registered-day':
        result = registered_day(args.source)
    elif args.mode == 'current-coverage':
        if args.day is None:
            parser.error('--day is required for current-coverage')
        result = current_coverage(args.source, args.day)
    elif args.mode == 'legacy-hours':
        result = dict(kind='LEGACY_ARCHIVE_H1_VERIFIED', contracts=legacy_hours(args.source))
    elif args.mode == 'legacy-pairs':
        if not args.hours:
            parser.error('--hours is required for legacy-pairs')
        hourly_bytes = args.hours.read_bytes()
        hourly = json.loads(hourly_bytes)['contracts']
        contracts = (args.contract,) if args.contract else sorted(hourly)
        rows = []
        for contract in contracts:
            row = legacy_pair(args.source, hourly[contract], contract, args.fee, args.slip)
            rows.append(row)
            print(contract, _wire(summarize_pairs(row['pairs'])), flush=True)
        result = dict(
            kind='SEEN_JM_DEVELOPMENT_FIXED_ENTRY_LEGACY_WITNESS',
            a_exit='current_m30_with_protections', b_exit=HOUR_EXIT,
            hourly_sha256=sha256(hourly_bytes).hexdigest(),
            summary=summarize_pairs([pair for row in rows for pair in row['pairs']]),
            contracts=rows,
        )
    else:
        plan, products, segments, coverage, _, fact_hashes = load_segments(
            args.source, compare_exits=True, diagnostics=args.mode == 'diagnostics',
            research_scope=args.mode == 'three-product',
        )
        result = dict(kind='HISTORICAL_RESEARCH_COVERAGE', requested=plan['dates'],
                      products=products, coverage=coverage, plan_hash=payload_hash(plan),
                      execution_facts_sha256=fact_hashes)
        if products == EXPANDED_PORTFOLIO_PRODUCTS:
            result['execution_status'] = 'ACTUAL_KNOWLEDGE_FACTS_REQUIRED_FOR_16'
        elif (args.mode in ('portfolio', 'three-product') and segments
              and all(row['status'] == 'VERIFIED' for row in coverage)):
            result.update(portfolio_comparison(
                segments, products, args.fee, args.slip, RANGE_EXIT if args.range_exit else HOUR_EXIT,
                payload_hash([plan, fact_hashes, coverage]),
            ))
    if code != code_hashes():
        raise ValueError('RESEARCH_CODE_CHANGED_DURING_REPLAY')
    dump(args.output, result | dict(code_hashes=code))


if __name__ == '__main__':
    main()
