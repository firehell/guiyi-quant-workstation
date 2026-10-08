from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import hashlib

from app.market_data.day_preparation import DayMetadataPreparation

SNAPSHOT_HASH = hashlib.sha256(b"test source snapshot").hexdigest()
PLAN_HASH = hashlib.sha256(b"test exact diff plan").hexdigest()

DAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 8, 12, 30, tzinfo=UTC)


def service(path: Path, *, ready=False, capture=None, apply=None, lease=True):
    calls = []
    class Lease:
        def release(self):
            calls.append("release")
    def captured(day):
        calls.append("capture")
        if capture:
            return capture(day)
        return {"snapshot_sha256": SNAPSHOT_HASH}
    def applied(day, snapshot, plan):
        calls.append("apply")
        if apply:
            return apply(day, snapshot)
        return {"plan_sha256": PLAN_HASH, "status": "applied"}
    item = DayMetadataPreparation(
        state_path=path, select_day=lambda now: DAY,
        is_ready=lambda day: ready, capture=captured, apply=applied,
        acquire_lease=lambda: Lease() if lease else None,
        plan=lambda day, snapshot: {"plan_sha256": PLAN_HASH}, binding_id="test-catalog",
    )
    return item, calls


def test_complete_catalog_never_opens_provider(tmp_path):
    item, calls = service(tmp_path / "state.json", ready=True)
    assert item.tick(NOW) is None
    assert calls == []


def test_once_per_day_across_restart_and_hash_bound_receipt(tmp_path):
    path = tmp_path / "state.json"
    item, calls = service(path)
    assert item.tick(NOW) is None
    assert calls == ["capture", "apply", "release"]
    receipt = item.read_selected_day(DAY)
    assert receipt["snapshot"]["snapshot_sha256"] == SNAPSHOT_HASH
    assert receipt["receipt"]["plan_sha256"] == PLAN_HASH
    restarted, calls = service(path, ready=True)
    assert restarted.tick(NOW) is None
    assert calls == []


@pytest.mark.parametrize("failure", ["COMMIT_OUTCOME_UNKNOWN", "MAIN_CONTRACT_CONFLICT"])
def test_failed_or_unknown_attempt_is_never_retried_even_when_catalog_now_ready(tmp_path, failure):
    def fail(*args):
        raise ValueError(failure)
    path = tmp_path / "state.json"
    item, calls = service(path, apply=fail)
    assert item.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    restarted, retry_calls = service(path, ready=True)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert retry_calls == []
    assert restarted.read_state()[DAY.isoformat()]["reason"] == failure
    assert calls == ["capture", "apply", "release"]


def test_busy_lease_does_not_consume_attempt(tmp_path):
    item, calls = service(tmp_path / "state.json", lease=False)
    assert item.tick(NOW) == "METADATA_PREPARATION_SOURCE_BUSY"
    assert calls == []
    assert item.read_state() == {}


def test_process_interruption_before_provider_is_durable_and_blocks_restart(tmp_path):
    def crash(day):
        raise KeyboardInterrupt
    path = tmp_path / "state.json"
    item, calls = service(path, capture=crash)
    with pytest.raises(KeyboardInterrupt):
        item.tick(NOW)
    restarted, calls = service(path)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert calls == []


def test_naive_clock_and_unknown_day_do_not_capture(tmp_path):
    item, calls = service(tmp_path / "state.json")
    assert item.tick(datetime(2026, 10, 8)) == "METADATA_PREPARATION_CLOCK_INVALID"
    item.select_day = lambda now: None
    assert item.tick(NOW) is None
    assert calls == []


def test_selection_reuses_phase_resolver_and_night_session_trading_day():
    from app.market_data.day_preparation import select_preparation_day
    from app.market_data.market_phase import MarketPhase, ProductMarketPhase
    class Resolver:
        def resolve(self, product, now):
            phase = MarketPhase.TRADING if now.minute == 0 else MarketPhase.CLOSED
            return ProductMarketPhase(product, phase, DAY if phase is MarketPhase.TRADING else None,
                                      None, None)
    assert select_preparation_day(Resolver(), ("rb", "cu"), NOW) == DAY


