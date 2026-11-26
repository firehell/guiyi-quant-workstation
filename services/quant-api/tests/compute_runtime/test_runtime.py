from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from app.compute_runtime import ComputeBusy, ComputeRuntime, ComputeWindow
from guiyi_quant.compute import BarSeries, CompletedBar, FeatureRequest, REGISTRY, SeriesIdentity


START = datetime(2026, 11, 26, 1, tzinfo=UTC)
EMA = FeatureRequest("ema10")


def series(*, product="jm", contract="JM2701", revision="rev-1", count=12):
    identity = SeriesIdentity(product, contract, "segment-1", "1m", revision)
    points = []
    for index in range(count):
        end = START + timedelta(minutes=index)
        price = 100.0 + index
        points.append(CompletedBar(
            contract, "segment-1", START.date(), "session-1", end, end, end,
            price, price, price, price, 1.0, "VALID",
        ))
    return BarSeries(identity, tuple(points))


def window(bars):
    return ComputeWindow.from_series(bars, as_of=bars.bars[-1].available_at)


def test_batch_read_is_cache_only_and_running_work_is_bounded():
    source = series()
    other = series(product="rb", contract="RB2701")
    key = window(source)
    entered = Event()
    release = Event()
    calls = 0

    def load():
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(3)
        return source

    with ComputeRuntime(REGISTRY, batch_pending=1) as runtime:
        assert runtime.read_batch(key, (EMA,), use="web") is None
        assert calls == 0
        first = runtime.submit_batch(key, (EMA,), use="web", load=load)
        try:
            assert entered.wait(3)
            duplicate = runtime.submit_batch(key, (EMA,), use="web", load=load)
            assert runtime.read_batch(key, (EMA,), use="web") is None
            with pytest.raises(ComputeBusy, match="batch"):
                runtime.submit_batch(window(other), (EMA,), use="web", load=lambda: other)
        finally:
            release.set()
        result = first.result(timeout=3)
        assert duplicate.result(timeout=3) is result
        assert runtime.read_batch(key, (EMA,), use="web") == result
        assert calls == 1


def test_revision_invalidation_leaves_earlier_windows_and_other_series_reusable():
    source = series()
    other = series(product="rb", contract="RB2701")
    earlier = ComputeWindow.from_series(source, as_of=source.bars[4].available_at)
    with ComputeRuntime(REGISTRY) as runtime:
        for key, data in ((earlier, source), (window(source), source), (window(other), other)):
            runtime.submit_batch(key, (EMA,), use="web", load=lambda: data).result(timeout=3)

        runtime.invalidate_revision(source.identity, from_bar_end=source.bars[6].bar_end)
        assert runtime.read_batch(window(source), (EMA,), use="web") is None
        assert runtime.read_batch(earlier, (EMA,), use="web") is not None
        assert runtime.read_batch(window(other), (EMA,), use="web") is not None

        revised = series(revision="rev-2")
        result, = runtime.submit_batch(window(revised), (EMA,), use="web", load=lambda: revised).result(timeout=3)
        assert result.identity.source.source_revision == "rev-2"


def test_loaded_window_must_match_the_requested_prefix():
    source = series()
    target = window(source)
    truncated = BarSeries(source.identity, source.bars[1:])
    with ComputeRuntime(REGISTRY) as runtime:
        with pytest.raises(ValueError, match="COMPUTE_WINDOW_MISMATCH"):
            runtime.submit_batch(target, (EMA,), use="web", load=lambda: truncated).result(timeout=3)
        assert runtime.read_batch(target, (EMA,), use="web") is None

        wrong_owner = BarSeries(replace(source.identity, source_revision="revision-other"), source.bars)
        with pytest.raises(ValueError, match="COMPUTE_WINDOW_MISMATCH"):
            runtime.submit_batch(target, (EMA,), use="web", load=lambda: wrong_owner).result(timeout=3)


