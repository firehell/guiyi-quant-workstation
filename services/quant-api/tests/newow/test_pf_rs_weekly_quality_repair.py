"""PF/RS quality repair changes only pinned W1 Catalog pointers."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models.market_tables import MarketPartition
from scripts import pf_rs_weekly_quality_repair as repair


def _bar(day: date) -> CanonicalBar:
    return CanonicalBar(datetime(day.year, day.month, day.day, 7, tzinfo=UTC), day,
                        Decimal("1"), Decimal("2"), Decimal("1"), Decimal("2"),
                        Decimal("3"), Decimal("4"), Decimal("5"))


def _record(store, catalog, root, key, month, previous, candidate):
    old = catalog.all_partitions(key)[0]
    record = {"contract": key.series_or_contract, "year": month.year, "month": month.month,
              "old": repair._identity(old, root),
              "removed_days": [bar.trading_day.isoformat() for bar in previous if bar not in candidate],
              "retained_days": [bar.trading_day.isoformat() for bar in candidate],
              "old_count": len(previous), "new_count": len(candidate),
              "action": "replace" if candidate else "remove_pointer"}
    if candidate:
        digest = repair._candidate_sha(candidate)
        directory = store._month_directory(key, month.year, month.month)
        record.update(candidate_uri=(directory.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                      candidate_sha256=digest,
                      catalog_candidate=repair._candidate_catalog(candidate))
    return record


def test_exact_scope_has_fifteen_distinct_weeks_and_seven_months() -> None:
    assert sum(map(len, repair.TARGETS.values())) == 15
    assert {contract: len(days) for contract, days in repair.TARGETS.items()} == {
        "PF2611": 11, "RS2609": 4}
    assert len({(contract, day[:7]) for contract, days in repair.TARGETS.items()
                for day in days}) == 7


def test_restore_scope_rejects_foreign_month_even_with_self_consistent_hash() -> None:
    packet = {"schema_version": "pf_rs_weekly_quality_repair_v1",
              "cutoff": repair.CUTOFF.isoformat(),
              "repair_source_sha256": repair._sha(Path(repair.__file__).read_bytes()),
              "contracts": [{"contract": contract, "weeks": [{"week_end": day} for day in days]}
                            for contract, days in repair.TARGETS.items()],
              "months": []}
    for (contract, year, month), action in repair._MONTH_ACTIONS.items():
        days = [day for day in repair.TARGETS[contract]
                if (date.fromisoformat(day).year, date.fromisoformat(day).month) == (year, month)]
        base = (f"kind=contract/symbol={contract[:2].lower()}/series={contract}/"
                f"frequency=1w/year={year}/month={month:02d}/")
        record = {"contract": contract, "year": year, "month": month,
                  "action": action, "removed_days": days,
                  "old": {"uri": base + "part.parquet"}, "old_count": len(days),
                  "new_count": 0, "retained_days": []}
        if action == "replace":
            record.update(old_count=len(days) + 1, new_count=1,
                          retained_days=["retained"], candidate_sha256="a" * 64,
                          candidate_uri=base + f"part.{'a' * 64}.parquet")
        packet["months"].append(record)
    repair._validate_scope(packet)
    foreign = copy.deepcopy(packet)
    foreign["months"][0]["contract"] = "OI2611"
    with pytest.raises(repair.QualityRepairError, match="PREPARED_SCOPE_INVALID"):
        repair._validate_scope(foreign)
    omitted = copy.deepcopy(packet)
    omitted["months"].pop()
    with pytest.raises(repair.QualityRepairError, match="PREPARED_SCOPE_INVALID"):
        repair._validate_scope(omitted)


@pytest.mark.parametrize("dynamic", [False, True])
def test_apply_removes_empty_month_and_replaces_partial_month_atomically(
    monkeypatch, tmp_path: Path, dynamic: bool,
) -> None:
    monkeypatch.setattr(repair, "_validate_scope", lambda _: None)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    root = tmp_path / "canonical"
    store = CanonicalMonthlyStore(root)
    pf = DatasetKey("contract", "pf", "PF2611", "1w")
    rs = DatasetKey("contract", "rs", "RS2609", "1w")
    unrelated = DatasetKey("contract", "oi", "OI2611", "1w")
    pf_old = (_bar(date(2025, 11, 21)), _bar(date(2025, 11, 28)))
    rs_old = (_bar(date(2026, 8, 7)), _bar(date(2026, 8, 14)))
    oi_old = (_bar(date(2026, 8, 7)),)
    with Session(engine) as session:
        catalog = MarketCatalog(session, root)
        for key, year, month, bars in ((pf, 2025, 11, pf_old),
                                       (rs, 2026, 8, rs_old),
                                       (unrelated, 2026, 8, oi_old)):
            catalog.register_partition(store.publish(PublishRequest(
                key, year, month, bars, tuple(bar.bar_end for bar in bars))))
        session.commit()
        old_pf_uri = catalog.all_partitions(pf)[0].file_path
        oi_uri = catalog.all_partitions(unrelated)[0].file_path
        oi_bytes = oi_uri.read_bytes()
        months = [_record(store, catalog, root, pf, date(2025, 11, 28), pf_old, ()),
                  _record(store, catalog, root, rs, date(2026, 8, 14), rs_old,
                          (rs_old[0],))]
        packet = {"schema_version": "pf_rs_weekly_quality_repair_v1",
                  "cutoff": repair.CUTOFF.isoformat(),
                  "canonical_root_sha256": "root",
                  "contracts": [{"contract": contract, "d1_preimages": [], "weeks": []} for contract in repair.TARGETS],
                  "months": months}
        calls = []
        if dynamic:
            packet.update(schema_version="newow_weekly_quality_repair_v2",
                          target_scope={"PF2611": ["2025-11-21", "2025-11-28"], "RS2609": ["2026-08-14"]})
        def reprepare(*_, **kwargs):
            calls.append(kwargs)
            return packet, ((), (rs_old[0],))
        monkeypatch.setattr(repair, "prepare", reprepare)
        assert repair.inspect(session, root, packet)["status"] == "old"
        assert repair.apply(session, root, "root", packet)["status"] == "committed"
        assert calls == ([{"targets": packet["target_scope"], "cutoff": repair.CUTOFF}] if dynamic else [{}])
    with Session(engine) as readback:
        catalog = MarketCatalog(readback, root)
        assert repair.inspect(readback, root, packet)["status"] == "candidate"
        assert catalog.all_partitions(pf) == ()
        assert old_pf_uri.exists()  # Historical file remains available.
        assert [bar.trading_day for bar in store.read_catalog_partition(
            catalog.all_partitions(rs)[0])] == [date(2026, 8, 7)]
        assert catalog.all_partitions(unrelated)[0].file_path == oi_uri
        assert oi_uri.read_bytes() == oi_bytes
        assert readback.query(MarketPartition).count() == 2
        assert repair.restore(readback, root, packet)["status"] == "restored"
    with Session(engine) as restored:
        catalog = MarketCatalog(restored, root)
        assert repair.inspect(restored, root, packet)["status"] == "old"
        assert [bar.trading_day for bar in store.read_catalog_partition(
            catalog.all_partitions(pf)[0])] == [bar.trading_day for bar in pf_old]
        assert [bar.trading_day for bar in store.read_catalog_partition(
            catalog.all_partitions(rs)[0])] == [bar.trading_day for bar in rs_old]
        assert catalog.all_partitions(unrelated)[0].file_path == oi_uri
    engine.dispose()


def test_apply_rejects_stale_packet_before_write(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(repair, "_validate_scope", lambda _: None)
    class Catalog:
        def __init__(self, *_):
            pass

        def acquire_maintenance_lock(self):
            class Lease:
                def release(self):
                    pass
            return Lease()

    class FakeSession:
        commits = 0
        rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    monkeypatch.setattr(repair, "MarketCatalog", Catalog)
    monkeypatch.setattr(repair, "prepare", lambda *_: ({"new": True}, ()))
    session = FakeSession()
    with pytest.raises(repair.QualityRepairError, match="PREPARE_IDENTITY_MOVED"):
        repair.apply(session, tmp_path, "root", {"old": True, "canonical_root_sha256": "root"})
    assert (session.commits, session.rollbacks) == (0, 1)


def test_inspect_rejects_wrong_scope(tmp_path: Path) -> None:
    with pytest.raises(repair.QualityRepairError, match="PREPARED_SCOPE_INVALID"):
        repair.inspect(None, tmp_path, {"schema_version": "pf_rs_weekly_quality_repair_v1",
                                        "cutoff": repair.CUTOFF.isoformat(),
                                        "contracts": [{"contract": "PF2611", "d1_preimages": []}],
                                        "months": []})


def test_failed_second_publish_rolls_back_both_month_pointers(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(repair, "_validate_scope", lambda _: None)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    root = tmp_path / "canonical"
    store = CanonicalMonthlyStore(root)
    pf = DatasetKey("contract", "pf", "PF2611", "1w")
    rs = DatasetKey("contract", "rs", "RS2609", "1w")
    pf_old = (_bar(date(2025, 11, 21)),)
    rs_old = (_bar(date(2026, 8, 7)), _bar(date(2026, 8, 14)))
    with Session(engine) as session:
        catalog = MarketCatalog(session, root)
        for key, year, month, bars in ((pf, 2025, 11, pf_old), (rs, 2026, 8, rs_old)):
            catalog.register_partition(store.publish(PublishRequest(
                key, year, month, bars, tuple(bar.bar_end for bar in bars))))
        session.commit()
        packet = {"canonical_root_sha256": "root", "months": [
            _record(store, catalog, root, pf, date(2025, 11, 21), pf_old, ()),
            _record(store, catalog, root, rs, date(2026, 8, 14), rs_old, (rs_old[0],))]}
        monkeypatch.setattr(repair, "prepare", lambda *_: (packet, ((), (rs_old[0],))))

        def fail_publish(self, request):
            raise RuntimeError("isolated publish failure")

        monkeypatch.setattr(repair.CanonicalMonthlyStore, "publish", fail_publish)
        with pytest.raises(RuntimeError, match="isolated publish failure"):
            repair.apply(session, root, "root", packet)
    with Session(engine) as readback:
        catalog = MarketCatalog(readback, root)
        assert catalog.all_partitions(pf)[0].row_count == 1
        assert catalog.all_partitions(rs)[0].row_count == 2
    engine.dispose()


@pytest.mark.parametrize("scope", [
    {"CJ2305": ["2022-05-20", "2022-05-20"]},
    {"CJ2305": ["2022-05-27", "2022-05-20"]},
    {"CJ2305": ["2027-05-20"]},
    {"../CJ2305": ["2022-05-20"]},
    {"OI2305": ["2022-05-20"]},
])
def test_dynamic_targets_reject_duplicates_future_and_foreign_scope(scope):
    with pytest.raises(repair.QualityRepairError, match="PREPARED_SCOPE_INVALID"):
        repair._validated_targets(scope, repair.CUTOFF)


def test_dynamic_targets_accept_exact_historical_quality_contracts():
    assert repair._validated_targets({"CJ2305": ["2022-05-20"]}, repair.CUTOFF) == {
        "CJ2305": ("2022-05-20",)}


def test_dynamic_targets_keep_contract_order_after_json_roundtrip():
    import json
    unsorted = {"RS2609": ["2026-08-14"], "CJ2305": ["2022-05-20"]}
    before = repair._validated_targets(unsorted, repair.CUTOFF)
    after = repair._validated_targets(json.loads(json.dumps(unsorted, sort_keys=True)), repair.CUTOFF)
    assert list(before.items()) == list(after.items())


def test_dynamic_scope_requires_exact_months_and_removed_days():
    base = "kind=contract/symbol=cj/series=CJ2305/frequency=1w/year=2022/month=05/"
    packet = {"schema_version": "newow_weekly_quality_repair_v2", "cutoff": repair.CUTOFF.isoformat(),
              "repair_source_sha256": repair._sha(Path(repair.__file__).read_bytes()),
              "target_scope": {"CJ2305": ["2022-05-20"]},
              "contracts": [{"contract": "CJ2305", "weeks": [{"week_end": "2022-05-20"}]}],
              "months": [{"contract": "CJ2305", "year": 2022, "month": 5, "action": "remove_pointer",
                          "removed_days": ["2022-05-20"], "retained_days": [], "old_count": 1, "new_count": 0,
                          "old": {"uri": base + "part.parquet"}}]}
    repair._validate_scope(packet)
    packet["months"][0]["removed_days"] = ["2022-05-27"]
    with pytest.raises(repair.QualityRepairError, match="PREPARED_SCOPE_INVALID"):
        repair._validate_scope(packet)