def test_unknown_phase_never_guesses_day():
    from app.market_data.day_preparation import select_preparation_day
    from app.market_data.market_phase import MarketPhase, ProductMarketPhase
    class Resolver:
        def resolve(self, product, now):
            return ProductMarketPhase(product, MarketPhase.UNKNOWN, None, None, None)
    with pytest.raises(ValueError, match="AUTHORITY_UNAVAILABLE"):
        select_preparation_day(Resolver(), ("rb",), NOW)


def test_plan_only_freezes_exact_source_once_and_apply_requires_both_hashes(tmp_path):
    path = tmp_path / "state.json"
    item, calls = service(path)
    assert item.tick(NOW, phase="plan") is None
    assert calls == ["capture", "release"]
    assert item.tick(NOW, phase="plan") is None
    assert calls == ["capture", "release", "release"]
    assert item.tick(NOW, phase="apply", expected_snapshot_sha256="c" * 64,
                     expected_plan_sha256=PLAN_HASH) == "METADATA_PREPARATION_PLAN_DRIFT"
    assert "apply" not in calls
    assert item.tick(NOW, phase="apply", expected_snapshot_sha256=SNAPSHOT_HASH,
                     expected_plan_sha256=PLAN_HASH) is None
    assert calls.count("capture") == 1
    assert calls.count("apply") == 1


def test_durable_state_cannot_cross_catalog_binding(tmp_path):
    item, _ = service(tmp_path / "state.json")
    assert item.tick(NOW, phase="plan") is None
    other, calls = service(tmp_path / "state.json", ready=True)
    other.binding_id = "different-catalog"
    assert other.tick(NOW) == "METADATA_PREPARATION_AUTHORITY_UNAVAILABLE"
    assert calls == []


def test_catalog_fingerprint_detects_owner_session_and_calendar_changes():
    from app.market_data.day_preparation import catalog_day_fingerprint
    from tests.data_foundation.test_current_day_metadata_recovery import _session, DAY as SOURCE_DAY
    from app.models import MainContractMap, TradingCalendar, TradingSession
    from sqlalchemy import select
    with _session() as session:
        baseline = catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY)
        row = session.scalar(select(MainContractMap).where(MainContractMap.symbol == "j"))
        row.contract_code = "J2610"
        session.commit()
        changed = catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY)
        assert changed != baseline
        calendar = session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == SOURCE_DAY))
        calendar.has_night_session = not calendar.has_night_session
        session.commit()
        next_changed = catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY)
        assert next_changed != changed
        trading_session = session.scalar(select(TradingSession).where(TradingSession.effective_from == SOURCE_DAY))
        trading_session.is_active = not trading_session.is_active
        session.commit()
        assert catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY) != next_changed


def test_fingerprint_includes_authoritative_prior_night_anchor():
    from app.market_data.day_preparation import catalog_day_fingerprint
    from tests.data_foundation.test_current_day_metadata_recovery import _session, DAY as SOURCE_DAY
    from app.models import TradingCalendar
    from datetime import timedelta
    with _session() as session:
        old = catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY)
        prior = TradingCalendar(exchange_code="DCE", trade_date=SOURCE_DAY - timedelta(days=1),
                                is_trading_day=True, has_night_session=True, provider="rqdata")
        session.add(prior)
        session.commit()
        added = catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY)
        assert added != old
        prior.is_trading_day = False
        session.commit()
        assert catalog_day_fingerprint(session, ("j", "jm"), SOURCE_DAY) != added


def test_ten_large_daily_snapshots_keep_index_bounded_and_all_evidence(tmp_path):
    from datetime import timedelta
    path = tmp_path / "state.json"
    item, calls = service(path, capture=lambda day: {"snapshot_sha256": SNAPSHOT_HASH,
                                                   "source": "x" * 3_000_000})
    for index in range(10):
        day = DAY + timedelta(days=index)
        item.select_day = lambda now, chosen=day: chosen
        assert item.tick(NOW) is None
        assert item.read_selected_day(day)["snapshot"]["source"] == "x" * 3_000_000
    assert path.stat().st_size < 20_000
    assert len(list(item.archive_root.glob("*.json"))) == 10
    assert calls.count("capture") == 10
    assert calls.count("apply") == 10