def test_invalidation_while_a_batch_is_loading_revokes_stale_publication():
    source = series()
    entered = Event()
    release = Event()

    def load():
        entered.set()
        assert release.wait(3)
        return source

    with ComputeRuntime(REGISTRY) as runtime:
        pending = runtime.submit_batch(window(source), (EMA,), use="web", load=load)
        try:
            assert entered.wait(3)
            runtime.invalidate_revision(source.identity, from_bar_end=source.bars[6].bar_end)
        finally:
            release.set()
        with pytest.raises(ValueError, match="COMPUTE_REVISION_INVALIDATED"):
            pending.result(timeout=3)
        assert runtime.read_batch(window(source), (EMA,), use="web") is None


def scope(bars, *, consumer, revision=None):
    from app.compute_runtime import ComputeScope

    owner = bars.identity
    return ComputeScope(consumer, owner.product, owner.physical_contract, owner.segment_id, owner.frequency, (EMA,), revision)


def test_live_scope_accepts_only_completed_contiguous_commits_and_deduplicates():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    first, following = full.bars[-2:]
    target = scope(full, consumer="htdy_simulation", revision=full.identity.source_revision)
    first_loads = 0

    def initial_prefix():
        nonlocal first_loads
        first_loads += 1
        return BarSeries(full.identity, full.bars[:-1])

    commit = CommittedLiveBar(full.identity, first, "commit-1", full.bars[-3].bar_end)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as runtime:
        with pytest.raises(ValueError, match="COMPUTE_SCOPE_NOT_ENABLED"):
            runtime.submit_live("newow_reference", commit, load=initial_prefix)
        with pytest.raises(ValueError, match="COMPUTE_SCOPE_NOT_ENABLED"):
            different_generation = replace(commit, source=replace(full.identity, source_revision="another-stream"))
            runtime.submit_live("htdy_simulation", different_generation, load=initial_prefix)
        original, = runtime.submit_live("htdy_simulation", commit, load=initial_prefix).result(timeout=3)
        repeated, = runtime.submit_live("htdy_simulation", commit, load=initial_prefix).result(timeout=3)
        assert repeated.duplicate
        assert original.checkpoint == repeated.checkpoint
        assert first_loads == 1

        rewritten_id = replace(commit, commit_id="a-different-commit")
        with pytest.raises(ValueError, match="COMPUTE_LIVE_COMMIT_CONFLICT"):
            runtime.submit_live("htdy_simulation", rewritten_id, load=initial_prefix).result(timeout=3)

        changed = replace(commit, bar=replace(first, close=first.close + 0.5))
        with pytest.raises(ValueError, match="STATE_INPUT_OUT_OF_ORDER_OR_REVISED"):
            runtime.submit_live("htdy_simulation", changed, load=initial_prefix).result(timeout=3)

        gap = CommittedLiveBar(full.identity, following, "commit-2", full.bars[-3].bar_end)
        with pytest.raises(ValueError, match="COMPUTE_LIVE_NONCONTIGUOUS"):
            runtime.submit_live("htdy_simulation", gap, load=initial_prefix).result(timeout=3)

        successor = replace(gap, previous_bar_end=first.bar_end)
        next_update, = runtime.submit_live("htdy_simulation", successor, load=initial_prefix).result(timeout=3)
        assert not next_update.duplicate
        assert next_update.checkpoint.identity.bar_count == len(full.bars)
        assert first_loads == 1
        expected, = REGISTRY.calculate(full, (EMA,), as_of=following.available_at, use="research")
        assert next_update.point == expected.points[-1]


