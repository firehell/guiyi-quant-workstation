from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary

from app.reference_trading.inputs import _insert_boundaries
from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest
from app.reference_trading.service import HistoricalReferenceService
from tests.reference_trading.test_bootstrap import Reader, _plan, _repository


def _append_plan(reader: Reader, base_plan, *, operation: str):
    last = reader.bars[-1]
    payload = last.payload
    extra_bar = replace(
        payload.bar,
        bar_end=payload.bar.bar_end + timedelta(days=1),
        trading_day=payload.bar.trading_day + timedelta(days=1),
    )
    extra_payload = replace(
        payload,
        segment=replace(
            payload.segment,
            bars=(*payload.segment.bars, extra_bar),
            owner_through=extra_bar.trading_day,
        ),
        bar=extra_bar,
        through=extra_bar.trading_day,
    )
    # Existing payloads keep stable since/through context; only the tail receives
    # the extended owner horizon so old fingerprints are not recalculated.
    from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint

    extra = replace(
        last,
        bar_end=extra_bar.bar_end,
        trading_day=extra_bar.trading_day,
        reference_price=extra_bar.close,
        fingerprint=strategy_input_fingerprint({"bar": extra_bar.bar_end, "close": extra_bar.close}),
        payload=extra_payload,
    )
    reader.bars = (*reader.bars, extra)
    reader.token = "source-v2"
    request = replace(
        base_plan.streams[0].request,
        through=extra_bar.trading_day,
        as_of=extra_bar.bar_end + timedelta(seconds=1),
    )
    requested = HistoricalReferenceRequest(
        operation,
        (request,),
        replace(base_plan.budget, max_input_bars=200),
        base_plan.batch_size,
    )
    original = reader._snapshot

    def snapshot(req):
        result = original(req)
        return replace(
            result,
            dependency_manifest={
                **result.dependency_manifest,
                "partitions": [
                    *result.dependency_manifest["partitions"],
                    {"key": "RB2605-tail", "sha256": "b" * 64},
                ],
            },
        )

    reader._snapshot = snapshot
    return HistoricalReferencePlanner(reader, now=lambda: request.as_of).plan(requested)


def test_advance_steps_only_new_tail_and_advances_dependency_atomically() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=10)
    assert HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash).status == "completed"
    next_plan = _append_plan(reader, initial, operation="advance")
    stepped = 0

    def count(value):
        nonlocal stepped
        stepped += value

    report = HistoricalReferenceService(repository, reader, step_counter=count).advance(
        next_plan, next_plan.plan_hash,
    )

    assert report.status == "completed"
    assert stepped == 1
    state = repository.read_state(initial.streams[0].request.identity.stream_id)
    assert state.dependency_manifest == next_plan.streams[0].input_manifest
    assert state.checkpoint.seq == initial.streams[0].input_count // 10 + 2 + 1


def test_advance_with_no_new_input_and_same_manifest_is_zero_write_noop() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=10)
    first = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    before = repository.read_state(initial.streams[0].request.identity.stream_id)
    requested = HistoricalReferenceRequest(
        "advance", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    report = HistoricalReferenceService(repository, reader).advance(plan, plan.plan_hash)
    after = repository.read_state(initial.streams[0].request.identity.stream_id)

    assert first.status == "completed"
    assert report.status == "noop"
    assert after == before


def test_changed_prefix_requires_rebuild_instead_of_append() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=10)
    HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    reader.token = "source-changed"
    original = reader._snapshot

    def changed(req):
        result = original(req)
        manifest = {**result.dependency_manifest}
        manifest["partitions"] = [{"key": "RB2605", "sha256": "f" * 64}]
        return replace(result, dependency_manifest=manifest)

    reader._snapshot = changed
    requested = HistoricalReferenceRequest(
        "advance", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    report = HistoricalReferenceService(repository, reader).advance(plan, plan.plan_hash)

    assert report.status == "blocked"
    assert report.streams[0].reason == "REBUILD_REQUIRED"


def test_boundary_added_to_processed_last_bar_requires_rebuild() -> None:
    reader = Reader()
    reader.data_interruptions = []
    original_snapshot = reader._snapshot

    def with_input_identity(req):
        result = original_snapshot(req)
        return replace(result, dependency_manifest={
            **result.dependency_manifest,
            "input_fingerprints": [item.fingerprint for item in reader.bars],
            "data_interruptions": list(reader.data_interruptions),
        })

    reader._snapshot = with_input_identity
    repository = _repository()
    initial = _plan(reader, batch_size=10)
    assert HistoricalReferenceService(
        repository, reader,
    ).execute(initial, initial.plan_hash).status == "completed"

    anchor = reader.bars[-1]
    boundary = ReferenceBoundary(
        initial.streams[0].request.identity,
        BoundaryReason.DATA_INTERRUPTED,
        anchor.physical_contract,
        anchor.owner_segment_id,
        anchor.calculation_segment_id,
        anchor.bar_end,
        anchor.trading_day,
    )
    reader.bars = tuple(_insert_boundaries(list(reader.bars), (boundary,)))
    reader.data_interruptions.append("interruption-on-processed-last-bar")
    advance_plan = _append_plan(reader, initial, operation="advance")

    advanced = HistoricalReferenceService(repository, reader).advance(
        advance_plan, advance_plan.plan_hash,
    )

    assert advanced.status == "blocked"
    assert advanced.streams[0].reason == "REBUILD_REQUIRED"
