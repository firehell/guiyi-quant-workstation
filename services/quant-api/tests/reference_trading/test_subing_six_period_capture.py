from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity
from guiyi_quant.subing_reference import ReferenceBar, ReferenceSegment
from app.reference_trading.forward_inputs import capture_subing_canonical, ForwardInputUnavailable

END = datetime(2026, 10, 23, 7, tzinfo=UTC)


def identity(period):
    return StreamIdentity('subing_reference', (f'subing_ths_{period}_v1',),
        f'subing_reference_{period}_v1', 'subing_reference_reverse_close_v1',
        'subing_actual_dominant_v1', 'RB', period, 'actual_dominant',
        RecordingMode.FORWARD_OBSERVATION, "completed_canonical_v1")


class Source:
    def __init__(self, ends=(END,)):
        self.ends = ends
        self.reads = 0
    def resolve_forward_read_window(self, query):
        return END.date(), END.date(), self.ends[-1], END + timedelta(seconds=1)
    def _session_windows(self, symbol, day):
        from types import SimpleNamespace
        return (SimpleNamespace(start=END-timedelta(days=30)),)
    def load_historical_inputs(self, **kwargs):
        self.reads += 1
        bars = tuple(ReferenceBar(end, end.date(), Decimal(100)) for end in self.ends)
        segment = ReferenceSegment('RB2701', 'owner', bars, date(2026, 10, 1), END.date())
        return (segment,), [{'bars': [{'bar_end': end.isoformat(), 'close': '100'} for end in self.ends]}], {}, self.ends[-1]


@pytest.mark.parametrize('period', ['1d', '1w'])
def test_daily_weekly_canonical_capture_is_bounded_and_replay_safe(period):
    source = Source()
    args = dict(revision_id='r', generation=1, now=END+timedelta(seconds=1),
        recording_start=END-timedelta(days=1))
    result = capture_subing_canonical(source, identity(period), after=None, **args)
    assert result.source_kind == 'canonical_completed'
    assert result.source_proof['frequency'] == period
    assert result.source_proof['expected_endpoints'] == [END.isoformat()]
    assert capture_subing_canonical(source, identity(period), after=END, **args) is None
    assert source.reads == 1
    assert capture_subing_canonical(source, identity(period), after=None,
        **{**args, 'recording_start': END+timedelta(microseconds=1)}) is None


def test_canonical_capture_never_replays_missed_bars_as_first_seen():
    with pytest.raises(ForwardInputUnavailable, match='OBSERVATION_GAP'):
        capture_subing_canonical(Source((END-timedelta(days=1), END)), identity('1d'),
            revision_id='r', generation=1, after=None, now=END+timedelta(seconds=1),
            recording_start=END-timedelta(days=2))


def test_warm_prefix_drives_first_forward_signal_without_historical_position():
    from guiyi_quant.indicators.subing_ths import SubingThs15mKernel
    from guiyi_quant.reference_trading.subing_forward import seed_subing_forward, advance_subing_forward
    from guiyi_quant.reference_trading import ReferenceState
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    for i in range(50):
        state, _ = kernel.step(state, 100, bar_end=(END-timedelta(weeks=50-i)).isoformat())
    stream = identity('1w')
    strategy, actions, transition, display = advance_subing_forward(seed_subing_forward(),
        ReferenceState.flat(stream, recording_start=END-timedelta(days=1)),
        physical_contract='RB2701', owner_segment_id='owner', calculation_segment_id='owner',
        bar_end=END, trading_day=END.date(), close=Decimal(120), warmup_kernel=state)
    assert display['ready'] and display['direction'] == 'buy'
    assert len(actions) == 1
    assert strategy.processed_count == 51
    assert transition.state.open_trade.entry_bar_end == END


def test_real_daily_quality_prefix_before_watermark_does_not_break_capture():
    from tests.test_subing_reference_service import DailyQualityMarket
    from app.market_data.subing_reference import SubingReferenceService
    market = DailyQualityMarket()
    now = datetime.combine(market.days[-1], datetime.min.time(), UTC) + timedelta(hours=7)
    from types import SimpleNamespace
    market.query_page = lambda _: SimpleNamespace(bars=(market.bars[-1],))
    service = SubingReferenceService(market, coverage=SimpleNamespace(product_start=lambda _: market.days[0]), active_products={'rb'}, now=lambda: now)
    result = capture_subing_canonical(service, identity('1d'), revision_id='r', generation=1,
        after=market.bars[-2].bar_end, recording_start=market.bars[-2].bar_end-timedelta(days=1), now=now)
    assert result.bar_end == market.bars[-1].bar_end


def test_warm_checkpoint_roundtrip_uses_prefix_only_and_keeps_flat_position():
    from dataclasses import replace
    from app.reference_trading.subing_forward import subing_warmup_checkpoint
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json
    stream = replace(identity('1w'), observation_policy_version='subing_physical_prefix_forward_v2')
    bars = tuple(ReferenceBar(END-timedelta(weeks=51-i), date(2025, 1, 1), Decimal(100)) for i in range(50))
    text = subing_warmup_checkpoint(stream, 'RB2701', 'owner', 'calc', bars)
    restored = adapter_checkpoint_from_json(text, expected_stream=stream, expected_strategy_schema='subing_forward_v1')
    assert restored.strategy_state.processed_count == 50
    assert restored.computed_through < END
    assert restored.reference_state.open_trade is None


