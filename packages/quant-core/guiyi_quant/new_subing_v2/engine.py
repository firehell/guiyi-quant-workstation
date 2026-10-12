"""Causal event loop for V2 research. No I/O and no mutable global state."""
from __future__ import annotations

from collections import defaultdict
from bisect import bisect_right
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from hashlib import sha256
import re
from typing import Mapping, Sequence, cast

from guiyi_quant.paper import FeeSchedule

from . import ExecutionBar, ExecutionFacts, PreparedResearch, Profile, StrategyBar
from .account import LayerAccount
from .signals import Snapshot, build_snapshots, divergence_events, direction, setup_evidence

D = Decimal
ZERO = D('0')


def _side_name(side: int) -> str:
    return 'LONG' if side > 0 else 'SHORT'


def daily_anchor_trigger(qty: int, close: D, prior: StrategyBar) -> bool:
    if abs(qty) <= 1:
        return False
    side = (qty > 0) - (qty < 0)
    anchor = prior.low if side > 0 else prior.high
    return (close - anchor) * side < 0


def daily_macd_reaction(current: Snapshot, previous: Snapshot | None,
                        side: int, net_profit: D) -> str | None:
    weak = (current.macd_cross == -side or
            (previous is not None and current.histogram is not None and
             previous.histogram is not None and
             (current.histogram - previous.histogram) * side < 0))
    if not weak:
        return None
    return 'CLEAR' if net_profit <= 0 else 'REDUCE'


def _fees(f: FeeSchedule, scenario: str) -> FeeSchedule:
    if scenario != 'double_commission':
        return f
    return FeeSchedule(open_rate=f.open_rate * 2,
                       open_per_contract=f.open_per_contract * 2,
                       close_rate=f.close_rate * 2,
                       close_per_contract=f.close_per_contract * 2,
                       close_today_rate=f.close_today_rate * 2,
                       close_today_per_contract=f.close_today_per_contract * 2,
                       source_id=f.source_id)


def _scenario_facts(f: ExecutionFacts, scenario: str) -> ExecutionFacts:
    if scenario != 'double_commission':
        return f
    from dataclasses import replace
    return replace(f, fees=_fees(f.fees, scenario))


def _empty_result(profile: Profile, reason: str) -> dict[str, object]:
    return {'summary': {'status': reason, 'initial_cash': str(profile.initial_cash),
                        'final_equity': None, 'account_return_pct': None,
                        'max_drawdown_pct': None, 'closed_trades': 0,
                        'total_fees': None, 'ending_qty': 0, 'annual_eligible': False},
            'decisions': [], 'trades': [], 'equity': [], 'fills': [],
            'stages': [], 'layers': [], 'projection': {'hold_frequency': '5m', 'open_layers': []},
            'diagnostics': {'status': reason, 'rejections': {}, 'segments': [],
                            'stage_counts': {name: 0 for name in
                                             ('TRIAL', 'BREAKOUT_CONFIRMED', 'PULLBACK', 'TREND')},
                            'stage_summary': {'last_stage': 'FLAT', 'transition_count': 0,
                                              'upgraded_to_daily': False, 'first_atr': None,
                                              'hold_frequency': '5m'},
                            'layer_summary': {'opened_layers': 0, 'closed_layer_events': 0,
                                              'named_guard_closes': 0, 'remaining_layers': 0,
                                              'remaining_average_price': None,
                                              'realized_gross_pnl': '0', 'close_fees': '0'},
                            'case_parity': 'PENDING', 'oos_status': 'NOT_PROVEN'}}


def _validate_inputs(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                     execution_bars: Sequence[ExecutionBar], scenario: str,
                     since: date, through: date) -> None:
    if scenario not in ('baseline', 'double_commission', 'double_slippage'):
        raise ValueError('unsupported scenario')
    if type(since) is not date or type(through) is not date or since > through:
        raise ValueError('invalid requested window')
    if not isinstance(bars_by_frequency, Mapping) or not isinstance(execution_bars, Sequence):
        raise ValueError('invalid research inputs')
    if not {'1m', '5m', '15m', '1d'}.issubset(bars_by_frequency):
        raise ValueError('1m, 5m, 15m and 1d histories required')
    products: set[str] = set()
    for frequency, bars in bars_by_frequency.items():
        if frequency not in ('1m', '5m', '15m', '1d', '1w') or not isinstance(bars, Sequence):
            raise ValueError('invalid frequency history')
        keys: set[tuple[str, datetime]] = set()
        previous: tuple[datetime, str] | None = None
        confirmations: dict[str, datetime] = {}
        for bar in bars:
            if type(bar) is not StrategyBar or bar.frequency != frequency:
                raise ValueError('bar frequency mismatch')
            if re.fullmatch(r'[A-Za-z]{1,3}\d{3,4}(?:\.[A-Za-z]+)?', bar.physical_contract) is None:
                raise ValueError('physical monthly contract required')
            products.add(bar.product.upper())
            key = (bar.physical_contract, bar.bar_end)
            if key in keys or (previous and (bar.bar_end, bar.physical_contract) < previous):
                raise ValueError('duplicate or unordered history')
            keys.add(key)
            previous = (bar.bar_end, bar.physical_contract)
            if bar.physical_contract in confirmations and bar.confirmed_at < confirmations[bar.physical_contract]:
                raise ValueError('out-of-order confirmation within physical history')
            confirmations[bar.physical_contract] = bar.confirmed_at
    if len(products) > 1:
        raise ValueError('one product per research account')
    one_minute = {(b.physical_contract, b.bar_end): b for b in bars_by_frequency['1m']}
    previous_time: datetime | None = None
    previous_confirmed: datetime | None = None
    seen: set[datetime] = set()
    for execution in execution_bars:
        if type(execution) is not ExecutionBar or execution.bar.product.upper() not in products:
            raise ValueError('execution product mismatch')
        bar = execution.bar
        if one_minute.get((bar.physical_contract, bar.bar_end)) != bar:
            raise ValueError('execution bar differs from 1m history')
        if not bar.observation_eligible or not since <= bar.trading_day <= through:
            raise ValueError('execution must be eligible owner within requested window')
        if previous_time and bar.bar_end <= previous_time or bar.bar_end in seen:
            raise ValueError('execution bars must be strictly ordered')
        if previous_confirmed and bar.confirmed_at < previous_confirmed:
            raise ValueError('execution confirmation must be ordered')
        previous_time = bar.bar_end
        previous_confirmed = bar.confirmed_at
        seen.add(bar.bar_end)


