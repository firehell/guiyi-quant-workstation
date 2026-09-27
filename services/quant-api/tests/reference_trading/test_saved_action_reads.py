from datetime import UTC, date, datetime
from copy import deepcopy
import pytest
from sqlalchemy import select
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.presentation import envelope, presentation_point
from tests.reference_trading.test_repository import (
    _seed_repository,
    _open_batch,
    _digest,
)


def saved_actions(monkeypatch, count=3, input_count=3):
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    evidence = {"presentation_v1": envelope([])}
    repository.commit_batch(
        seed, _open_batch(stream, revision, manifest, seed, evidence=evidence)
    )
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest)
    )
    manifest = {**manifest, "input_count": input_count}
    with factory() as session:
        template = session.scalar(
            select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream.stream_id,
                ReferenceBatch.kind == "calculation",
            )
        )
        values = {
            c.name: deepcopy(getattr(template, c.name))
            for c in ReferenceBatch.__table__.columns
        }
        values["dependency_manifest"] = manifest
        session.delete(template)
        session.flush()
        seq = 1
        for start in range(0, count, 1000):
            seq += 1
            points = [
                presentation_point(
                    kind="action",
                    formula_versions=("v1",),
                    trading_day=date(2026, 9, 19),
                    value={
                        "signal_id": f"action-{i}",
                        "bar_end": "2026-09-19T07:00:00+00:00",
                        "physical_contract": "RB2610",
                        "segment_id": "owner-1",
                        "sequence": i,
                    },
                )
                for i in range(start, min(count, start + 1000))
            ]
            session.add(
                ReferenceBatch(
                    **{
                        **values,
                        "batch_id": f"test-batch-{seq}",
                        "batch_key": f"test-key-{seq}",
                        "seq": seq,
                        "source_evidence": {"presentation_v1": envelope(points)},
                    }
                )
            )
        session.get(ReferenceStream, stream.stream_id).latest_seq = seq
        session.get(ReferenceRevision, (stream.stream_id, revision)).last_seq = seq
        session.commit()
    monkeypatch.setattr(
        HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True)
    )
    query = HistoricalReferenceQuery(factory)
    summary = query.summary(
        stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 19)
    )
    params = {
        "snapshot_token": summary["snapshot"],
        "since": date.min,
        "through": date(2026, 9, 19),
        "cutoff": None,
    }
    return query, factory, stream, params


def test_historical_actions_exceed_web_cap_without_truncation(monkeypatch):
    query, _, stream, params = saved_actions(
        monkeypatch, count=200001, input_count=100001
    )
    with pytest.raises(QueryConflict, match="PRESENTATION_BUDGET_EXCEEDED"):
        query.presentation_facts(
            stream.stream_id, **params, kinds=("action",), max_points=200000
        )
    points = list(
        query.historical_actions(stream.stream_id, **params, input_count=100001)
    )
    assert len(points) == 200001
    assert points[0]["value"]["signal_id"] == "action-0"
    assert all(
        point["value"]["signal_id"] == f"action-{i}" for i, point in enumerate(points)
    )


@pytest.mark.parametrize("input_count", (True, 0, -1, "3", 3.0))
def test_historical_actions_reject_untrusted_count(monkeypatch, input_count):
    query, _, stream, params = saved_actions(monkeypatch)
    with pytest.raises(QueryConflict):
        list(
            query.historical_actions(
                stream.stream_id, **params, input_count=input_count
            )
        )


def test_historical_action_budget_and_snapshot_fail_closed(monkeypatch):
    query, _, stream, params = saved_actions(monkeypatch, count=3, input_count=1)
    with pytest.raises(QueryConflict):
        list(query.historical_actions(stream.stream_id, **params, input_count=1))
    with pytest.raises(QueryConflict):
        list(query.historical_actions(stream.stream_id, **params, input_count=3))
    with pytest.raises(QueryConflict):
        list(
            query.historical_actions(
                stream.stream_id,
                **{**params, "through": date(2026, 9, 20)},
                input_count=1,
            )
        )


def test_historical_cancel_closes_transaction_and_subsequent_read_succeeds(monkeypatch):
    query, factory, stream, params = saved_actions(monkeypatch)
    seen = []

    def cancelled():
        seen.append(1)
        if len(seen) > 1:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        list(
            query.historical_actions(
                stream.stream_id, **params, input_count=3, check_cancelled=cancelled
            )
        )
    assert (
        len(list(query.historical_actions(stream.stream_id, **params, input_count=3)))
        == 3
    )
    with factory() as session:
        assert not session.in_transaction()