def test_warm_rollover_interrupts_before_new_signal_and_keeps_both_records():
    from guiyi_quant.indicators.subing_ths import SubingThs15mKernel
    from guiyi_quant.reference_trading import ReferenceState, ReferenceAction, ActionKind, reduce_reference
    from guiyi_quant.reference_trading.subing_forward import seed_subing_forward, advance_subing_forward
    stream = identity('1w')
    old_end = END-timedelta(weeks=1)
    ref = reduce_reference(ReferenceState.flat(stream, recording_start=old_end), actions=(ReferenceAction(
        stream=stream, source_action_id='old', sequence=0, kind=ActionKind.OPEN_LONG,
        physical_contract='RB2610', owner_segment_id='old', calculation_segment_id='old',
        bar_end=old_end, trading_day=old_end.date(), reference_price=Decimal(100), reference_price_type='close'),),
        completed_bar_end=old_end, completed_trading_day=old_end.date(), completed_reference_price=Decimal(100)).state
    strategy, _, _, _ = advance_subing_forward(seed_subing_forward(), ReferenceState.flat(stream, recording_start=old_end),
        physical_contract='RB2610', owner_segment_id='old', calculation_segment_id='old',
        bar_end=old_end, trading_day=old_end.date(), close=Decimal(100))
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    for i in range(50):
        state, _ = kernel.step(state, 100, bar_end=(END-timedelta(weeks=51-i)).isoformat())
    _, actions, transition, display = advance_subing_forward(strategy, ref,
        physical_contract='RB2701', owner_segment_id='new', calculation_segment_id='new',
        bar_end=END, trading_day=END.date(), close=Decimal(120), warmup_kernel=state,
        rollover_at=END-timedelta(days=4))
    assert len(actions) == 1 and display['direction'] == 'buy'
    assert [t.status.value for t in transition.changed_trades] == ['ROLLOVER_INTERRUPTED', 'OPEN']
    assert transition.changed_trades[0].exit_reference_price is None
    assert transition.state.open_trade.physical_contract == 'RB2701'


def test_v2_canonical_capture_commit_restart_and_duplicate_are_exact():
    from functools import partial
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.reference_trading.subing_activation import plan_subing_activation, apply_subing_activation, subing_identity
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.subing_forward import evaluate_subing_capture
    class WarmSource(Source):
        def load_historical_inputs(self, **kwargs):
            bars = tuple(ReferenceBar(END-timedelta(weeks=50-i), (END-timedelta(weeks=50-i)).date(),
                Decimal(120 if i == 50 else 100)) for i in range(51))
            segment = ReferenceSegment('RB2701','owner',bars,END.date(),END.date())
            return (segment,), [{'bars': [{'close': str(bar.close), 'bar_end': bar.bar_end.isoformat()} for bar in bars]}], {}, END
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    now = END-timedelta(minutes=2)
    plan = plan_subing_activation('rb','1w',operational={'rb'},start=END-timedelta(minutes=1),
        expiry=now+timedelta(seconds=30),now=now,host='local',environment='isolated')
    applied = apply_subing_activation(factory,plan,expected_plan_hash=plan['plan_hash'],operational={'rb'},now=now)
    stream = subing_identity('rb','1w',forward=True)
    repo = ReferenceRepository(factory)
    capture = capture_subing_canonical(WarmSource(),stream,revision_id=applied['revision_id'],generation=1,
        after=None, recording_start=END-timedelta(minutes=1),now=END+timedelta(seconds=1))
    first_id = repo.capture_forward(capture)
    assert repo.capture_forward(capture) == first_id
    service = ForwardReferenceService(repo,partial(evaluate_subing_capture,
        dependency_manifest=repo.read_state(stream.stream_id).dependency_manifest))
    service.process_pending(stream.stream_id)
    assert service.process_pending(stream.stream_id) is None
    restarted = ReferenceRepository(factory)
    state = restarted.read_state(stream.stream_id)
    _, checkpoint = restarted.load_checkpoint(stream.stream_id,state.revision_id)
    assert checkpoint.strategy_state.processed_count == 51
    assert checkpoint.reference_state.open_trade.entry_bar_end == END


def test_first_live_composed_capture_separates_read_boundary_from_checkpoint_watermark():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from types import SimpleNamespace
    from app.db.base import Base
    from app.reference_trading.subing_activation import plan_subing_activation, apply_subing_activation, subing_identity
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.composition import build_forward_reference_worker
    from tests.reference_trading.test_forward_inputs import _Read
    read = _Read()
    read.current_contract_replay_window = lambda *_args, **_kwargs: SimpleNamespace(bars=read.bars)
    end = read.bars[-1].bar_end
    start = end-timedelta(seconds=30)
    now = start-timedelta(minutes=1)
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    plan = plan_subing_activation('rb','5m',operational={'rb'},start=start,
        expiry=now+timedelta(seconds=30),now=now,host='local',environment='isolated')
    apply_subing_activation(factory,plan,expected_plan_hash=plan['plan_hash'],operational={'rb'},now=now)
    stream = subing_identity('rb','5m',forward=True)
    repo = ReferenceRepository(factory)
    worker = build_forward_reference_worker(repository=repo,market_read=read,newow_reader=None,
        owner_segments=lambda *_: ('owner','calc'),expected_endpoints=lambda *_: (end,),
        newow_capability_ready=lambda *_: False,now=lambda: end+timedelta(seconds=1),enabled=True,
        subing_owner_started_at=lambda *_: end-timedelta(days=1))
    capture = worker._read_input(stream.stream_id,'live_event',end)
    assert capture.source_proof['previous_watermark'] is None
    repo.capture_forward(capture)
    result = worker._service_for(stream.stream_id).process_pending(stream.stream_id)
    assert result is not None
    state = repo.read_state(stream.stream_id)
    _, checkpoint = repo.load_checkpoint(stream.stream_id,state.revision_id)
    assert checkpoint.computed_through == end
