from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import app.alerts.wechat_courier as courier
from app.alerts.wechat_courier import (
    WeChatCourierDependency,
    WeChatCourierError,
    WeChatCourierRunner,
    resolve_wechat_courier_dependency,
)
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
