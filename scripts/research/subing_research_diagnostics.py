"""Single-factor and lower-timeframe setup diagnostics on verified replay inputs.

This screen counts setups before account admission using the same clock for
both timing choices. It reports two ways to bound a confirmed H1 opportunity.
"""

from collections import Counter, defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
from statistics import median

from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.new_subing_research import NewSubingInputError, validate_series
from guiyi_quant.indicators import subing_trend as trend, subing_macd as macd
from guiyi_quant.indicators.atr import initial_atr_state
from guiyi_quant.indicators.ema import initial_ema_state
from guiyi_quant.indicators.macd import initial_macd_state, step_macd
from guiyi_quant.indicators.subing_conditions import entry_conditions
from guiyi_quant.indicators.subing_volume import VolumeState, observe


def distribution(values):
    if not values:
        return None
    return dict(min=min(values), median=median(values), max=max(values))


def tier(volume, base, contract, at):
    return observe(VolumeState((contract, '30m'), base), contract=contract,
                   frequency='30m', bar_end=at, volume=volume)[1].tier


def frequency_bars(market, product, contract, freq, day, cutoff):
    source_args = dict(symbol=product, contract=contract, frequency=freq, before=cutoff)
    source = market.contract_source_evidence(**source_args)
    expected = market.expected_contract_replay_endpoints(
        symbol=product, contract=contract, frequency=freq, trading_day=day, cutoff=cutoff,
    )
    if not expected:
        raise NewSubingInputError('LOWER_TIMING_EXPECTED_INPUT_EMPTY')
    series = market.query_contract_trading_days(
        ContractTradingDayQuery(product, contract, freq, expected[0][1], day),
    )
    validate_series(series, product=product, contract=contract, frequency=freq, expected=expected)
    if source != market.contract_source_evidence(**source_args):
        raise NewSubingInputError('LOWER_TIMING_SOURCE_CHANGED')
    return series.bars, source


def trade_clock_frame(contract, freq, bars, minutes):
    trend_state = trend.TrendState((contract, freq.value), initial_ema_state(21),
                                   initial_atr_state(14, smoothing_policy='wilder_sma_seed'))
    macd_state = initial_macd_state(12, 26, 9, ema_seed_policy='sma_window', histogram_scale=2)
    previous_macd = previous_volume = None
    result = {}
    for bar in bars:
        at = bar.bar_end
        trend_state, point = trend.step(trend_state, contract=contract, frequency=freq.value,
                                        bar_end=at, high=float(bar.high), low=float(bar.low),
                                        close=float(bar.close))
        macd_state, values = step_macd(macd_state, float(bar.close), bar_end=at.isoformat())
        cross = macd.CrossPoint()
        if all(value.ready and value.valid and value.value is not None for value in values):
            dif, dea = (value.value for value in values[:2])
            cross = macd.cross_point(previous_macd, dif, dea)
            previous_macd = (dif, dea)
        else:
            previous_macd = None
        if minutes[0].bar.bar_end <= at <= minutes[-1].bar.bar_end:
            result[at] = dict(
                angle=point.angle, ema=point.ema21, close=bar.close,
                golden=cross.near_zero_golden, death=cross.near_zero_death,
                tier=tier(bar.volume, previous_volume, contract, at),
            )
        previous_volume = bar.volume
    return result


