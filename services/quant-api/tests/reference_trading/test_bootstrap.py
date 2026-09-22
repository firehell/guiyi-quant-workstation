from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint
from guiyi_quant.subing_reference import (
    FORMULA_VERSIONS,
    REFERENCE_MODEL_VERSION_V2,
    ReferenceBar,
    ReferenceSegment,
    project_reference,
)

from app.db.base import Base
from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputSnapshot
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
)
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.service import (
    HistoricalReferenceService,
    ServiceInterrupted,
    SubingHistoricalPayload,
)


def _stream() -> StreamIdentity:
    return StreamIdentity(
        strategy_code="subing_reference",
        formula_versions=(FORMULA_VERSIONS["1d"],),
        profile_id="subing_reference_1d_v1",
        reference_model_version=REFERENCE_MODEL_VERSION_V2,
        futures_adaptation_version="subing_actual_dominant_v1",
        product="RB",
        frequency="1d",
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


class Reader:
    def __init__(self) -> None:
        at = datetime(2026, 1, 1, 15, tzinfo=UTC)
        prices = [100] * 50 + [120, 80, 120, 80]
        raw = tuple(
            ReferenceBar(at + timedelta(days=i), (at + timedelta(days=i)).date(), Decimal(price))
            for i, price in enumerate(prices)
        )
        segment = ReferenceSegment(
            "RB2605", "owner-1", raw, raw[0].trading_day, raw[-1].trading_day,
        )
        self.bars = tuple(
            HistoricalInputBar(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                physical_contract="RB2605",
                owner_segment_id="owner-1",
                calculation_segment_id="owner-1",
                reference_price=bar.close,
                fingerprint=strategy_input_fingerprint({"bar": bar.bar_end, "close": bar.close}),
                payload=SubingHistoricalPayload(
                    segment=segment,
                    bar=bar,
                    since=raw[0].trading_day,
                    through=raw[-1].trading_day,
                    quality_segmented=True,
                ),
            )
            for bar in raw
        )
        self.token = "source-v1"

    def _snapshot(self, request):
        return HistoricalInputSnapshot(
            request.identity,
            self.bars[0].trading_day,
            self.bars[-1].bar_end,
            self.bars,
            {
                "dataset_revision": "fixture-v1",
                "partitions": [{"key": "RB2605", "sha256": "a" * 64}],
                "calendar": "calendar-v1",
                "session": "session-v1",
                "rank1": [["RB2605", str(self.bars[0].trading_day), str(self.bars[-1].trading_day)]],
                "quality": "quality-v1",
            },
            self.token,
            4096,
        )

    def plan_stream(self, request):
        return self._snapshot(request)

    def load_stream(self, request, *, expected_source_token):
        assert expected_source_token == self.token
        return self._snapshot(request)

    def revalidate(self, request, *, expected_source_token):
        return expected_source_token == self.token


def _plan(reader: Reader, *, batch_size: int = 11):
    stream = _stream()
    request = HistoricalReferenceRequest(
        "build",
        (HistoricalStreamRequest(
            stream, reader.bars[0].trading_day, reader.bars[-1].trading_day,
            reader.bars[-1].bar_end + timedelta(seconds=1),
        ),),
        WorkBudget(1, 100, 30, 100_000),
        batch_size=batch_size,
    )
    return HistoricalReferencePlanner(
        reader, now=lambda: request.streams[0].as_of,
    ).plan(request)


def _repository():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ReferenceRepository(sessionmaker(engine, expire_on_commit=False))


def test_first_build_starts_flat_persists_all_batches_and_publishes() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "completed"
    stream_report = report.streams[0]
    assert stream_report.completed_bars == len(reader.bars)
    assert stream_report.resume_token is None
    state = repository.read_state(_stream().stream_id)
    assert state.revision_status == "active"
    assert state.checkpoint.seq == 1 + (len(reader.bars) + 10) // 11
    snapshot = stream_report.snapshot
    assert snapshot is not None
    assert repository.read_actions(snapshot, cutoff=None, limit=100).items
    assert repository.read_trades(snapshot, cutoff=None, limit=100).items


def test_historical_build_matches_legacy_subing_trade_projection_fields() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader, batch_size=7)
    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)
    snapshot = report.streams[0].snapshot
    assert snapshot is not None
    payload = reader.bars[0].payload
    assert isinstance(payload, SubingHistoricalPayload)
    legacy = project_reference(
        "rb",
        (payload.segment,),
        since=payload.since,
        through=payload.through,
        as_of=reader.bars[-1].bar_end,
        frequency="1d",
        quality_segmented=True,
    )
    durable = sorted(
        repository.read_trades(snapshot, cutoff=None, limit=100).items,
        key=lambda item: item.entry_bar_end,
    )
    expected = sorted(legacy.trades, key=lambda item: item.entry_bar_end)
    sqlite_scale = Decimal("0.0000000001")
    normalize = lambda value: (  # noqa: E731 - compact field-normalizer for parity tuple
        None if value is None else value.quantize(sqlite_scale)
    )

    assert len(durable) == len(expected)
    assert [
        (
            item.side.value,
            item.physical_contract,
            item.owner_segment_id,
            item.calculation_segment_id,
            item.entry_bar_end,
            item.entry_reference_price,
            item.exit_bar_end,
            item.exit_reference_price,
            item.status.value,
            normalize(item.reference_return),
            item.holding_bars,
            item.mark_bar_end,
            item.mark_reference_price,
            normalize(item.mark_return),
        )
        for item in durable
    ] == [
        (
            item.side,
            item.physical_contract,
            item.segment_id,
            item.calculation_segment_id,
            item.entry_bar_end,
            item.entry_reference_price,
            item.exit_bar_end,
            item.exit_reference_price,
            item.status,
            normalize(item.reference_return_pct),
            item.holding_bars,
            item.mark_bar_end,
            item.mark_reference_price,
            normalize(item.mark_change_pct),
        )
        for item in expected
    ]


