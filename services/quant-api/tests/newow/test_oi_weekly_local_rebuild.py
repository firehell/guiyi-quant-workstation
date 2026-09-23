"""The OI repair only appends exact missing W1 endpoints to monthly candidates."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar
from app.market_data.domain import DatasetKey
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models.market_tables import MarketPartition
from scripts import oi_weekly_local_rebuild as repair
from scripts.oi_weekly_local_rebuild import MISSING_DAYS, OIRebuildError, _merge_month


def _bar(day: date, *, end: datetime | None = None) -> CanonicalBar:
    return CanonicalBar(
        bar_end=end or datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        trading_day=day,
        open=Decimal("1"), high=Decimal("2"), low=Decimal("1"), close=Decimal("2"),
        volume=Decimal("3"), turnover=Decimal("4"), open_interest=Decimal("5"),
    )


def test_exact_pinned_scope_excludes_quality_interruption() -> None:
    assert len(MISSING_DAYS) == 37
    assert MISSING_DAYS[0] == date(2025, 11, 28)
    assert MISSING_DAYS[-1] == date(2026, 8, 14)
    assert date(2025, 11, 21) not in MISSING_DAYS


def test_merge_month_handles_absent_and_partially_populated_partitions() -> None:
    aug_7, aug_14, aug_21 = (_bar(date(2026, 8, day)) for day in (7, 14, 21))
    assert _merge_month((), (aug_7, aug_14)) == (aug_7, aug_14)
    assert _merge_month((aug_21,), (aug_14, aug_7)) == (aug_7, aug_14, aug_21)
    assert _merge_month((aug_21,), (aug_14, aug_7))[2] is aug_21


@pytest.mark.parametrize("previous,additions", [
    ((date(2026, 8, 7),), (date(2026, 8, 7),)),
    ((), (date(2026, 8, 7), date(2026, 8, 7))),
])
def test_merge_month_rejects_existing_or_duplicate_week(previous, additions) -> None:
    with pytest.raises(OIRebuildError, match="W1_DUPLICATE_ENDPOINT"):
        _merge_month(tuple(map(_bar, previous)), tuple(map(_bar, additions)))


def test_merge_month_rejects_distinct_end_for_same_trading_day() -> None:
    day = date(2026, 8, 7)
    with pytest.raises(OIRebuildError, match="W1_TARGET_ALREADY_PRESENT"):
        _merge_month((_bar(day),), (_bar(day, end=datetime(2026, 8, 7, 8, tzinfo=UTC)),))


def test_complete_daily_week_rejects_gap_and_quality_fact() -> None:
    first = _bar(date(2026, 8, 6))
    last = _bar(date(2026, 8, 7))
    points = ((first.bar_end, first.trading_day), (last.bar_end, last.trading_day))
    assert repair._complete_daily_week(points, {first.trading_day: first, last.trading_day: last}, {},
                                       last.trading_day) == (first, last)
    with pytest.raises(OIRebuildError, match="D1_COMPLETE_WEEK_INVALID"):
        repair._complete_daily_week(points, {first.trading_day: first}, {}, last.trading_day)
    quality = SimpleNamespace(bar_end=last.bar_end, trading_day=last.trading_day)
    with pytest.raises(OIRebuildError, match="D1_QUALITY_INTERRUPTION"):
        repair._complete_daily_week(points, {first.trading_day: first}, {last.trading_day: quality},
                                    last.trading_day)


class _Session:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("unknown outcome")

    def rollback(self) -> None:
        self.rollbacks += 1


def _fake_catalog(monkeypatch, *, d1=(), w1=(), lock=True):
    state = SimpleNamespace(released=0, registered=[])

    class _Lease:
        def release(self):
            state.released += 1

    class _Catalog:
        def __init__(self, session, root):
            pass

        def all_partitions(self, key):
            return d1 if key.frequency.value == "1d" else w1

        def acquire_maintenance_lock(self):
            return _Lease() if lock else None

        def register_partition(self, partition):
            state.registered.append(partition)

    monkeypatch.setattr(repair, "MarketCatalog", _Catalog)
    return state


def test_inspect_rejects_moved_active_d1_pointer(monkeypatch, tmp_path: Path) -> None:
    original = tmp_path / "original.parquet"
    moved = tmp_path / "moved.parquet"
    original.write_bytes(b"original")
    moved.write_bytes(b"moved")
    common = dict(year=2026, month=8, row_count=1, coverage_start=None, coverage_end=None,
                  source_coverage_start=None, source_coverage_end=None, source_quality_sha256=None)
    old_part = SimpleNamespace(file_path=original, **common)
    moved_part = SimpleNamespace(file_path=moved, **common)
    source = {"year": 2026, "month": 8, **repair._partition_identity(old_part, tmp_path)}
    _fake_catalog(monkeypatch, d1=(moved_part,))
    packet = {"schema_version": "oi_weekly_local_rebuild_v1", "contract": "OI2611",
              "d1_preimages": [source], "months": []}
    with pytest.raises(OIRebuildError, match="D1_PREIMAGE_MOVED"):
        repair.inspect(_Session(), tmp_path, packet)


def test_inspect_distinguishes_old_candidate_and_concurrent_fill(monkeypatch, tmp_path: Path) -> None:
    bar = _bar(date(2026, 8, 7))
    candidate_path = tmp_path / "candidate.parquet"
    candidate_path.write_bytes(b"candidate")
    other_path = tmp_path / "other.parquet"
    other_path.write_bytes(b"other")
    values = dict(year=2026, month=8, row_count=1,
                  coverage_start=bar.bar_end - repair.timedelta(days=7),
                  coverage_end=bar.bar_end,
                  source_coverage_start=bar.bar_end - repair.timedelta(days=7),
                  source_coverage_end=bar.bar_end, source_quality_sha256=None)
    candidate_part = SimpleNamespace(file_path=candidate_path, **values)
    other_part = SimpleNamespace(file_path=other_path, **values)
    packet = {"schema_version": "oi_weekly_local_rebuild_v1", "contract": "OI2611",
              "d1_preimages": [], "quality_facts": [], "months": [{
                  "year": 2026, "month": 8,
                  "old": None, "candidate_uri": candidate_path.name,
                  "candidate_sha256": repair._sha(candidate_path.read_bytes()),
                  "catalog_candidate": {key: value for key, value in repair._partition_identity(candidate_part, tmp_path).items()
                                        if key not in ("uri", "sha256")},
                  "new_count": 1, "added_days": [bar.trading_day.isoformat()],
              }]}

    class _Store:
        def __init__(self, root):
            pass

        def read_catalog_partition(self, partition):
            return (bar,)

    monkeypatch.setattr(repair, "CanonicalMonthlyStore", _Store)
    _fake_catalog(monkeypatch, w1=())
    assert repair.inspect(_Session(), tmp_path, packet)["status"] == "old"
    _fake_catalog(monkeypatch, w1=(candidate_part,))
    assert repair.inspect(_Session(), tmp_path, packet)["status"] == "candidate"
    _fake_catalog(monkeypatch, w1=(other_part,))
    assert repair.inspect(_Session(), tmp_path, packet)["status"] == "mixed_or_unknown"


def test_inspect_validates_source_quality_payload(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "daily.parquet"
    source_path.write_bytes(b"daily")
    part = SimpleNamespace(file_path=source_path, year=2025, month=11, row_count=1,
                           coverage_start=None, coverage_end=None,
                           source_coverage_start=None, source_coverage_end=None,
                           source_quality_sha256=None)
    _fake_catalog(monkeypatch, d1=(part,))

    class _Store:
        def __init__(self, root):
            pass

        def read_catalog_partition_quality(self, partition):
            return (), (SimpleNamespace(trading_day=date(2025, 11, 17),
                                        classification="NONPOSITIVE_CLOSE"),)

    monkeypatch.setattr(repair, "CanonicalMonthlyStore", _Store)
    packet = {"schema_version": "oi_weekly_local_rebuild_v1", "contract": "OI2611",
              "d1_preimages": [{"year": 2025, "month": 11,
                                 **repair._partition_identity(part, tmp_path)}],
              "quality_facts": [], "months": []}
    with pytest.raises(OIRebuildError, match="QUALITY_INTERRUPTION_MOVED"):
        repair.inspect(_Session(), tmp_path, packet)


def test_apply_rejects_stale_plan_under_lock(monkeypatch, tmp_path: Path) -> None:
    state = _fake_catalog(monkeypatch)
    monkeypatch.setattr(repair, "prepare", lambda *_: ({"identity": "new"}, ()))
    session = _Session()
    with pytest.raises(OIRebuildError, match="PREPARE_IDENTITY_MOVED"):
        repair.apply(session, tmp_path, "root", {"identity": "old"})
    assert session.rollbacks == 1 and session.commits == 0
    assert state.released == 1 and not state.registered


def test_apply_rejects_busy_maintenance_lock(monkeypatch, tmp_path: Path) -> None:
    _fake_catalog(monkeypatch, lock=False)
    with pytest.raises(OIRebuildError, match="MAINTENANCE_BUSY"):
        repair.apply(_Session(), tmp_path, "root", {})


def test_apply_reports_unknown_commit_and_releases_lock(monkeypatch, tmp_path: Path) -> None:
    state = _fake_catalog(monkeypatch)
    bar = _bar(date(2026, 8, 7))
    candidate = (bar,)
    target = tmp_path / "part.candidate.parquet"
    catalog_values = {
        "row_count": 1,
        "coverage_start": (bar.bar_end - repair.timedelta(days=7)).isoformat(),
        "coverage_end": bar.bar_end.isoformat(),
        "source_coverage_start": (bar.bar_end - repair.timedelta(days=7)).isoformat(),
        "source_coverage_end": bar.bar_end.isoformat(),
        "quality_sha256": None,
    }
    packet = {"months": [{"year": 2026, "month": 8, "candidate_uri": target.name,
                          "catalog_candidate": catalog_values}]}
    monkeypatch.setattr(repair, "prepare", lambda *_: (packet, (candidate,)))

    class _Store:
        def __init__(self, root):
            pass

        def publish(self, request):
            return SimpleNamespace(parquet_path=target, row_count=1,
                                   coverage_start=bar.bar_end - repair.timedelta(days=7),
                                   coverage_end=bar.bar_end,
                                   source_coverage_start=bar.bar_end - repair.timedelta(days=7),
                                   source_coverage_end=bar.bar_end,
                                   source_quality_sha256=None)

    monkeypatch.setattr(repair, "CanonicalMonthlyStore", _Store)
    session = _Session(fail_commit=True)
    with pytest.raises(OIRebuildError, match="COMMIT_OUTCOME_UNKNOWN"):
        repair.apply(session, tmp_path, "root", packet)
    assert session.commits == 1 and session.rollbacks == 1
    assert state.released == 1 and len(state.registered) == 1


def test_apply_persists_only_oi_candidate_in_isolated_catalog(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    root = tmp_path / "canonical"
    store = CanonicalMonthlyStore(root)
    oi_key = DatasetKey("contract", "oi", "OI2611", "1w")
    other_key = DatasetKey("contract", "pf", "PF2611", "1w")
    bar = _bar(date(2026, 8, 7))
    other_bar = _bar(date(2026, 8, 14))
    with Session(engine) as session:
        catalog = MarketCatalog(session, root)
        other = store.publish(PublishRequest(other_key, 2026, 8, (other_bar,),
                                             (other_bar.bar_end,)))
        catalog.register_partition(other)
        session.commit()
        other_uri = catalog.all_partitions(other_key)[0].file_path
        other_bytes = other_uri.read_bytes()
        candidate_sha = repair._candidate_sha((bar,))
        candidate_uri = (store._month_directory(oi_key, 2026, 8).relative_to(root)
                         / f"part.{candidate_sha}.parquet").as_posix()
        start = (bar.bar_end - repair.timedelta(days=7)).isoformat()
        end = bar.bar_end.isoformat()
        packet = {"schema_version": "oi_weekly_local_rebuild_v1", "contract": "OI2611",
                  "d1_preimages": [], "quality_facts": [], "months": [{
                      "year": 2026, "month": 8, "old": None,
                      "candidate_uri": candidate_uri, "candidate_sha256": candidate_sha,
                      "catalog_candidate": {"row_count": 1, "coverage_start": start,
                                            "coverage_end": end, "source_coverage_start": start,
                                            "source_coverage_end": end, "quality_sha256": None},
                      "new_count": 1, "added_days": [bar.trading_day.isoformat()],
                  }]}
        monkeypatch.setattr(repair, "prepare", lambda *_: (packet, ((bar,),)))
        assert repair.inspect(session, root, packet)["status"] == "old"
        assert repair.apply(session, root, "root", packet)["status"] == "committed"
    with Session(engine) as readback:
        assert repair.inspect(readback, root, packet)["status"] == "candidate"
        assert readback.query(MarketPartition).count() == 2
        assert MarketCatalog(readback, root).all_partitions(other_key)[0].file_path == other_uri
        assert other_uri.read_bytes() == other_bytes
    engine.dispose()