def test_live_worker_rebuilds_incompatible_checkpoint_only_from_verified_prefix():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    target = scope(full, consumer="subing_simulation", revision=full.identity.source_revision)
    prior_full = BarSeries(full.identity, full.bars[:-1])
    prior_commit = CommittedLiveBar(full.identity, full.bars[-2], "commit-1", full.bars[-3].bar_end)
    last_commit = CommittedLiveBar(full.identity, full.bars[-1], "commit-2", full.bars[-2].bar_end)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as first:
        update, = first.submit_live("subing_simulation", prior_commit, load=lambda: prior_full).result(timeout=3)

    prior = replace(update.checkpoint, state_schema_version="retired", prefix_digest="incompatible-bytes", live_commit_id=None)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        with pytest.raises(ValueError, match="COMPUTE_LIVE_PREFIX_UNVERIFIED"):
            restarted.submit_live(
                "subing_simulation", last_commit, load=lambda: prior_full, checkpoints=(prior,),
            ).result(timeout=3)
        recovered, = restarted.submit_live(
            "subing_simulation", last_commit, load=lambda: full, checkpoints=(prior,),
        ).result(timeout=3)
        expected, = REGISTRY.calculate(full, (EMA,), as_of=full.bars[-1].available_at, use="research")
        assert recovered.point == expected.points[-1]
        assert recovered.recovery == "STATE_SCHEMA_REBUILT"
        assert recovered.checkpoint.prefix_digest != prior.prefix_digest


def test_live_restart_rejects_changed_earlier_prefix_under_the_same_source_identity():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    target = scope(full, consumer="subing_simulation", revision=full.identity.source_revision)
    before_prior = CommittedLiveBar(full.identity, full.bars[-3], "commit-0", full.bars[-4].bar_end)
    prior = CommittedLiveBar(full.identity, full.bars[-2], "commit-1", full.bars[-3].bar_end)
    following = CommittedLiveBar(full.identity, full.bars[-1], "commit-2", full.bars[-2].bar_end)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as runtime:
        older, = runtime.submit_live("subing_simulation", before_prior, load=lambda: full).result(timeout=3)
        first, = runtime.submit_live("subing_simulation", prior, load=lambda: full).result(timeout=3)

    old = full.bars[3]
    changed = replace(old, low=old.low - 1, close=old.close - 1)
    revised = BarSeries(full.identity, (*full.bars[:3], changed, *full.bars[4:]))
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        with pytest.raises(ValueError, match="COMPUTE_LIVE_NONCONTIGUOUS"):
            restarted.submit_live(
                "subing_simulation", following, load=lambda: full, checkpoints=(older.checkpoint,),
            ).result(timeout=3)
        for checkpoint in (first.checkpoint, replace(first.checkpoint, state_schema_version="unsupported")):
            with pytest.raises(ValueError, match="COMPUTE_LIVE_CHECKPOINT_CONFLICT"):
                restarted.submit_live(
                    "subing_simulation", following, load=lambda: revised, checkpoints=(checkpoint,),
                ).result(timeout=3)
        with pytest.raises(ValueError, match="COMPUTE_LIVE_COMMIT_CONFLICT"):
            restarted.submit_live(
                "subing_simulation", replace(following, commit_id=prior.commit_id),
                load=lambda: full, checkpoints=(first.checkpoint,),
            ).result(timeout=3)
        continued, = restarted.submit_live(
            "subing_simulation", following, load=lambda: full, checkpoints=(first.checkpoint,),
        ).result(timeout=3)
        expected, = REGISTRY.calculate(full, (EMA,), as_of=following.bar.available_at, use="research")
        assert not continued.duplicate
        assert continued.point == expected.points[-1]


def test_live_restart_preserves_committed_bar_boundary_when_availability_ties():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    first, following = full.bars[-2:]
    first = replace(first, available_at=following.available_at)
    full = BarSeries(full.identity, (*full.bars[:-2], first, following))
    prefix = BarSeries(full.identity, full.bars[:-1])
    consumer = "subing_simulation"
    target = scope(full, consumer=consumer, revision=full.identity.source_revision)
    prior_commit = CommittedLiveBar(full.identity, first, "commit-1", full.bars[-3].bar_end)
    next_commit = CommittedLiveBar(full.identity, following, "commit-2", first.bar_end)

    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as continuous:
        prior, = continuous.submit_live(consumer, prior_commit, load=lambda: prefix).result(timeout=3)
        expected, = continuous.submit_live(consumer, next_commit, load=lambda: full).result(timeout=3)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        restored, = restarted.submit_live(
            consumer, next_commit, load=lambda: full, checkpoints=(prior.checkpoint,),
        ).result(timeout=3)
        assert restored.checkpoint == expected.checkpoint
        assert restored.point == expected.point
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        repeated, = restarted.submit_live(
            consumer, prior_commit, load=lambda: full, checkpoints=(prior.checkpoint,),
        ).result(timeout=3)
        assert repeated.duplicate
        assert repeated.checkpoint == prior.checkpoint
        assert repeated.point == prior.point
        assert restarted.submit_live(consumer, next_commit, load=lambda: full).result(timeout=3) == (expected,)