def timing_setups(segment, hourly, frames, *, sustained=False):
    outcomes = defaultdict(Counter)
    enabled = {frequency: {} for frequency in frames}
    hour_at = direction = None
    w = {}
    rejected = set()
    groups = 0
    for minute, x in enumerate(segment.executions):
        at = x.bar.bar_end
        if at in hourly:
            new_direction = hourly[at]['direction']
            if not sustained or direction != new_direction:
                hour_at = at
                w = {}
                direction = new_direction
                groups += direction in ('UP', 'DOWN')
                continue
        if hour_at is None or direction not in ('UP', 'DOWN'):
            continue
        e = segment.observations[at]
        daily = ('SAME' if e['daily_direction'] == direction else
                 'OPPOSITE' if e['daily_direction'] in ('UP', 'DOWN') else e['daily_direction'])
        sign = 1 if direction == 'UP' else -1
        for frequency, rows in frames.items():
            row = rows.get(at)
            if not row:
                continue
            if frequency == '5m' and not any(t < at for t in enabled.get('15m', {}).get(hour_at, [])):
                continue
            outcomes[frequency]['covered_bars'] += 1
            cross = row['golden' if sign == 1 else 'death']
            if cross is True:
                w[frequency] = minute
            elif cross is None:
                w.pop(frequency, None)
            active = frequency in w and minute - w[frequency] <= 150
            if not active:
                continue
            allowed_tier = row['tier'] in ('TIER_1', 'TIER_2', 'TIER_3')
            angle = None if row['angle'] is None else D(str(row['angle'])) * sign
            price_gate = None if row['ema'] is None else (row['close'] - D(str(row['ema']))) * sign > 0
            # Count the same technical setup in the D1 opposed group too.
            technical = entry_conditions(daily_direction='NEUTRAL', minute_angle=angle,
                                         above_ema=price_gate, golden_window=True,
                                         volume_effective=allowed_tier)
            if technical['met'] is not True:
                continue
            if daily not in ('SAME', 'NEUTRAL'):
                key = (frequency, w[frequency], daily)
                if key not in rejected:
                    outcomes[frequency][f'D1_{daily}'] += 1
                    rejected.add(key)
                continue
            w.pop(frequency)
            outcomes[frequency][f'D1_{daily}'] += 1
            enabled[frequency].setdefault(hour_at, []).append(at)
    a, b = (set(enabled.get(f, {})) for f in ('30m', '15m'))
    comparison_available = '15m' in frames
    return dict(
        setup_counts=dict(outcomes),
        confirmed_direction_h1=sum(h['direction'] in ('UP', 'DOWN') for h in hourly.values()),
        directional_opportunity_groups=groups,
        h1_with_both=len(a & b) if comparison_available else None,
        h1_with_only_30m=len(a - b) if comparison_available else None,
        h1_with_only_15m=len(b - a) if comparison_available else None,
        h1_with_nested_5m=len(enabled['5m']) if comparison_available and '5m' in frames else None,
        repeat_setups={
            f: sum(max(0, len(times) - 1) for times in by_hour.values())
            for f, by_hour in enabled.items()
        },
        expiry=('strictly after confirmed H1 direction change and through consecutive same-direction H1'
                if sustained else 'strictly after H1 and before next H1'),
        expiry_clock='maximum 150 validated trading minutes from the cross',
        measurement='technical setups before account admission; no PnL',
    )



def range_trial_screen(segment, hourly, m15):
    """Candidate: supported M15 trend during H1 range and flat before Session end."""
    counts = Counter()
    by_window = defaultdict(list)
    for i, x in enumerate(segment.executions):
        by_window[x.bar.session_open_at].append(i)
    ends = {key: points[-1] for key, points in by_window.items()}
    active = False
    crosses = {}
    for i, x in enumerate(segment.executions):
        at = x.bar.bar_end
        if at in hourly:
            active = hourly[at]['regime'] == 'RANGE'
            if active:
                counts['confirmed_h1_range_bars'] += 1
            else:
                crosses.clear()
            continue
        row = m15.get(at)
        if not active or row is None:
            continue
        counts['covered_m15_in_h1_range'] += 1
        obs = segment.observations[at]
        for sign, direction, field in ((1, 'UP', 'golden'), (-1, 'DOWN', 'death')):
            if row[field] is True:
                crosses[direction] = i
            elif row[field] is None:
                crosses.pop(direction, None)
            if direction not in crosses or i - crosses[direction] > 150:
                continue
            ema = row['ema']
            angle = row['angle']
            if (ema is None or angle is None or sign * angle <= 0 or
                    sign * (row['close'] - D(str(ema))) <= 0 or
                    row['tier'] not in ('TIER_1', 'TIER_2', 'TIER_3')):
                continue
            crosses.pop(direction)
            if obs['daily_direction'] not in (direction, 'NEUTRAL'):
                counts['d1_rejected_setups'] += 1
            elif ends[x.bar.session_open_at] - i < 3:
                counts['session_admission_rejected_setups'] += 1
            else:
                counts['eligible_technical_setups_before_risk'] += 1
    return dict(counts, overnight_permission=False, allow_new_exposure_when_remaining_minutes_at_least=3,
                latest_close_intent='penultimate validated 1m; last minute is first eligible close fill',
                unresolved_close='keep exit owed if the last minute cannot fill',
                pnl_status='NOT_EVALUATED_FOR_SCREENED_SETUPS')


