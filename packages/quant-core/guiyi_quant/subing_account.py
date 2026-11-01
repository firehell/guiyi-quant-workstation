"""Single-contract offline SuBing account replay. No provider, broker or Runtime I/O."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Mapping, Sequence

from .new_subing import ExecutionBar
from .subing_decision import DecisionModel, _wire

D = Decimal
VERSION = 'subing_jm30_account_next1m_close_v1'
INITIAL_CASH = D('100000')
TECHNICAL_FIELDS = set('event_id kind at contract trading_day close daily_direction daily_at day_end_window m30'.split())


def replay(executions: Sequence[ExecutionBar], observations: Mapping[datetime, dict], run_id: str) -> dict:
    """Replay verified complete 1m input; observations contain no financial overrides.

    Historical confirmation is assumed at bar end. Fills use the strictly later
    completed minute's close +/- one tick, only if inside OHLC and daily limits.
    The caller proves coverage, rank1 ownership and historical execution sources.
    """
    with localcontext() as ctx:
        ctx.prec = 28
        return _replay(executions, observations, run_id)


def _replay(executions, observations, run_id):
    if not executions:
        raise ValueError('ACCOUNT_INPUT_EMPTY')
    contract = executions[0].bar.physical_contract
    model = DecisionModel(contract, run_id)
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
        return cash + sum(((mark - layer['price']) * multiplier for layer in layers.values()), D('0'))

    def close_fee(layer, price, facts):
        kind = 'close_today' if layer['trading_day'] == facts.trading_day else 'close'
        return facts.fees.amount(kind, price, multiplier), kind

    def finance(mark, facts):
        eq = equity(mark)
        used = len(layers) * max(mark, facts.prev_settlement) * multiplier * facts.long_margin_ratio
        estimated_open_fee = facts.fees.amount('open', mark + facts.tick_size, multiplier)
        prospective_equity = eq - facts.tick_size * multiplier - estimated_open_fee
        prospective_margin = (len(layers)+1) * max(mark + facts.tick_size, facts.prev_settlement) * multiplier * facts.long_margin_ratio
        round_net = eq-round_start if round_start is not None else D('0')
        day_net = eq-day_start
        remainder = sum(((mark-layer['price'])*multiplier-layer['open_fee']-close_fee(layer,mark,facts)[0]
            for layer in layers.values()), D('0'))
        allowed = (len(layers) < 3 and prospective_equity > 0 and prospective_margin <= prospective_equity*D('.70')
            and prospective_margin <= prospective_equity and round_net > D('-2000') and day_net > D('-5000')
            and (round_start is None or prospective_equity-round_start > D('-2000'))
            and prospective_equity-day_start > D('-5000'))
        return dict(equity=eq, cash=cash, margin=used, available=eq-used,
            round_net=round_net, day_net=day_net, remaining_net=remainder,
            admission=allowed, round_loss=round_net <= D('-2000'), day_loss=day_net <= D('-5000'))

    for index, execution in enumerate(executions):
        b, f = execution.bar, execution.facts
        technical = observations[b.bar_end]
        if current_day != b.trading_day:
            current_day, day_start = b.trading_day, last_equity
        pending = deepcopy(model.pending)
        if pending is not None and b.bar_end > pending['at']:
            opening = pending['kind'] in ('OPEN','ADD')
            price = b.close + (f.tick_size if opening else -f.tick_size)
            pre = finance(b.close,f)
            current_frame = technical['m30']
            current_exit = current_frame is not None and any(current_frame.get(key) is True for key in ('below_ema', 'below_previous_low', 'high_death'))
            protected_layer = any(layer['kind'] == 'ADD' and b.close < layer['price'] for layer in layers.values())
            frame_unknown = current_frame is not None and (current_frame.get('minute_angle') is None or any(current_frame.get(key) is None for key in ('near_zero_golden','above_ema','volume_effective','below_previous_low','high_death','below_ema','qualified_pullback')))
            reject = None
            if opening and pending['cancel_requested']:
                reject = 'CANCEL_REQUESTED'
            elif opening and (current_exit or protected_layer):
                reject = 'EXIT_PRIORITY_AT_EXECUTION'
            elif opening and frame_unknown:
                reject = 'TECHNICAL_FACTS_UNKNOWN_AT_EXECUTION'
            elif opening and (technical['day_end_window'] or technical['daily_direction'] not in ('UP','NEUTRAL')):
                reject = 'OPENING_CONTEXT_CHANGED'
            elif opening and ((model.day_halted and model.day == b.trading_day) or not pre['admission']):
                reject = 'OPENING_FINANCIAL_RECHECK'
            elif b.volume <= 0:
                reject = 'ZERO_VOLUME'
            elif not b.low <= price <= b.high:
                reject = 'SLIPPAGE_OUTSIDE_BAR'
            elif not f.limit_down <= price <= f.limit_up:
                reject = 'EXCHANGE_LIMIT'
            elif (opening and b.low == f.limit_up) or (not opening and b.high == f.limit_down):
                reject = 'LOCKED_LIMIT'
            targets = [] if opening else pending['layer_ids'][:int(b.volume)]
            if not opening and not targets and reject is None:
                reject = 'INSUFFICIENT_VOLUME'
            if reject:
                execution_events.append(dict(at=b.bar_end,decision_id=pending['decision_id'],kind='CANCEL' if opening else 'UNFILLED',reason=reject))
                if opening:
                    result = model.apply(dict(event_id=f'account:cancel:{index}',kind='ack',at=b.bar_end.isoformat(),contract=contract,
                        decision_id=pending['decision_id'],status='CANCELLED',price=None,layer_ids=[]))
                    trace.append(result)
            else:
                if opening and b.volume < 1:
                    raise ValueError('ACCOUNT_FRACTIONAL_VOLUME')
                fee_parts = [(f.fees.amount('open',price,multiplier),'open')] if opening else [close_fee(layers[key],price,f) for key in targets]
                fee = sum((part[0] for part in fee_parts),D('0'))
                quantity = 1 if opening else len(targets)
                result = model.apply(dict(event_id=f'account:fill:{index}',kind='ack',at=b.bar_end.isoformat(),contract=contract,
                    decision_id=pending['decision_id'],status='FILLED',price=str(price),layer_ids=targets))
                trace.append(result)
                gross = D('0')
                if opening:
                    if not layers:
                        round_start, round_at, round_fills = cash, b.bar_end, []
                    layers[pending['decision_id']] = dict(layer_id=pending['decision_id'],kind=pending['kind'],price=price,
                        at=b.bar_end,trading_day=b.trading_day,open_fee=fee)
                else:
                    gross = sum(((price-layers[key]['price'])*multiplier for key in targets),D('0'))
                    for key in targets:
                        del layers[key]
                cash += gross-fee
                fees += fee
                gross_realized += gross
                fill = dict(fill_id=f'{run_id}:fill:{len(fills)+1}',decision_id=pending['decision_id'],decision_at=pending['at'],
                    fill_at=b.bar_end,contract=contract,trading_day=b.trading_day,action=pending['kind'],quantity=quantity,
                    price=price,fee=fee,fee_kinds=[part[1] for part in fee_parts],gross_realized=gross,
                    layer_ids=[pending['decision_id']] if opening else targets,reasons=pending['reasons'],
                    execution_source=f.source_id,fee_source=f.fees.source_id,bar_source=b.source_identity)
                fills.append(fill);round_fills.append(fill['fill_id'])
                if not layers:
                    closed_rounds.append(dict(entry_at=round_at,exit_at=b.bar_end,net_pnl=cash-round_start,
                        fills=list(round_fills)))
                    round_start,round_at,round_fills = None,None,[]
        # Both state machines must agree before granting reconciliation/admission.
        if set(layers) != {layer['layer_id'] for layer in model.layers} or any(layers[layer['layer_id']]['price'] != layer['price'] for layer in model.layers):
            raise ValueError('ACCOUNT_LAYER_RECONCILIATION')
        if cash != INITIAL_CASH+gross_realized-fees:
            raise ValueError('ACCOUNT_CASH_RECONCILIATION')
        now = finance(b.close,f)
        event = dict(technical,admission=now['admission'],round_loss=now['round_loss'],day_loss=now['day_loss'],
            remaining_net=str(now['remaining_net']),reconciled=True)
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
    return _wire(dict(version=VERSION,contract=contract,run_id=run_id,
        status='OPEN' if layers else 'PENDING' if model.pending else 'COMPLETED',
        summary=dict(cash=cash,equity=last_equity,net_pnl=last_equity-INITIAL_CASH,fees=fees,open_quantity=len(layers),fill_count=len(fills),closed_round_count=len(closed_rounds)),
        initial_cash=INITIAL_CASH,cash=cash,equity=last_equity,unrealized=last_equity-cash,fees=fees,
        gross_realized=gross_realized,net_pnl=last_equity-INITIAL_CASH,
        open_layers=list(layers.values()),closed_rounds=closed_rounds,
        open_round=None if round_start is None else dict(entry_at=round_at,net_pnl=last_equity-round_start,fills=round_fills),
        fills=fills,execution_events=execution_events,daily_equity=daily,trace=trace,pending=model.pending,
        decision_state=model.state(),decision_checkpoint=model.checkpoint(),
        valuation_at=last.bar.bar_end,valuation_price=last.bar.close,
        assumptions='retrospective confirmation=bar_end; later completed 1m close +/-1 tick; no terminal liquidation; single physical contract; no broker fills'))