def test_live_restart_rejects_multiple_checkpoints_for_one_feature_or_an_unsubscribed_feature():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    consumer = "subing_simulation"
    target = replace(scope(full, consumer=consumer, revision=full.identity.source_revision),
                     features=(EMA, FeatureRequest("ema21")))
    latest = CommittedLiveBar(full.identity, full.bars[-1], "commit-2", full.bars[-2].bar_end)
    earlier = CommittedLiveBar(full.identity, full.bars[-2], "commit-1", full.bars[-3].bar_end)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as running:
        first, _ = running.submit_live(consumer, latest, load=lambda: full).result(timeout=3)
    checkpoint = first.checkpoint
    stale = replace(checkpoint, identity=replace(checkpoint.identity, source=replace(full.identity, source_revision="old")))
    unrelated = replace(checkpoint, identity=replace(checkpoint.identity, feature_id="macd"))
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        for checkpoints in ((stale, checkpoint), (unrelated,)):
            with pytest.raises(ValueError, match="COMPUTE_CHECKPOINT_SCOPE_INVALID"):
                restarted.submit_live(consumer, earlier, load=lambda: full, checkpoints=checkpoints)


def test_post_canonical_revisions_reuse_only_verified_prefix_and_leave_live_worker_available():
    from app.compute_runtime import CommittedLiveBar
    from app.market_data.market_archive import MarketArchiveReceipt

    initial = series(count=11)
    full = series(revision="rev-2")
    canonical = scope(full, consumer="canonical_research")
    live = scope(initial, consumer="subing_simulation", revision=initial.identity.source_revision)
    batch_entered, batch_release = Event(), Event()

    def load_batch():
        batch_entered.set()
        assert batch_release.wait(3)
        return initial

    def receipt(bars):
        return MarketArchiveReceipt(
            f"receipt-{bars.identity.source_revision}", START.date(), bars.bars[-1].available_at,
            {"jm": bars.identity.source_revision},
        )

    def load_source():
        raise AssertionError("retry of the same receipt should reuse its compute result")

    with ComputeRuntime(REGISTRY, canonical_scopes=(canonical,), live_scopes=(live,)) as runtime:
        active_batch = runtime.submit_batch(window(initial), (EMA,), use="web", load=load_batch)
        try:
            assert batch_entered.wait(3)
            with pytest.raises(ValueError, match="COMPUTE_CANONICAL_RECEIPT_REQUIRED"):
                runtime.submit_canonical({}, window(initial), consumer="canonical_research", load=lambda: initial)
            with pytest.raises(ValueError, match="COMPUTE_CANONICAL_RECEIPT_MISMATCH"):
                runtime.submit_canonical(receipt(initial), window(full), consumer="canonical_research", load=lambda: full)
            first, = runtime.submit_canonical(
                receipt(initial), window(initial), consumer="canonical_research", load=lambda: initial,
            ).result(timeout=3)
            assert first.resumed_bars == 0

            commit = CommittedLiveBar(initial.identity, initial.bars[-1], "latest", initial.bars[-2].bar_end)
            advance, = runtime.submit_live("subing_simulation", commit, load=lambda: initial).result(timeout=3)
            assert advance.point == first.point

            next_result, = runtime.submit_canonical(
                receipt(full), window(full), consumer="canonical_research", load=lambda: full,
            ).result(timeout=3)
            assert next_result.resumed_bars == len(initial.bars)
            assert runtime.submit_canonical(
                receipt(full), window(full), consumer="canonical_research", load=load_source,
            ).result(timeout=3) == (next_result,)

            old = full.bars[5]
            revised = BarSeries(
                replace(full.identity, source_revision="rev-3"),
                (*full.bars[:5], replace(old, low=old.low - 1, close=old.close - 1), *full.bars[6:]),
            )
            changed, = runtime.submit_canonical(
                receipt(revised), window(revised), consumer="canonical_research", load=lambda: revised,
            ).result(timeout=3)
            expected, = REGISTRY.calculate(revised, (EMA,), as_of=revised.bars[-1].available_at, use="research")
            assert changed.resumed_bars == 0
            assert changed.point == expected.points[-1]
            assert changed.point != next_result.point
        finally:
            batch_release.set()
        assert active_batch.result(timeout=3)


