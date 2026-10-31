"""Deployment-only proof of a classified, still unavailable weekly route.

No strategy, capture, checkpoint, trade or source mutation is produced here.
"""
from dataclasses import asdict
from hashlib import sha256
import json

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import ActualDominantTradingDayQuery, BarFrequency
from app.market_data.subing_reference import _wire
from app.market_data.weekly_quality import (
    WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2, WeeklySourceInterruption,
)
from app.reference_trading.forward_inputs import ForwardInputUnavailable

SCHEMA = 'subing_weekly_unavailable_deployment_v1'


def require(value):
    if not value:
        raise ValueError('REFERENCE_WEEKLY_QUALITY_UNPROVEN')


class ClassifiedWeeklyUnavailable(ForwardInputUnavailable):
    def __init__(self, proof):
        require(proof.get('schema') == SCHEMA and proof.get('status') == 'DATA_UNAVAILABLE')
        super().__init__('SUBING_REFERENCE_DATA_UNAVAILABLE')
        self.proof = proof


def prove_weekly_unavailable(service, identity, *, since, through, cutoff):
    """Prove ALL requested owners and full physical prefixes, including breaks.

    MDS verifies D1 revisions/quality, complete Calendar/Session endpoints,
    persisted W1 equality and absence of a stored Bar at a quality interruption.
    The separate rank1 read must agree with those same physical source facts.
    """
    require(identity.strategy_code == 'subing_reference' and identity.frequency == '1w'
            and identity.series_kind == 'actual_dominant'
            and identity.observation_policy_version == 'subing_physical_prefix_forward_v2')
    symbol = identity.product.lower()
    market = service.market_data
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(
        symbol=symbol, since=since, through=through)
    rows, owned_bars, owned_gaps, source = [], [], [], []
    gap_count = 0
    for owner in owners:
        last = min(owner.end_trading_day, through)
        end = max(w.end for w in service._session_windows(symbol, last))
        require(end <= cutoff)
        expected = market.expected_contract_replay_endpoints(
            symbol=symbol, contract=owner.contract, frequency=BarFrequency.W1,
            trading_day=last, cutoff=end, after=None)
        bars, gaps = market.query_contract_weekly_replay_quality(
            symbol=symbol, contract=owner.contract, through=last, cutoff=end,
            classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
        points = [(b.bar_end, b.trading_day) for b in bars]
        require(all(b.close > 0 for b in bars))
        for gap in gaps:
            require(isinstance(gap, WeeklySourceInterruption)
                    and gap.product == symbol and gap.physical_contract == owner.contract
                    and gap.classification_version == WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2
                    and gap.unavailable_days and gap.quality_source_hashes
                    and len(gap.daily_revision_sha256) == 64)
            points.append((gap.bar_end, gap.trading_day))
        require(len(points) == len(set(points)) and tuple(sorted(points)) == tuple(expected)
                and all(at <= end for at, _ in points))
        owned_bars.extend(b for b in bars if owner.start_trading_day <= b.trading_day <= last)
        owned_gaps.extend((owner.contract, g) for g in gaps
                          if owner.start_trading_day <= g.trading_day <= last)
        gap_count += len(gaps)
        rows.append({'contract': owner.contract, 'owner_since': owner.start_trading_day.isoformat(),
            'owner_through': last.isoformat(), 'expected_count': len(expected),
            'valid_count': len(bars), 'quality_interruptions': len(gaps)})
        source.append({'owner': asdict(owner), 'expected': expected,
                       'bars': [asdict(b) for b in bars], 'interruptions': [asdict(g) for g in gaps]})
    require(gap_count > 0)
    actual, actual_gaps = market.query_actual_dominant_trading_days_quality(
        ActualDominantTradingDayQuery(symbol, BarFrequency.W1, owners[0].start_trading_day, through),
        weekly_classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
    require(actual.request_identity == {**actual.request_identity, 'symbol': symbol,
        'series_kind': 'actual_dominant', 'contract': None, 'frequency': '1w'}
        and actual.requested_trading_day_window == (owners[0].start_trading_day, through)
        and tuple(sorted(owned_bars, key=lambda b: b.bar_end)) == actual.bars
        and tuple(sorted(owned_gaps, key=lambda item: item[1].bar_end)) == actual_gaps)
    payload = {'stream_id': identity.stream_id, 'cutoff': cutoff, 'sources': source,
               'actual_identity': actual.request_identity}
    return {'schema': SCHEMA, 'stream_id': identity.stream_id, 'product': symbol,
        'frequency': '1w', 'status': 'DATA_UNAVAILABLE', 'cutoff': cutoff.isoformat(),
        'quality_interruptions': gap_count, 'contracts': rows,
        'source_sha256': sha256(json.dumps(_wire(payload), sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()}
