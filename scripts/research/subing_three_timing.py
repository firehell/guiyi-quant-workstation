"""Compare confirmed SuBing entry clocks without changing the portfolio engine."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal as D
from itertools import groupby
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import payload_hash
from app.market_data.storage import CanonicalMonthlyStore
from guiyi_quant.subing_decision import _wire, daily_allows, direction_sign
from guiyi_quant.subing_one_lot import THREE_PRODUCT_RESEARCH, planned_loss
from guiyi_quant.subing_one_lot.portfolio import INITIAL_CASH, Portfolio
from scripts.research.subing_exit_comparison import compact_prefix, market_engine
from scripts.research.subing_one_lot_stress import dump, hashes, sha, stressed
from scripts.research.subing_portfolio_replay import load_segments
from scripts.research.subing_research_diagnostics import frequency_bars, trade_clock_frame

FREQUENCIES = (BarFrequency.M30, BarFrequency.M15, BarFrequency.M5)
STUDY_VERSION = "subing_three_entry_clock_v1"
ALLOWED_TIERS = ("TIER_1", "TIER_2", "TIER_3")
EVALUATION_STARTS = ("2025-11-21", "2026-02-21", "2026-05-21", "2026-08-21")


def window_index(day):
    return sum(day >= start for start in EVALUATION_STARTS) - 1


def prepare_inputs(source):
    plan, products, segments, coverage, _, facts = load_segments(
        source, compare_exits=True, research_scope=True,
    )
    if any(row['status'] != 'VERIFIED' for row in coverage):
        raise ValueError('ENTRY_CLOCK_BASE_COVERAGE_INCOMPLETE')
    evidence, clocks = {}, {}
    engine, root = market_engine()
    try:
        for segment in segments:
            xs = segment.executions
            initial, last = xs[0].bar, xs[-1].bar
            contract = initial.physical_contract
            prices = {x.bar.bar_end: x.bar.close for x in xs}
            evidence[contract] = {}
            clocks[contract] = {}
            with Session(engine, autoflush=False) as db, readonly_transaction(db, timeout_seconds=120):
                market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
                for frequency in FREQUENCIES:
                    bars, source_id = frequency_bars(
                        market, segment.product, contract, frequency, last.trading_day, last.bar_end,
                    )
                    for bar in bars:
                        if initial.bar_end <= bar.bar_end <= last.bar_end and prices.get(bar.bar_end) != bar.close:
                            raise ValueError(f'ENTRY_CLOCK_MINUTE_CONFLICT:{contract}:{frequency}')
                    clocks[contract][frequency.value] = trade_clock_frame(contract, frequency, bars, xs)
                    evidence[contract][frequency.value] = dict(
                        source=source_id, physical_bars=len(bars),
                        owned_bars=len(clocks[contract][frequency.value]),
                    )
            print('timing inputs', contract, flush=True)
    finally:
        engine.dispose()
    return segments, clocks, dict(
        requested=plan['dates'], products=products, coverage=coverage,
        plan_hash=payload_hash(plan), execution_facts_sha256=facts, entry_clock_sources=evidence,
    )


def setups(segment, frames, group, *, parent=None):
    """Physical clocks update only from completed bars. One trigger per cross."""
    xs = segment.executions
    direction = anchor = None
    candidate_cross = {}
    latest_m30 = None
    result = {}
    base = {} if parent is None else parent
    seen_parent = set()
    window_end = {}
    for minute in xs:
        window_end[minute.bar.session_open_at] = minute.bar.bar_end

    for idx, x in enumerate(xs):
        at = x.bar.bar_end
        obs = segment.observations[at]
        if obs['m30'] is not None:
            latest_m30 = obs['m30']
        structure = segment.structures[at.isoformat()]
        hour = structure.get('hourly') or {}
        at_key = at.isoformat()
        if group == 'intraday':
            latest = hour.get('direction')
            if latest != direction or (anchor and anchor[0] != x.bar.session_open_at):
                direction = latest
                anchor = (x.bar.session_open_at, hour.get('at'))
                candidate_cross.clear()
        else:
            latest = obs['daily_direction']
            if latest != direction:
                direction = latest
                anchor = (None, obs['daily_at'])
                candidate_cross.clear()
        if direction not in ('UP', 'DOWN') or anchor is None:
            continue
        side = 'LONG' if direction == 'UP' else 'SHORT'
        sign = direction_sign(side)
        # Day-specific subgroup identity keeps comparisons exact when the
        # daily direction persists for several trading days.
        episode = (x.bar.physical_contract, x.bar.trading_day.isoformat(), side, *anchor)
        row = frames.get(at)
        if at in base and base[at]['episode'] == episode:
            seen_parent.add(episode)
        if row is None:
            continue
        if group == 'intraday' and (not hour.get('at') or hour['at'] >= at_key):
            continue
        field = 'golden' if direction == 'UP' else 'death'
        if row[field] is True:
            candidate_cross[side] = (idx, at)
        elif row[field] is None:
            candidate_cross.pop(side, None)
        cross = candidate_cross.get(side)
        if cross is None or idx - cross[0] > 150:
            continue
        if parent is not None and episode not in seen_parent:
            continue
        if parent is not None and at in base and base[at]['episode'] == episode:
            continue
        angle, ema = row['angle'], row['ema']
        if (ema is None or angle is None or sign * D(str(angle)) <= 0 or
                sign * (row['close'] - D(str(ema))) <= 0 or row['tier'] not in ALLOWED_TIERS):
            continue
        if not daily_allows(obs['daily_direction'], side):
            continue
        if group == 'intraday' and (window_end[x.bar.session_open_at] - at).total_seconds() < 180:
            continue
        if latest_m30 is None or latest_m30['ema21'] is None:
            continue
        extreme = latest_m30['low' if side == 'LONG' else 'high']
        if extreme is None:
            continue
        candidate_cross.pop(side)
        result[at] = dict(
            side=side, episode=episode, cross_at=cross[1], tier=row['tier'],
            ema=D(latest_m30['ema21']), extreme=D(extreme),
            regime=structure.get('base_regime', 'UNKNOWN'),
            d1=obs['daily_direction'],
        )
    return result


def timing_model(account, signals, structures, bars, closing_cutoffs):
    original = account.model
    model_type = type(original)

    class TimingModel(model_type):
        def _observe(self, event, at):
            was_flat = not (self.layers or self.pending)
            if self.layers and at in closing_cutoffs and not (self.pending or self.clear_reasons or self.exit_layers):
                self.clear_reasons.append('RESEARCH_SESSION_END')
            read = dict(event, admission=False) if was_flat else event
            actions = super()._observe(read, at)
            if not was_flat:
                return actions
            actions = [a for a in actions if a.get('opportunity') != 'OPEN']
            signal = signals.get(at)
            if signal is None or self.layers or self.pending or self.clear_reasons:
                self.chain[-1]['actions'] = _wire(actions)
                return actions
            side = signal['side']
            sign = direction_sign(side)
            price = D(event['close'])
            facts = bars[at].facts
            stop = (min(signal['ema'], signal['extreme']) - self.stop_buffer if side == 'LONG'
                    else max(signal['ema'], signal['extreme']) + self.stop_buffer)
            quote = price + sign * facts.tick_size * account.slippage_ticks
            risk = planned_loss(quote, stop, side, facts, account.slippage_ticks)
            blocked = []
            if self.regime in ('RANGE', 'UNKNOWN') or structures[at.isoformat()].get('phase') == 'BREAK_PENDING':
                blocked.append('ENTRY_ENVIRONMENT')
            if not self.technical_ready or not event['reconciled'] or not self.day_reconciled:
                blocked.append('TECHNICAL_FACTS_UNKNOWN')
            if event['day_end_window'] or self.day_halted or event['round_loss'] is not False or event['day_loss'] is not False:
                blocked.append('DAY_OR_RISK_HALT')
            if not event['admission']:
                blocked.append('ADMISSION_OR_RISK_NOT_PROVEN')
            if not daily_allows(event['daily_direction'], side):
                blocked.append('DAILY_NOT_ALLOWED')
            if self.last_flat_at is not None and at <= self.last_flat_at:
                blocked.append('SAME_OBSERVATION_AS_CLEAR')
            if risk is None or risk > D('5000'):
                blocked.append('PLANNED_STOP_RISK_OVER_BUDGET')
            if self.loss_pause_day is not None and (
                event['trading_day'] <= self.loss_pause_day or signal['cross_at'] <= self.loss_pause_at
                or self.regime != ('TREND_UP' if side == 'LONG' else 'TREND_DOWN')
            ):
                blocked.append('CONSECUTIVE_LOSS_PAUSE')
            if blocked:
                actions.append(dict(kind='REJECT', opportunity='OPEN', side=side, reasons=blocked))
            else:
                action = self._intent(at, 'OPEN', [], ['ENTRY_MET'], side=side)
                attributes = dict(signal_at=at, entry_volume_tier=signal['tier'], initial_stop=stop)
                self.pending.update(attributes)
                action.update(attributes)
                actions.append(action)
                if self.loss_pause_day is not None:
                    self.loss_pause_day = self.loss_pause_at = None
                    self.loss_streak = 0
            self.chain[-1].update(actions=_wire(actions), position=self.state())
            return actions

    updated = TimingModel(
        account.contract, account.run_id, regime_research_profile=original.regime_research_profile,
    )
    updated.version = f'{original.version}:{STUDY_VERSION}'
    updated.regime_since = original.regime_since
    account.model = updated


class TimingPortfolio(Portfolio):
    def __init__(self, segments, run_id, signal_book, group, slip):
        self.signals = signal_book
        self.intraday = group == 'intraday'
        super().__init__(segments, run_id, products=THREE_PRODUCT_RESEARCH,
                         research_scope=True, slippage_ticks=slip)

    def register(self, product, bars, structures, schedule):
        super().register(product, bars, structures, schedule)
        contract = next(iter(bars.values())).bar.physical_contract
        account = self.accounts[contract]
        signals = self.signals[contract]
        closing = set()
        if self.intraday:
            for _, group in groupby(bars.values(), key=lambda item: item.bar.session_open_at):
                times = [x.bar.bar_end for x in group]
                if len(times) >= 2:
                    closing.add(times[-2])
        timing_model(account, signals, structures, bars, closing)
        base_finance = account.finance

        def finance(mark, facts, side):
            current = self.marks[contract].bar.bar_end
            signal = signals.get(current)
            if signal and not (account.layers or account.model.pending):
                side = signal['side']
            return base_finance(mark, facts, side)

        account.finance = finance


def evaluate(segments, signal_book, group, frequency, input_id, fee, slip):
    label = f'{group}-{frequency}'
    book = TimingPortfolio(
        segments, f'{STUDY_VERSION}:{input_id}:{label}:f{fee}s{slip}', signal_book, group, slip,
    )
    rows = sorted(
        ((x, segment.observations[x.bar.bar_end]) for segment in segments for x in segment.executions),
        key=lambda pair: pair[0].bar.bar_end,
    )
    last_equity, peak, drawdown = INITIAL_CASH, INITIAL_CASH, D(0)
    period = {}
    rejects_by_contract = defaultdict(Counter)
    for _, batch in groupby(rows, key=lambda pair: pair[0].bar.bar_end):
        batch = list(batch)
        book.step_batch(batch)
        equity = book.equity()
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        index = window_index(book.day.isoformat())
        stats = period.setdefault(index, dict(start=last_equity, peak=last_equity, drawdown=D(0)))
        stats['equity'] = equity
        stats['peak'] = max(stats['peak'], equity)
        stats['drawdown'] = max(stats['drawdown'], stats['peak'] - equity)
        last_equity = equity
        for x, _ in batch:
            contract = x.bar.physical_contract
            account = book.accounts[contract]
            chain = account.model.chain
            if len(chain) < 256:
                continue
            for row in chain[:-1]:
                rejects_by_contract[contract].update(
                    reason for a in row['actions'] if a.get('opportunity') == 'OPEN'
                    for reason in a['reasons']
                )
            latest = chain[-1]
            compact_prefix(account)
            chain.append(latest)
    trades, by_product = [], defaultdict(Counter)
    bars = {s.executions[0].bar.physical_contract: {x.bar.bar_end: x for x in s.executions}
            for s in segments}
    for contract, account in book.accounts.items():
        if account.last is None:
            continue
        product = account.product
        by_product[product]['net'] += account.equity(account.last.bar.close) - INITIAL_CASH
        by_product[product]['fees'] += account.fees
        seen = {fill['fill_id']: fill for fill in account.fills}
        for fill in account.fills:
            mark = bars[contract][fill['fill_bar_end']]
            by_product[product]['slippage'] += abs(fill['price'] - mark.bar.close) * mark.facts.multiplier
        for row in account.model.chain:
            rejects_by_contract[contract].update(
                reason for a in row['actions'] if a.get('opportunity') == 'OPEN'
                for reason in a['reasons']
            )
        for r in account.closed_rounds:
            opening, closing = (seen[f] for f in r['fills'])
            signal = signal_book[contract][opening['decision_bar_end']]
            by_product[product]['closed_rounds'] += 1
            trades.append(dict(
                product=product, contract=contract, entry=opening, exit=closing,
                net=r['net_pnl'], episode=signal['episode'], entry_regime=signal['regime'],
                entry_d1=signal['d1'], period=window_index(closing['trading_day'].isoformat()),
                crossed_session=bars[contract][opening['fill_bar_end']].bar.session_open_at !=
                                bars[contract][closing['fill_bar_end']].bar.session_open_at,
            ))
    return _wire(dict(
        case=label, fee_multiplier=fee, slippage_ticks=slip,
        signal_count=sum(len(x) for x in signal_book.values()), closed_rounds=len(trades),
        net=last_equity - INITIAL_CASH, drawdown=drawdown, by_product=by_product,
        period={str(i): dict(net=p['equity']-p['start'], drawdown=p['drawdown'])
                for i, p in period.items()},
        rejects=dict(rejects_by_contract), trades=trades,
        valuation_unproven=sorted(book.unproven_marks), risk_records=book.risk_records,
        closing_owed=sorted(c for c, a in book.accounts.items() if a.layers or a.model.pending),
    ))


def timing_differences(base, candidate):
    def episodes(rows):
        grouped = defaultdict(list)
        for row in rows:
            grouped[tuple(row['episode'])].append(row)
        return grouped

    a, b = episodes(base['trades']), episodes(candidate['trades'])
    aligned = [k for k in sorted(a.keys() & b.keys()) if len(a[k]) == len(b[k]) == 1]
    early = [k for k in aligned if b[k][0]['entry']['fill_at'] < a[k][0]['entry']['fill_at']]
    only = [row for k in b.keys() - a.keys() for row in b[k]]
    return dict(exact_one_to_one=len(aligned), ambiguous=len(a.keys() & b.keys())-len(aligned),
                candidate_earlier=len(early),
                earlier_net_delta=sum((D(b[k][0]['net']) - D(a[k][0]['net']) for k in early), D(0)),
                candidate_only=len(only), candidate_only_losses=sum(D(t['net']) < 0 for t in only),
                candidate_only_net=sum((D(t['net']) for t in only), D(0)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--group', choices=('intraday', 'trend'), required=True)
    p.add_argument('--fee', type=int, choices=(1, 2), default=1)
    p.add_argument('--slip', type=int, choices=(1, 2), default=1)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    code = {**hashes(), Path(__file__).name: sha(Path(__file__))}
    segments, frames, evidence = prepare_inputs(args.source)
    if args.fee != 1:
        from dataclasses import replace
        segments = [replace(s, executions=tuple(stressed(s.executions, args.fee))) for s in segments]
    input_id = payload_hash(evidence)
    results = {}
    parents = {}
    for frequency in ('30m', '15m', '5m'):
        signals = {}
        for segment in segments:
            contract = segment.executions[0].bar.physical_contract
            signals[contract] = setups(
                segment, frames[contract][frequency], args.group,
                parent=parents.get(contract) if frequency == '5m' else None,
            )
        if frequency == '15m':
            parents = signals
        row = evaluate(segments, signals, args.group, frequency, input_id, args.fee, args.slip)
        results[frequency] = row
        print(row['case'], row['net'], row['closed_rounds'], flush=True)
    if code != {**hashes(), Path(__file__).name: sha(Path(__file__))}:
        raise ValueError('ENTRY_CLOCK_CODE_CHANGED')
    dump(args.output, dict(
        kind=STUDY_VERSION, code_hashes=code, **evidence, runs=results,
        comparing={f: timing_differences(results['30m'], results[f]) for f in ('15m', '5m')},
        chronological_slice_starts=EVALUATION_STARTS,
        holdout_status='LATE_RETROSPECTIVE_SLICE_NOT_UNSEEN_OOS',
        entry_contract=dict(
            active_signal_minutes=150, stop_anchor='latest confirmed M30',
            five_minute='subsequent confirmation within completed M15 opportunity',
            intraday='H1 direction, D1 veto, next completed 1m close, close obligation before Session end',
            trend='strict-before D1 direction, ordinary M30 exits',
        ),
    ))


if __name__ == '__main__':
    main()