def test_batch_reuses_a_dependency_across_queries_without_bypassing_its_permissions():
    from guiyi_quant.compute import ComputeRegistry

    source = series(count=25)
    ema10 = REGISTRY.definition("ema10")
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return ema10.calculate(*args)

    registry = ComputeRegistry((
        replace(ema10, calculate=counted, allowed_uses=frozenset(("web",))),
        replace(REGISTRY.definition("ema21"), dependencies=(EMA,)),
    ))
    main = (FeatureRequest("ema21"),)
    key = window(source)

    with ComputeRuntime(registry) as runtime:
        runtime.submit_batch(key, main, use="web", load=lambda: source).result(timeout=3)
        assert runtime.read_batch(key, (EMA,), use="web") is not None
        with pytest.raises(ValueError, match="FEATURE_USE_NOT_ALLOWED: ema10"):
            runtime.read_batch(key, main, use="research")
        assert calls == 1


def test_batch_waiter_cancel_does_not_cancel_shared_work():
    source = series()
    entered = Event()
    release = Event()

    def load():
        entered.set()
        assert release.wait(3)
        return source

    with ComputeRuntime(REGISTRY, batch_pending=1) as runtime:
        first = runtime.submit_batch(window(source), (EMA,), use="web", load=load)
        try:
            assert entered.wait(3)
            other = runtime.submit_batch(window(source), (EMA,), use="research", load=load)
            assert first.cancel()
        finally:
            release.set()
        assert other.result(timeout=3)


def test_same_day_receipt_retry_does_not_publish_the_same_revision_again():
    from app.market_data.market_archive import MarketArchiveReceipt

    source = series()
    timestamp = window(source).as_of
    later = timestamp + timedelta(seconds=5)
    canonical = scope(source, consumer="canonical_research")
    first_receipt = MarketArchiveReceipt("retained", START.date(), timestamp, {"jm": source.identity.source_revision})
    retry_receipt = replace(first_receipt, finished_at=later)

    def load_again():
        raise AssertionError("retry tried to recompute an already successful receipt")

    with ComputeRuntime(REGISTRY, canonical_scopes=(canonical,)) as runtime:
        before = runtime.submit_canonical(
            first_receipt, window(source), consumer="canonical_research", load=lambda: source,
        ).result(timeout=3)
        after = runtime.submit_canonical(
            retry_receipt, ComputeWindow.from_series(source, as_of=later),
            consumer="canonical_research", load=load_again,
        ).result(timeout=3)
        assert before is after
        assert after[0].checkpoint.identity.as_of == timestamp


def test_canonical_correction_uses_closest_unchanged_checkpoint():
    from app.market_data.market_archive import MarketArchiveReceipt

    prior = series(count=5)
    original = series(revision="rev-2")
    edited = original.bars[6]
    corrected = BarSeries(
        replace(original.identity, source_revision="rev-3"),
        (*original.bars[:6], replace(edited, low=edited.low - 2, close=edited.close - 2), *original.bars[7:]),
    )

    def update(runtime, bars):
        receipt = MarketArchiveReceipt(
            f"receipt-{bars.identity.source_revision}", START.date(), bars.bars[-1].available_at,
            {"jm": bars.identity.source_revision},
        )
        result, = runtime.submit_canonical(
            receipt, window(bars), consumer="canonical_research", load=lambda: bars,
        ).result(timeout=3)
        return result

    with ComputeRuntime(REGISTRY, canonical_scopes=(scope(prior, consumer="canonical_research"),)) as runtime:
        update(runtime, prior)
        update(runtime, original)
        runtime.invalidate_revision(original.identity, from_bar_end=edited.bar_end)
        result = update(runtime, corrected)
        assert result.resumed_bars == len(prior.bars)
        expected, = REGISTRY.calculate(corrected, (EMA,), as_of=edited.bar_end + timedelta(minutes=5), use="research")
        assert result.point == expected.points[-1]


