"""Single-contract offline SuBing account replay. No provider, broker or Runtime I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, time
from decimal import Decimal, localcontext
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from .new_subing import ExecutionBar
from .subing_decision import DecisionModel, _wire, candidate_side, daily_allows, directional_frame, direction_sign

D = Decimal
VERSION = 'subing_jm30_account_next1m_close_v5'
INITIAL_CASH = D('100000')
TECHNICAL_FIELDS = set('event_id kind at contract trading_day close daily_direction daily_at day_end_window m30'.split())


def replay(executions: Sequence[ExecutionBar], observations: Mapping[datetime, dict], run_id: str, *, slippage_ticks: int = 1, execution_model: str = 'completed_close', research_profile: str | None = None) -> dict:
    """Replay verified complete 1m input; observations contain no financial overrides.

    Historical confirmation is assumed at bar end. Fills use the strictly later
    completed minute's close +/- slippage ticks, inside OHLC and daily limits.
    theoretical_open instead assumes up to three lots at a strictly later minute
    start, using open plus adverse slippage without future OHLCV filtering.
    Its liquidity is assumed, not evidenced. Fixed research_profile scenarios
    alter only the declared decision parameters and carry separate identities.
    The caller proves coverage, rank1 ownership and historical execution sources.
    """
    if type(slippage_ticks) is not int or slippage_ticks not in (1, 2, 3):
        raise ValueError('ACCOUNT_SLIPPAGE_SCENARIO_INVALID')
    if execution_model not in ('completed_close', 'theoretical_open'):
        raise ValueError('ACCOUNT_EXECUTION_MODEL_INVALID')
    if research_profile is not None and execution_model != 'theoretical_open':
        raise ValueError('ACCOUNT_RESEARCH_PROFILE_REQUIRES_THEORETICAL_OPEN')
    with localcontext() as ctx:
        ctx.prec = 28
        return _replay(executions, observations, run_id, slippage_ticks, execution_model, research_profile)


def _replay(executions, observations, run_id, slippage_ticks, execution_model, research_profile):
    at_open = execution_model == 'theoretical_open'
    if not executions:
        raise ValueError('ACCOUNT_INPUT_EMPTY')
    contract = executions[0].bar.physical_contract
    model = DecisionModel(contract, run_id, research_profile=research_profile)
    prior = None
    observation_ids = set()
    multiplier = executions[0].facts.multiplier
    for execution in executions:
        if type(execution) is not ExecutionBar:
            raise ValueError('ACCOUNT_EXECUTION_TYPE')
        b, f = execution.bar, execution.facts
        if b.physical_contract != contract or b.product.lower() != 'jm' or f.multiplier != multiplier:
            raise ValueError('ACCOUNT_PHYSICAL_IDENTITY_CHANGED')
        if b.volume != b.volume.to_integral_value():
            raise ValueError('ACCOUNT_FRACTIONAL_VOLUME')
        if b.confirmed_at != b.bar_end or not b.observation_eligible:
            raise ValueError('ACCOUNT_CONFIRMATION_NOT_PROVEN')
        if b.session_open_at is None or b.session_close_at is None or b.bar_end - timedelta(minutes=1) < b.session_open_at:
            raise ValueError('ACCOUNT_SESSION_MISSING')
        if prior is not None and (b.bar_end <= prior.bar_end or b.trading_day < prior.trading_day):
            raise ValueError('ACCOUNT_INPUT_ORDER')
        if prior is not None and b.session_open_at == prior.session_open_at and b.bar_end - prior.bar_end != timedelta(minutes=1):
            raise ValueError('ACCOUNT_MINUTE_GAP')
        for value in (b.open, b.high, b.low, b.close):
            if value % f.tick_size != 0 or not f.limit_down <= value <= f.limit_up:
                raise ValueError('ACCOUNT_PRICE_FACT_CONFLICT')
        o = observations.get(b.bar_end)
        if type(o) is not dict or set(o) != TECHNICAL_FIELDS:
            raise ValueError('ACCOUNT_OBSERVATION_FIELDS')
        if o['kind'] != 'observe' or o['contract'] != contract or datetime.fromisoformat(o['at']) != b.bar_end or o['trading_day'] != b.trading_day.isoformat() or type(o['close']) is not str or D(o['close']) != b.close:
            raise ValueError('ACCOUNT_OBSERVATION_IDENTITY')
        if not isinstance(o['event_id'], str) or not o['event_id'] or o['event_id'] in observation_ids or o['event_id'].startswith('account:'):
            raise ValueError('ACCOUNT_OBSERVATION_ID')
        observation_ids.add(o['event_id'])
        prior = b
    if len(observations) != len(executions):
        raise ValueError('ACCOUNT_OBSERVATION_COVERAGE')
    cash, fees, gross_realized = INITIAL_CASH, D('0'), D('0')
    layers = {}
    fills, closed_rounds, trace, execution_events, daily = [], [], [], [], []
    current_day, day_start, last_equity = None, INITIAL_CASH, INITIAL_CASH
    round_start, round_at, round_fills = None, None, []

    def equity(mark):
        return cash + sum((direction_sign(layer['side']) * (mark - layer['price']) * multiplier for layer in layers.values()), D('0'))

    def close_fee(layer, price, facts):
        kind = 'close_today' if layer['trading_day'] == facts.trading_day else 'close'
        return facts.fees.amount(kind, price, multiplier), kind

    def finance(mark, facts, side):
        sign = direction_sign(side)
        ratio = facts.long_margin_ratio if side == 'LONG' else facts.short_margin_ratio
        eq = equity(mark)
        used = len(layers) * max(mark, facts.prev_settlement) * multiplier * ratio
        estimated_open_fee = facts.fees.amount('open', mark + sign * facts.tick_size * slippage_ticks, multiplier)
        prospective_equity = eq - facts.tick_size * slippage_ticks * multiplier - estimated_open_fee
        prospective_margin = (len(layers)+1) * max(mark + sign * facts.tick_size * slippage_ticks, facts.prev_settlement) * multiplier * ratio
        round_net = eq-round_start if round_start is not None else D('0')
        day_net = eq-day_start
        layer_nets = {key: direction_sign(layer['side'])*(mark-layer['price'])*multiplier-layer['open_fee']-close_fee(layer,mark,facts)[0]
            for key, layer in layers.items()}
        remainder = sum(layer_nets.values(), D('0'))
        base_net = next((layer_nets[key] for key, layer in layers.items() if layer['kind'] == 'OPEN'), None)
        allowed = (len(layers) < 3 and prospective_equity > 0 and prospective_margin <= prospective_equity*D('.70')
            and prospective_margin <= prospective_equity and round_net > D('-2000') and day_net > D('-5000')
            and (round_start is None or prospective_equity-round_start > D('-2000'))
            and prospective_equity-day_start > D('-5000'))
        return dict(equity=eq, cash=cash, margin=used, available=eq-used,
            round_net=round_net, day_net=day_net, remaining_net=remainder, base_net=base_net, layer_nets=layer_nets,
            admission=allowed, round_loss=round_net <= D('-2000'), day_loss=day_net <= D('-5000'))

    for index, execution in enumerate(executions):
        b, f = execution.bar, execution.facts
        technical = observations[b.bar_end]
        if current_day != b.trading_day:
            current_day, day_start = b.trading_day, last_equity
        side = model.side or (model.pending['side'] if model.pending else candidate_side(technical['m30'] or model.latest_frame))
        sign = direction_sign(side)
        pending = deepcopy(model.pending)
        execution_at = b.bar_end - timedelta(minutes=1) if at_open else b.bar_end
        mark = b.open if at_open else b.close
        known = observations[executions[index-1].bar.bar_end] if at_open and index else technical
        local_execution = execution_at.astimezone(ZoneInfo('Asia/Shanghai'))
        end_window = (local_execution.date() == b.trading_day and local_execution.time() >= time(14, 50)) if at_open else known['day_end_window']
        if pending is not None and execution_at > pending['at']:
            opening = pending['kind'] in ('OPEN','ADD')
            buying = (opening and side == 'LONG') or (not opening and side == 'SHORT')
            price = mark + (f.tick_size if buying else -f.tick_size) * slippage_ticks
            pre = finance(mark,f,side)
            current_frame = directional_frame(known['m30'], side)
            # At open, prior completed technical events have already been consumed
            # by DecisionModel; pending cancellation/exit obligations carry their effect.
            current_exit = not at_open and current_frame is not None and any(current_frame.get(key) is True for key in ('below_ema', 'below_previous_low', 'high_death'))
            protected_layer = any(layer['kind'] == 'ADD' and sign * (mark - layer['price']) < 0 for layer in layers.values())
            frame_unknown = current_frame is not None and (current_frame.get('minute_angle') is None or any(current_frame.get(key) is None for key in ('near_zero_golden','above_ema','volume_effective','below_previous_low','high_death','below_ema','qualified_pullback')))
            fixed_stop = model.initial_stop is not None and sign * (mark - model.initial_stop) <= 0
            profit_hit = model.profit_target is not None and not model.profit_taken and sign * (mark - model.profit_target) >= 0
            reject = None
            if opening and pending['cancel_requested']:
                reject = 'CANCEL_REQUESTED'
            elif opening and (current_exit or protected_layer or fixed_stop or profit_hit):
                reject = 'EXIT_PRIORITY_AT_EXECUTION'
            elif opening and frame_unknown:
                reject = 'TECHNICAL_FACTS_UNKNOWN_AT_EXECUTION'
            elif opening and (end_window or not daily_allows(known['daily_direction'], side)):
                reject = 'OPENING_CONTEXT_CHANGED'
            elif opening and ((model.day_halted and model.day == b.trading_day) or not pre['admission']):
                reject = 'OPENING_FINANCIAL_RECHECK'
            elif pending['kind'] == 'ADD' and (pre['base_net'] is None or pre['base_net'] <= 0):
                reject = 'BASE_NET_NOT_POSITIVE_AT_EXECUTION'
            elif pending['kind'] == 'ADD' and sign * (mark - pending['breakout_level']) <= 0:
                reject = 'PULLBACK_BREAKOUT_LOST_AT_EXECUTION'
            elif pending['kind'] == 'OPEN' and sign * (price - pending['initial_stop']) <= 0:
                reject = 'INITIAL_STOP_INVALID_AT_EXECUTION'
            elif not at_open and b.volume <= 0:
                reject = 'ZERO_VOLUME'
            elif not at_open and not b.low <= price <= b.high:
                reject = 'SLIPPAGE_OUTSIDE_BAR'
            elif not f.limit_down <= price <= f.limit_up:
                reject = 'EXCHANGE_LIMIT'
            elif (buying and (b.open if at_open else b.low) == f.limit_up) or (not buying and (b.open if at_open else b.high) == f.limit_down):
                reject = 'LOCKED_LIMIT'
            targets = [] if opening else pending['layer_ids'][:3 if at_open else int(b.volume)]
            if not opening and not targets and reject is None:
                reject = 'INSUFFICIENT_VOLUME'
            if reject:
                execution_events.append(dict(at=execution_at,decision_id=pending['decision_id'],kind='CANCEL' if opening else 'UNFILLED',reason=reject))
                if opening:
                    result = model.apply(dict(event_id=f'account:cancel:{index}',kind='ack',at=execution_at.isoformat(),contract=contract,
                        decision_id=pending['decision_id'],status='CANCELLED',price=None,layer_ids=[]))
                    trace.append(result)
            else:
                if opening and not at_open and b.volume < 1:
                    raise ValueError('ACCOUNT_FRACTIONAL_VOLUME')
                fee_parts = [(f.fees.amount('open',price,multiplier),'open')] if opening else [close_fee(layers[key],price,f) for key in targets]
                fee = sum((part[0] for part in fee_parts),D('0'))
                quantity = 1 if opening else len(targets)
                result = model.apply(dict(event_id=f'account:fill:{index}',kind='ack',at=execution_at.isoformat(),contract=contract,
                    decision_id=pending['decision_id'],status='FILLED',price=str(price),layer_ids=targets))
                trace.append(result)
                gross = D('0')
                if opening:
                    if not layers:
                        round_start, round_at, round_fills = cash, execution_at, []
                    layers[pending['decision_id']] = dict(layer_id=pending['decision_id'],kind=pending['kind'],side=side,price=price,
                        at=execution_at,trading_day=b.trading_day,open_fee=fee)
                else:
                    gross = sum((direction_sign(layers[key]['side'])*(price-layers[key]['price'])*multiplier for key in targets),D('0'))
                    for key in targets:
                        del layers[key]
                cash += gross-fee
                fees += fee
                gross_realized += gross
                fill = dict(fill_id=f'{run_id}:fill:{len(fills)+1}',decision_id=pending['decision_id'],decision_at=pending['at'],
                    fill_at=execution_at,contract=contract,trading_day=b.trading_day,action=pending['kind'],side=side,order_side='BUY' if buying else 'SELL',quantity=quantity,
                    price=price,fee=fee,fee_kinds=[part[1] for part in fee_parts],gross_realized=gross,
                    layer_ids=[pending['decision_id']] if opening else targets,reasons=pending['reasons'],
                    execution_source=f.source_id,fee_source=f.fees.source_id,bar_source=b.source_identity)
                fills.append(fill);round_fills.append(fill['fill_id'])
                if not layers:
                    closed_rounds.append(dict(side=side,entry_at=round_at,exit_at=execution_at,net_pnl=cash-round_start,
                        fills=list(round_fills)))
                    round_start,round_at,round_fills = None,None,[]
        # Both state machines must agree before granting reconciliation/admission.
        if set(layers) != {layer['layer_id'] for layer in model.layers} or any((layers[layer['layer_id']]['price'], layers[layer['layer_id']]['side']) != (layer['price'], layer['side']) for layer in model.layers):
            raise ValueError('ACCOUNT_LAYER_RECONCILIATION')
        if cash != INITIAL_CASH+gross_realized-fees:
            raise ValueError('ACCOUNT_CASH_RECONCILIATION')
        side = model.side or (model.pending['side'] if model.pending else candidate_side(technical['m30'] or model.latest_frame))
        now = finance(b.close,f,side)
        event = dict(technical,admission=now['admission'],round_loss=now['round_loss'],day_loss=now['day_loss'],
            remaining_net=str(now['remaining_net']),base_net=None if now['base_net'] is None else str(now['base_net']),
            layer_nets={k: str(v) for k,v in now['layer_nets'].items()},reconciled=True)
        result = model.apply(event)
        result['finance'] = _wire(now)
        if result['actions'] or technical['m30'] is not None:
            trace.append(result)
        last_equity = now['equity']
        row = dict(trading_day=current_day,at=b.bar_end,equity=last_equity,cash=cash,day_start_equity=day_start,
            day_net=last_equity-day_start,quantity=len(layers))
        if daily and daily[-1]['trading_day'] == current_day:
            daily[-1] = row
        else:
            daily.append(row)
    last = executions[-1]
    version = f'subing_jm30_account_theoretical_open_v2_slip{slippage_ticks}' if at_open else (VERSION if slippage_ticks == 1 else f'{VERSION}_research_slip{slippage_ticks}')
    identity = {}
    if research_profile is not None:
        version += f'_parameter_stability_v1_{research_profile}'
        identity = dict(research_profile=research_profile, research_parameters=dict(window_max_age=model.window_age, stop_buffer=model.stop_buffer, target_r=model.target_r))
    return _wire(dict(version=version,contract=contract,run_id=run_id, **identity,
        status='OPEN' if layers else 'PENDING' if model.pending else 'COMPLETED',
        summary=dict(cash=cash,equity=last_equity,net_pnl=last_equity-INITIAL_CASH,fees=fees,open_quantity=len(layers),fill_count=len(fills),closed_round_count=len(closed_rounds)),
        initial_cash=INITIAL_CASH,cash=cash,equity=last_equity,unrealized=last_equity-cash,fees=fees,
        gross_realized=gross_realized,net_pnl=last_equity-INITIAL_CASH,
        open_layers=list(layers.values()),closed_rounds=closed_rounds,
        open_round=None if round_start is None else dict(side=model.side,entry_at=round_at,net_pnl=last_equity-round_start,fills=round_fills),
        fills=fills,execution_events=execution_events,daily_equity=daily,trace=trace,pending=model.pending,
        decision_state=model.state(),decision_checkpoint=model.checkpoint(),
        valuation_at=last.bar.bar_end,valuation_price=last.bar.close,
        assumptions=(f'THEORETICAL ONLY; liquidity unverified; minute start strictly after decision; open +/-{slippage_ticks} tick; capacity assumed up to 3 lots; completed technical exit events consumed once; no future OHLCV fill filter; no terminal liquidation; no broker fills' if at_open else f'retrospective confirmation=bar_end; later completed 1m close +/-{slippage_ticks} tick; no terminal liquidation; single physical contract; no broker fills')))
