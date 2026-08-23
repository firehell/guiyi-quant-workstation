from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import threading
from typing import IO, Any
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

    def fail_replace(source: Path | str, target: Path | str, **_kwargs: object) -> None:
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


def test_read_log_tail_bounds_encoded_output_for_invalid_utf8(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    store.run_paths(RUN_ID).stdout_log.write_bytes(b"\xff" * 65_536)

    tail = store.read_log_tail(RUN_ID, "stdout")

    assert len(tail.encode("utf-8")) <= 65_536
    assert len(tail.splitlines()) <= 200


def test_read_log_tail_bounds_output_when_byte_window_splits_utf8_character(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    store.run_paths(RUN_ID).stdout_log.write_bytes(
        b"prefix" + ("界" * 21_846).encode("utf-8")
    )

    tail = store.read_log_tail(RUN_ID, "stdout")

    assert tail.endswith("界")
    assert len(tail.encode("utf-8")) <= 65_536
    assert len(tail.splitlines()) <= 200


def test_read_log_tail_cannot_be_redirected_after_path_validation(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    log = store.run_paths(RUN_ID).stdout_log
    log.write_text("trusted", encoding="utf-8")
    outside = tmp_path / "outside.log"
    outside.write_text("escaped", encoding="utf-8")
    original_open = Path.open
    swapped = False

    def swap_before_path_open(path: Path, *args: object, **kwargs: object) -> IO[Any]:
        nonlocal swapped
        if path == log and not swapped:
            swapped = True
            path.rename(path.with_name("stdout.original"))
            path.symlink_to(outside)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swap_before_path_open)

    assert store.read_log_tail(RUN_ID, "stdout") == "trusted"


def test_atomic_update_cannot_follow_run_directory_swapped_after_read(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    run_root = store.run_paths(RUN_ID).root
    outside = tmp_path / "outside-run"
    outside.mkdir()
    outside_record = {"run_id": "outside", "status": "protected"}
    (outside / "run.json").write_text(json.dumps(outside_record), encoding="utf-8")
    real_replace = artifact_store_module.os.replace
    swapped = False

    def swap_before_replace(
        source: str | bytes | Path,
        target: str | bytes | Path,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if Path(target).name == "run.json" and not swapped:
            swapped = True
            run_root.rename(run_root.with_name(f"{RUN_ID}-original"))
            run_root.symlink_to(outside, target_is_directory=True)
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(artifact_store_module.os, "replace", swap_before_replace)

    store.update_run(RUN_ID, {"status": RunStatus.SUCCEEDED})

    assert (
        json.loads((outside / "run.json").read_text(encoding="utf-8")) == outside_record
    )
    assert (
        json.loads(
            (run_root.with_name(f"{RUN_ID}-original") / "run.json").read_text(
                encoding="utf-8"
            )
        )["status"]
        == "succeeded"
    )


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

    expected = {
        "result_pickle": b"pickle bytes are download-only",
        "equity_png": b"png",
        "stdout_log": b"",
        "stderr_log": b"",
        "run_json": paths.run_json.read_bytes(),
    }
    for kind, content in expected.items():
        with store.resolve_artifact(RUN_ID, kind) as artifact:
            assert artifact.read() == content

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


def test_resolved_artifact_handle_remains_bound_when_path_is_replaced(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
) -> None:
    _create_run(store, strategy_file)
    artifact_path = store.run_paths(RUN_ID).equity_png
    artifact_path.write_bytes(b"trusted-png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"escaped-png")

    with store.resolve_artifact(RUN_ID, "equity_png") as artifact:
        artifact_path.rename(artifact_path.with_name("equity.original.png"))
        artifact_path.symlink_to(outside)

        assert artifact.read() == b"trusted-png"


def test_missing_run_is_reported_consistently_for_all_artifact_kinds(
    store: ArtifactStore,
) -> None:
    for kind in ("equity_png", "stdout_log"):
        with pytest.raises(BacktestError, match="^BACKTEST_RUN_NOT_FOUND$"):
            store.resolve_artifact(RUN_ID, kind)

    with pytest.raises(BacktestError, match="^BACKTEST_RUN_NOT_FOUND$"):
        with store.temporary_report_zip(RUN_ID):
            pytest.fail("a missing run must not yield a report archive")


def test_resolve_artifact_closes_descriptor_when_fstat_fails(
    store: ArtifactStore,
    strategy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    store.run_paths(RUN_ID).equity_png.write_bytes(b"png")
    real_open = artifact_store_module.os.open
    real_fstat = artifact_store_module.os.fstat
    artifact_descriptors: list[int] = []

    def record_artifact_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "equity.png":
            artifact_descriptors.append(descriptor)
        return descriptor

    def fail_artifact_fstat(descriptor: int) -> Any:
        if descriptor in artifact_descriptors:
            raise OSError("injected artifact fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(artifact_store_module.os, "open", record_artifact_open)
    monkeypatch.setattr(artifact_store_module.os, "fstat", fail_artifact_fstat)

    with pytest.raises(BacktestError, match="^BACKTEST_ARTIFACT_NOT_FOUND$"):
        store.resolve_artifact(RUN_ID, "equity_png")

    assert len(artifact_descriptors) == 1
    with pytest.raises(OSError):
        real_fstat(artifact_descriptors[0])


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
        with store.temporary_report_zip(RUN_ID) as zip_handle:
            with ZipFile(zip_handle) as archive:
                assert archive.namelist() == [
                    "report/summary.csv",
                    "report/trades/trades.csv",
                ]
            raise RuntimeError("consumer failed")

    assert zip_handle.closed


def test_temporary_report_zip_preserves_consumer_value_error(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    (store.run_paths(RUN_ID).report_dir / "summary.csv").write_text(
        "summary",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="consumer rejected response"):
        with store.temporary_report_zip(RUN_ID) as zip_handle:
            raise ValueError("consumer rejected response")

    assert zip_handle.closed


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


def test_report_zip_reads_opened_file_not_replaced_path(
    store: ArtifactStore,
    strategy_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    report_file = store.run_paths(RUN_ID).report_dir / "summary.csv"
    report_file.write_bytes(b"trusted-report")
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"escaped-report")
    original_write = ZipFile.write
    swapped = False

    def swap_before_zip_read(
        archive: ZipFile,
        filename: str | Path,
        arcname: str | Path | None = None,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> None:
        nonlocal swapped
        path = Path(filename)
        if path == report_file and not swapped:
            swapped = True
            path.rename(path.with_name("summary.original.csv"))
            path.symlink_to(outside)
        original_write(
            archive,
            filename,
            arcname=arcname,
            compress_type=compress_type,
            compresslevel=compresslevel,
        )

    monkeypatch.setattr(ZipFile, "write", swap_before_zip_read)

    with store.temporary_report_zip(RUN_ID) as zip_handle:
        with ZipFile(zip_handle) as archive:
            assert archive.read("report/summary.csv") == b"trusted-report"


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


def test_acquire_lock_fstat_failure_closes_and_removes_created_lock(
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = artifact_store_module.os.open
    real_fstat = artifact_store_module.os.fstat
    lock_descriptors: list[int] = []

    def record_lock_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "active.lock":
            lock_descriptors.append(descriptor)
        return descriptor

    def fail_lock_fstat(descriptor: int) -> Any:
        if descriptor in lock_descriptors:
            raise OSError("injected lock fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(artifact_store_module.os, "open", record_lock_open)
    monkeypatch.setattr(artifact_store_module.os, "fstat", fail_lock_fstat)

    with pytest.raises(OSError, match="injected lock fstat failure"):
        store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    assert len(lock_descriptors) == 1
    with pytest.raises(OSError):
        real_fstat(lock_descriptors[0])
    assert not store.lock_path.exists()


def test_acquire_lock_fdopen_failure_closes_and_removes_created_lock(
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = artifact_store_module.os.open
    real_fdopen = artifact_store_module.os.fdopen
    real_fstat = artifact_store_module.os.fstat
    lock_descriptors: list[int] = []

    def record_lock_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "active.lock":
            lock_descriptors.append(descriptor)
        return descriptor

    def fail_lock_fdopen(descriptor: int, *args: Any, **kwargs: Any) -> IO[Any]:
        if descriptor in lock_descriptors:
            raise OSError("injected lock fdopen failure")
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(artifact_store_module.os, "open", record_lock_open)
    monkeypatch.setattr(artifact_store_module.os, "fdopen", fail_lock_fdopen)

    with pytest.raises(OSError, match="injected lock fdopen failure"):
        store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    assert len(lock_descriptors) == 1
    with pytest.raises(OSError):
        real_fstat(lock_descriptors[0])
    assert not store.lock_path.exists()


def test_open_run_closes_descriptor_when_directory_fstat_fails(
    store: ArtifactStore,
    strategy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    real_open = artifact_store_module.os.open
    real_fstat = artifact_store_module.os.fstat
    run_descriptors: list[int] = []

    def record_run_open(
        path: str | bytes | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == RUN_ID:
            run_descriptors.append(descriptor)
        return descriptor

    def fail_run_fstat(descriptor: int) -> Any:
        if descriptor in run_descriptors:
            raise OSError("injected run fstat failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(artifact_store_module.os, "open", record_run_open)
    monkeypatch.setattr(artifact_store_module.os, "fstat", fail_run_fstat)

    with pytest.raises(OSError, match="injected run fstat failure"):
        store.read_run(RUN_ID)

    assert len(run_descriptors) == 1
    with pytest.raises(OSError):
        real_fstat(run_descriptors[0])


def test_release_lock_only_removes_matching_run(store: ArtifactStore) -> None:
    store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    assert store.release_lock("another-run") is False
    assert store.lock_path.exists()
    assert store.release_lock(RUN_ID) is True
    assert not store.lock_path.exists()


def test_release_lock_serializes_owner_check_and_unlink_across_store_instances(
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)
    other_store = ArtifactStore(
        BacktestSettings(
            python_executable=store.runs_root.parent / "python",
            bundle_path=store.runs_root.parent / "bundle",
            runs_root=store.runs_root,
            timeout_seconds=3600,
            cors_origins=("http://127.0.0.1:5173",),
        )
    )
    old_release_paused = threading.Event()
    allow_old_release = threading.Event()
    replacement_entered = threading.Event()
    replacement_done = threading.Event()
    errors: list[BaseException] = []
    releasing_thread_id: int | None = None
    real_unlink = artifact_store_module.os.unlink
    paused_once = False

    def pause_before_owner_unlink(
        path: str | bytes | Path,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal paused_once
        if (
            threading.get_ident() == releasing_thread_id
            and Path(path).name == "active.lock"
            and not paused_once
        ):
            paused_once = True
            old_release_paused.set()
            assert allow_old_release.wait(timeout=5)
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(artifact_store_module.os, "unlink", pause_before_owner_unlink)

    def release_old_owner() -> None:
        nonlocal releasing_thread_id
        releasing_thread_id = threading.get_ident()
        try:
            store.release_lock(RUN_ID)
        except BaseException as exc:
            errors.append(exc)

    def replace_owner() -> None:
        replacement_entered.set()
        try:
            other_store.release_lock(RUN_ID)
            other_store.acquire_lock("new-owner", pid=5678, started_at=STARTED_AT)
        except BaseException as exc:
            errors.append(exc)
        finally:
            replacement_done.set()

    old_thread = threading.Thread(target=release_old_owner)
    replacement_thread = threading.Thread(target=replace_owner)
    old_thread.start()
    assert old_release_paused.wait(timeout=5)
    replacement_thread.start()
    assert replacement_entered.wait(timeout=5)
    replacement_was_serialized = not replacement_done.wait(timeout=0.2)
    allow_old_release.set()
    old_thread.join(timeout=5)
    replacement_thread.join(timeout=5)

    assert replacement_was_serialized
    assert errors == []
    assert store.read_lock() is not None
    assert store.read_lock().run_id == "new-owner"


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


def test_reconcile_checks_pid_without_holding_directory_lock(
    store: ArtifactStore,
    strategy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_run(store, strategy_file)
    expected_lock = store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)
    real_flock = artifact_store_module.fcntl.flock
    directory_lock_held = False
    checker_observed_lock_state: list[bool] = []

    def track_flock(descriptor: int, operation: int) -> Any:
        nonlocal directory_lock_held
        result = real_flock(descriptor, operation)
        if operation == artifact_store_module.fcntl.LOCK_EX:
            directory_lock_held = True
        elif operation == artifact_store_module.fcntl.LOCK_UN:
            directory_lock_held = False
        return result

    def pid_exists(_pid: int) -> bool:
        checker_observed_lock_state.append(directory_lock_held)
        return True

    monkeypatch.setattr(artifact_store_module.fcntl, "flock", track_flock)

    assert store.reconcile_stale_lock(pid_exists=pid_exists) == expected_lock
    assert checker_observed_lock_state == [False]


def test_reconcile_revalidates_lock_after_pid_check(
    store: ArtifactStore,
    strategy_file: Path,
) -> None:
    _create_run(store, strategy_file)
    store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)
    replacement = {
        "run_id": "replacement-run",
        "pid": 5678,
        "started_at": STARTED_AT,
    }

    def replace_owner(_pid: int) -> bool:
        store.lock_path.unlink()
        store.lock_path.write_text(json.dumps(replacement), encoding="utf-8")
        return False

    reconciled = store.reconcile_stale_lock(pid_exists=replace_owner)

    assert reconciled is not None
    assert reconciled.run_id == "replacement-run"
    assert store.read_run(RUN_ID)["status"] == "running"
    assert json.loads(store.lock_path.read_text(encoding="utf-8")) == replacement


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


@pytest.mark.parametrize(
    "damaged_record",
    [
        {},
        {"run_id": "different-run", "status": "running", "started_at": STARTED_AT},
        {"run_id": RUN_ID, "status": "unknown", "started_at": STARTED_AT},
        {"run_id": RUN_ID, "started_at": STARTED_AT},
        {"run_id": RUN_ID, "status": "running", "started_at": "different-time"},
    ],
)
def test_reconcile_damaged_run_identity_fails_closed_and_keeps_lock(
    store: ArtifactStore,
    strategy_file: Path,
    damaged_record: dict[str, object],
) -> None:
    _create_run(store, strategy_file)
    store.run_paths(RUN_ID).run_json.write_text(
        json.dumps(damaged_record),
        encoding="utf-8",
    )
    expected_lock = store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    with pytest.raises(ValueError, match="^BACKTEST_RUN_RECORD_INVALID$"):
        store.reconcile_stale_lock(pid_exists=lambda _pid: False)

    assert store.read_lock() == expected_lock


@pytest.mark.parametrize("damage", ["missing", "invalid-utf8"])
def test_reconcile_unreadable_run_record_fails_closed_and_keeps_lock(
    store: ArtifactStore,
    strategy_file: Path,
    damage: str,
) -> None:
    _create_run(store, strategy_file)
    run_json = store.run_paths(RUN_ID).run_json
    if damage == "missing":
        run_json.unlink()
    else:
        run_json.write_bytes(b"\xff")
    expected_lock = store.acquire_lock(RUN_ID, pid=1234, started_at=STARTED_AT)

    with pytest.raises(ValueError, match="^BACKTEST_RUN_RECORD_INVALID$"):
        store.reconcile_stale_lock(pid_exists=lambda _pid: False)

    assert store.read_lock() == expected_lock
