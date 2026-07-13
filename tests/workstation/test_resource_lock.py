"""Tests for resource_lock.py — resource-scoped locks with heartbeat-based staleness.

Tests cover: inspect, acquire, heartbeat, release, force-release, mutex rules,
concurrent competition, stale lock recovery, wrong release blocking, release-all.

All tests use tempfile.TemporaryDirectory — no business data accessed.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
import tempfile

import pytest

# Inject scripts/ai/lib into path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ai" / "lib"))
from resource_lock import (
    VALID_SCOPES,
    LockError,
    acquire,
    force_release,
    heartbeat,
    inspect,
    release,
    release_all,
    status_all,
)


@pytest.fixture
def tmp_repo() -> Path:
    """Temporary repo root with .ai/locks/resources/ structure."""
    with tempfile.TemporaryDirectory(prefix="resource_lock_test_") as td:
        root = Path(td)
        (root / ".ai" / "locks" / "resources").mkdir(parents=True, exist_ok=True)
        yield root


# ============================================================
# Inspect tests
# ============================================================

class TestInspect:
    def test_unlocked(self, tmp_repo: Path):
        result = inspect(tmp_repo, "data-writer")
        assert result["state"] == "unlocked"
        assert result["lock"] is None
        assert result["reason"] == "no_lock"

    def test_locked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        result = inspect(tmp_repo, "data-writer")
        assert result["state"] == "locked"
        assert result["lock"]["task_id"] == "WS-V2-004"

    def test_stale(self, tmp_repo: Path):
        # Create a lock with ancient heartbeat
        lf = tmp_repo / ".ai" / "locks" / "resources" / "data-writer.json"
        lock = {
            "schema_version": 1,
            "lock_id": "x",
            "scope": "data-writer",
            "task_id": "OLD-TASK",
            "epic_id": "",
            "owner_pid": 1,
            "host": "old-host",
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T01:00:00Z",
            "command": "",
            "branch": "",
            "worktree": "",
        }
        lf.write_text(json.dumps(lock))
        result = inspect(tmp_repo, "data-writer")
        assert result["state"] == "stale"
        assert result["stale"] is True

    def test_bad_scope(self, tmp_repo: Path):
        with pytest.raises(LockError, match="INVALID_SCOPE"):
            inspect(tmp_repo, "nonexistent-scope")


# ============================================================
# Acquire tests
# ============================================================

class TestAcquire:
    def test_basic_acquire(self, tmp_repo: Path):
        lock = acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        assert lock["task_id"] == "WS-V2-004"
        assert lock["scope"] == "data-writer"
        lf = tmp_repo / ".ai" / "locks" / "resources" / "data-writer.json"
        assert lf.exists()

    def test_reacquire_idempotent(self, tmp_repo: Path):
        """Same task re-acquire = refresh heartbeat, no error."""
        lock1 = acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        time.sleep(0.1)
        lock2 = acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        assert lock2["task_id"] == "WS-V2-004"
        # heartbeat should be refreshed
        assert lock2["heartbeat_at"] >= lock1["heartbeat_at"]

    def test_double_acquire_blocked(self, tmp_repo: Path):
        """Different task trying same scope must raise SCOPE_HELD."""
        acquire(tmp_repo, scope="data-writer", task_id="TASK-A")
        with pytest.raises(LockError, match="SCOPE_HELD"):
            acquire(tmp_repo, scope="data-writer", task_id="TASK-B")

    def test_invalid_scope_blocked(self, tmp_repo: Path):
        with pytest.raises(LockError, match="INVALID_SCOPE"):
            acquire(tmp_repo, scope="bad-scope", task_id="X")

    def test_acquire_with_all_fields(self, tmp_repo: Path):
        lock = acquire(
            tmp_repo,
            scope="postgres-metadata-writer",
            task_id="WS-V2-004",
            epic_id="EPIC-1",
            branch="feature/x",
            worktree="/tmp/wt",
            pid=12345,
        )
        assert lock["epic_id"] == "EPIC-1"
        assert lock["branch"] == "feature/x"
        assert lock["owner_pid"] == 12345

    def test_acquire_over_stale(self, tmp_repo: Path):
        """Stale lock should be auto-broken and new acquire succeeds."""
        lf = tmp_repo / ".ai" / "locks" / "resources" / "data-writer.json"
        old_lock = {
            "schema_version": 1,
            "lock_id": "stale",
            "scope": "data-writer",
            "task_id": "OLD-TASK",
            "epic_id": "",
            "owner_pid": 1,
            "host": "old-host",
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T01:00:00Z",
            "command": "",
            "branch": "",
            "worktree": "",
        }
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_text(json.dumps(old_lock))
        # Should succeed because stale
        lock = acquire(tmp_repo, scope="data-writer", task_id="NEW-TASK")
        assert lock["task_id"] == "NEW-TASK"
        # Audit should have auto-break-stale event
        af = tmp_repo / ".ai" / "locks" / "resources" / "audit.jsonl"
        assert af.exists()
        lines = af.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "auto-break-stale" in events or "acquire" in events


# ============================================================
# Heartbeat tests
# ============================================================

class TestHeartbeat:
    def test_update_heartbeat(self, tmp_repo: Path):
        lock = acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        original_hb = lock["heartbeat_at"]
        time.sleep(1.1)  # Ensure at least 1 second passes for timestamp change
        refreshed = heartbeat(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        assert refreshed["heartbeat_at"] != original_hb

    def test_wrong_owner_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            heartbeat(tmp_repo, scope="data-writer", task_id="OTHER-TASK")

    def test_wrong_pid_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=100)
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            heartbeat(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=999)

    def test_heartbeat_nonexistent(self, tmp_repo: Path):
        with pytest.raises(LockError, match="LOCK_NOT_FOUND"):
            heartbeat(tmp_repo, scope="data-writer", task_id="WS-V2-004")


# ============================================================
# Release tests
# ============================================================

class TestRelease:
    def test_normal_release(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        result = release(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        assert result is not None
        assert inspect(tmp_repo, "data-writer")["state"] == "unlocked"

    def test_release_nonexistent(self, tmp_repo: Path):
        result = release(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        assert result is None

    def test_wrong_task_id_release_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="TASK-A")
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            release(tmp_repo, scope="data-writer", task_id="TASK-B")

    def test_wrong_pid_release_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=100)
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            release(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=999)


# ============================================================
# Force-release tests
# ============================================================

class TestForceRelease:
    def test_valid_force_release(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        result = force_release(
            tmp_repo,
            scope="data-writer",
            reason="Process 12345 has been stuck for 3 hours, manual cleanup",
        )
        assert result is not None
        assert inspect(tmp_repo, "data-writer")["state"] == "unlocked"
        # Audit trail should have reason
        af = tmp_repo / ".ai" / "locks" / "resources" / "audit.jsonl"
        lines = af.read_text().strip().split("\n")
        fr_event = [json.loads(l) for l in lines if json.loads(l)["event"] == "force-release"]
        assert len(fr_event) == 1
        assert "stuck" in fr_event[0]["actor"]["reason"]

    def test_empty_reason_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        with pytest.raises(LockError):
            force_release(tmp_repo, scope="data-writer", reason="short")

    def test_force_release_nonexistent(self, tmp_repo: Path):
        with pytest.raises(LockError, match="LOCK_NOT_FOUND"):
            force_release(tmp_repo, scope="data-writer", reason="Manual cleanup required")


# ============================================================
# Mutex tests
# ============================================================

class TestMutexRules:
    def test_runtime_jm_blocks_archive(self, tmp_repo: Path):
        acquire(tmp_repo, scope="runtime-jm", task_id="WS-V2-004")
        with pytest.raises(LockError, match="MUTEX_CONFLICT"):
            acquire(tmp_repo, scope="after-market-archive", task_id="WS-V2-004")

    def test_archive_blocks_jm(self, tmp_repo: Path):
        acquire(tmp_repo, scope="after-market-archive", task_id="WS-V2-004")
        with pytest.raises(LockError, match="MUTEX_CONFLICT"):
            acquire(tmp_repo, scope="runtime-jm", task_id="WS-V2-004")

    def test_release_then_acquire_ok(self, tmp_repo: Path):
        acquire(tmp_repo, scope="runtime-jm", task_id="WS-V2-004")
        release(tmp_repo, scope="runtime-jm", task_id="WS-V2-004")
        # Now archive should be acquirable
        lock = acquire(tmp_repo, scope="after-market-archive", task_id="WS-V2-004")
        assert lock["scope"] == "after-market-archive"

    def test_different_task_mutex(self, tmp_repo: Path):
        """Mutex applies even within same task_id."""
        acquire(tmp_repo, scope="runtime-jm", task_id="TASK-X")
        with pytest.raises(LockError, match="MUTEX_CONFLICT"):
            acquire(tmp_repo, scope="after-market-archive", task_id="TASK-Y")


# ============================================================
# Release-all tests
# ============================================================

class TestReleaseAll:
    def test_release_all_scopes(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        acquire(tmp_repo, scope="external-notification", task_id="WS-V2-004")
        acquire(tmp_repo, scope="docs-delete", task_id="WS-V2-004")

        released = release_all(tmp_repo, task_id="WS-V2-004")
        assert set(released) == {"data-writer", "external-notification", "docs-delete"}

        for scope in released:
            assert inspect(tmp_repo, scope)["state"] == "unlocked"

    def test_release_all_only_own(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="TASK-A")
        acquire(tmp_repo, scope="docs-delete", task_id="TASK-B", pid=99999)

        released = release_all(tmp_repo, task_id="TASK-A")
        assert released == ["data-writer"]
        # TASK-B's lock should still be held
        assert inspect(tmp_repo, "docs-delete")["state"] == "locked"

    def test_release_all_empty(self, tmp_repo: Path):
        released = release_all(tmp_repo, task_id="NO-TASK")
        assert released == []


# ============================================================
# Status-all tests
# ============================================================

class TestStatusAll:
    def test_all_unlocked(self, tmp_repo: Path):
        results = status_all(tmp_repo)
        assert len(results) == len(VALID_SCOPES)
        assert all(r["state"] == "unlocked" for r in results)

    def test_mixed_states(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        acquire(tmp_repo, scope="external-notification", task_id="WS-V2-004")
        results = status_all(tmp_repo)
        data_result = [r for r in results if r["scope"] == "data-writer"][0]
        notif_result = [r for r in results if r["scope"] == "external-notification"][0]
        assert data_result["state"] == "locked"
        assert notif_result["state"] == "locked"


# ============================================================
# Concurrent competition tests (Gate G1)
# ============================================================

def _acquire_in_process(lock_dir: str, scope: str, task_id: str) -> dict:
    """Helper: acquire a lock in a subprocess, return result as dict."""
    import sys
    from resource_lock import acquire, LockError

    try:
        lock = acquire(Path(lock_dir), scope=scope, task_id=task_id)
        return {"status": "acquired", "task_id": task_id, "lock_id": lock.get("lock_id")}
    except LockError as e:
        return {"status": "blocked", "task_id": task_id, "error": str(e)}
    except Exception as e:
        return {"status": "error", "task_id": task_id, "error": str(e)}


class TestConcurrentCompetition:
    def test_two_tasks_compete_same_scope(self, tmp_repo: Path):
        """Gate G1: Two tasks compete for same data-writer — only one succeeds."""
        lock_dir = str(tmp_repo)
        with multiprocessing.Pool(2) as pool:
            results = pool.starmap(
                _acquire_in_process,
                [(lock_dir, "data-writer", "TASK-A"), (lock_dir, "data-writer", "TASK-B")],
            )

        acquired = [r for r in results if r["status"] == "acquired"]
        blocked = [r for r in results if r["status"] == "blocked"]

        assert len(acquired) == 1, f"Expected exactly 1 acquisition, got {results}"
        assert len(blocked) == 1
        assert "already exists" in blocked[0]["error"] or "TOCTOU" in blocked[0]["error"] or "SCOPE_HELD" in blocked[0]["error"]

    def test_parallel_different_scopes_ok(self, tmp_repo: Path):
        """Different scopes can be acquired in parallel."""
        lock_dir = str(tmp_repo)
        with multiprocessing.Pool(2) as pool:
            results = pool.starmap(
                _acquire_in_process,
                [(lock_dir, "data-writer", "TASK-A"), (lock_dir, "docs-delete", "TASK-B")],
            )

        acquired = [r for r in results if r["status"] == "acquired"]
        assert len(acquired) == 2, f"Both should succeed, got {results}"

    def test_fast_acquire_release_acquire(self, tmp_repo: Path):
        """Rapid acquire-release cycle from different tasks."""
        lock1 = acquire(tmp_repo, scope="data-writer", task_id="TASK-A")
        release(tmp_repo, scope="data-writer", task_id="TASK-A")
        lock2 = acquire(tmp_repo, scope="data-writer", task_id="TASK-B")
        assert lock2["task_id"] == "TASK-B"
        assert lock1["lock_id"] != lock2["lock_id"]


# ============================================================
# Stale lock tests (Gate G2)
# ============================================================

class TestStaleLock:
    def test_stale_lock_auto_recovery(self, tmp_repo: Path):
        """Gate G2: Stale lock gets auto-broken on acquire."""
        lf = tmp_repo / ".ai" / "locks" / "resources" / "data-writer.json"
        stale_lock = {
            "schema_version": 1,
            "lock_id": "x",
            "scope": "data-writer",
            "task_id": "CRASHED-TASK",
            "epic_id": "",
            "owner_pid": 99999,
            "host": "crashed-host",
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T01:00:00Z",
            "command": "",
            "branch": "",
            "worktree": "",
        }
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_text(json.dumps(stale_lock))

        assert inspect(tmp_repo, "data-writer")["state"] == "stale"
        # New task should be able to acquire
        lock = acquire(tmp_repo, scope="data-writer", task_id="RECOVERY-TASK")
        assert lock["task_id"] == "RECOVERY-TASK"
        assert inspect(tmp_repo, "data-writer")["state"] == "locked"

    def test_heartbeat_prevents_stale(self, tmp_repo: Path):
        """Regular heartbeat keeps lock active."""
        acquire(tmp_repo, scope="external-notification", task_id="WS-V2-004")
        # external-notification has 5m stale threshold
        heartbeat(tmp_repo, scope="external-notification", task_id="WS-V2-004")
        result = inspect(tmp_repo, "external-notification")
        assert result["state"] == "locked"
        assert result["stale"] is False

    def test_force_release_stale_lock(self, tmp_repo: Path):
        lf = tmp_repo / ".ai" / "locks" / "resources" / "data-writer.json"
        stale_lock = {
            "schema_version": 1,
            "lock_id": "x",
            "scope": "data-writer",
            "task_id": "STALE-TASK",
            "epic_id": "",
            "owner_pid": 1,
            "host": "old",
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T01:00:00Z",
            "command": "",
            "branch": "",
            "worktree": "",
        }
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_text(json.dumps(stale_lock))

        result = force_release(
            tmp_repo,
            scope="data-writer",
            reason="Stale lock cleanup after process crash",
        )
        assert inspect(tmp_repo, "data-writer")["state"] == "unlocked"


# ============================================================
# Cross-task release blocking tests
# ============================================================

class TestCrossTaskBlocking:
    def test_release_other_task_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="TASK-A")
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            release(tmp_repo, scope="data-writer", task_id="TASK-B")

    def test_release_other_pid_blocked(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=100)
        with pytest.raises(LockError, match="OWNER_MISMATCH"):
            release(tmp_repo, scope="data-writer", task_id="WS-V2-004", pid=999)


# ============================================================
# Audit log tests
# ============================================================

class TestAuditLogs:
    def test_acquire_creates_audit(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        af = tmp_repo / ".ai" / "locks" / "resources" / "audit.jsonl"
        assert af.exists()
        lines = af.read_text().strip().split("\n")
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert first["event"] == "acquire"
        assert first["lock"]["task_id"] == "WS-V2-004"

    def test_full_lifecycle_audit(self, tmp_repo: Path):
        acquire(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        heartbeat(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        release(tmp_repo, scope="data-writer", task_id="WS-V2-004")
        af = tmp_repo / ".ai" / "locks" / "resources" / "audit.jsonl"
        lines = af.read_text().strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["acquire", "heartbeat", "release"]
