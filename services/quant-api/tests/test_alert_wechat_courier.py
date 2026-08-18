from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

import app.alerts.wechat_courier as courier
from app.alerts.wechat_courier import (
    WeChatCourierDependency,
    WeChatCourierError,
    WeChatGroupAlertSender,
    WeChatGroupSendSummary,
    WeChatCourierRunner,
    resolve_wechat_courier_dependency,
)
from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage
from app.alerts.wechat_group_config import WeChatGroupTarget


PINNED_COMMIT = "981bd14e238302b2a0e206cb5f28e8e2505bb874"


def _versions_file(tmp_path: Path) -> Path:
    path = tmp_path / "versions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": "bladydora/WeChat-Courier-macOS",
                "commit": PINNED_COMMIT,
            }
        ),
        encoding="utf-8",
    )
    return path


def _dependency_tree(tmp_path: Path) -> Path:
    root = tmp_path / "courier"
    for directory in (
        root / "source/.git",
        root / "runtime",
        root / "tmp",
        root / "cache/clang",
        root / "venv/bin",
    ):
        directory.mkdir(parents=True)
    (root / "source/wechat_courier.py").write_text("# fixture\n", encoding="utf-8")
    python = root / "venv/bin/python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    return root


def _target() -> WeChatGroupTarget:
    return WeChatGroupTarget(
        1,
        "wechat-courier",
        "primary_alert_group",
        "fixture-group-title",
    )


def _message() -> AlertNotificationMessage:
    return AlertNotificationMessage(
        rule_code="htdy_original_15m",
        symbol="ag",
        product_name="白银",
        contract="AG2610",
        frequency="15m",
        bar_end=datetime(2026, 8, 13, 2, 45, tzinfo=UTC),
        result_codes=("buy",),
    )


def test_dependency_resolver_uses_fixed_git_argv_and_exact_clean_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _dependency_tree(tmp_path)
    monkeypatch.setattr(courier, "VERSIONS_FILE", _versions_file(tmp_path))
    calls: list[list[str]] = []

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        stdout = f"{PINNED_COMMIT}\n" if argv[-2:] == ["rev-parse", "HEAD"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "private raw stderr")

    dependency = resolve_wechat_courier_dependency(root, run_process=run_process)

    assert dependency == WeChatCourierDependency(
        root=root.resolve(),
        source_root=(root / "source").resolve(),
        python_executable=(root / "venv/bin/python").resolve(),
        upstream_commit=PINNED_COMMIT,
    )
    assert calls == [
        ["/usr/bin/git", "-C", str(root / "source"), "rev-parse", "HEAD"],
        ["/usr/bin/git", "-C", str(root / "source"), "status", "--porcelain"],
    ]


@pytest.mark.parametrize(
    "failure",
    (
        "missing_root",
        "missing_python",
        "missing_module",
        "wrong_commit",
        "dirty",
        "escaping_source",
    ),
)
def test_dependency_resolver_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root = _dependency_tree(tmp_path)
    monkeypatch.setattr(courier, "VERSIONS_FILE", _versions_file(tmp_path))
    selected_root = root
    if failure == "missing_root":
        selected_root = tmp_path / "absent"
    elif failure == "missing_python":
        (root / "venv/bin/python").unlink()
    elif failure == "missing_module":
        (root / "source/wechat_courier.py").unlink()
    elif failure == "escaping_source":
        outside = tmp_path / "outside-source"
        (root / "source/wechat_courier.py").unlink()
        (root / "source/.git").rmdir()
        (root / "source").rmdir()
        outside.mkdir()
        (outside / ".git").mkdir()
        (outside / "wechat_courier.py").write_text("fixture", encoding="utf-8")
        (root / "source").symlink_to(outside, target_is_directory=True)

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[-2:] == ["rev-parse", "HEAD"]:
            stdout = "0" * 40 if failure == "wrong_commit" else PINNED_COMMIT
        else:
            stdout = " M wechat_courier.py" if failure == "dirty" else ""
        return subprocess.CompletedProcess(argv, 0, f"{stdout}\n", "private")

    with pytest.raises(WeChatCourierError, match="^WECHAT_COURIER_DEPENDENCY_INVALID$"):
        resolve_wechat_courier_dependency(selected_root, run_process=run_process)