def validate_histories(bars_by_frequency: Mapping[str, Sequence[StrategyBar]]) -> None:
    _validate_inputs(bars_by_frequency, (), 'baseline', date.min, date.max)


def prepare_snapshots(bars_by_frequency: Mapping[str, Sequence[StrategyBar]], profile: Profile
                      ) -> tuple[tuple[str, tuple[tuple[str, tuple[Snapshot, ...]], ...]], ...]:
    grouped: dict[str, dict[str, list[StrategyBar]]] = defaultdict(lambda: defaultdict(list))
    for frequency, bars in bars_by_frequency.items():
        for bar in bars:
            grouped[bar.physical_contract][frequency].append(bar)
    return tuple((contract, tuple((frequency, tuple(build_snapshots(bars, profile)))
                                  for frequency, bars in sorted(frequencies.items())
                                  if frequency in ('5m', '15m', '1d', '1w')))
                 for contract, frequencies in sorted(grouped.items()))


def _decision_id(at: datetime, action: str, contract: str, reason: str) -> str:
    return sha256(f'{at.isoformat()}|{action}|{contract}|{reason}'.encode()).hexdigest()[:24]


def run_research_impl(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                      execution_bars: Sequence[ExecutionBar], profile: Profile,
                      scenario: str, since: date, through: date,
                      prepared: PreparedResearch | None = None) -> dict[str, object]:
    _validate_inputs(bars_by_frequency, execution_bars, scenario, since, through)
    if not execution_bars or not bars_by_frequency['5m'] or not bars_by_frequency['15m'] or not bars_by_frequency['1d']:
        return _empty_result(profile, 'DATA_INSUFFICIENT')

    grouped: dict[str, dict[str, list[StrategyBar]]] = defaultdict(lambda: defaultdict(list))
    for frequency, bars in bars_by_frequency.items():
        for bar in bars:
            grouped[bar.physical_contract][frequency].append(bar)
    frozen = prepared.snapshots if prepared is not None else prepare_snapshots(bars_by_frequency, profile)
    snapshots: dict[str, dict[str, list[Snapshot]]] = {
        contract: {frequency: list(values) for frequency, values in frequencies}
        for contract, frequencies in frozen}
    context_times = {contract: {frequency: [s.bar.confirmed_at for s in history]
                                for frequency, history in frequencies.items()}
                     for contract, frequencies in snapshots.items()}
    context_ends = {contract: {frequency: [s.bar.bar_end for s in history]
                               for frequency, history in frequencies.items()}
                    for contract, frequencies in snapshots.items()}
    divergences = {contract: {side: divergence_events(frequencies.get('5m', []), side, profile)
                              for side in (-1, 1)}
                   for contract, frequencies in snapshots.items()}
    session_minutes: dict[tuple[str, datetime], tuple[list[datetime], list[datetime]]] = {}
    for execution in execution_bars:
        b = execution.bar
        if b.session_open_at is None:
            continue
        ends, confirmed = session_minutes.setdefault((b.physical_contract, b.session_open_at), ([], []))
        ends.append(b.bar_end)
        confirmed.append(b.confirmed_at)
    contract_minutes: dict[str, tuple[list[datetime], list[datetime]]] = {}
    for contract, by_frequency in grouped.items():
        one_minute = by_frequency.get('1m', [])
        contract_minutes[contract] = ([b.bar_end for b in one_minute],
                                      [b.confirmed_at for b in one_minute])

    def completed_session_minutes(bar: StrategyBar, at: datetime) -> int:
        if bar.session_open_at is None:
            return 0
        ends, confirmations = session_minutes.get((bar.physical_contract, bar.session_open_at), ([], []))
        return min(bisect_right(ends, bar.bar_end), bisect_right(confirmations, at))

    def completed_trading_minutes_since(contract: str, after: datetime,
                                        through_end: datetime, at: datetime) -> int:
        ends, confirmations = contract_minutes.get(contract, ([], []))
        observed = min(bisect_right(ends, through_end), bisect_right(confirmations, at))
        return max(0, observed - bisect_right(ends, after))

    def context_snapshot(contract: str, frequency: str, at: datetime,
                         signal_end: datetime) -> Snapshot | None:
        history = snapshots[contract].get(frequency, [])
        times = context_times[contract].get(frequency, [])
        ends = context_ends[contract].get(frequency, [])
        index = min(bisect_right(times, at), bisect_right(ends, signal_end)) - 1
        return history[index] if index >= 0 else None

    account = LayerAccount(profile.initial_cash, profile.day_loss_fraction)
    decisions: list[dict[str, object]] = []
    all_trades: list[dict[str, object]] = []
    all_fills: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    rejections: dict[str, int] = defaultdict(int)
    segments: list[dict[str, object]] = []
    pending: dict[str, object] | None = None
    setup: dict[str, object] | None = None
    add_setup: dict[str, object] | None = None
    current_contract: str | None = None
    interrupted = False
    stop: D | None = None
    entry_atr: D | None = None
    first_entry_atr: D | None = None
    frozen_level: D | None = None
    first_budget: D | None = None
    first_risk: D | None = None
    first_qty = 0
    adds = 0
    stage = 'FLAT'
    confirmed_count = 0
    pullback_index: int | None = None
    hold_frequency = '5m'
    entry_5m_index = 0
    peak_profit = ZERO
    reduction_used: set[str] = set()
    stage_rows: list[dict[str, object]] = []
    layer_rows: list[dict[str, object]] = []
    blocked_setup_sources: set[str] = set()
    last_5m: Snapshot | None = None
    last_5m_index = 0
    current_facts: ExecutionFacts | None = None
    ready_observation = False
    fact_blocked = False
    seq = 0

    def record(at: datetime, action: str, side: int, reason: str, target: int,
               facts: dict[str, object] | None = None) -> None:
        nonlocal seq
        seq += 1
        decisions.append({'decision_id': _decision_id(at, action, current_contract or '', reason) + f'-{seq}',
                          'at': at.isoformat(), 'action': action, 'side': _side_name(side) if side else 'FLAT',
                          'reason': reason, 'target_qty': target,
                          'physical_contract': current_contract, 'effective_after': at.isoformat(),
                          'facts': facts or {}})

    def reject(at: datetime, reason: str, side: int = 0, facts: dict[str, object] | None = None) -> None:
        rejections[reason] += 1
        record(at, 'REJECT', side, reason, account.qty, facts)

    def queue(at: datetime, action: str, side: int, reason: str,
              facts: dict[str, object] | None = None) -> None:
        nonlocal pending, pullback_index, stage
        priority = {'CLEAR': 5, 'LAYER_CLEAR': 4, 'REDUCE': 3, 'ADD': 2, 'OPEN': 1}
        if pending and priority[action] <= priority[str(pending['action'])]:
            return
        if pending:
            record(at, 'CANCEL', cast(int, pending['side']), f'SUPERSEDED_BY_{action}', account.qty,
                   {'cancelled_action': pending['action'], 'cancelled_reason': pending['reason']})
        pending = {'at': at, 'effective_after': at, 'action': action, 'side': side,
                   'reason': reason, 'facts': facts or {}, 'contract': current_contract,
                   'trading_day': current_facts.trading_day if current_facts else None,
                   'session_open_at': last_5m.bar.session_open_at if last_5m else None}
        if action in ('REDUCE', 'LAYER_CLEAR', 'CLEAR'):
            pullback_index = None
            if stage == 'PULLBACK' and hold_frequency == '5m' and action != 'CLEAR':
                stage = 'BREAKOUT_CONFIRMED'
                stage_rows.append({'at': at.isoformat(), 'stage': stage,
                                   'source_identity': reason})
        record(at, action, side, reason, account.qty, facts)

    def margin_used(facts: ExecutionFacts, mark: D) -> D:
        ratio = facts.long_margin_ratio if account.side > 0 else facts.short_margin_ratio
        return abs(account.qty) * mark * facts.multiplier * ratio

    def net_unrealized(mark: D, facts: ExecutionFacts) -> D:
        if not account.qty:
            return ZERO
        gross = (mark - account.average_price) * facts.multiplier * account.qty
        close_fees = sum((D(layer.qty) * facts.fees.amount(
            'close_today' if layer.trading_day == facts.trading_day else 'close',
            mark, facts.multiplier) for layer in account.layers), ZERO)
        exit_slippage = D(2 if scenario == 'double_slippage' else 1) * facts.tick_size * facts.multiplier
        return gross - close_fees - abs(account.qty) * exit_slippage

    def open_qty(price: D, facts: ExecutionFacts, side: int, action: str) -> int:
        if stop is None or entry_atr is None or frozen_level is None:
            return 0
        equity = account.equity(price, facts) if account.qty else account.cash
        margin_per = price * facts.multiplier * (facts.long_margin_ratio if side > 0 else facts.short_margin_ratio)
        if margin_per <= 0 or equity <= 0:
            return 0
        budget = equity * profile.initial_margin_fraction if action == 'OPEN' else (first_budget or ZERO) * (D('2') / 3 if adds == 0 else D('1') / 3)
        risk_budget = equity * profile.initial_risk_fraction if action == 'OPEN' else \
            (first_risk or ZERO) * (D('2') / 3 if adds == 0 else D('1') / 3)
        slip = 2 if scenario == 'double_slippage' else 1
        roundtrip_slip = D(slip * 2) * facts.tick_size * facts.multiplier
        fees = facts.fees.amount('open', price, facts.multiplier) + max(
            facts.fees.amount('close', stop, facts.multiplier),
            facts.fees.amount('close_today', stop, facts.multiplier))
        risk_per = abs(price - stop) * facts.multiplier + roundtrip_slip + fees
        if risk_per <= 0 or (price - stop) * side <= 0:
            return 0
        available_margin = max(ZERO, equity * profile.max_margin_fraction - margin_used(facts, price))
        held_risk = sum((D(layer.qty) * (max(ZERO, (layer.entry_price - layer.stop) * side) * facts.multiplier
                     + roundtrip_slip + fees) for layer in account.layers), ZERO)
        available_risk = max(ZERO, equity * profile.max_risk_fraction - held_risk)
        qty = min(int((budget / margin_per).to_integral_value(rounding=ROUND_FLOOR)),
                  int((risk_budget / risk_per).to_integral_value(rounding=ROUND_FLOOR)),
                  int((available_margin / margin_per).to_integral_value(rounding=ROUND_FLOOR)),
                  int((available_risk / risk_per).to_integral_value(rounding=ROUND_FLOOR)))
        return max(0, qty)

    def execute(execution: ExecutionBar) -> None:
        nonlocal pending, setup, add_setup, stop, entry_atr, first_entry_atr
        nonlocal frozen_level, first_budget, first_risk, first_qty
        nonlocal adds, stage, confirmed_count, pullback_index, hold_frequency
        nonlocal entry_5m_index, peak_profit, reduction_used
        bar = execution.bar
        raw_facts = execution.facts
        facts = _scenario_facts(raw_facts, scenario)
        if not pending or bar.bar_end - timedelta(minutes=1) <= cast(datetime, pending['effective_after']):
            return
        if pending['action'] in ('OPEN', 'ADD') and bar.trading_day != pending['trading_day']:
            record(bar.bar_end, 'CANCEL', cast(int, pending['side']), 'STALE_OPENING_DAY', account.qty)
            pending = None
            return
        if pending['action'] in ('OPEN', 'ADD'):
            if bar.session_open_at is None or bar.session_open_at != pending['session_open_at']:
                reject(bar.bar_end, 'SESSION_FACT_MISSING_OR_CHANGED', cast(int, pending['side']))
                pending = None
                return
            start = bar.bar_end - timedelta(minutes=1)
            ends, confirmations = session_minutes.get((bar.physical_contract, bar.session_open_at), ([], []))
            elapsed = min(bisect_right(ends, start), bisect_right(confirmations, start))
            if elapsed < profile.opening_minutes:
                reject(bar.bar_end, 'OPENING_20_MINUTES', cast(int, pending['side']))
                return
        if not bar.observation_eligible or bar.volume <= 0 or not bar.low <= bar.open <= bar.high:
            reject(bar.bar_end, 'NO_EXECUTABLE_VOLUME_OR_PRICE')
            return
        if facts.physical_contract != pending['contract']:
            reject(bar.bar_end, 'PHYSICAL_CONTRACT_MISMATCH')
            return
        action = str(pending['action'])
        side = cast(int, pending['side'])
        trade_side = side if action in ('OPEN', 'ADD') else -account.side
        if trade_side == 0:
            pending = None
            return
        slip_ticks = 2 if scenario == 'double_slippage' else 1
        price = bar.open + D(trade_side * slip_ticks) * facts.tick_size
        if price < facts.limit_down or price > facts.limit_up or \
           (trade_side > 0 and bar.open >= facts.limit_up) or \
           (trade_side < 0 and bar.open <= facts.limit_down):
            reject(bar.bar_end, 'LIMIT_BLOCKED', side)
            return
        if (price / facts.tick_size) % 1 != 0:
            reject(bar.bar_end, 'OFF_TICK_EXECUTION', side)
            return
        if action in ('OPEN', 'ADD'):
            if account.daily_halt or account.closed_loss_streak >= profile.consecutive_losses_halt or \
               (account.opening_direction is not None and account.opening_direction != side):
                reject(bar.bar_end, 'OPENING_HALT', side)
                pending = None
                return
            if action == 'ADD' and (frozen_level is None or
                                    (price - frozen_level) * side <= 0 or
                                    net_unrealized(price, facts) <= 0):
                reject(bar.bar_end, 'STALE_ADD_DIRECTION_OR_PROFIT', side)
                pending = None
                return
            qty = open_qty(price, facts, side, action)
            if qty < 1:
                reject(bar.bar_end, 'MIN_LOT_BUDGET', side,
                       {'price': str(price), 'stop': str(stop)})
                pending = None
                return
            if action == 'OPEN':
                first_budget = account.cash * profile.initial_margin_fraction
                first_risk = account.cash * profile.initial_risk_fraction
                first_qty = qty
                first_entry_atr = entry_atr
                adds = 0
                stage = 'TRIAL'
                stage_rows.append({'at': (bar.bar_end - timedelta(minutes=1)).isoformat(),
                                   'stage': stage, 'source_identity': bar.source_identity})
                confirmed_count = 0
                pullback_index = None
                hold_frequency = '5m'
                peak_profit = ZERO
                reduction_used = set()
                entry_5m_index = last_5m_index
            else:
                adds += 1
                stage = 'TREND' if hold_frequency == '1d' else 'BREAKOUT_CONFIRMED'
                pullback_index = None
                stage_rows.append({'at': (bar.bar_end - timedelta(minutes=1)).isoformat(),
                                   'stage': stage, 'source_identity': bar.source_identity})
            layer_stop = cast(D, stop) if action == 'OPEN' else price
            fill = account.open(side, qty, price, facts, bar.bar_end - timedelta(minutes=1),
                                layer_stop, cast(D, entry_atr), cast(D, frozen_level),
                                'TRIAL' if action == 'OPEN' else 'ADD')
            fill['reason'] = pending['reason']
        else:
            qty = abs(account.qty) if action == 'CLEAR' else min(
                abs(account.qty) - 1,
                int((D(abs(account.qty)) * profile.reduce_fraction).to_integral_value(rounding=ROUND_CEILING)))
            layer_id = None
            if action == 'LAYER_CLEAR':
                layer_id = str(cast(dict[str, object], pending['facts'])['layer_id'])
                layer = next((x for x in account.layers if x.layer_id == layer_id), None)
                qty = layer.qty if layer else 0
            if qty < 1:
                reject(bar.bar_end, 'UNSPLITTABLE_ONE_LOT', account.side)
                pending = None
                return
            fill = account.close(qty, price, facts, bar.bar_end - timedelta(minutes=1), layer_id=layer_id)
            fill['reason'] = pending['reason']
            account.mark(price, facts)
            if action == 'REDUCE':
                add_setup = None
                pullback_index = None
                reduction_used.add(str(pending['reason']))
            if account.qty == 0:
                stop = entry_atr = first_entry_atr = frozen_level = None
                setup = None
                add_setup = None
                stage = 'FLAT'
                hold_frequency = '5m'
        fill['observed_at'] = bar.confirmed_at.isoformat()
        fill['source_bar_end'] = bar.bar_end.isoformat()
        all_fills.append(fill)
        layer_rows.append({'at': (bar.bar_end - timedelta(minutes=1)).isoformat(),
                           'action': action, 'layers': [
                               {'layer_id': x.layer_id, 'qty': x.qty, 'entry_price': str(x.entry_price),
                                'trading_day': x.trading_day.isoformat(), 'stop': str(x.stop),
                                'stage': x.stage} for x in account.layers]})
        fill_at = bar.bar_end - timedelta(minutes=1)
        equity_rows.append({'at': fill_at.isoformat(),
                            'equity': str(account.equity(price, facts)),
                            'cash': str(account.cash), 'qty': account.qty,
                            'physical_contract': account.contract or bar.physical_contract})
        pending = None

    def process_5m(s: Snapshot, index: int) -> None:
        nonlocal setup, add_setup, stop, entry_atr, frozen_level, last_5m, last_5m_index
        nonlocal peak_profit, ready_observation, fact_blocked, stage, confirmed_count
        nonlocal pullback_index, hold_frequency, pending
        bar = s.bar
        at = bar.confirmed_at
        if not bar.observation_eligible or not since <= bar.trading_day <= through:
            return
        if current_facts is None or current_facts.physical_contract != bar.physical_contract or \
           current_facts.trading_day != bar.trading_day:
            reject(at, 'EXECUTION_FACTS_MISSING', facts={'source_identity': bar.source_identity})
            fact_blocked = True
            return
        last_5m, last_5m_index = s, index
        local = snapshots[bar.physical_contract]
        daily = context_snapshot(bar.physical_contract, '1d', at, bar.bar_end)
        weekly = context_snapshot(bar.physical_contract, '1w', at, bar.bar_end)
        confirm = context_snapshot(bar.physical_contract, '15m', at, bar.bar_end)
        if confirm is not None and (
            confirm.bar.trading_day != bar.trading_day or
            confirm.bar.bar_end > bar.bar_end or
            completed_trading_minutes_since(bar.physical_contract, confirm.bar.bar_end,
                                            bar.bar_end, at) >= 15
        ):
            confirm = None
        if s.ma is not None and s.atr is not None and daily is not None and daily.ma is not None and \
           confirm is not None and confirm.ma is not None:
            ready_observation = True
        daily_side = direction(daily) if daily else 0
        weekly_side = direction(weekly) if weekly else 0
        confirm_side = direction(confirm) if confirm else 0
        daily_ready = daily is not None and daily.ma is not None
        trial_side = direction(s) if daily is not None and daily_ready and \
            (daily.chop or daily_side == 0) else daily_side
        direction_ready = (daily_ready and trial_side != 0 and direction(s) == trial_side and
                           confirm_side == trial_side and weekly_side != -trial_side and
                           (daily_side != -trial_side or (daily is not None and daily.chop)))
        indicator_ready = s.atr is not None and s.atr > 0 and s.ma is not None
        opening_ready = (bar.session_open_at is not None and
                         completed_session_minutes(bar, at) >= profile.opening_minutes)
        basic_ready = direction_ready and indicator_ready and opening_ready
        if account.qty:
            side = account.side
            net_profit = net_unrealized(bar.close, current_facts)
            profit_per_lot = net_profit / abs(account.qty)
            peak_profit = max(peak_profit, profit_per_lot)
            if pullback_index is not None:
                broken = frozen_level is None or \
                    (bar.low < frozen_level if side > 0 else bar.high > frozen_level)
                if broken or not basic_ready or net_profit <= 0:
                    reason = ('PULLBACK_LEVEL_BROKEN' if broken else
                              'PULLBACK_CONTEXT_UNREADY' if not basic_ready else 'PULLBACK_NONPROFIT')
                    record(at, 'SETUP_INVALIDATED', side, reason, account.qty)
                    pullback_index = None
                    if hold_frequency == '5m' and stage == 'PULLBACK':
                        stage = 'BREAKOUT_CONFIRMED'
                    if pending and pending['action'] == 'ADD':
                        record(at, 'CANCEL', side, 'STALE_ADD_SETUP', account.qty)
                        pending = None
            if stage == 'TRIAL' and index > entry_5m_index and frozen_level is not None:
                if (bar.close - frozen_level) * side > 0:
                    confirmed_count += 1
                    if confirmed_count >= profile.confirmation_bars:
                        stage = 'BREAKOUT_CONFIRMED'
                        stage_rows.append({'at': at.isoformat(), 'stage': stage, 'source_identity': bar.source_identity})
                else:
                    confirmed_count = 0
            if first_entry_atr is not None and net_profit >= abs(account.qty) * first_entry_atr * profile.breakeven_atr_multiple * current_facts.multiplier:
                for layer in account.layers:
                    exit_fee = current_facts.fees.amount(
                        'close_today' if layer.trading_day == bar.trading_day else 'close',
                        layer.entry_price, current_facts.multiplier)
                    entry_fee = layer.open_fee / layer.original_qty
                    new_stop = layer.entry_price + side * ((entry_fee + exit_fee) / current_facts.multiplier)
                    layer.stop = max(layer.stop, new_stop) if side > 0 else min(layer.stop, new_stop)
            if (hold_frequency == '5m' and s.ma is not None and (bar.close - s.ma) * side < 0) or \
               (daily_side == -side and not (daily.chop if daily else False)) or \
               (index - entry_5m_index >= profile.no_profit_bars and net_profit <= 0):
                reason = ('MA21_CLEAR' if hold_frequency == '5m' and s.ma is not None and
                          (bar.close - s.ma) * side < 0 else 'DAILY_REVERSE' if daily_side == -side
                          else 'FIVE_BARS_NO_PROFIT')
                queue(at, 'CLEAR', side, reason, {'source_identity': bar.source_identity})
                return
            if hold_frequency == '5m' and first_entry_atr is not None and first_qty and \
               net_profit >= D(2) * first_entry_atr * first_qty * current_facts.multiplier and \
               weekly_side == side and daily_side == side and not (daily.chop if daily else False):
                hold_frequency = '1d'
                stage = 'TREND'
                stage_rows.append({'at': at.isoformat(), 'stage': stage, 'source_identity': bar.source_identity})
            reasons: list[str] = []
            if index - entry_5m_index <= profile.fast_profit_bars and net_profit >= margin_used(current_facts, bar.close) * profile.fast_profit_margin_fraction and 'FAST_PROFIT' not in reduction_used:
                reasons.append('FAST_PROFIT')
            if peak_profit > 0 and profit_per_lot <= peak_profit * (1 - profile.peak_drawdown_fraction) and 'PEAK_DRAWDOWN' not in reduction_used:
                reasons.append('PEAK_DRAWDOWN')
            divergence = divergences[bar.physical_contract][side][index]
            reverse_cross = any(x.macd_cross == -side for x in local['5m'][max(0,index-profile.trigger_window+1):index+1])
            if divergence and reverse_cross:
                key = f'DIVERGENCE:{divergence[0]}:{divergence[1]}'
                if key not in reduction_used:
                    reasons.append(key)
            if hold_frequency == '5m' and s.histogram is not None and index > 0 and \
               local['5m'][index-1].histogram is not None and \
               (s.macd_cross == -side or (s.histogram - cast(D, local['5m'][index-1].histogram)) * side < 0):
                if net_profit <= 0:
                    queue(at, 'CLEAR', side, 'FIVE_MINUTE_MACD_LOSS')
                    return
                if 'FIVE_MINUTE_MACD_REDUCE' not in reduction_used:
                    reasons.append('FIVE_MINUTE_MACD_REDUCE')
            if reasons:
                if abs(account.qty) == 1:
                    if pending and pending['action'] in ('CLEAR', 'REDUCE'):
                        return
                    reduction_used.update(reasons)
                    record(at, 'REDUCE_SKIPPED', side, 'UNSPLITTABLE_ONE_LOT', account.qty,
                           {'all_reasons': reasons})
                    return
                queue(at, 'REDUCE', side, reasons[0], {'all_reasons': reasons})
                return
            if not basic_ready or pending or adds >= profile.max_adds or net_profit <= 0 or frozen_level is None:
                return
            if stage == 'TRIAL':
                return
            if index > entry_5m_index and (bar.close - local['5m'][index-1].bar.close) * side < 0 and \
               (bar.low >= frozen_level if side > 0 else bar.high <= frozen_level):
                pullback_index = index
                if hold_frequency == '5m' and stage != 'PULLBACK':
                    stage = 'PULLBACK'
                    stage_rows.append({'at': at.isoformat(), 'stage': stage,
                                       'source_identity': bar.source_identity})
            if pullback_index is not None and index > pullback_index and s.breakout == side and \
               s.volume_spike and s.breakout_level is not None and bar.open_interest is not None:
                previous_oi = local['5m'][index-1].bar.open_interest
                if previous_oi is not None and bar.open_interest > previous_oi and \
                   (bar.close - frozen_level) * side > 0 and s.dif is not None and \
                   s.dea is not None and s.histogram is not None and \
                   s.dif * side > 0 and (s.dif - s.dea) * side > 0 and \
                   s.histogram * side > 0:
                    stop = (min(cast(D, s.ma), s.breakout_level) - current_facts.tick_size if side > 0 else
                            max(cast(D, s.ma), s.breakout_level) + current_facts.tick_size)
                    entry_atr = s.atr
                    queue(at, 'ADD', side, 'REBREAKOUT_ADD',
                          {'source_identity': bar.source_identity, 'level': str(s.breakout_level)})
            return

        if pending:
            return
        if account.daily_halt or account.closed_loss_streak >= profile.consecutive_losses_halt:
            reject(at, 'OPENING_HALT')
            return
        if not direction_ready:
            reject(at, 'MULTI_TIMEFRAME_DIRECTION_UNREADY')
            return
        if not indicator_ready:
            reject(at, 'BASE_CONSTRAINT')
            return
        if bar.session_open_at is None:
            reject(at, 'SESSION_FACT_MISSING')
            return
        if not opening_ready:
            reject(at, 'OPENING_20_MINUTES', trial_side)
            return
        evidence = setup_evidence(local['5m'], index, trial_side, profile)
        if evidence is None:
            return
        trigger_key = f"{bar.physical_contract}|{evidence['trigger_at']}|{evidence['trigger']}"
        if trigger_key in blocked_setup_sources:
            return
        blocked_setup_sources.add(trigger_key)
        frozen_level = cast(D, evidence['level'])
        entry_atr = s.atr
        stop = (min(cast(D, s.ma), frozen_level) - current_facts.tick_size if trial_side > 0 else
                max(cast(D, s.ma), frozen_level) + current_facts.tick_size)
        if (bar.close - stop) * trial_side <= 0:
            reject(at, 'INVALID_STOP_SIDE', trial_side)
            return
        record(at, 'SETUP', trial_side, str(evidence['trigger']), 0,
               {'level': str(evidence['level']), 'votes': evidence['votes'],
                'all_triggers': evidence['all_triggers'], 'trigger_source': evidence['trigger_source']})
        queue(at, 'OPEN', trial_side, 'TRIAL_SETUP',
              {'setup_trigger': evidence['trigger'], 'frozen_level': str(frozen_level),
               'votes': evidence['votes'], 'source_identity': bar.source_identity,
               'weekly': 'UNKNOWN' if weekly_side == 0 else _side_name(weekly_side),
               'daily': 'CHOP' if daily and daily.chop else _side_name(daily_side) if daily_side else 'FLAT'})

    # Historical replay events are ordered by when each fact becomes observable.
    events: list[tuple[datetime, int, str, object]] = []
    for e in execution_bars:
        start = e.bar.bar_end - timedelta(minutes=1)
        events.append((start, 3, 'EXECUTE', e))
        events.append((e.bar.confirmed_at, 0, 'ONE_MINUTE_CLOSE', e))
    for contract, frequencies in snapshots.items():
        for index, s in enumerate(frequencies.get('5m', [])):
            if s.bar.observation_eligible and since <= s.bar.trading_day <= through:
                events.append((s.bar.confirmed_at, 1, 'FIVE_MINUTE_CLOSE', (contract, index, s)))
        for s in frequencies.get('1d', []):
            if s.bar.observation_eligible and since <= s.bar.trading_day <= through:
                events.append((s.bar.confirmed_at, 2, 'DAILY_CLOSE', (contract, s)))
    events.sort(key=lambda x: (x[0], x[1]))

    for at, _, kind, payload in events:
        if interrupted:
            break
        if kind == 'EXECUTE':
            execution_event = cast(ExecutionBar, payload)
            bar = execution_event.bar
            if current_contract != bar.physical_contract:
                if current_contract is not None:
                    if account.qty or pending:
                        interrupted = True
                        record(at, 'INTERRUPTED', account.side, 'ROLLOVER_WITH_POSITION_OR_PENDING', account.qty,
                               {'old_contract': current_contract, 'new_contract': bar.physical_contract})
                        break
                    segments.append({'physical_contract': current_contract, 'closed_trades': len(account.closed_trades),
                                     'final_equity': str(account.cash)})
                    setup = None
                    add_setup = None
                    stop = entry_atr = first_entry_atr = frozen_level = first_budget = first_risk = None
                    first_qty = adds = 0
                    stage = 'FLAT'
                    confirmed_count = 0
                    pullback_index = None
                    hold_frequency = '5m'
                    last_5m = None
                    last_5m_index = 0
                    peak_profit = ZERO
                    reduction_used = set()
                current_contract = bar.physical_contract
            facts = _scenario_facts(execution_event.facts, scenario)
            current_facts = facts
            if account.trading_day != bar.trading_day:
                account.begin_day(bar.trading_day, account._mark, account._mark_facts,
                                  can_reset=account.qty == 0 and pending is None)
            execute(execution_event)
        elif kind == 'ONE_MINUTE_CLOSE':
            execution_event = cast(ExecutionBar, payload)
            bar = execution_event.bar
            if current_contract != bar.physical_contract or not account.qty:
                continue
            facts = _scenario_facts(execution_event.facts, scenario)
            value = account.mark(bar.close, facts)
            profit = net_unrealized(bar.close, facts)
            peak_profit = max(peak_profit, profit / abs(account.qty))
            if account.daily_halt:
                queue(at, 'CLEAR', account.side, 'DAILY_2_PERCENT_HALT')
            else:
                breached = [layer for layer in account.layers
                            if ((bar.close - layer.stop) * account.side < 0 if layer.stage == 'ADD'
                                else (bar.close - layer.stop) * account.side <= 0)]
                base = next((layer for layer in account.layers if layer.stage == 'TRIAL'), None)
                if base is not None and base in breached:
                    queue(at, 'CLEAR', account.side, 'HARD_STOP', {'layer_id': base.layer_id})
                elif breached:
                    layer = breached[-1]
                    queue(at, 'LAYER_CLEAR', account.side, 'LAYER_GUARD',
                          {'layer_id': layer.layer_id, 'layer_stop': str(layer.stop)})
            if hold_frequency == '5m' and last_5m is not None and last_5m.bar.bar_end < bar.bar_end and \
                 last_5m.bar.confirmed_at <= at and profit > 0:
                anchor = last_5m.bar.low if account.side > 0 else last_5m.bar.high
                if (bar.close - anchor) * account.side < 0:
                    key = f'ANCHOR:{last_5m.bar.source_identity}'
                    if key not in reduction_used:
                        if abs(account.qty) == 1:
                            reduction_used.add(key)
                            record(at, 'REDUCE_SKIPPED', account.side, 'UNSPLITTABLE_ONE_LOT',
                                   account.qty, {'anchor': str(anchor), 'trigger': key})
                        else:
                            queue(at, 'REDUCE', account.side, key, {'anchor': str(anchor)})
            if bar.session_close_at is not None and bar.session_close_at - timedelta(minutes=2) <= bar.bar_end <= bar.session_close_at and profit < 0:
                queue(at, 'CLEAR', account.side, 'FINAL_SESSION_LOSS')
            equity_rows.append({'at': at.isoformat(), 'equity': str(value), 'cash': str(account.cash),
                                'qty': account.qty, 'physical_contract': account.contract})
        elif kind == 'FIVE_MINUTE_CLOSE':
            contract, index, s = cast(tuple[str, int, Snapshot], payload)
            if current_contract == contract:
                process_5m(s, index)
                if fact_blocked:
                    break
        else:
            contract, s = cast(tuple[str, Snapshot], payload)
            if current_contract == contract and account.qty:
                if direction(s) == -account.side and not s.chop:
                    queue(at, 'CLEAR', account.side, 'DAILY_REVERSE',
                          {'source_identity': s.bar.source_identity})
                elif hold_frequency == '1d':
                    daily_history = snapshots[contract].get('1d', [])
                    position = daily_history.index(s)
                    if position >= 9:
                        ma10 = sum((x.bar.close for x in daily_history[position-9:position+1]), ZERO) / 10
                        if (s.bar.close - ma10) * account.side < 0:
                            queue(at, 'CLEAR', account.side, 'DAILY_MA10_CLEAR',
                                  {'source_identity': s.bar.source_identity, 'ma10': str(ma10)})
                    if position > 0:
                        previous = daily_history[position-1].bar
                        anchor = previous.low if account.side > 0 else previous.high
                        if daily_anchor_trigger(account.qty, s.bar.close, previous) and \
                           'DAILY_ANCHOR' not in reduction_used:
                            queue(at, 'REDUCE', account.side, 'DAILY_ANCHOR', {'anchor': str(anchor)})
                    previous_snapshot = daily_history[position-1] if position > 0 else None
                    profit = net_unrealized(s.bar.close, cast(ExecutionFacts, current_facts))
                    reaction = daily_macd_reaction(s, previous_snapshot, account.side, profit)
                    if reaction is not None:
                        if reaction == 'CLEAR':
                            queue(at, 'CLEAR', account.side, 'DAILY_MACD_LOSS')
                        elif 'DAILY_MACD_REDUCE' not in reduction_used:
                            if abs(account.qty) > 1:
                                queue(at, 'REDUCE', account.side, 'DAILY_MACD_REDUCE')
                            else:
                                reduction_used.add('DAILY_MACD_REDUCE')
                                record(at, 'REDUCE_SKIPPED', account.side,
                                       'UNSPLITTABLE_ONE_LOT', account.qty)

    if current_contract is not None:
        segments.append({'physical_contract': current_contract, 'closed_trades': len(account.closed_trades),
                         'final_equity': str(account.cash) if not account.qty else None})
    all_trades.extend(account.closed_trades)
    all_fills.extend(x for x in account.fills if x not in all_fills)
    status = ('EXECUTION_FACTS_MISSING' if fact_blocked else
              'ROLLOVER_INTERRUPTED' if interrupted else
              'DATA_INSUFFICIENT' if not ready_observation else
              'PENDING_UNFILLED' if pending else
              'COMPLETED')
    if status == 'COMPLETED' and not account.qty:
        terminal_at = execution_bars[-1].bar.confirmed_at
        if not equity_rows or datetime.fromisoformat(str(equity_rows[-1]['at'])) < terminal_at:
            equity_rows.append({'at': terminal_at.isoformat(), 'equity': str(account.cash),
                                'cash': str(account.cash), 'qty': 0,
                                'physical_contract': current_contract})
    if status == 'COMPLETED' and account.qty:
        last_equity = str(equity_rows[-1]['equity']) if equity_rows else None
    else:
        last_equity = str(account.cash) if status == 'COMPLETED' else None
    final = D(last_equity) if last_equity is not None else None
    peaks: list[D] = []
    max_dd = ZERO
    for row in equity_rows:
        val = D(str(row['equity']))
        peak = max(peaks[-1], val) if peaks else max(profile.initial_cash, val)
        peaks.append(peak)
        if peak > 0:
            max_dd = max(max_dd, (peak - val) / peak * 100)
    summary = {'status': status, 'initial_cash': str(profile.initial_cash),
               'final_equity': str(final) if final is not None else None,
               'account_return_pct': str((final / profile.initial_cash - 1) * 100) if final is not None else None,
               'max_drawdown_pct': str(max_dd) if status == 'COMPLETED' else None,
               'closed_trades': len(all_trades),
               'total_fees': str(account.total_fees) if status == 'COMPLETED' else None,
               'ending_qty': account.qty, 'annual_eligible': False}
    stage_counts = {name: sum(row['stage'] == name for row in stage_rows)
                    for name in ('TRIAL', 'BREAKOUT_CONFIRMED', 'PULLBACK', 'TREND')}
    opened_layers = [fill for fill in all_fills if fill['action'] == 'OPEN']
    closed_fills = [fill for fill in all_fills if fill['action'] == 'CLOSE']
    layer_summary = {'opened_layers': len(opened_layers),
                     'closed_layer_events': sum(len(cast(list[object], fill['layer_closes']))
                                                for fill in closed_fills),
                     'named_guard_closes': sum(fill.get('named_layer_id') is not None
                                               for fill in closed_fills),
                     'remaining_layers': len(account.layers),
                     'remaining_average_price': str(account.average_price) if account.layers else None,
                     'realized_gross_pnl': str(sum((D(str(fill['realized_pnl']))
                                                    for fill in closed_fills), ZERO)),
                     'close_fees': str(sum((D(str(fill['fee'])) for fill in closed_fills), ZERO))}
    return {'summary': summary, 'decisions': decisions, 'trades': all_trades,
            'equity': equity_rows, 'fills': all_fills,
            'stages': stage_rows, 'layers': layer_rows,
            'projection': {'hold_frequency': hold_frequency,
                           'open_layers': [{'layer_id': x.layer_id, 'qty': x.qty,
                                            'basis': str(x.entry_price), 'stop': str(x.stop)}
                                           for x in account.layers]},
            'diagnostics': {'status': status, 'rejections': dict(rejections),
                            'segments': segments, 'pending_order': bool(pending),
                            'stage_counts': stage_counts,
                            'stage_summary': {'last_stage': stage, 'transition_count': len(stage_rows),
                                              'upgraded_to_daily': stage_counts['TREND'] > 0,
                                              'first_atr': str(first_entry_atr) if first_entry_atr else None,
                                              'hold_frequency': hold_frequency},
                            'layer_summary': layer_summary,
                            'case_parity': 'PENDING', 'oos_status': 'NOT_PROVEN'}}
