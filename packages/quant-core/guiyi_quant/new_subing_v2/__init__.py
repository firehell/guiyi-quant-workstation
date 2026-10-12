"""New SuBing V2 research candidate: pure deterministic replay, no live I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from typing import TYPE_CHECKING, Literal, Mapping, Sequence

from guiyi_quant.new_subing import ExecutionBar, ExecutionFacts, StrategyBar

if TYPE_CHECKING:
    from .signals import Snapshot


@dataclass(frozen=True)
class Profile:
    initial_cash: Decimal = Decimal('100000')
    strategy_code: str = 'new_subing_v2'
    formula_version: str = 'new_subing_formula_v2'
    risk_profile_version: str = 'new_subing_risk_v2'
    execution_profile_version: str = 'new_subing_next_1m_open_v2'
    account_model_version: str = 'new_subing_layers_v2'
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
    volume_window: int = 20
    volume_multiple: Decimal = Decimal('3')
    breakout_window: int = 20
    trigger_window: int = 3
    votes_required: int = 3
    confirmation_bars: int = 3
    initial_margin_fraction: Decimal = Decimal('.10')
    initial_risk_fraction: Decimal = Decimal('.005')
    max_margin_fraction: Decimal = Decimal('.30')
    max_risk_fraction: Decimal = Decimal('.01')
    day_loss_fraction: Decimal = Decimal('.02')
    no_profit_bars: int = 5
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
        if type(self.initial_cash) is not Decimal or self.initial_cash not in (Decimal('100000'), Decimal('1000000')):
            raise ValueError('V2 initial_cash must be Decimal 100000 or 1000000')
        if (self.strategy_code, self.formula_version, self.risk_profile_version,
            self.execution_profile_version, self.account_model_version) != (
                'new_subing_v2', 'new_subing_formula_v2', 'new_subing_risk_v2',
                'new_subing_next_1m_open_v2', 'new_subing_layers_v2'):
            raise ValueError('V2 identity is frozen')
        fixed = Profile.__dataclass_fields__
        for key, field in fixed.items():
            if key in ('initial_cash', 'strategy_code', 'formula_version', 'risk_profile_version',
                       'execution_profile_version', 'account_model_version'):
                continue
            if getattr(self, key) != field.default or type(getattr(self, key)) is not type(field.default):
                raise ValueError(f'V2 quantized mapping {key} is frozen')

    @property
    def profile_id(self) -> str:
        return 'new_subing_stage_v2_100k' if self.initial_cash == Decimal('100000') else 'new_subing_stage_v2_1m'


def profile_payload(profile: Profile | None = None) -> dict[str, object]:
    p = profile or Profile()
    return {
        'strategy_code': p.strategy_code, 'formula_version': p.formula_version,
        'profile_id': p.profile_id, 'risk_profile_version': p.risk_profile_version,
        'execution_profile_version': p.execution_profile_version,
        'account_model_version': p.account_model_version, 'initial_cash': str(p.initial_cash),
        'rules': {
            'source': 'Notion disclosed ideas; exact thresholds and event arbitration are Guiyi quantized V2 mapping',
            'ma21': 'simple; direction is completed close relative to MA21',
            'boll21': 'population standard deviation times 2; prior 3 widths nonexpanding for BOLL vote',
            'macd': '12/26/9, SMA seed, 6 digits; DIF zero cross and signal cross',
            'macd_exit': 'reverse cross: nonpositive net PnL clear, positive net PnL reduce; histogram weakening alone: positive net PnL reduce only',
            'stage': 'TRIAL -> BREAKOUT_CONFIRMED -> PULLBACK -> TREND',
            'trial_confirmation': 'three later completed 5m closes outside frozen level',
            'entry': 'at least three of five votes plus MA/MACD/breakout event; 5m chop requires volume breakout',
            'execution': 'strictly later executable 1m open, physical contract, integer lots',
            'account': 'net direction with named entry layers; FIFO ordinary reduction; layer-specific guard close',
            'budgets': {'first_margin': '.10', 'adds_margin': ['2/3', '1/3'],
                        'first_risk': '.005', 'total_margin': '.30', 'total_risk': '.01', 'day_loss': '.02'},
            'auto_order': False, 'case_parity': 'PENDING',
        },
        'result_statuses': ['COMPLETED', 'DATA_INSUFFICIENT', 'EXECUTION_FACTS_MISSING',
                            'PENDING_UNFILLED', 'ROLLOVER_INTERRUPTED'],
        'aggregate_return_status': 'COMPLETED',
    }


@dataclass(frozen=True)
class PreparedResearch:
    formula_version: str
    input_hash: str
    snapshot_hash: str
    bars: tuple[tuple[str, tuple[StrategyBar, ...]], ...]
    snapshots: tuple[tuple[str, tuple[tuple[str, tuple[Snapshot, ...]], ...]], ...]


def _input_tuple(bars_by_frequency: Mapping[str, Sequence[StrategyBar]]) -> tuple[tuple[str, tuple[StrategyBar, ...]], ...]:
    return tuple((frequency, tuple(bars_by_frequency[frequency])) for frequency in sorted(bars_by_frequency))


def prepare_research(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                     profile: Profile | None = None) -> PreparedResearch:
    from .engine import prepare_snapshots, validate_histories
    p = profile or Profile()
    validate_histories(bars_by_frequency)
    bars = _input_tuple(bars_by_frequency)
    digest = sha256(repr((p.formula_version, bars)).encode()).hexdigest()
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        frozen = prepare_snapshots(bars_by_frequency, p)
    return PreparedResearch(p.formula_version, digest,
                            sha256(repr(frozen).encode()).hexdigest(), bars, frozen)


def run_research(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                 execution_bars: Sequence[ExecutionBar], *, profile: Profile | None = None,
                 scenario: str = 'baseline', since: date, through: date,
                 prepared: PreparedResearch | None = None) -> dict[str, object]:
    from .engine import run_research_impl
    p = profile or Profile()
    if prepared is not None:
        if type(prepared) is not PreparedResearch or prepared.formula_version != p.formula_version or \
           prepared.bars != _input_tuple(bars_by_frequency) or \
           prepared.input_hash != sha256(repr((p.formula_version, prepared.bars)).encode()).hexdigest() or \
           prepared.snapshot_hash != sha256(repr(prepared.snapshots).encode()).hexdigest():
            raise ValueError('prepared research input/formula mismatch')
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return run_research_impl(bars_by_frequency, execution_bars, p, scenario, since, through, prepared)


__all__ = ['Profile', 'PreparedResearch', 'StrategyBar', 'ExecutionFacts', 'ExecutionBar',
           'profile_payload', 'prepare_research', 'run_research']