def test_runner_uses_fixed_child_argv_stdin_and_exact_environment(tmp_path: Path) -> None:
    root = _dependency_tree(tmp_path)
    dependency = WeChatCourierDependency(
        root.resolve(),
        (root / "source").resolve(),
        (root / "venv/bin/python").resolve(),
        PINNED_COMMIT,
    )
    observed: dict[str, object] = {}

    def run_process(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed["input"] = json.loads(str(kwargs["input"]))
        observed["env"] = kwargs["env"]
        observed["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(argv, 0, '{"status":"verified"}\n', "private")

    WeChatCourierRunner(dependency, run_process=run_process).verify_target(_target())

    assert observed["argv"] == [
        str(dependency.python_executable),
        str(courier.ADAPTER_PATH),
    ]
    assert observed["input"] == {
        "action": "verify",
        "target_chat": "fixture-group-title",
        "upstream_root": str(dependency.source_root),
    }
    assert observed["env"] == {
        "PATH": f"{root.resolve()}/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(root.resolve() / "tmp"),
        "CLANG_MODULE_CACHE_PATH": str(root.resolve() / "cache/clang"),
        "PYTHONUNBUFFERED": "1",
    }
    assert observed["cwd"] == str(dependency.root / "runtime")


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    (
        (1, '{"status":"failed","error_code":"WECHAT_GROUP_TARGET_UNVERIFIED"}'),
        (0, "not-json"),
        (0, '{"status":"verified","extra":true}'),
    ),
)
def test_runner_collapses_child_failure_without_leaking_private_output(
    tmp_path: Path,
    returncode: int,
    stdout: str,
) -> None:
    root = _dependency_tree(tmp_path)
    dependency = WeChatCourierDependency(
        root.resolve(),
        (root / "source").resolve(),
        (root / "venv/bin/python").resolve(),
        PINNED_COMMIT,
    )

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode, stdout, "fixture-group-title raw")

    with pytest.raises(WeChatCourierError) as captured:
        WeChatCourierRunner(dependency, run_process=run_process).verify_target(_target())
    assert "fixture-group-title" not in str(captured.value)


def test_gui_lock_is_nonblocking_and_never_starts_second_child(tmp_path: Path) -> None:
    root = _dependency_tree(tmp_path)
    dependency = WeChatCourierDependency(
        root.resolve(),
        (root / "source").resolve(),
        (root / "venv/bin/python").resolve(),
        PINNED_COMMIT,
    )
    lock_path = root / "runtime/guiyi-wechat-courier.lock"
    holder = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        runner = WeChatCourierRunner(
            dependency,
            run_process=lambda *_args, **_kwargs: pytest.fail(
                "busy sender must not start a child"
            ),
        )
        with pytest.raises(WeChatCourierError, match="^WECHAT_COURIER_BUSY$"):
            runner.send_text(_target(), "fixture-alert")
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)


def test_runner_send_uses_one_child_and_does_not_put_private_text_in_argv(
    tmp_path: Path,
) -> None:
    root = _dependency_tree(tmp_path)
    dependency = WeChatCourierDependency(
        root.resolve(),
        (root / "source").resolve(),
        (root / "venv/bin/python").resolve(),
        PINNED_COMMIT,
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run_process(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, '{"status":"sent"}', "private")

    WeChatCourierRunner(dependency, run_process=run_process).send_text(
        _target(), "fixture-alert"
    )

    assert len(calls) == 1
    assert "fixture-alert" not in " ".join(calls[0][0])
    assert json.loads(str(calls[0][1]["input"])) == {
        "action": "send",
        "target_chat": "fixture-group-title",
        "text": "fixture-alert",
        "upstream_root": str(dependency.source_root),
    }


@pytest.mark.parametrize(
    ("returncode", "stdout", "error_code"),
    (
        (1, '{"status":"failed","error_code":"WECHAT_COURIER_SEND_FAILED"}', "WECHAT_COURIER_SEND_FAILED"),
        (0, "not-json", "WECHAT_COURIER_DEPENDENCY_INVALID"),
        (0, '{"status":"sent","extra":true}', "WECHAT_COURIER_DEPENDENCY_INVALID"),
    ),
)
def test_runner_send_failure_is_single_shot_and_privacy_safe(
    tmp_path: Path,
    returncode: int,
    stdout: str,
    error_code: str,
) -> None:
    root = _dependency_tree(tmp_path)
    dependency = WeChatCourierDependency(
        root.resolve(),
        (root / "source").resolve(),
        (root / "venv/bin/python").resolve(),
        PINNED_COMMIT,
    )
    calls = 0

    def run_process(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, returncode, stdout, "fixture-alert raw")

    with pytest.raises(WeChatCourierError, match=f"^{error_code}$"):
        WeChatCourierRunner(dependency, run_process=run_process).send_text(
            _target(), "fixture-alert"
        )
    assert calls == 1


def test_group_sender_formats_once_and_returns_structured_canary_summary() -> None:
    calls: list[tuple[WeChatGroupTarget, str]] = []

    class Runner:
        def send_text(self, target: WeChatGroupTarget, text: str) -> None:
            calls.append((target, text))

    sender = WeChatGroupAlertSender(target=_target(), runner=Runner())
    sender.send(_message())
    summary = sender.send_canary()

    assert calls == [
        (
            _target(),
            "【归一量化】AG 白银\n\n火天大有 · 买入观察\n主力：AG2610\n15m · 10:45 收线",
        ),
        (_target(), ALERT_CANARY_TEXT),
    ]
    assert summary == WeChatGroupSendSummary(1, 1, 0, ())


def test_group_canary_failure_returns_alias_only_without_retry() -> None:
    calls = 0

    class Runner:
        def send_text(self, _target: WeChatGroupTarget, _text: str) -> None:
            nonlocal calls
            calls += 1
            raise WeChatCourierError("WECHAT_COURIER_SEND_FAILED")

    summary = WeChatGroupAlertSender(target=_target(), runner=Runner()).send_canary()

    assert calls == 1
    assert summary == WeChatGroupSendSummary(1, 0, 1, ("primary_alert_group",))
