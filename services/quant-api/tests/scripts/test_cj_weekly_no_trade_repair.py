"""Failure boundaries for the exact CJ W1 repair publisher."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import cj_weekly_no_trade_repair as repair


class _Session:
    def __init__(self, *, commit_error: bool = False) -> None:
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error:
            raise RuntimeError("uncertain")

    def rollback(self) -> None:
        self.rollbacks += 1


class _Lease:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


def _install_fakes(monkeypatch, root: Path, *, fail_publish_at: int | None = None,
                   interrupted_contract: str | None = None):
    lease = _Lease()
    calls: list[str] = []
    packet = {"targets": [
        {"contract": contract, "week_end": day, "candidate_w1_partition_uri": uri}
        for contract, day, uri in (
            ("CJ2305", "2022-05-20", "may.parquet"),
            ("CJ2309", "2022-09-30", "september.parquet"),
        )
    ]}
    may_candidate = (
        SimpleNamespace(trading_day=date(2022, 5, 20),
                        bar_end=datetime(2022, 5, 20, 7, tzinfo=UTC)),
    )
    september_candidate = (
        SimpleNamespace(trading_day=date(2022, 9, 30),
                        bar_end=datetime(2022, 9, 30, 7, tzinfo=UTC)),
    )

    class Catalog:
        def __init__(self, *_args):
            pass

        def acquire_maintenance_lock(self):
            calls.append("lock")
            return lease

        def register_partition(self, _partition):
            calls.append("register")

    class Store:
        def __init__(self, *_args):
            pass

        def publish(self, request):
            calls.append("publish")
            if fail_publish_at == calls.count("publish"):
                raise RuntimeError("candidate publish failed")
            filename = "may.parquet" if request.dataset.series_or_contract == "CJ2305" else "september.parquet"
            return SimpleNamespace(parquet_path=root / filename)

    class Market:
        def __init__(self, *_args):
            pass

        def query_contract_weekly_replay_quality(self, **kwargs):
            calls.append("readback")
            contract = kwargs["contract"]
            target = may_candidate[0] if contract == "CJ2305" else september_candidate[0]
            if contract == interrupted_contract:
                return (), (SimpleNamespace(trading_day=target.trading_day),)
            return (target,), ()

    monkeypatch.setattr(repair, "MarketCatalog", Catalog)
    monkeypatch.setattr(repair, "CanonicalMonthlyStore", Store)
    monkeypatch.setattr(repair, "MarketDataService", Market)
    monkeypatch.setattr(repair, "prepare", lambda *_args: (packet, (may_candidate, september_candidate)))
    return packet, calls, lease


def test_apply_rejects_moved_prepare_before_publication(monkeypatch, tmp_path) -> None:
    packet, calls, lease = _install_fakes(monkeypatch, tmp_path)
    session = _Session()
    with pytest.raises(repair.CJRepairError, match="PREPARE_IDENTITY_MOVED"):
        repair.apply(session, tmp_path, "a" * 64, {**packet, "catalog_revision": "moved"})
    assert calls == ["lock"]
    assert session.commits == 0 and session.rollbacks == 1 and lease.released


def test_apply_rolls_back_if_second_candidate_fails(monkeypatch, tmp_path) -> None:
    packet, calls, lease = _install_fakes(monkeypatch, tmp_path, fail_publish_at=2)
    session = _Session()
    with pytest.raises(RuntimeError, match="candidate publish failed"):
        repair.apply(session, tmp_path, "a" * 64, packet)
    assert calls == ["lock", "publish", "register", "readback", "publish"]
    assert session.commits == 0 and session.rollbacks == 1 and lease.released


def test_apply_reports_unknown_commit_without_retry(monkeypatch, tmp_path) -> None:
    packet, calls, lease = _install_fakes(monkeypatch, tmp_path)
    session = _Session(commit_error=True)
    with pytest.raises(repair.CJRepairError, match="COMMIT_OUTCOME_UNKNOWN"):
        repair.apply(session, tmp_path, "a" * 64, packet)
    assert calls.count("publish") == 2
    assert session.commits == 1 and session.rollbacks == 1 and lease.released


def test_apply_rejects_interrupted_target_before_commit(monkeypatch, tmp_path) -> None:
    packet, calls, lease = _install_fakes(
        monkeypatch, tmp_path, interrupted_contract="CJ2309",
    )
    session = _Session()
    with pytest.raises(repair.CJRepairError, match="CANDIDATE_READBACK_INVALID"):
        repair.apply(session, tmp_path, "a" * 64, packet)
    assert calls.count("publish") == 2 and calls.count("readback") == 2
    assert session.commits == 0 and session.rollbacks == 1 and lease.released


def test_inspect_recognizes_both_committed_candidates(monkeypatch, tmp_path) -> None:
    records = []
    bars = {}
    for contract, day, name in (
        ("CJ2305", date(2022, 5, 20), "may.parquet"),
        ("CJ2309", date(2022, 9, 30), "september.parquet"),
    ):
        path = tmp_path / name
        path.write_bytes(name.encode())
        records.append({
            "contract": contract, "week_end": day.isoformat(),
            "d1_preimages": [],
            "candidate_w1_partition_uri": name,
            "candidate_w1_partition_sha256": repair._sha(path.read_bytes()),
            "old_w1_partition_uri": f"old-{name}",
            "old_w1_partition_sha256": "0" * 64,
        })
        bars[contract] = SimpleNamespace(
            trading_day=day, bar_end=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        )

    class Catalog:
        def __init__(self, *_args):
            pass

        def all_partitions(self, key):
            bar = bars[key.series_or_contract]
            filename = "may.parquet" if key.series_or_contract == "CJ2305" else "september.parquet"
            return (SimpleNamespace(year=bar.trading_day.year, month=bar.trading_day.month,
                                    file_path=tmp_path / filename),)

    class Store:
        def __init__(self, *_args):
            pass

        def read_catalog_partition(self, partition):
            contract = "CJ2305" if partition.month == 5 else "CJ2309"
            return (bars[contract],)

    class Market:
        def __init__(self, *_args):
            pass

        def query_contract_weekly_replay_quality(self, **kwargs):
            return (bars[kwargs["contract"]],), ()

    monkeypatch.setattr(repair, "MarketCatalog", Catalog)
    monkeypatch.setattr(repair, "CanonicalMonthlyStore", Store)
    monkeypatch.setattr(repair, "MarketDataService", Market)
    assert repair.inspect(_Session(), tmp_path, {"targets": records}) == {
        "status": "candidate", "targets": ["candidate", "candidate"],
    }