def test_interrupted_build_resumes_same_candidate_without_replaying_committed_prefix() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader, batch_size=10)
    calls = 0

    def interrupt_after_first(_stage, _context):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServiceInterrupted("test interruption")

    first = HistoricalReferenceService(
        repository, reader, after_batch=interrupt_after_first,
    ).execute(plan, plan.plan_hash)

    assert first.status == "partial"
    token = first.streams[0].resume_token
    assert token is not None
    candidate = repository.read_state(_stream().stream_id, token.revision_id)
    assert candidate.revision_status == "candidate"

    resumed = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )
    assert resumed.status == "completed", resumed.streams
    assert resumed.streams[0].completed_bars == len(reader.bars)
    assert repository.read_state(_stream().stream_id).revision_status == "active"


def test_execute_elapsed_budget_starts_before_input_reload_and_seed() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader, batch_size=10)
    times = iter((0.0, 31.0))

    report = HistoricalReferenceService(
        repository, reader, monotonic_clock=lambda: next(times),
    ).execute(plan, plan.plan_hash)

    assert report.status == "partial"
    assert report.streams[0].reason == "INTERRUPTED"
    assert report.streams[0].completed_bars == 0
    assert report.streams[0].resume_token is not None


def test_source_change_blocks_resume_without_creating_another_revision() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader, batch_size=10)

    def stop(_stage, _context):
        raise ServiceInterrupted("stop")

    first = HistoricalReferenceService(repository, reader, after_batch=stop).execute(
        plan, plan.plan_hash,
    )
    token = first.streams[0].resume_token
    assert token is not None
    reader.token = "source-v2"

    result = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )

    assert result.status == "blocked"
    assert result.streams[0].reason == "SOURCE_CHANGED"
    assert repository.read_state(_stream().stream_id, token.revision_id).revision_status == "candidate"


