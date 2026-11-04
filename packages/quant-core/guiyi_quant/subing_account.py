"""Single-contract offline SuBing account replay. No provider, broker or Runtime I/O."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, time
from decimal import Decimal, localcontext
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo
from .new_subing import ExecutionBar
from .subing_decision import _contract_version, RISK_RESEARCH_PROFILES, DecisionModel, _wire, candidate_side, daily_allows, directional_frame, direction_sign
D = Decimal
VERSION = 'subing_jm30_account_next1m_close_v5'
INITIAL_CASH = D('100000')
TECHNICAL_FIELDS = set('event_id kind at contract trading_day close daily_direction daily_at day_end_window m30'.split())

def replay(executions: Sequence[ExecutionBar], observations: Mapping[datetime, dict], run_id: str, *, slippage_ticks: int=1, execution_model: str='completed_close', research_profile: str | None=None, risk_research_profile: str | None=None, regime_research_profile: str | None=None) -> dict:
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
    if (research_profile is not None or risk_research_profile is not None or regime_research_profile is not None) and execution_model != 'theoretical_open':
        raise ValueError('ACCOUNT_RESEARCH_PROFILE_REQUIRES_THEORETICAL_OPEN')
    with localcontext() as ctx:
        ctx.prec = 28
        return _replay(executions, observations, run_id, slippage_ticks, execution_model, research_profile, risk_research_profile, regime_research_profile)

def _replay(executions, observations, run_id, slippage_ticks, execution_model, research_profile, risk_research_profile, regime_research_profile):
    if not executions:
        raise ValueError('ACCOUNT_INPUT_EMPTY')
    b = executions[0].bar
    if b.product.lower() not in ('jm', 'ma', 'ta') or not b.physical_contract.startswith(b.product.upper()):
        raise ValueError('ACCOUNT_PHYSICAL_IDENTITY_CHANGED')
    engine = AccountEngine(b.physical_contract, b.product.lower(), executions[0].facts.multiplier, run_id, slippage_ticks, execution_model, research_profile, risk_research_profile, regime_research_profile)
    if len(observations) != len(executions):
        raise ValueError('ACCOUNT_OBSERVATION_COVERAGE')
    for execution in executions:
        engine.step(execution, observations.get(execution.bar.bar_end))
    return engine.snapshot()

class AccountEngine:

    def __init__(self, contract, product, multiplier, run_id, slippage_ticks=1, execution_model='completed_close', research_profile=None, risk_research_profile=None, regime_research_profile=None, decision_factory=None, live=False):
        if execution_model not in ("completed_close","theoretical_open") or type(slippage_ticks) is not int or slippage_ticks not in (1,2,3) or (live and execution_model!="completed_close"):
            raise ValueError("ACCOUNT_EXECUTION_MODEL_INVALID")
        self.contract = contract
        self.product = product
        self.multiplier = multiplier
        self.run_id = run_id
        self.slippage_ticks = slippage_ticks
        self.research_profile = research_profile
        self.risk_research_profile = risk_research_profile
        self.regime_research_profile = regime_research_profile
        self.live=live
        self.pending_known_at=None
        self.last_observed_at=None
        self.at_open = execution_model == 'theoretical_open'
        self.model = (decision_factory or DecisionModel)(self.contract, self.run_id, research_profile=self.research_profile, risk_research_profile=self.risk_research_profile, regime_research_profile=self.regime_research_profile)
        self.round_limit, self.day_limit, self.margin_fraction, _ = RISK_RESEARCH_PROFILES.get(self.risk_research_profile, (D('2000'), D('5000'), D('.70'), True))
        self.prior = None
        self.observation_ids = set()
        self.cash, self.fees, self.gross_realized = (INITIAL_CASH, D('0'), D('0'))
        self.layers = {}
        self.fills, self.closed_rounds, self.trace, self.execution_events, self.daily = ([], [], [], [], [])
        self.current_day, self.day_start, self.last_equity = (None, INITIAL_CASH, INITIAL_CASH)
        self.round_start, self.round_at, self.round_fills = (None, None, [])
        self.index = 0
        self.last = None
        self.previous_technical = None

    def equity(self, mark):
        return self.cash + sum((direction_sign(layer['side']) * (mark - layer['price']) * self.multiplier for layer in self.layers.values()), D('0'))

    def close_fee(self, layer, price, facts):
        kind = 'close_today' if layer['trading_day'] == facts.trading_day else 'close'
        return (facts.fees.amount(kind, price, self.multiplier), kind)

    def finance(self, mark, facts, side):
        sign = direction_sign(side)
        ratio = facts.long_margin_ratio if side == 'LONG' else facts.short_margin_ratio
        eq = self.equity(mark)
        used = len(self.layers) * max(mark, facts.prev_settlement) * self.multiplier * ratio
        estimated_open_fee = facts.fees.amount('open', mark + sign * facts.tick_size * self.slippage_ticks, self.multiplier)
        prospective_equity = eq - facts.tick_size * self.slippage_ticks * self.multiplier - estimated_open_fee
        prospective_margin = (len(self.layers) + 1) * max(mark + sign * facts.tick_size * self.slippage_ticks, facts.prev_settlement) * self.multiplier * ratio
        round_net = eq - self.round_start if self.round_start is not None else D('0')
        day_net = eq - self.day_start
        layer_nets = {key: direction_sign(layer['side']) * (mark - layer['price']) * self.multiplier - layer['open_fee'] - self.close_fee(layer, mark, facts)[0] for key, layer in self.layers.items()}
        remainder = sum(layer_nets.values(), D('0'))
        base_net = next((layer_nets[key] for key, layer in self.layers.items() if layer['kind'] == 'OPEN'), None)
        allowed = len(self.layers) < 3 and prospective_equity > 0 and (prospective_margin <= prospective_equity * self.margin_fraction) and (prospective_margin <= prospective_equity) and (round_net > -self.round_limit) and (day_net > -self.day_limit) and (self.round_start is None or prospective_equity - self.round_start > -self.round_limit) and (prospective_equity - self.day_start > -self.day_limit)
        return dict(equity=eq, cash=self.cash, margin=used, available=eq - used, round_net=round_net, day_net=day_net, remaining_net=remainder, base_net=base_net, layer_nets=layer_nets, admission=allowed, round_loss=round_net <= -self.round_limit, day_loss=day_net <= -self.day_limit)

    def validate(self, execution, technical, observed_at=None):
        if type(execution) is not ExecutionBar:
            raise ValueError('ACCOUNT_EXECUTION_TYPE')
        b, f = (execution.bar, execution.facts)
        if b.physical_contract != self.contract or b.product.lower() != self.product or f.multiplier != self.multiplier:
            raise ValueError('ACCOUNT_PHYSICAL_IDENTITY_CHANGED')
        if b.volume != b.volume.to_integral_value():
            raise ValueError('ACCOUNT_FRACTIONAL_VOLUME')
        if (not self.live and b.confirmed_at != b.bar_end) or not b.observation_eligible or (self.live and (observed_at is None or observed_at.tzinfo is None or observed_at < b.confirmed_at or (self.last_observed_at and observed_at < self.last_observed_at))):
            raise ValueError('ACCOUNT_CONFIRMATION_NOT_PROVEN')
        if b.session_open_at is None or b.session_close_at is None or b.bar_end - timedelta(minutes=1) < b.session_open_at:
            raise ValueError('ACCOUNT_SESSION_MISSING')
        if self.prior is not None and (b.bar_end <= self.prior.bar_end or b.trading_day < self.prior.trading_day):
            raise ValueError('ACCOUNT_INPUT_ORDER')
        if self.prior is not None and b.session_open_at == self.prior.session_open_at and (b.bar_end - self.prior.bar_end != timedelta(minutes=1)):
            raise ValueError('ACCOUNT_MINUTE_GAP')
        for value in (b.open, b.high, b.low, b.close):
            if value % f.tick_size != 0 or not f.limit_down <= value <= f.limit_up:
                raise ValueError('ACCOUNT_PRICE_FACT_CONFLICT')
        o = technical
        if type(o) is not dict or set(o) != TECHNICAL_FIELDS:
            raise ValueError('ACCOUNT_OBSERVATION_FIELDS')
        if o['kind'] != 'observe' or o['contract'] != self.contract or datetime.fromisoformat(o['at']) != b.bar_end or (o['trading_day'] != b.trading_day.isoformat()) or (type(o['close']) is not str) or (D(o['close']) != b.close):
            raise ValueError('ACCOUNT_OBSERVATION_IDENTITY')
        if not isinstance(o['event_id'], str) or not o['event_id'] or o['event_id'] in self.observation_ids or o['event_id'].startswith('account:'):
            raise ValueError('ACCOUNT_OBSERVATION_ID')
        self.observation_ids.add(o['event_id'])
        self.prior = b

    def step(self, execution, technical, *, observed_at=None):
        self.validate(execution, technical, observed_at)
        pending_before=self.model.pending["decision_id"] if self.model.pending else None
        prior_fill_count=len(self.fills)
        prior_known_at=self.pending_known_at
        index = self.index
        b, f = (execution.bar, execution.facts)
        if self.current_day != b.trading_day:
            self.current_day, self.day_start = (b.trading_day, self.last_equity)
        side = self.model.side or (self.model.pending['side'] if self.model.pending else candidate_side(technical['m30'] or self.model.latest_frame))
        sign = direction_sign(side)
        pending = deepcopy(self.model.pending)
        execution_at = b.bar_end - timedelta(minutes=1) if self.at_open else b.bar_end
        mark = b.open if self.at_open else b.close
        known = self.previous_technical if self.at_open and self.index else technical
        local_execution = execution_at.astimezone(ZoneInfo('Asia/Shanghai'))
        end_window = local_execution.date() == b.trading_day and local_execution.time() >= time(14, 50) if self.at_open else known['day_end_window']
        if pending is not None and execution_at > pending['at'] and (not self.live or (self.pending_known_at is not None and b.bar_end > self.pending_known_at)):
            opening = pending['kind'] in ('OPEN', 'ADD')
            buying = opening and side == 'LONG' or (not opening and side == 'SHORT')
            price = mark + (f.tick_size if buying else -f.tick_size) * self.slippage_ticks
            pre = self.finance(mark, f, side)
            current_frame = directional_frame(known['m30'], side)
            current_exit = not self.at_open and current_frame is not None and any((current_frame.get(key) is True for key in ('below_ema', 'below_previous_low', 'high_death')))
            protected_layer = self.model.add_protection and any((layer['kind'] == 'ADD' and sign * (mark - layer['price']) < 0 for layer in self.layers.values()))
            frame_unknown = current_frame is not None and (current_frame.get('minute_angle') is None or any((current_frame.get(key) is None for key in ('near_zero_golden', 'above_ema', 'volume_effective', 'below_previous_low', 'high_death', 'below_ema', 'qualified_pullback'))))
            fixed_stop = self.model.initial_stop is not None and sign * (mark - self.model.initial_stop) <= 0
            profit_hit = self.model.profit_target is not None and (not self.model.profit_taken) and (sign * (mark - self.model.profit_target) >= 0)
            reject = None
            if opening and pending['cancel_requested']:
                reject = 'CANCEL_REQUESTED'
            elif opening and (current_exit or protected_layer or fixed_stop or profit_hit):
                reject = 'EXIT_PRIORITY_AT_EXECUTION'
            elif opening and frame_unknown:
                reject = 'TECHNICAL_FACTS_UNKNOWN_AT_EXECUTION'
            elif opening and (end_window or not daily_allows(known['daily_direction'], side)):
                reject = 'OPENING_CONTEXT_CHANGED'
            elif opening and (self.model.day_halted and self.model.day == b.trading_day or not pre['admission']):
                reject = 'OPENING_FINANCIAL_RECHECK'
            elif pending['kind'] == 'ADD' and (not self.model.regime_allows_add(side)):
                reject = 'REGIME_NOT_SAME_DIRECTION_AT_EXECUTION'
            elif pending['kind'] == 'ADD' and (pre['base_net'] is None or pre['base_net'] <= 0):
                reject = 'BASE_NET_NOT_POSITIVE_AT_EXECUTION'
            elif pending['kind'] == 'ADD' and sign * (mark - pending['breakout_level']) <= 0:
                reject = 'PULLBACK_BREAKOUT_LOST_AT_EXECUTION'
            elif pending['kind'] == 'OPEN' and sign * (price - pending['initial_stop']) <= 0:
                reject = 'INITIAL_STOP_INVALID_AT_EXECUTION'
            elif not self.at_open and b.volume <= 0:
                reject = 'ZERO_VOLUME'
            elif not self.at_open and (not b.low <= price <= b.high):
                reject = 'SLIPPAGE_OUTSIDE_BAR'
            elif not f.limit_down <= price <= f.limit_up:
                reject = 'EXCHANGE_LIMIT'
            elif buying and (b.open if self.at_open else b.low) == f.limit_up or (not buying and (b.open if self.at_open else b.high) == f.limit_down):
                reject = 'LOCKED_LIMIT'
            targets = [] if opening else pending['layer_ids'][:3 if self.at_open else int(b.volume)]
            if not opening and (not targets) and (reject is None):
                reject = 'INSUFFICIENT_VOLUME'
            if reject:
                self.execution_events.append(dict(at=execution_at, decision_id=pending['decision_id'], kind='CANCEL' if opening else 'UNFILLED', reason=reject))
                if opening:
                    result = self.model.apply(dict(event_id=f'account:cancel:{index}', kind='ack', at=execution_at.isoformat(), contract=self.contract, decision_id=pending['decision_id'], status='CANCELLED', price=None, layer_ids=[]))
                    self.trace.append(result)
            else:
                if opening and (not self.at_open) and (b.volume < 1):
                    raise ValueError('ACCOUNT_FRACTIONAL_VOLUME')
                fee_parts = [(f.fees.amount('open', price, self.multiplier), 'open')] if opening else [self.close_fee(self.layers[key], price, f) for key in targets]
                fee = sum((part[0] for part in fee_parts), D('0'))
                quantity = 1 if opening else len(targets)
                result = self.model.apply(dict(event_id=f'account:fill:{index}', kind='ack', at=execution_at.isoformat(), contract=self.contract, decision_id=pending['decision_id'], status='FILLED', price=str(price), layer_ids=targets))
                self.trace.append(result)
                gross = D('0')
                if opening:
                    if not self.layers:
                        self.round_start, self.round_at, self.round_fills = (self.cash, execution_at, [])
                    self.layers[pending['decision_id']] = dict(layer_id=pending['decision_id'], kind=pending['kind'], side=side, price=price, at=execution_at, trading_day=b.trading_day, open_fee=fee)
                else:
                    gross = sum((direction_sign(self.layers[key]['side']) * (price - self.layers[key]['price']) * self.multiplier for key in targets), D('0'))
                    for key in targets:
                        del self.layers[key]
                self.cash += gross - fee
                self.fees += fee
                self.gross_realized += gross
                fill = dict(fill_id=f'{self.run_id}:fill:{len(self.fills) + 1}', decision_id=pending['decision_id'], decision_at=pending['at'], fill_at=execution_at, contract=self.contract, trading_day=b.trading_day, action=pending['kind'], side=side, order_side='BUY' if buying else 'SELL', quantity=quantity, price=price, fee=fee, fee_kinds=[part[1] for part in fee_parts], gross_realized=gross, layer_ids=[pending['decision_id']] if opening else targets, reasons=pending['reasons'], execution_source=f.source_id, fee_source=f.fees.source_id, bar_source=b.source_identity)
                self.fills.append(fill)
                self.round_fills.append(fill['fill_id'])
                if not self.layers:
                    self.closed_rounds.append(dict(side=side, entry_at=self.round_at, exit_at=execution_at, net_pnl=self.cash - self.round_start, fills=list(self.round_fills)))
                    self.round_start, self.round_at, self.round_fills = (None, None, [])
        if set(self.layers) != {layer['layer_id'] for layer in self.model.layers} or any(((self.layers[layer['layer_id']]['price'], self.layers[layer['layer_id']]['side']) != (layer['price'], layer['side']) for layer in self.model.layers)):
            raise ValueError('ACCOUNT_LAYER_RECONCILIATION')
        if self.cash != INITIAL_CASH + self.gross_realized - self.fees:
            raise ValueError('ACCOUNT_CASH_RECONCILIATION')
        side = self.model.side or (self.model.pending['side'] if self.model.pending else candidate_side(technical['m30'] or self.model.latest_frame))
        now = self.finance(b.close, f, side)
        event = dict(technical, admission=now['admission'], round_loss=now['round_loss'], day_loss=now['day_loss'], remaining_net=str(now['remaining_net']), base_net=None if now['base_net'] is None else str(now['base_net']), layer_nets={k: str(v) for k, v in now['layer_nets'].items()}, reconciled=True)
        result = self.model.apply(event)
        result['finance'] = _wire(now)
        if result['actions'] or technical['m30'] is not None:
            self.trace.append(result)
        self.last_equity = now['equity']
        row = dict(trading_day=self.current_day, at=b.bar_end, equity=self.last_equity, cash=self.cash, day_start_equity=self.day_start, day_net=self.last_equity - self.day_start, quantity=len(self.layers))
        if self.daily and self.daily[-1]['trading_day'] == self.current_day:
            self.daily[-1] = row
        else:
            self.daily.append(row)
        self.index += 1
        self.last = execution
        self.previous_technical = deepcopy(technical)
        if self.live:
            for fill in self.fills[prior_fill_count:]:
                fill['decision_bar_end']=fill['decision_at']
                fill['fill_bar_end']=fill['fill_at']
                fill['decision_at']=prior_known_at
                fill['fill_at']=observed_at
                if fill['action']=='OPEN':
                    self.round_at=observed_at
                    self.layers[fill['decision_id']]['at']=observed_at
                elif fill['action']=='CLOSE' and not self.layers and self.closed_rounds:
                    self.closed_rounds[-1]['exit_bar_end']=self.closed_rounds[-1]['exit_at']
                    self.closed_rounds[-1]['exit_at']=observed_at
            pending_after=self.model.pending['decision_id'] if self.model.pending else None
            if pending_after!=pending_before:self.pending_known_at=observed_at if pending_after else None
            self.last_observed_at=observed_at

    def snapshot(self, *, include_journal=True):
        last = self.last
        version = f'subing_jm30_account_theoretical_open_v2_slip{self.slippage_ticks}' if self.at_open else VERSION if self.slippage_ticks == 1 else f'{VERSION}_research_slip{self.slippage_ticks}'
        if self.live:version="subing_jm30_completed_observation_account_v1"
        identity = {}
        if self.research_profile is not None:
            version += f'_parameter_stability_v1_{self.research_profile}'
            identity = dict(research_profile=self.research_profile, research_parameters=dict(window_max_age=self.model.window_age, stop_buffer=self.model.stop_buffer, target_r=self.model.target_r))
        if self.risk_research_profile is not None:
            version += f'_risk_stability_v1_{self.risk_research_profile}'
            identity = dict(risk_research_profile=self.risk_research_profile, research_parameters=dict(round_loss_limit=self.round_limit, day_loss_limit=self.day_limit, margin_fraction=self.margin_fraction, add_protection=self.model.add_protection))
        if self.regime_research_profile is not None:
            version += '_regime_add_v1'
            identity = dict(regime_research_profile=self.regime_research_profile)
        version = _contract_version(version, self.contract)
        result = _wire(dict(version=version, contract=self.contract, run_id=self.run_id, **identity, status='OPEN' if self.layers else 'PENDING' if self.model.pending else 'COMPLETED', summary=dict(cash=self.cash, equity=self.last_equity, net_pnl=self.last_equity - INITIAL_CASH, fees=self.fees, open_quantity=len(self.layers), fill_count=len(self.fills), closed_round_count=len(self.closed_rounds)), initial_cash=INITIAL_CASH, cash=self.cash, equity=self.last_equity, unrealized=self.last_equity - self.cash, fees=self.fees, gross_realized=self.gross_realized, net_pnl=self.last_equity - INITIAL_CASH, open_layers=list(self.layers.values()), closed_rounds=self.closed_rounds, open_round=None if self.round_start is None else dict(side=self.model.side, entry_at=self.round_at, net_pnl=self.last_equity - self.round_start, fills=self.round_fills), fills=self.fills, execution_events=self.execution_events, daily_equity=self.daily, trace=self.trace if include_journal else [], pending=self.model.pending, decision_state=self.model.state(), decision_checkpoint=self.model.checkpoint() if include_journal else None, valuation_at=last.bar.bar_end, valuation_price=last.bar.close, assumptions=f'THEORETICAL ONLY; liquidity unverified; minute start strictly after decision; open +/-{self.slippage_ticks} tick; capacity assumed up to 3 lots; completed technical exit events consumed once; no future OHLCV fill filter; no terminal liquidation; no broker fills' if self.at_open else f'retrospective confirmation=bar_end; later completed 1m close +/-{self.slippage_ticks} tick; no terminal liquidation; single physical contract; no broker fills'))

        if self.live:result['assumptions']='DEVELOPMENT MODEL ONLY; next completed 1m close with adverse slippage; actual knowledge and confirmation times bound; no historical same-bar fills; no broker orders or fills'
        return result
