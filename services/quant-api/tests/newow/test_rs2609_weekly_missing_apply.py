"""Isolated transaction and recovery tests for the pinned RS2609 W1 batch."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models.market_tables import MarketPartition
from scripts import rs2609_weekly_missing_apply as repair


def _bar(day: date) -> CanonicalBar:
    return CanonicalBar(
        datetime(day.year, day.month, day.day, 7, tzinfo=UTC), day,
        Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"),
        Decimal("10"), Decimal("1000"), Decimal("2"),
    )


def _packet(store, catalog, root):
    key = DatasetKey("contract", "rs", "RS2609", "1w")
    old_jan = catalog.all_partitions(key)[0]
    additions = {date.fromisoformat(value): _bar(date.fromisoformat(value)) for value in (
        "2025-09-30", "2025-12-31", "2026-01-09", "2026-01-16")}
    records = []
    for (year, month), days in repair.EXPECTED_ADDITIONS.items():
        previous = (_bar(date(2026, 1, 30)),) if (year, month) == (2026, 1) else ()
        candidate = tuple(sorted((*previous, *(additions[date.fromisoformat(day)] for day in days)),
                                 key=lambda bar: bar.bar_end))
        digest = repair.planner._candidate_sha(candidate)
        directory = store._month_directory(key, year, month)
        records.append({"year": year, "month": month,
                        "old": repair.planner._identity(old_jan, root) if previous else None,
                        "candidate_uri": (directory.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                        "candidate_sha256": digest,
                        "candidate_coverage_start": (candidate[0].bar_end - timedelta(days=7)).isoformat(),
                        "candidate_coverage_end": candidate[-1].bar_end.isoformat(),
                        "old_count": len(previous), "new_count": len(candidate),
                        "added_days": list(days),
                        "retained_days": [bar.trading_day.isoformat() for bar in previous]})
    return {"d1_preimages": [], "months": records,
            "weeks": [{"trading_day": day.isoformat(), "bar_end": bar.bar_end.isoformat(),
                       "candidate_w1": {field: str(getattr(bar, field)) for field in repair.FIELDS}}
                      for day, bar in additions.items()]}


def _setup(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    root = tmp_path / "canonical"
    store = CanonicalMonthlyStore(root)
    key = DatasetKey("contract", "rs", "RS2609", "1w")
    unrelated = DatasetKey("contract", "oi", "OI2611", "1w")
    with Session(engine) as session:
        catalog = MarketCatalog(session, root)
        for target, day in ((key, date(2026, 1, 30)),
                            (unrelated, date(2026, 1, 30))):
            bar = _bar(day)
            catalog.register_partition(store.publish(PublishRequest(
                target, 2026, 1, (bar,), (bar.bar_end,))))
        session.commit()
        packet = _packet(store, catalog, root)
        unrelated_path = catalog.all_partitions(unrelated)[0].file_path
        unrelated_bytes = unrelated_path.read_bytes()
        old_path = catalog.all_partitions(key)[0].file_path
    return engine, root, packet, old_path, unrelated, unrelated_path, unrelated_bytes


def _stub_proofs(monkeypatch, packet):
    monkeypatch.setattr(repair, "_validate_scope", lambda *_: None)
    monkeypatch.setattr(repair.planner, "prepare", lambda *_: packet)
    monkeypatch.setattr(repair, "_require_candidate_replay", lambda *_: {
        "normal_bars": 33, "quality_interruptions": 18})


def test_apply_and_exact_restore_preserve_unrelated_and_old_bytes(monkeypatch, tmp_path: Path) -> None:
    engine, root, packet, old_path, unrelated, unrelated_path, unrelated_bytes = _setup(tmp_path)
    _stub_proofs(monkeypatch, packet)
    with Session(engine, autoflush=False) as session:
        assert repair.inspect(session, root, packet)["status"] == "old"
        assert repair.apply(session, root, "root", packet)["status"] == "committed"
    with Session(engine, autoflush=False) as session:
        assert repair.inspect(session, root, packet)["status"] == "candidate"
        assert repair.restore(session, root, packet)["status"] == "restored"
    with Session(engine) as session:
        catalog = MarketCatalog(session, root)
        assert repair.inspect(session, root, packet)["status"] == "old"
        active = catalog.all_partitions(DatasetKey("contract", "rs", "RS2609", "1w"))
        assert [(part.year, part.month) for part in active] == [(2026, 1)]
        assert old_path.exists()
        assert catalog.all_partitions(unrelated)[0].file_path == unrelated_path
        assert unrelated_path.read_bytes() == unrelated_bytes
        assert session.query(MarketPartition).count() == 2
    engine.dispose()


def test_second_publish_failure_keeps_all_old_pointers(monkeypatch, tmp_path: Path) -> None:
    engine, root, packet, _, _, _, _ = _setup(tmp_path)
    _stub_proofs(monkeypatch, packet)
    publish = repair.CanonicalMonthlyStore.publish
    calls = 0

    def fail_second(self, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("isolated publish failure")
        return publish(self, request)

    monkeypatch.setattr(repair.CanonicalMonthlyStore, "publish", fail_second)
    with Session(engine, autoflush=False) as session:
        with pytest.raises(RuntimeError, match="isolated publish failure"):
            repair.apply(session, root, "root", packet)
    with Session(engine) as readback:
        assert repair.inspect(readback, root, packet)["status"] == "old"
    engine.dispose()


def test_stale_packet_rejected_before_publish(monkeypatch, tmp_path: Path) -> None:
    engine, root, packet, _, _, _, _ = _setup(tmp_path)
    _stub_proofs(monkeypatch, packet)
    monkeypatch.setattr(repair.planner, "prepare", lambda *_: {"moved": True})
    with Session(engine, autoflush=False) as session:
        with pytest.raises(repair.RSApplyError, match="PREPARE_IDENTITY_MOVED"):
            repair.apply(session, root, "root", packet)
    with Session(engine) as readback:
        assert repair.inspect(readback, root, packet)["status"] == "old"
    engine.dispose()


def test_unknown_commit_stops_and_preserves_readback_path(monkeypatch, tmp_path: Path) -> None:
    engine, root, packet, _, _, _, _ = _setup(tmp_path)
    _stub_proofs(monkeypatch, packet)
    with Session(engine, autoflush=False) as session:
        def fail_commit():
            raise RuntimeError("uncertain outcome")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(repair.RSApplyError, match="COMMIT_OUTCOME_UNKNOWN"):
            repair.apply(session, root, "root", packet)
    with Session(engine) as readback:
        assert repair.inspect(readback, root, packet)["status"] == "old"
    engine.dispose()
