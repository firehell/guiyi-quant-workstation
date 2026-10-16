"""New SuBing V1: pure historical research, no data-provider or broker I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from typing import Literal, Mapping, Sequence

from guiyi_quant.paper import FeeSchedule


def _decimal(value: Decimal, name: str, *, positive: bool = False, nonnegative: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f'{name} must be a finite Decimal')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(f'{name} out of range')


def _time(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')


@dataclass(frozen=True)
class Profile:
    strategy_code: str = 'new_subing_v1'
    formula_version: str = 'new_subing_formula_v1'
    profile_id: str = 'new_subing_fixed_v1'
    risk_profile_version: str = 'new_subing_risk_v1'
    execution_profile_version: str = 'new_subing_next_1m_open_v1'
    initial_cash: Decimal = Decimal('100000')
    ma_window: int = 21
    boll_sigma: Decimal = Decimal('2')
    atr_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_histogram_scale: Literal[2] = 2
    macd_round_digits: int = 6
    opening_minutes: int = 20
    noise_window: int = 10
    noise_switches: int = 3
    max_ma_distance_atr: Decimal = Decimal('1')
    macd_zero_axis_atr: Decimal = Decimal('.1')
    volume_window: int = 20
    volume_multiple: Decimal = Decimal('3')
    breakout_window: int = 20
    trigger_window: int = 3
    votes_required: int = 3
    confirmation_bars: int = 3
    add_oi_growth: Decimal = Decimal('.005')
    initial_margin_fraction: Decimal = Decimal('.10')
    initial_risk_fraction: Decimal = Decimal('.005')
    max_margin_fraction: Decimal = Decimal('.30')
    max_risk_fraction: Decimal = Decimal('.01')
    day_loss_fraction: Decimal = Decimal('.02')
    no_profit_bars: int = 6
    fast_profit_bars: int = 12
    fast_profit_margin_fraction: Decimal = Decimal('.30')
    peak_drawdown_fraction: Decimal = Decimal('.20')
    reduce_fraction: Decimal = Decimal('.20')
    breakeven_atr_multiple: Decimal = Decimal('2')
    pivot_left: int = 2
    pivot_right: int = 2
    max_adds: int = 2
    consecutive_losses_halt: int = 2

    def __post_init__(self) -> None:
        expected = ('new_subing_v1', 'new_subing_formula_v1', 'new_subing_fixed_v1',
                    'new_subing_risk_v1', 'new_subing_next_1m_open_v1')
        if tuple(getattr(self, k) for k in ('strategy_code', 'formula_version', 'profile_id',
                                            'risk_profile_version', 'execution_profile_version')) != expected:
            raise ValueError('V1 identity is frozen')
        _decimal(self.initial_cash, 'initial_cash', positive=True)
        if self.initial_cash != Decimal('100000'):
            raise ValueError('V1 initial cash is fixed at 100000')
        fixed = {
            'ma_window': 21, 'boll_sigma': Decimal('2'), 'atr_period': 14,
            'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9,
            'macd_histogram_scale': 2, 'macd_round_digits': 6,
            'opening_minutes': 20, 'noise_window': 10, 'noise_switches': 3,
            'max_ma_distance_atr': Decimal('1'), 'macd_zero_axis_atr': Decimal('.1'),
            'volume_window': 20, 'volume_multiple': Decimal('3'), 'breakout_window': 20,
            'trigger_window': 3, 'votes_required': 3, 'confirmation_bars': 3,
            'add_oi_growth': Decimal('.005'), 'initial_margin_fraction': Decimal('.10'),
            'initial_risk_fraction': Decimal('.005'), 'max_margin_fraction': Decimal('.30'),
            'max_risk_fraction': Decimal('.01'), 'day_loss_fraction': Decimal('.02'),
            'no_profit_bars': 6, 'fast_profit_bars': 12,
            'fast_profit_margin_fraction': Decimal('.30'),
            'peak_drawdown_fraction': Decimal('.20'), 'reduce_fraction': Decimal('.20'),
            'breakeven_atr_multiple': Decimal('2'), 'pivot_left': 2, 'pivot_right': 2,
            'max_adds': 2, 'consecutive_losses_halt': 2,
        }
        if any(getattr(self, name) != value or type(getattr(self, name)) is not type(value)
               for name, value in fixed.items()):
            raise ValueError('V1 profile policy is fixed; create a new profile/version to change it')


@dataclass(frozen=True)
class StrategyBar:
    product: str
    physical_contract: str
    frequency: str
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None
    source_identity: str
    confirmed_at: datetime
    observation_eligible: bool = True
    session_open_at: datetime | None = None
    session_close_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(type(x) is str and x.strip() for x in (self.product, self.physical_contract, self.frequency, self.source_identity)):
            raise ValueError('bar identity required')
        if self.frequency not in ('1m', '5m', '15m', '1d', '1w'):
            raise ValueError('unsupported research frequency')
        if type(self.trading_day) is not date or type(self.observation_eligible) is not bool:
            raise ValueError('invalid trading day or observation flag')
        _time(self.bar_end, 'bar_end')
        _time(self.confirmed_at, 'confirmed_at')
        if self.confirmed_at < self.bar_end:
            raise ValueError('confirmation before bar end')
        for name in ('session_open_at', 'session_close_at'):
            value = getattr(self, name)
            if value is not None:
                _time(value, name)
        for name in ('open', 'high', 'low', 'close'):
            _decimal(getattr(self, name), name, positive=True)
        _decimal(self.volume, 'volume', nonnegative=True)
        if self.open_interest is not None:
            _decimal(self.open_interest, 'open_interest', nonnegative=True)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError('invalid OHLC range')
        if self.session_open_at is not None and self.session_open_at >= self.bar_end:
            raise ValueError('session open must precede bar end')
        if self.session_close_at is not None and self.session_close_at < self.bar_end:
            raise ValueError('session close before bar end')


@dataclass(frozen=True)
class ExecutionFacts:
    physical_contract: str
    trading_day: date
    tick_size: Decimal
    multiplier: Decimal
    prev_settlement: Decimal
    long_margin_ratio: Decimal
    short_margin_ratio: Decimal
    limit_up: Decimal
    limit_down: Decimal
    fees: FeeSchedule
    source_id: str

    def __post_init__(self) -> None:
        if not self.physical_contract or not self.source_id or type(self.trading_day) is not date:
            raise ValueError('execution fact identity required')
        for name in ('tick_size', 'multiplier', 'prev_settlement', 'long_margin_ratio',
                     'short_margin_ratio', 'limit_up', 'limit_down'):
            _decimal(getattr(self, name), name, positive=True)
        if self.limit_down >= self.limit_up or not self.limit_down < self.prev_settlement < self.limit_up:
            raise ValueError('invalid exchange limits')
        if type(self.fees) is not FeeSchedule:
            raise ValueError('FeeSchedule required')


@dataclass(frozen=True)
class ExecutionBar:
    bar: StrategyBar
    facts: ExecutionFacts

    def __post_init__(self) -> None:
        if self.bar.frequency != '1m' or self.bar.physical_contract != self.facts.physical_contract or self.bar.trading_day != self.facts.trading_day:
            raise ValueError('1m bar and physical execution facts must align')


def profile_payload(profile: Profile | None = None) -> dict[str, object]:
    p = profile or Profile()
    payload: dict[str, object] = {'strategy_code': p.strategy_code, 'formula_version': p.formula_version,
            'profile_id': p.profile_id, 'risk_profile_version': p.risk_profile_version,
            'execution_profile_version': p.execution_profile_version,
            'initial_cash': str(p.initial_cash),
            'rules': {'source': {'ma21': 'owner_choice', 'daily_direction': 'owner_choice',
                                 'one_minute_exit': 'owner_choice', 'three_votes': 'owner_choice',
                                 'net_account': 'owner_choice',
                                 'setup_thresholds': 'guiyi_fixed_v1',
                                 'original_ideas': 'notion_disclosed'},
                      'ma_window': p.ma_window, 'boll_sigma': str(p.boll_sigma),
                      'atr_period': p.atr_period,
                      'macd': {'fast': p.macd_fast, 'slow': p.macd_slow,
                               'signal': p.macd_signal, 'seed': 'sma_window',
                               'histogram_scale': p.macd_histogram_scale,
                               'round_digits': p.macd_round_digits},
                      'decision_frequency': '5m', 'confirmation_frequency': '15m',
                      'direction_frequency': '1d', 'exit_frequency': '1m',
                      'weekly_context_only': True,
                      'opening_minutes': p.opening_minutes,
                      'opening_gate': 'before_setup_and_add_setup',
                      'fifteen_minute_freshness': 'fewer_than_15_completed_same_contract_trading_1m_since_latest_15m',
                      'noise_window': p.noise_window, 'noise_switches': p.noise_switches,
                      'max_ma_distance_atr': str(p.max_ma_distance_atr),
                      'macd_zero_axis_atr': str(p.macd_zero_axis_atr),
                      'volume_window': p.volume_window,
                      'volume_multiple': str(p.volume_multiple),
                      'breakout_window': p.breakout_window,
                      'trigger_window': p.trigger_window,
                      'setup_votes_required': p.votes_required,
                      'confirmation_bars': p.confirmation_bars,
                      'add_oi_growth': str(p.add_oi_growth),
                      'add_pullback_required': True,
                      'initial_add_budgets': ['3/6', '2/6', '1/6'],
                      'initial_margin_fraction': str(p.initial_margin_fraction),
                      'initial_risk_fraction': str(p.initial_risk_fraction),
                      'max_margin_fraction': str(p.max_margin_fraction),
                      'max_risk_fraction': str(p.max_risk_fraction),
                      'day_loss_fraction': str(p.day_loss_fraction),
                      'no_profit_bars': p.no_profit_bars,
                      'fast_profit_bars': p.fast_profit_bars,
                      'fast_profit_margin_fraction': str(p.fast_profit_margin_fraction),
                      'peak_drawdown_fraction': str(p.peak_drawdown_fraction),
                      'reduce_fraction': str(p.reduce_fraction),
                      'breakeven_atr_multiple': str(p.breakeven_atr_multiple),
                      'pivot_left': p.pivot_left, 'pivot_right': p.pivot_right,
                      'max_adds': p.max_adds,
                      'consecutive_losses_halt': p.consecutive_losses_halt,
                      'next_execution': 'strictly_later_1m_open',
                      'slippage_ticks': {'baseline': 1, 'double_slippage': 2},
                      'close_inventory_order': 'yesterday_before_today',
                      'net_account': 'single_bidirectional_integer_lot',
                      'auto_order': False, 'case_parity': 'PENDING'},
            'result_statuses': ['COMPLETED', 'DATA_INSUFFICIENT',
                                'EXECUTION_FACTS_MISSING', 'PENDING_UNFILLED',
                                'ROLLOVER_INTERRUPTED'],
            'aggregate_return_status': 'COMPLETED'}
    rules = payload['rules']
    assert isinstance(rules, dict)
    owner_choices = {'ma_window', 'direction_frequency', 'exit_frequency',
                     'setup_votes_required', 'net_account'}
    rules['provenance'] = {
        key: 'owner_choice' if key in owner_choices else 'guiyi_fixed_v1'
        for key in rules if key not in ('source', 'provenance')
    }
    return payload


def run_research(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                 execution_bars: Sequence[ExecutionBar], *, profile: Profile | None = None,
                 scenario: str = 'baseline', since: date, through: date) -> dict[str, object]:
    from .engine import run_research_impl
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return run_research_impl(bars_by_frequency, execution_bars, profile or Profile(), scenario, since, through)


__all__ = ['Profile', 'StrategyBar', 'ExecutionFacts', 'ExecutionBar', 'profile_payload', 'run_research']