def test_resume_rejects_tampered_input_index_before_publishing_candidate() -> None:
    reader = Reader()
    repository = _repository()
    plan = _plan(reader, batch_size=10)

    def stop(_stage, _context):
        raise ServiceInterrupted("stop")

    first = HistoricalReferenceService(repository, reader, after_batch=stop).execute(
        plan, plan.plan_hash,
    )
    token = first.streams[0].resume_token
    assert token is not None
    forged = replace(token, next_input_index=len(reader.bars))

    result = HistoricalReferenceService(repository, reader).resume(
        plan, forged, plan.plan_hash,
    )

    assert result.status == "blocked"
    assert result.streams[0].reason == "REFERENCE_RESUME_POSITION_CONFLICT"
    state = repository.read_state(_stream().stream_id, token.revision_id)
    assert state.revision_status == "candidate"
    assert state.stream.active_revision_id is None


class _UnknownCommitRepository:
    def __init__(self, inner: ReferenceRepository, *, after_commit: bool) -> None:
        self.inner = inner
        self.after_commit = after_commit
        self.commit_calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def commit_batch(self, expected, prepared):
        self.commit_calls += 1
        if not self.after_commit:
            raise OSError("connection outcome unavailable")
        self.inner.commit_batch(expected, prepared)
        raise OSError("connection outcome unavailable")


class _TransientUnknownCommitRepository(_UnknownCommitRepository):
    def __init__(self, inner: ReferenceRepository) -> None:
        super().__init__(inner, after_commit=True)
        self.readback_available = False

    def read_batch(self, *args):
        if not self.readback_available:
            raise OSError("receipt readback temporarily unavailable")
        return self.inner.read_batch(*args)


def test_unknown_commit_after_database_commit_is_resolved_by_receipt_readback() -> None:
    reader = Reader()
    repository = _UnknownCommitRepository(_repository(), after_commit=True)
    plan = _plan(reader, batch_size=10)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "completed"
    assert repository.commit_calls > 0
    assert repository.read_state(_stream().stream_id).revision_status == "active"


def test_unknown_commit_without_receipt_stops_without_retry_and_returns_resume() -> None:
    reader = Reader()
    repository = _UnknownCommitRepository(_repository(), after_commit=False)
    plan = _plan(reader, batch_size=10)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "partial"
    assert repository.commit_calls == 1
    assert report.streams[0].reason == "COMMIT_OUTCOME_UNKNOWN"
    assert report.streams[0].resume_token is not None
    assert report.streams[0].resume_token.next_input_index == 0


def test_resume_reconciles_a_durable_batch_after_transient_unknown_commit() -> None:
    reader = Reader()
    repository = _TransientUnknownCommitRepository(_repository())
    plan = _plan(reader, batch_size=10)

    partial = HistoricalReferenceService(repository, reader).execute(
        plan, plan.plan_hash,
    )
    token = partial.streams[0].resume_token
    assert partial.streams[0].reason == "COMMIT_OUTCOME_UNKNOWN"
    assert token is not None
    assert token.next_input_index == 0
    repository.readback_available = True

    resumed = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )

    assert resumed.status == "completed", resumed.streams
    assert repository.read_state(_stream().stream_id).revision_status == "active"


class _UnknownPublishRepository:
    def __init__(self, inner: ReferenceRepository, *, after_publish: bool) -> None:
        self.inner = inner
        self.after_publish = after_publish
        self.publish_calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def publish_revision(self, *args):
        self.publish_calls += 1
        if not self.after_publish:
            raise OSError("publish outcome unavailable")
        self.inner.publish_revision(*args)
        raise OSError("publish outcome unavailable")


class _TransientUnknownPublishRepository(_UnknownPublishRepository):
    def __init__(self, inner: ReferenceRepository) -> None:
        super().__init__(inner, after_publish=True)
        self.readback_available = False

    def read_state(self, *args):
        if not self.readback_available:
            raise OSError("publish readback temporarily unavailable")
        return self.inner.read_state(*args)