def test_closing_iterator_releases_connection_and_web_cap_remains_fixed(monkeypatch):
    from sqlalchemy import event

    query, factory, stream, params = saved_actions(monkeypatch)
    with factory() as session:
        engine = session.get_bind()
    events = []
    event.listen(engine, "checkout", lambda *_: events.append("checkout"))
    event.listen(engine, "checkin", lambda *_: events.append("checkin"))
    with pytest.raises(QueryConflict):
        query.presentation_facts(
            stream.stream_id, **params, kinds=("action",), max_points=200001
        )
    assert events.count("checkout") == events.count("checkin")
    iterator = query.historical_actions(stream.stream_id, **params, input_count=3)
    assert next(iterator)["value"]["signal_id"] == "action-0"
    assert events.count("checkout") == events.count("checkin") + 1
    iterator.close()
    assert events.count("checkout") == events.count("checkin")


def test_exact_saved_manifest_count_type_is_required(monkeypatch):
    query, _, stream, params = saved_actions(monkeypatch, input_count=True)
    with pytest.raises(QueryConflict):
        list(query.historical_actions(stream.stream_id, **params, input_count=1))


def test_saved_fusion_sources_keep_actions_and_dependencies_and_close_on_decode_error(
    monkeypatch,
):
    from types import SimpleNamespace
    from newow.product_fixtures import ProductCases
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductStrategy, ProductFrequency
    from app.reference_trading.newow_fusion import SavedFusionSources
    from app.reference_trading.presentation import _wire
    from dataclasses import replace

    cases = ProductCases()
    identities = {
        s: build_product_identity("rb", s, ProductFrequency("1m"))
        for s in (ProductStrategy.TREND, ProductStrategy.OSCILLATION)
    }
    expected = {
        s: [
            replace(
                cases.closed(strategy=s.value, frequency="1m").entry, identity=identity
            ),
            replace(
                cases.closed(strategy=s.value, frequency="1m").exit, identity=identity
            ),
        ]
        for s, identity in identities.items()
    }
    manifest = {
        "reader": "newow_product_reader_intraday_v3",
        "query_since": "2026-09-19",
        "query_through": "2026-09-19",
        "query_as_of": "2026-09-19T07:00:00+00:00",
        "source_evidence_sha256": "a" * 64,
        "input_count": 2,
        "quality_policy": "physical_prefix",
    }
    closed = []
    calls = []

    class Query:
        def streams(self, **kw):
            return [{"stream_id": kw["strategy"]}]

        def summary(self, stream_id, **kw):
            return {"revision_id": "revision", "seq": 2, "snapshot": "saved"}

        def historical_actions(self, stream_id, **kw):
            calls.append(kw)
            try:
                for action in expected[
                    ProductStrategy(stream_id.removeprefix("newow_"))
                ]:
                    yield {"value": _wire(action)}
            finally:
                closed.append(stream_id)

        def presentation_facts(self, *a, **kw):
            raise AssertionError("Web collector must not be used by historical build")

    loader = SavedFusionSources.__new__(SavedFusionSources)
    loader._query = Query()
    loader._check_cancelled = None
    loader._persisted = SimpleNamespace(
        _manifest=lambda stream_id, *a: (
            identities[ProductStrategy(stream_id.removeprefix("newow_"))],
            manifest,
        )
    )
    request = SimpleNamespace(
        identity=SimpleNamespace(product="rb", frequency="1m"),
        since=date(2026, 9, 19),
        through=date(2026, 9, 19),
        as_of=datetime(2026, 9, 19, 7, tzinfo=UTC),
    )
    actions, deps = loader(request, manifest)
    actual = [action for values in actions.values() for action in values]
    assert sorted((_wire(a) for a in actual), key=lambda a: a["signal_id"]) == sorted(
        (_wire(a) for values in expected.values() for a in values),
        key=lambda a: a["signal_id"],
    )
    assert len(deps) == 2 and all(
        d["revision_id"] == "revision" and d["seq"] == 2 and d["snapshot"] == "saved"
        for d in deps
    )
    assert all(c["since"] == date.min and c["input_count"] == 2 for c in calls)
    assert set(closed) == {"newow_trend", "newow_oscillation"}
    closed.clear()
    import app.reference_trading.newow_fusion as module

    def reject(*args):
        raise ValueError("decode-corrupt")

    monkeypatch.setattr(module, "decode_source_action", reject)
    with pytest.raises(ValueError, match="decode-corrupt"):
        loader(request, manifest)
    assert closed == ["newow_trend"]