def test_restart_with_latest_checkpoint_identifies_replayed_commit_and_rejects_cursors_behind():
    from app.compute_runtime import CommittedLiveBar

    full = series()
    target = scope(full, consumer="subing_simulation", revision=full.identity.source_revision)
    final = CommittedLiveBar(full.identity, full.bars[-1], "last", full.bars[-2].bar_end)
    earlier = CommittedLiveBar(full.identity, full.bars[-2], "prior", full.bars[-3].bar_end)
    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as first:
        final_update, = first.submit_live("subing_simulation", final, load=lambda: full).result(timeout=3)

    with ComputeRuntime(REGISTRY, live_scopes=(target,)) as restarted:
        for checkpoint in (
            final_update.checkpoint,
            replace(final_update.checkpoint, state_schema_version="unsupported"),
        ):
            with pytest.raises(ValueError, match="COMPUTE_LIVE_CHECKPOINT_AHEAD"):
                restarted.submit_live(
                    "subing_simulation", earlier, load=lambda: full, checkpoints=(checkpoint,),
                ).result(timeout=3)
        with pytest.raises(ValueError, match="COMPUTE_LIVE_COMMIT_CONFLICT"):
            restarted.submit_live(
                "subing_simulation", replace(final, commit_id="rewritten"),
                load=lambda: full, checkpoints=(final_update.checkpoint,),
            ).result(timeout=3)
        with pytest.raises(ValueError, match="COMPUTE_LIVE_COMMIT_CONFLICT"):
            restarted.submit_live(
                "subing_simulation", final, load=lambda: full,
                checkpoints=(replace(final_update.checkpoint, live_commit_id=None),),
            ).result(timeout=3)
        repeated, = restarted.submit_live(
            "subing_simulation", final, load=lambda: full, checkpoints=(final_update.checkpoint,),
        ).result(timeout=3)
        assert repeated.duplicate
        assert repeated.checkpoint == final_update.checkpoint


def test_canonical_receipts_out_of_order_cannot_return_a_future_publication():
    from app.market_data.market_archive import MarketArchiveReceipt

    source = series()
    earlier = window(source).as_of
    later = earlier + timedelta(minutes=1)
    original = MarketArchiveReceipt("original", START.date(), earlier, {"jm": source.identity.source_revision})
    retry = replace(original, identity="retry", finished_at=later)

    with ComputeRuntime(REGISTRY, canonical_scopes=(scope(source, consumer="canonical_research"),)) as runtime:
        first = runtime.submit_canonical(
            retry, ComputeWindow.from_series(source, as_of=later),
            consumer="canonical_research", load=lambda: source,
        )
        next_ = runtime.submit_canonical(
            original, window(source), consumer="canonical_research", load=lambda: source,
        )
        assert first.result(timeout=3)[0].checkpoint.identity.as_of == later
        assert next_.result(timeout=3)[0].checkpoint.identity.as_of == earlier


def test_batch_windows_with_different_members_do_not_hit_same_cache():
    source = series(count=18)
    one = BarSeries(source.identity, (*source.bars[:3], *source.bars[4:]))
    two = BarSeries(source.identity, (*source.bars[:12], *source.bars[13:]))
    with ComputeRuntime(REGISTRY) as runtime:
        base, = runtime.submit_batch(window(one), (EMA,), use="web", load=lambda: one).result(timeout=3)
        assert runtime.read_batch(window(two), (EMA,), use="web") is None
        actual, = runtime.submit_batch(window(two), (EMA,), use="web", load=lambda: two).result(timeout=3)
        assert base.identity.input_digest != actual.identity.input_digest
        expected, = REGISTRY.calculate(two, (EMA,), use="web", as_of=window(two).as_of)
        assert actual == expected