@pytest.mark.parametrize("status", ["passed", "blocked"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_terminal_archive_missing_or_corrupted_never_retries(tmp_path, status, damage):
    def fail(*args):
        raise ValueError("COMMIT_OUTCOME_UNKNOWN")
    path = tmp_path / "state.json"
    item, _ = service(path, apply=fail if status == "blocked" else None)
    item.tick(NOW)
    proof = item.read_state()[DAY.isoformat()]["archive"]
    archive = item.archive_root / proof["file"]
    if damage == "missing":
        archive.unlink()
    else:
        archive.chmod(0o600)
        archive.write_text("{}")
    restarted, calls = service(path, ready=True)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert calls == []


def test_archive_fsync_failure_after_commit_keeps_inflight_and_never_retries(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    item, calls = service(path)
    def fail(*args):
        raise OSError("fsync failed")
    monkeypatch.setattr(item, "_archive_terminal", fail)
    assert item.tick(NOW) is not None
    restarted, calls = service(path, ready=True)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert calls == []


def test_existing_full_v1_terminal_is_archived_without_recapture(tmp_path):
    item, calls = service(tmp_path / "state.json", ready=True)
    full = {"status": "passed", "started_at": NOW.isoformat(),
            "snapshot": {"snapshot_sha256": SNAPSHOT_HASH, "source": "v1 evidence"},
            "plan": {"plan_sha256": PLAN_HASH}, "receipt": {"status": "applied"}}
    item._write({DAY.isoformat(): full})
    assert item.tick(NOW) is None
    assert calls == []
    assert "snapshot" not in item.read_state()[DAY.isoformat()]
    assert item.read_selected_day(DAY) == full


def test_only_selected_terminal_archive_is_read(tmp_path):
    from datetime import timedelta
    item, calls = service(tmp_path / "state.json")
    assert item.tick(NOW) is None
    next_day = DAY + timedelta(days=1)
    item.select_day = lambda now: next_day
    assert item.tick(NOW) is None
    old = item.read_state()[DAY.isoformat()]["archive"]
    (item.archive_root / old["file"]).unlink()
    restarted, calls = service(tmp_path / "state.json", ready=True)
    restarted.select_day = lambda now: next_day
    assert restarted.tick(NOW) is None
    assert calls == []


def test_actual_archive_fsync_failure_preserves_prior_inflight_proof(tmp_path, monkeypatch):
    import os
    from app.market_data import day_preparation
    path = tmp_path / "state.json"
    item, calls = service(path)
    original = os.fsync
    def fail_archive(fd):
        if os.fstat(fd).st_mode & 0o777 == 0o400:
            raise OSError("archive fsync failed")
        return original(fd)
    monkeypatch.setattr(day_preparation.os, "fsync", fail_archive)
    assert item.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert calls.count("apply") == 1
    assert item.read_state()[DAY.isoformat()]["status"] == "inflight"
    assert item.read_state()[DAY.isoformat()]["snapshot"]["snapshot_sha256"] == SNAPSHOT_HASH
    restarted, retry_calls = service(path, ready=True)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert retry_calls == []


def test_index_fsync_failure_after_commit_retains_full_source_and_never_retries(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    item, calls = service(path)
    original = item._write
    def fail_terminal_index(days):
        if any("archive" in record for record in days.values()):
            raise OSError("index fsync failed")
        return original(days)
    monkeypatch.setattr(item, "_write", fail_terminal_index)
    assert item.tick(NOW) is not None
    restarted, retry_calls = service(path, ready=True)
    assert restarted.tick(NOW) == "METADATA_PREPARATION_READBACK_REQUIRED"
    assert retry_calls == []
    assert restarted.read_state()[DAY.isoformat()]["snapshot"]["snapshot_sha256"] == SNAPSHOT_HASH
    assert len(list(item.archive_root.glob("*.json"))) == 2
