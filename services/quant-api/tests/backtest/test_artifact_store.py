from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.backtest import artifact_store as artifact_store_module
from app.backtest.artifact_store import ArtifactStore
from app.backtest.config import BacktestSettings
from app.backtest.contracts import RunStatus
from app.backtest.errors import BacktestError, RunFailureCode


RUN_ID = "20260823T010203-run001"
STARTED_AT = "2026-08-23T01:02:03+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    settings = BacktestSettings(
        python_executable=tmp_path / "python",
        bundle_path=tmp_path / "bundle",
        runs_root=tmp_path / "runs",
        timeout_seconds=3600,
        cors_origins=("http://127.0.0.1:5173",),
    )
    return ArtifactStore(settings)


@pytest.fixture
def strategy_file(tmp_path: Path) -> Path:
    path = tmp_path / "registered_strategy.py"
    path.write_text('print("safe")\n', encoding="utf-8")
    return path


def _create_run(
    store: ArtifactStore,
    strategy_file: Path,
    *,
    run_id: str = RUN_ID,
    started_at: str = STARTED_AT,
) -> None:
    store.create_run(
        run_id,
        run_record={
            "status": RunStatus.RUNNING,
            "started_at": started_at,
            "requested": {"future_cash": "1000000"},
        },
        strategy_file=strategy_file,
        strategy_params={"quantity": 1, "threshold": "0.5"},
    )


def test_create_run_uses_only_fixed_paths_and_snapshots_strategy_with_sha(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    paths = store.create_run(
        RUN_ID,
        run_record={"status": RunStatus.RUNNING, "started_at": STARTED_AT},
        strategy_file=strategy_file,
        strategy_params={"quantity": 1},
    )

    assert {item.name for item in paths.root.iterdir()} == {
        "run.json",
        "strategy.py",
        "strategy_params.json",
        "report",
        "stdout.log",
        "stderr.log",
    }
    assert paths.strategy_file.read_bytes() == b'print("safe")\n'
    assert store.read_run(RUN_ID) == {
        "run_id": RUN_ID,
        "status": "running",
        "started_at": STARTED_AT,
        "strategy_sha256": (
            "75ac77dcb489232b4a58483857001625704659f61c160d128763792cb488fb34"
        ),
    }
    assert json.loads(paths.strategy_params_json.read_text(encoding="utf-8")) == {
        "quantity": 1
    }


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../escape", "nested/run", "/absolute", "back\\slash", "空"],
)
def test_create_run_rejects_unsafe_run_ids(
    store: ArtifactStore,
    strategy_file: Path,
    run_id: str,
) -> None:
    with pytest.raises(ValueError, match="^BACKTEST_RUN_ID_INVALID$"):
        _create_run(store, strategy_file, run_id=run_id)


