from dataclasses import replace
import json
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.compute_runtime import ComputeScope
from app.compute_runtime.canonical_publications import CanonicalPublicationCompute, CanonicalResearchWindow
from app.compute_runtime.formal_publications import FormalCanonicalPublications, configured_windows
from app.market_data.after_market import AfterMarketResult, _atomic_write_status
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_archive import (
    build_isolated_archive, current_retained_receipt, reference_catalog_revision, retain_archive_receipt,
    retain_archive_status,
)
from app.market_data.storage import CanonicalMonthlyStore
from app.models import Contract, Exchange, Instrument, MainContractMap, TradingSession
from guiyi_quant.compute import FeatureRequest
from tests.data_foundation.test_market_archive import DAY, FINISHED, _status
from tests.data_foundation.test_market_pagination import _bar, _publish
from tests.data_foundation.test_tick_htdy_integration import disposable_market  # noqa: F401


def _scope(contract, since, through):
    scope = ComputeScope("canonical_research", "jm", contract, f"contract:{contract}", "1d",
                         (FeatureRequest("ema10"),))
    return CanonicalResearchWindow(scope, DAY.replace(day=since), DAY.replace(day=through))


def test_physical_subscription_refuses_an_unproved_segment():
    target = _scope("JM2701", 5, 15)
    with pytest.raises(ValueError, match="COMPUTE_CANONICAL_PHYSICAL_SCOPE_REQUIRED"):
        replace(target, scope=replace(target.scope, segment_id="JM2701:2026-11-05"))