def test_unknown_publish_after_commit_is_resolved_from_active_revision_readback() -> None:
    reader = Reader()
    repository = _UnknownPublishRepository(_repository(), after_publish=True)
    plan = _plan(reader, batch_size=100)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "completed"
    assert repository.publish_calls == 1
    assert repository.read_state(_stream().stream_id).revision_status == "active"


def test_unknown_publish_without_active_receipt_stops_with_resume_token() -> None:
    reader = Reader()
    repository = _UnknownPublishRepository(_repository(), after_publish=False)
    plan = _plan(reader, batch_size=100)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "partial"
    assert repository.publish_calls == 1
    assert report.streams[0].reason == "PUBLISH_OUTCOME_UNKNOWN"
    assert report.streams[0].resume_token is not None
    assert report.streams[0].resume_token.next_input_index == len(reader.bars)


def test_resume_reconciles_an_already_published_revision_without_republishing() -> None:
    reader = Reader()
    repository = _TransientUnknownPublishRepository(_repository())
    plan = _plan(reader, batch_size=100)

    partial = HistoricalReferenceService(repository, reader).execute(
        plan, plan.plan_hash,
    )
    token = partial.streams[0].resume_token
    assert partial.streams[0].reason == "PUBLISH_OUTCOME_UNKNOWN"
    assert token is not None
    repository.readback_available = True

    resumed = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )

    assert resumed.status == "completed", resumed.streams
    assert repository.publish_calls == 1
    assert resumed.streams[0].snapshot is not None


def test_source_change_inside_final_publish_guard_keeps_candidate_unpublished() -> None:
    class RacingReader(Reader):
        guard_count = 0

        @contextmanager
        def source_guard(self, request, *, expected_source_token):
            self.guard_count += 1
            if self.guard_count == 2:
                self.token = "source-v2"
            yield

    reader = RacingReader()
    repository = _repository()
    plan = _plan(reader, batch_size=100)

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "blocked"
    assert report.streams[0].reason == "SOURCE_CHANGED"
    revision_id = report.streams[0].candidate_revision_id
    assert revision_id is not None
    state = repository.read_state(_stream().stream_id, revision_id)
    assert state.revision_status == "candidate"
    assert state.stream.active_revision_id is None


def test_one_stream_failure_does_not_stop_an_independent_stream() -> None:
    class MultiReader(Reader):
        def _snapshot(self, request):
            result = super()._snapshot(request)
            if request.identity.product == "RB":
                return result
            converted = []
            for item in self.bars:
                payload = item.payload
                segment = replace(
                    payload.segment,
                    physical_contract="HC2605",
                    segment_id="owner-hc",
                )
                converted.append(replace(
                    item,
                    physical_contract="HC2605",
                    owner_segment_id="owner-hc",
                    calculation_segment_id="owner-hc",
                    payload=replace(payload, segment=segment),
                ))
            return replace(result, stream=request.identity, bars=tuple(converted))

        def load_stream(self, request, *, expected_source_token):
            if request.identity.product == "HC":
                raise ValueError("TEST_STREAM_FAILURE")
            return super().load_stream(
                request, expected_source_token=expected_source_token,
            )

    reader = MultiReader()
    rb = _stream()
    hc = replace(rb, product="HC")
    stream_request = _plan(reader).streams[0].request
    request = HistoricalReferenceRequest(
        "build",
        (
            replace(stream_request, identity=hc),
            replace(stream_request, identity=rb),
        ),
        WorkBudget(2, 200, 30, 200_000),
        batch_size=100,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: stream_request.as_of,
    ).plan(request)

    report = HistoricalReferenceService(_repository(), reader).execute(
        plan, plan.plan_hash,
    )

    assert report.status == "partial"
    assert [item.status for item in report.streams] == ["failed", "completed"]
    assert report.streams[0].reason == "TEST_STREAM_FAILURE"