def diagnose_segment(market, segment, rows, hourly):
    xs = segment.executions
    product, contract = segment.product, xs[0].bar.physical_contract
    minutes = {x.bar.bar_end: x for x in xs}
    window_lengths = defaultdict(lambda: defaultdict(list))
    for x in xs:
        window_lengths[x.bar.trading_day][x.bar.session_open_at].append(x.bar.bar_end)
    mark = defaultdict(list)
    counts, ranges, volume_counts = Counter(), Counter(), defaultdict(Counter)
    prior_volumes = defaultdict(lambda: deque(maxlen=5))
    previous_regime = None
    frames = {'30m': {}}
    for row in rows:
        at = datetime.fromisoformat(row['time'])
        if row['frequency'] != '30m' or at not in minutes:
            continue
        x = minutes[at]
        ctx = segment.structures[at.isoformat()]
        current_regime = ctx.get('base_regime')
        if current_regime == 'RANGE':
            ranges['range_completed_m30'] += 1
            if previous_regime in ('TREND_UP', 'TREND_DOWN'):
                ranges['trend_to_range_transitions'] += 1
        previous_regime = current_regime
        atr = D(str(row['atr14'])) if row['atr14'] is not None else None
        raw_macd = row['macd']
        if atr and atr > 0:
            for name, point_value in (('near', D(4)), ('extreme', D(17)), ('stop', D(13))):
                mark[f'{name}_over_atr'].append(point_value / atr)
                mark[f'{name}_in_ticks'].append(point_value / x.facts.tick_size)
                if name == 'stop':
                    mark['stop_buffer_cny_one_lot'].append(point_value * x.facts.multiplier)
            if raw_macd['height'] is not None:
                height = D(str(raw_macd['height']))
                golden = raw_macd['cross'] == 'GOLDEN'
                original = (raw_macd['near_zero_golden'] or raw_macd['near_zero_death'],
                            raw_macd['high_death'] or raw_macd['low_golden'])
                normalized = (abs(height) * D(17) <= atr * D(4),
                              height < -atr if golden else height > atr)
                counts['crosses_with_atr'] += 1
                for i, name in enumerate(('near', 'extreme')):
                    counts[f'{name}_fixed'] += bool(original[i])
                    counts[f'{name}_atr'] += normalized[i]
                    counts[f'{name}_changed'] += bool(original[i]) != normalized[i]
        windows = window_lengths[x.bar.trading_day]
        opening = x.bar.session_open_at
        ends = windows[opening]
        ordinal = (at - opening).total_seconds() // 60
        phase = ('OPEN' if opening == min(windows) and ordinal <= 30 else
                 'REOPEN' if opening != min(windows) and ordinal <= 30 else
                 'TAIL' if at == ends[-1] else 'INTERIOR')
        key = (opening.astimezone(ZoneInfo("Asia/Shanghai")).time(), ordinal)
        vol = row['volume_factor']
        volume_counts[phase][f"adjacent:{vol['tier']}"] += 1
        history = prior_volumes[key]
        if len(history) >= 3:
            alt = tier(vol['current'], median(history), contract, at)
            volume_counts[phase][f'relative:{alt}'] += 1
            volume_counts[phase]['relative_comparable'] += 1
            volume_counts[phase]['tier_changed'] += alt != vol['tier']
        history.append(vol['current'])
        frames['30m'][at] = dict(angle=row['angle'], ema=row['ema21'], close=D(str(row['close'])),
                                 golden=raw_macd['near_zero_golden'], death=raw_macd['near_zero_death'],
                                 tier=vol['tier'])
    lower_sources = {}
    for freq in (BarFrequency.M15, BarFrequency.M5):
        try:
            bars, source = frequency_bars(market, product, contract, freq, xs[-1].bar.trading_day,
                                           xs[-1].bar.bar_end)
            for bar in bars:
                if xs[0].bar.bar_end <= bar.bar_end <= xs[-1].bar.bar_end:
                    if bar.bar_end not in minutes or D(str(bar.close)) != minutes[bar.bar_end].bar.close:
                        raise NewSubingInputError('LOWER_TIMING_M1_ENDPOINT_OR_CLOSE_CONFLICT')
            frames[freq.value] = trade_clock_frame(contract, freq, bars, xs)
        except NewSubingInputError as exc:
            lower_sources[freq.value] = {'status': exc.code}
        else:
            lower_sources[freq.value] = dict(status='VERIFIED', warm_and_owned=len(bars),
                                            owned=len(frames[freq.value]), source=source)
    owned_hourly = {at: h for at, h in hourly.items() if at in minutes}
    return dict(
        macd=counts, scales={k: distribution(v) for k, v in mark.items()},
        volume=dict(volume_counts), ranges=dict(ranges),
        lower_sources=lower_sources, timing=timing_setups(segment, owned_hourly, frames),
        timing_sustained_h1=timing_setups(segment, owned_hourly, frames, sustained=True),
        h1_range_trial=range_trial_screen(segment, owned_hourly, frames['15m']) if '15m' in frames else None,
        parameters=dict(macd_near_atr='4/17', macd_extreme_atr='1',
                        relative_volume_prior_days='median of last 5 same physical contract/Session/offset, min 3'),
    )