@pytest.mark.isolated_postgresql
def test_committed_archive_drives_only_changed_scopes(
    disposable_market, monkeypatch, tmp_path, caplog,  # noqa: F811
):
    engine, redis = disposable_market
    root = tmp_path / "canonical"
    root.mkdir()
    monkeypatch.setenv("GUIYI_MARKET_FOUNDATION_SANDBOX", str(tmp_path))
    port = redis.connection_pool.connection_kwargs["port"]
    old = _scope("JM2701", 5, 15)
    other = _scope("JM2705", 16, 26)
    clock = [FINISHED]
    storage = CanonicalMonthlyStore(root)

    with Session(engine) as seed:
        seed.add(Exchange(code="DCE", name="DCE"))
        seed.flush()
        seed.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        seed.flush()
        seed.add_all(Contract(
            contract_code=target.scope.physical_contract, instrument_symbol="jm", exchange_code="DCE",
            listed_date=target.since, expired_date=DAY + timedelta(days=1),
        ) for target in (old, other))
        seed.add_all(MainContractMap(symbol="jm", trade_date=target.since, contract_code=target.scope.physical_contract)
                     for target in (old, other))
        seed.add(TradingSession(
            exchange_code="DCE", instrument_symbol="jm", session_name="day",
            start_time=time(9), end_time=time(15), effective_from=date(DAY.year, DAY.month, 1),
        ))
        seed.commit()

    def publish(target, close, *, revised=None):
        with Session(engine) as db:
            bars = tuple(_bar(
                day, close if revised is None or day != revised[0] else revised[1], month=DAY.month,
            ) for day in range(target.since.day, target.through.day + 1))
            bars = tuple(replace(bar, bar_end=bar.bar_end.replace(year=DAY.year),
                                 trading_day=bar.trading_day.replace(year=DAY.year)) for bar in bars)
            key = DatasetKey("contract", "jm", target.scope.physical_contract, "1d")
            _publish(MarketCatalog(db, root), storage, key, bars)
            db.commit()

    publish(old, 100)
    publish(other, 200)
    reference_receipts = []
    monkeypatch.setattr(
        "app.market_data.newow.market_reference_after_close.run_receipt",
        lambda sandbox, receipt, **_: reference_receipts.append(receipt.identity),
    )

    with Session(engine) as publisher_session, CanonicalPublicationCompute(
        engine, root, (old, other), now=lambda: clock[0],
    ) as compute:
        updater = build_isolated_archive(
            SimpleNamespace(catalog=MarketCatalog(publisher_session, root)),
            redis_url=f"redis://127.0.0.1:{port}/12", live_store=RedisLiveStore(redis),
            rqdata_factory=lambda: pytest.fail("no vendor in this test"), sleep=lambda _: None,
            products=("jm",), now=lambda: clock[0], canonical_compute=compute,
        )
        submissions = []
        submit = compute._runtime.submit_canonical

        def record(receipt, window, **kwargs):
            submissions.append((receipt.identity, window.source.physical_contract))
            return submit(receipt, window, **kwargs)

        monkeypatch.setattr(compute._runtime, "submit_canonical", record)

        def finish_guarded():
            with Session(engine) as proof:
                digest = reference_catalog_revision(proof, "jm", DAY)
            _atomic_write_status(updater.status_path, _status(finished=clock[0], digest=digest))
            return AfterMarketResult("passed", DAY, 1, None)

        # A failed guard does not reach the success callback.
        monkeypatch.setattr(updater, "_run_guarded", lambda: AfterMarketResult("failed", DAY, 1, "TEST"))
        assert updater.run().status == "failed" and submissions == []
        monkeypatch.setattr(updater, "_run_guarded", finish_guarded)
        assert updater.run().status == "passed"
        initial, = compute.latest_result(old)
        unaffected = compute.latest_result(other)
        assert initial.point.values == {"value": 100}
        assert initial.point.available_at == FINISHED
        assert unaffected[0].point.values == {"value": 200}
        assert [contract for _, contract in submissions] == ["JM2701", "JM2705"]

        clock[0] += timedelta(minutes=1)
        assert updater.run().status == "passed"
        assert len(submissions) == 2
        assert reference_receipts[0] == reference_receipts[1]

        publish(old, 100, revised=(15, 133))
        clock[0] += timedelta(minutes=1)
        assert updater.run().status == "passed"
        corrected, = compute.latest_result(old)
        assert corrected.point.values == {"value": 106}
        assert corrected.point.bar_end == initial.point.bar_end
        assert corrected.point.available_at == clock[0]
        assert corrected.checkpoint.identity.source.source_revision != initial.checkpoint.identity.source.source_revision
        assert compute.latest_result(other) is unaffected
        assert submissions[-1][1] == "JM2701" and len(submissions) == 3

        # An older trading-day repair may finish later without rolling back the
        # already accepted end of the next day's window.
        late_day = DAY - timedelta(days=1)
        clock[0] += timedelta(minutes=1)
        with Session(engine) as proof:
            late = _status(finished=clock[0], digest=reference_catalog_revision(proof, "jm", late_day))
        late["last_successful_trading_day"] = late_day.isoformat()
        late["last_run"]["trading_day"] = late_day.isoformat()
        late["last_run"]["live_evidence"]["trading_day"] = late_day.isoformat()
        late_status = tmp_path / "older-repair.json"
        _atomic_write_status(late_status, late)
        late_receipt = retain_archive_receipt(late_status, now=clock[0])
        assert compute.accept(late_receipt, late_day) == ()
        assert compute.latest_result(other) is unaffected and len(submissions) == 3

        # A once-current receipt is stale when its Catalog pointer has changed.
        earlier = retain_archive_receipt(updater.status_path, now=clock[0])
        publish(old, 100, revised=(15, 155))
        with CanonicalPublicationCompute(engine, root, (old,), now=lambda: clock[0]) as fresh:
            with pytest.raises(ValueError, match="MARKET_ARCHIVE_SOURCE_CHANGED"):
                fresh.accept(earlier, DAY)
            assert fresh.latest_result(old) is None

        def race(receipt, window, **kwargs):
            job = record(receipt, window, **kwargs)
            publish(old, 100, revised=(15, 177))
            return job

        monkeypatch.setattr(compute._runtime, "submit_canonical", race)
        clock[0] += timedelta(minutes=1)
        assert updater.run().status == "passed"
        assert compute.latest_result(old) == (corrected,)
        assert compute.latest_result(other) is unaffected
        assert "market_archive_compute_pending" in caplog.text

        monkeypatch.setattr(compute._runtime, "submit_canonical", record)
        clock[0] += timedelta(minutes=1)
        assert updater.run().status == "passed"
        recovered, = compute.latest_result(old)
        assert recovered.point.values == {"value": 114}
        assert recovered.point.available_at == clock[0]
        assert compute.latest_result(other) is unaffected


    # The prepared subscriber uses the formal archive hash mode and retains
    # the accepted result/cursor outside the Market and application trees.
    archive = tmp_path / "formal-archive"
    archive.mkdir(mode=0o700)
    previous = archive / "canonical-compute-progress.json"
    previous.write_bytes(b'{"schema":1,"scope":"former ordered scope with PD/PT","rows":{}}')
    (archive / "canonical-compute-windows.json").write_text(json.dumps([
        {"product": "jm", "contract": row.scope.physical_contract, "frequency": "1d",
         "features": ["ema10"], "since": row.since.isoformat(), "through": row.through.isoformat()}
        for row in (old, other)
    ]))

    def formal_receipt(day):
        clock[0] += timedelta(minutes=1)
        with Session(engine) as proof:
            digest = reference_catalog_revision(proof, "jm", day, archive_scope=True)
        status = _status(finished=clock[0], digest=digest)
        status["last_successful_trading_day"] = day.isoformat()
        status["last_run"]["trading_day"] = day.isoformat()
        status["last_run"]["live_evidence"]["trading_day"] = day.isoformat()
        return retain_archive_status(status, now=clock[0], archive_root=archive, formal=True)

    def current():
        return current_retained_receipt(archive, now=clock[0])

    assert configured_windows(archive) == (old, other)
    with FormalCanonicalPublications(engine, root, now=lambda: clock[0]) as service:
        assert service.poll(archive, None) == "waiting_archive"
        first_path = formal_receipt(DAY)
        assert service.poll(archive, current()) == "current"
    assert previous.read_bytes() == b'{"schema":1,"scope":"former ordered scope with PD/PT","rows":{}}'

    with CanonicalPublicationCompute(engine, root, (old, other), now=lambda: clock[0], archive_root=archive) as restarted:
        prior = restarted.latest_result(old)
        other_prior = restarted.latest_result(other)
        assert prior and prior[0].point.values == {"value": 114}
        submit = restarted._runtime.submit_canonical
        monkeypatch.setattr(restarted._runtime, "submit_canonical", lambda *a, **kw: pytest.fail("duplicate job"))
        assert restarted.accept(first_path, DAY) == ()
        late_day = DAY - timedelta(days=1)
        late_path = formal_receipt(late_day)
        assert restarted.accept(late_path, late_day) == ()
        assert restarted.latest_result(old) == prior and current().identity == first_path.stem
        monkeypatch.setattr(restarted._runtime, "submit_canonical", submit)

        publish(old, 100, revised=(15, 188))
        second = formal_receipt(DAY)
        with pytest.raises(RuntimeError, match="COMPUTE_CANONICAL_DRAINING"):
            restarted.accept(second, DAY, stop_requested=lambda: True)
        assert restarted.latest_result(old) == prior
        publish(old, 100, revised=(15, 199))
        with pytest.raises(ValueError, match="MARKET_ARCHIVE_SOURCE_CHANGED"):
            restarted.accept(second, DAY)
        assert restarted.latest_result(old) == prior
        latest = formal_receipt(DAY)
        revised, = restarted.accept(latest, DAY)
        assert revised.point.values == {"value": 118}
        assert restarted.latest_result(other) == other_prior

    with CanonicalPublicationCompute(engine, root, (old, other), now=lambda: clock[0], archive_root=archive) as recovered:
        assert recovered.latest_result(old) == (revised,)
        assert recovered.latest_result(other) == other_prior
        assert recovered.accept(latest, DAY) == ()


def test_formal_compute_ignores_retired_subscriptions_without_suppressing_active_ones(tmp_path):
    rows = [
        {"product": product, "contract": contract, "frequency": "1m", "features": ["ema"],
         "since": "2026-11-25", "through": "2026-11-27"}
        for product, contract in (("rb", "RB2701"), (" PD ", "PD2701"), ("pt", "PT2701"))
    ]
    path = tmp_path / "canonical-compute-windows.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert [window.scope.product for window in configured_windows(tmp_path)] == ["rb"]
    path.write_text(json.dumps(rows[1:]), encoding="utf-8")
    assert configured_windows(tmp_path) == ()
