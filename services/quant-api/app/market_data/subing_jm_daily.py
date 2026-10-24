"""Phase-B JM input adapter: existing MDS authority, only D1/M15/M1, local facts."""
from dataclasses import asdict, dataclass
from datetime import date

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.new_subing_research import load_execution_facts, validate_series
from guiyi_quant.new_subing import StrategyBar
from guiyi_quant.subing_jm_daily import Event, RANK, daily_frames, digest

SINCE, THROUGH = date(2024, 10, 14), date(2026, 10, 19)


def verified_days(phase_a):
    if (phase_a.get('kind') != 'PHASE_A_INPUT_AUDIT_NOT_BACKTEST'
            or not phase_a.get('facts_unchanged') or not phase_a.get('physical_sources_unchanged_at_end')):
        raise ValueError('JM_PHASE_A_NOT_VERIFIED')
    rows = phase_a['days']
    if len({r['day'] for r in rows}) != len(rows):
        raise ValueError('JM_PHASE_A_DUPLICATE_DAY')
    return {r['day']: r['contract'] for r in rows if r['status'] == 'INPUTS_VERIFIED'}


@dataclass(frozen=True)
class DailyInputs:
    events: tuple[Event, ...]
    input_hash: str
    facts_hash: str
    sources: tuple[dict, ...]


def load_inputs(market, raw_facts, *, phase_a: dict) -> DailyInputs:
    """Validate the whole frozen window before replay; never repair, shrink or substitute."""
    allowed = verified_days(phase_a)
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(
        symbol='jm', since=SINCE, through=THROUGH)
    minutes, daily, checks, sources, owned_days = [], [], [], [], set()
    sessions = {}

    def windows(day):
        if day not in sessions:
            values = tuple(market.session_windows(symbol='jm', trading_day=day))
            if not values or any(s.start >= s.end for s in values) or any(
                    a.end > b.start for a, b in zip(values, values[1:])):
                raise ValueError('JM_SESSION_INVALID')
            sessions[day] = values
        return sessions[day]

    seen_contracts = set()
    for owner in owners:
        if owner.contract in seen_contracts:
            raise ValueError('JM_REPEATED_PHYSICAL_OWNER_UNSUPPORTED')
        seen_contracts.add(owner.contract)
        start, end = max(SINCE, owner.start_trading_day), min(THROUGH, owner.end_trading_day)
        cutoff = max(w.end for w in windows(end))
        for frequency in (BarFrequency.D1, BarFrequency.M15, BarFrequency.M1):
            before = market.contract_source_evidence(symbol='jm', contract=owner.contract,
                                                     frequency=frequency, before=cutoff)
            expected = market.expected_contract_replay_endpoints(symbol='jm', contract=owner.contract,
                frequency=frequency, trading_day=end, cutoff=cutoff,
                since=None if frequency is BarFrequency.D1 else start)
            if not expected:
                raise ValueError('JM_INPUT_EMPTY')
            result = market.query_contract_trading_days(ContractTradingDayQuery(
                'jm', owner.contract, frequency, expected[0][1], end))
            validate_series(result, product='jm', contract=owner.contract,
                            frequency=frequency, expected=expected)
            converted = []
            for b in result.bars:
                day_windows = windows(b.trading_day)
                containing = [w for w in day_windows if w.start < b.bar_end <= w.end]
                if len(containing) != 1:
                    raise ValueError('JM_SESSION_IDENTITY_CONFLICT')
                eligible = start <= b.trading_day <= end
                if eligible:
                    if allowed.get(b.trading_day.isoformat()) != owner.contract:
                        raise ValueError('JM_OUTSIDE_PHASE_A_VERIFIED_WINDOW')
                    owned_days.add(b.trading_day.isoformat())
                converted.append(StrategyBar(product='jm', physical_contract=owner.contract,
                    frequency=frequency.value, source_identity=digest([owner.contract, start, end, asdict(b)]),
                    confirmed_at=b.bar_end, observation_eligible=eligible,
                    session_open_at=containing[0].start, session_close_at=max(w.end for w in day_windows),
                    **{k: v for k, v in asdict(b).items() if k != 'turnover'}))
            after = market.contract_source_evidence(symbol='jm', contract=owner.contract,
                                                    frequency=frequency, before=cutoff)
            if before != after:
                raise ValueError('JM_SOURCE_CHANGED_DURING_LOAD')
            sources.append({'contract': owner.contract, 'frequency': frequency.value,
                'through': end.isoformat(), 'source': before, 'source_hash': digest(before),
                'bar_hash': digest([asdict(b) for b in converted]), 'count': len(converted)})
            if frequency is BarFrequency.D1:
                frames = tuple(f for f in daily_frames(converted) if f.bar.observation_eligible)
                if any(f.ema is None for f in frames):
                    raise ValueError('JM_DAILY_WARMUP_UNAVAILABLE')
                daily.extend(frames)
            elif frequency is BarFrequency.M15:
                checks.extend(Event('15m', b) for b in converted)
            else:
                minutes.extend(converted)
    wanted = {d for d in allowed if SINCE.isoformat() <= d <= THROUGH.isoformat()}
    if owned_days != wanted or len(wanted) != 489:
        raise ValueError('JM_VERIFIED_DAY_ACCOUNTING_CONFLICT')
    executions, facts_hash = load_execution_facts(raw_facts, product='jm', bars=minutes)
    events = [*(Event('1m', x.bar, x.facts) for x in executions), *daily, *checks]
    events.sort(key=lambda e: (e.bar.confirmed_at, RANK[e.kind]))
    for s in sources:
        cutoff = max(w.end for w in windows(date.fromisoformat(s['through'])))
        final = market.contract_source_evidence(symbol='jm', contract=s['contract'],
            frequency=BarFrequency(s['frequency']), before=cutoff)
        if digest(final) != s['source_hash']:
            raise ValueError('JM_SOURCE_CHANGED_DURING_FULL_LOAD')
    return DailyInputs(tuple(events), digest(sources), facts_hash, tuple(sources))