def test_run_reads_reject_symlinked_directory_escape(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text('{"status":"succeeded"}', encoding="utf-8")
    store.runs_root.mkdir(parents=True)
    (store.runs_root / RUN_ID).symlink_to(outside, target_is_directory=True)

    with pytest.raises(BacktestError, match="^BACKTEST_RUN_NOT_FOUND$"):
        store.read_run(RUN_ID)


def test_update_run_is_atomic_and_preserves_existing_json_on_replace_failure(
    store: ArtifactStore,
    strategy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(artifact_store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        store.update_run(RUN_ID, {"status": RunStatus.SUCCEEDED})

    assert store.read_run(RUN_ID)["status"] == "running"
    assert not list((store.runs_root / RUN_ID).glob(".run.json.*.tmp"))


def test_update_run_merges_fields_without_dropping_lineage(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)

    updated = store.update_run(
        RUN_ID,
        {
            "status": RunStatus.SUCCEEDED,
            "finished_at": "2026-08-23T01:03:03+00:00",
        },
    )

    assert updated["status"] == "succeeded"
    assert updated["requested"] == {"future_cash": "1000000"}
    assert store.read_run(RUN_ID) == updated


def test_result_json_is_written_and_read_through_atomic_store_methods(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    payload = {
        "summary": {"total_returns": "0.1"},
        "equity": [{"date": "2026-01-05", "unit_net_value": "1.1"}],
        "trade_count": 1,
    }

    store.write_result(RUN_ID, payload)

    assert store.read_result(RUN_ID) == payload


def test_list_runs_is_newest_first_and_enforces_limit_bounds(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(
        store,
        strategy_file,
        run_id="run-old",
        started_at="2026-08-21T01:00:00+00:00",
    )
    _create_run(
        store,
        strategy_file,
        run_id="run-new",
        started_at="2026-08-23T01:00:00+00:00",
    )
    _create_run(
        store,
        strategy_file,
        run_id="run-middle",
        started_at="2026-08-22T01:00:00+00:00",
    )

    assert [item["run_id"] for item in store.list_runs(limit=2)] == [
        "run-new",
        "run-middle",
    ]
    for invalid_limit in (0, 101, True):
        with pytest.raises(ValueError, match="^BACKTEST_RUN_LIMIT_INVALID$"):
            store.list_runs(limit=invalid_limit)


def test_list_runs_ignores_symlinked_and_non_run_entries(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
) -> None:
    _create_run(store, strategy_file)
    outside = tmp_path / "outside-run"
    outside.mkdir()
    (outside / "run.json").write_text(
        '{"run_id":"escape","started_at":"9999-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    (store.runs_root / "escape").symlink_to(outside, target_is_directory=True)
    (store.runs_root / "README.txt").write_text("not a run", encoding="utf-8")

    assert [item["run_id"] for item in store.list_runs()] == [RUN_ID]


def test_read_log_tail_caps_lines_and_bytes(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    stdout = store.run_paths(RUN_ID).stdout_log
    stdout.write_text(
        "".join(f"line-{index:03d}\n" for index in range(250)),
        encoding="utf-8",
    )

    tail = store.read_log_tail(RUN_ID, "stdout")

    assert tail.splitlines()[0] == "line-050"
    assert tail.splitlines()[-1] == "line-249"
    assert len(tail.splitlines()) == 200

    stdout.write_text("x" * 70_000, encoding="utf-8")
    assert len(store.read_log_tail(RUN_ID, "stdout").encode("utf-8")) == 65_536


@pytest.mark.parametrize(
    ("stream", "max_lines", "max_bytes"),
    [
        ("arbitrary", 200, 65_536),
        ("stdout", 0, 65_536),
        ("stdout", 201, 65_536),
        ("stderr", 200, 65_537),
        ("stderr", True, 65_536),
    ],
)
def test_read_log_tail_rejects_paths_or_bounds_outside_allowlist(
    store: ArtifactStore,
    strategy_file: Path,
    stream: str,
    max_lines: int,
    max_bytes: int,
) -> None:
    _create_run(store, strategy_file)

    with pytest.raises(ValueError, match="^BACKTEST_LOG_REQUEST_INVALID$"):
        store.read_log_tail(
            RUN_ID,
            stream,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )


def test_resolve_artifact_accepts_only_fixed_available_files(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    paths = store.run_paths(RUN_ID)
    paths.result_pickle.write_bytes(b"pickle bytes are download-only")
    paths.equity_png.write_bytes(b"png")

    assert store.resolve_artifact(RUN_ID, "result_pickle") == paths.result_pickle
    assert store.resolve_artifact(RUN_ID, "equity_png") == paths.equity_png
    assert store.resolve_artifact(RUN_ID, "stdout_log") == paths.stdout_log
    assert store.resolve_artifact(RUN_ID, "stderr_log") == paths.stderr_log
    assert store.resolve_artifact(RUN_ID, "run_json") == paths.run_json

    for kind in ("strategy.py", "result_json", "../../outside", "report_zip"):
        with pytest.raises(BacktestError, match="^BACKTEST_ARTIFACT_NOT_FOUND$"):
            store.resolve_artifact(RUN_ID, kind)


def test_resolve_artifact_rejects_symlink_even_when_target_is_inside_run(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    paths = store.run_paths(RUN_ID)
    paths.result_pickle.write_bytes(b"result")
    paths.equity_png.symlink_to(paths.result_pickle)

    with pytest.raises(BacktestError, match="^BACKTEST_ARTIFACT_NOT_FOUND$"):
        store.resolve_artifact(RUN_ID, "equity_png")


def test_temporary_report_zip_contains_report_tree_and_is_always_cleaned_up(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    report = store.run_paths(RUN_ID).report_dir
    (report / "summary.csv").write_text("name,value\nreturn,0.1\n", encoding="utf-8")
    (report / "trades").mkdir()
    (report / "trades" / "trades.csv").write_text("id\n1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="consumer failed"):
        with store.temporary_report_zip(RUN_ID) as zip_path:
            assert zip_path.parent != store.runs_root
            assert zip_path.is_file()
            with ZipFile(zip_path) as archive:
                assert archive.namelist() == [
                    "report/summary.csv",
                    "report/trades/trades.csv",
                ]
            raise RuntimeError("consumer failed")

    assert not zip_path.exists()


def test_temporary_report_zip_rejects_symlinks_in_report_tree(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
) -> None:
    _create_run(store, strategy_file)
    outside = tmp_path / "outside.csv"
    outside.write_text("secret", encoding="utf-8")
    (store.run_paths(RUN_ID).report_dir / "escape.csv").symlink_to(outside)

    with pytest.raises(BacktestError, match="^BACKTEST_ARTIFACT_NOT_FOUND$"):
        with store.temporary_report_zip(RUN_ID):
            pytest.fail("unsafe report must not be yielded")


def test_acquire_lock_uses_exclusive_creation_and_preserves_first_owner(
    store: ArtifactStore,
) -> None:
    first = store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    with pytest.raises(BacktestError, match="^BACKTEST_ALREADY_RUNNING$"):
        store.acquire_lock("another-run", pid=5678, started_at=STARTED_AT)

    assert store.read_lock() == first
    assert json.loads(store.lock_path.read_text(encoding="utf-8")) == {
        "run_id": RUN_ID,
        "pid": 1234,
        "started_at": STARTED_AT,
    }


def test_release_lock_only_removes_matching_run(store: ArtifactStore) -> None:
    store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    assert store.release_lock("another-run") is False
    assert store.lock_path.exists()
    assert store.release_lock(RUN_ID) is True
    assert not store.lock_path.exists()


def test_read_lock_rejects_dangling_symlink_instead_of_treating_it_as_unlocked(
    store: ArtifactStore,
    tmp_path: Path,
) -> None:
    store.runs_root.mkdir(parents=True)
    store.lock_path.symlink_to(tmp_path / "missing-lock-target")

    with pytest.raises(ValueError, match="^BACKTEST_PATH_INVALID$"):
        store.read_lock()


def test_reconcile_stale_lock_keeps_pid_alive_busy(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    lock = store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    reconciled = store.reconcile_stale_lock(pid_exists=lambda pid: pid == 1234)

    assert reconciled == lock
    assert store.read_run(RUN_ID)["status"] == "running"
    assert store.lock_path.exists()


def test_reconcile_missing_pid_marks_running_run_interrupted_and_unlocks(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    reconciled = store.reconcile_stale_lock(pid_exists=lambda _pid: False)

    assert reconciled is None
    run = store.read_run(RUN_ID)
    assert run["status"] == "interrupted"
    assert run["failure_code"] == RunFailureCode.RUN_INTERRUPTED
    assert run["finished_at"].endswith("+00:00")
    datetime.fromisoformat(run["finished_at"])
    assert not store.lock_path.exists()
