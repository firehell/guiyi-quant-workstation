from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "jm_live_signal_event_deployment_gate.py"


def _load_module():
    assert MODULE_PATH.is_file(), "deployment gate script is required"
    spec = importlib.util.spec_from_file_location("jm_live_signal_event_deployment_gate", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_deployment_cli_modes_are_required_and_mutually_exclusive() -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.parse_args([])
    with pytest.raises(SystemExit):
        module.parse_args(["--prepare-deploy-packet", "--verify-deploy-packet"])

    parsed = module.parse_args(["--confirm-deploy"])
    assert isinstance(parsed, argparse.Namespace)
    assert parsed.confirm_deploy is True


@pytest.fixture(scope="module")
def gate():
    return _load_module()


PREVIOUS_COMMIT = "1" * 40
TARGET_COMMIT = "2" * 40
PREVIOUS_TREE = "3" * 40
TARGET_TREE = "4" * 40
UV_SHA256 = "5" * 64
FOUNDATION_SHA256 = "6" * 64
DB_IDENTITY_SHA256 = "7" * 64
PLIST_SHA256 = "8" * 64
RUNNER_SHA256 = "d" * 64
PACKET_PATH = "/safe/approval.json"
SAFE_FLAGS = {
    "GUIYI_LIVE_RUNTIME_ENABLED": True,
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
    "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
}
DATABASE_URL = (
    "postgresql+psycopg://example-user:example-password@db.invalid:5432/example_db"
)


def _foundation_receipt() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "gate": "JM_EOD_INCREMENTAL_AUTOMATION_READY",
        "status": "completed",
        "runtime_commit": PREVIOUS_COMMIT,
        "database_revision": "20260721_0025",
        "authorization_hash": "9" * 64,
        "deployment_lineage": {
            "d1_runtime_commit": "a" * 40,
            "d2_outage_runtime_commit": "b" * 40,
            "deployment_commit": PREVIOUS_COMMIT,
            "runtime_commit": PREVIOUS_COMMIT,
        },
        "d1": {
            "batch_id": "s607_20260722_aaaaaaaa",
            "trading_day": "2026-07-22",
            "runtime_commit": "a" * 40,
        },
        "d2": {
            "batch_id": "s607_20260724_11111111",
            "trading_day": "2026-07-24",
        },
    }


def _foundation_artifact() -> dict[str, Any]:
    return {
        "path": "/evidence/s6-final.json",
        "sha256": FOUNDATION_SHA256,
        "receipt": _foundation_receipt(),
    }


def _launchd(pid: int = 101) -> dict[str, Any]:
    home = Path.home()
    runner_path = home / "Library/Application Support/GuiyiQuant/run-local-service.sh"
    return {
        "label": "com.guiyi.quant-runtime-scheduler",
        "loaded": True,
        "pid": pid,
        "plist_path": str(home / "Library/LaunchAgents/com.guiyi.quant-runtime-scheduler.plist"),
        "plist_sha256": PLIST_SHA256,
        "loaded_program": "/bin/bash",
        "program_arguments": [
            "/bin/bash",
            str(runner_path),
            "scheduler",
        ],
        "environment": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_PROJECT_ROOT": "/runtime",
        },
        "working_directory": str(home),
        "project_root": "/runtime",
        "runner_path": str(runner_path),
        "runner_sha256": RUNNER_SHA256,
    }


def _runtime_lock_facts(
    *,
    runtime_root: str = "/runtime",
    runner_path: str | None = None,
    parent_device: int = 42,
    parent_inode: int = 43,
) -> dict[str, Any]:
    selected_runner = Path(runner_path or _launchd()["runner_path"])
    identity = hashlib.sha256(
        json.dumps(
            {
                "runtime_root": runtime_root,
                "launchd_label": "com.guiyi.quant-runtime-scheduler",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "path": str(
            selected_runner.parent
            / f".s6-08-runtime-deploy-{identity[:24]}.lock"
        ),
        "parent_path": str(selected_runner.parent),
        "parent_device": parent_device,
        "parent_inode": parent_inode,
        "runtime_root": runtime_root,
        "launchd_label": "com.guiyi.quant-runtime-scheduler",
        "identity_sha256": identity,
    }


def _facts() -> dict[str, Any]:
    evidence_files = [
        {
            "path": "data/manifests/jm_after_market_archive_s607_20260724_deadbeef.csv",
            "sha256": "a" * 64,
        }
    ]
    evidence_digest = hashlib.sha256(
        json.dumps(
            evidence_files,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "source_git": {
            "root": "/source",
            "branch": "main",
            "commit": TARGET_COMMIT,
            "local_main": TARGET_COMMIT,
            "origin_main": "0" * 40,
            "ahead_of_origin": 1,
            "tree": TARGET_TREE,
            "tracked_clean": True,
            "git_dir": "/source/.git/worktrees/s608",
            "git_common_dir": "/source/.git",
            "runner_relative_path": "scripts/run-local-service.sh",
            "runner_worktree_sha256": RUNNER_SHA256,
            "runner_target_blob_sha256": RUNNER_SHA256,
            "untracked_evidence": {
                "files": evidence_files,
                "aggregate_sha256": evidence_digest,
            },
            "uv_lock_sha256": UV_SHA256,
        },
        "target_commit": TARGET_COMMIT,
        "runtime": {
            "root": "/runtime",
            "current_commit": PREVIOUS_COMMIT,
            "tree": PREVIOUS_TREE,
            "tracked_clean": True,
            "untracked_executable_clean": True,
            "git_dir": "/runtime/.git/worktrees/runtime",
            "git_common_dir": "/runtime/.git",
            "uv_lock_sha256": UV_SHA256,
        },
        "foundation_receipt": {
            "path": "/evidence/s6-final.json",
            "sha256": FOUNDATION_SHA256,
            "schema_version": 2,
            "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
            "gate": "JM_EOD_INCREMENTAL_AUTOMATION_READY",
            "status": "completed",
            "runtime_commit": PREVIOUS_COMMIT,
            "database_revision": "20260721_0025",
            "authorization_hash": "9" * 64,
            "evidence_scope": {
                "d1_trading_day": "2026-07-22",
                "d2_trading_day": "2026-07-24",
                "lineage_commit_prefixes": ["11111111", "aaaaaaaa", "bbbbbbbb"],
                "d2_batch_id": "s607_20260724_11111111",
            },
        },
        "database": {
            "driver": "postgresql+psycopg",
            "identity_sha256": DB_IDENTITY_SHA256,
            "revision": "20260721_0025",
            "read_only": True,
            "rolled_back": True,
        },
        "runtime_environment": {
            "path": str(Path.home() / "Library/Application Support/GuiyiQuant/project.env"),
            "file_sha256": "e" * 64,
            "device": 42,
            "inode": 43,
            "size": 256,
            "flags": dict(SAFE_FLAGS),
        },
        "launchd": _launchd(),
        "runtime_health": {
            "status": "ok",
            "scheduler_status": "ok",
            "heartbeat_at": "2026-07-24T11:00:00+00:00",
            "last_cycle_status": "idle",
            "signal_events_enabled": False,
            "signal_event_authorization_hash": None,
        },
        "runtime_lock": _runtime_lock_facts(),
        "output_scope": {
            "root": "/approvals/s608",
            "root_device": 42,
            "packet_path": "/approvals/s608/approval.json",
            "packet_device": 42,
            "packet_parent_inode": 43,
            "receipt_path": "/approvals/s608/deployment.json",
            "receipt_device": 42,
            "receipt_parent_inode": 43,
        },
    }


class RecordingRunner:
    def __init__(
        self,
        *,
        outputs: dict[tuple[str, ...], str] | None = None,
        failures: dict[tuple[str, ...], set[int]] | None = None,
        returncodes: dict[tuple[str, ...], int] | None = None,
    ) -> None:
        self.outputs = outputs or {}
        self.failures = failures or {}
        self.returncodes = returncodes or {}
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.counts: dict[tuple[str, ...], int] = {}

    def __call__(self, argv, **kwargs):
        command = tuple(str(item) for item in argv)
        self.calls.append((command, kwargs))
        self.counts[command] = self.counts.get(command, 0) + 1
        if self.counts[command] in self.failures.get(command, set()):
            raise RuntimeError("runner secret=do-not-print")
        return SimpleNamespace(
            stdout=self.outputs.get(command, ""),
            returncode=self.returncodes.get(command, 0),
        )


def _dependencies(
    gate,
    *,
    runner: RecordingRunner | None = None,
    runtime_rows: list[dict[str, Any]] | None = None,
    database_rows: list[dict[str, Any]] | None = None,
    environment_rows: list[dict[str, Any]] | None = None,
    launchd_rows: list[dict[str, Any]] | None = None,
    health_rows: list[dict[str, Any]] | None = None,
    sanitizer=None,
):
    runtime_values = iter(runtime_rows or [])
    database_values = iter(database_rows or [])
    environment_values = iter(environment_rows or [])
    launchd_values = iter(launchd_rows or [])
    health_values = iter(health_rows or [])
    return gate.GateDependencies(
        command_runner=runner or RecordingRunner(),
        source_probe=lambda _root, _foundation: deepcopy(_facts()["source_git"]),
        runtime_probe=lambda _root: deepcopy(next(runtime_values)),
        database_probe=lambda _url: deepcopy(next(database_values)),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=deepcopy(next(environment_values)),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: deepcopy(next(launchd_values)),
        health_probe=lambda: deepcopy(next(health_values)),
        runtime_sanitizer=sanitizer or (lambda _root: None),
        foundation_validator=lambda _path, _sha: deepcopy(_foundation_artifact()),
        uid=501,
    )


def _post_runtime(*, commit: str = TARGET_COMMIT, tree: str = TARGET_TREE) -> dict[str, Any]:
    return {
        "root": "/runtime",
        "current_commit": commit,
        "tree": tree,
        "tracked_clean": True,
        "untracked_executable_clean": True,
        "git_dir": "/runtime/.git/worktrees/runtime",
        "git_common_dir": "/runtime/.git",
        "uv_lock_sha256": UV_SHA256,
    }


def _database() -> dict[str, Any]:
    return deepcopy(_facts()["database"])


def _environment() -> dict[str, Any]:
    return deepcopy(_facts()["runtime_environment"])


def _health(
    status: str = "ok",
    *,
    heartbeat_at: str = "2026-07-24T11:01:00+00:00",
    last_cycle_status: str = "idle",
    signal_events_enabled: bool = False,
    authorization_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "scheduler_status": status,
        "heartbeat_at": heartbeat_at,
        "last_cycle_status": last_cycle_status,
        "signal_events_enabled": signal_events_enabled,
        "signal_event_authorization_hash": authorization_hash,
    }


def test_main_rejects_missing_arguments_and_hash_before_collecting_facts(gate, capsys) -> None:
    collected = []

    assert gate.main(["--prepare-deploy-packet"], fact_collector=lambda **kwargs: collected.append(kwargs)) == 2
    assert collected == []
    assert json.loads(capsys.readouterr().out)["error_type"] == "required_argument_missing"

    assert (
        gate.main(
            [
                "--prepare-deploy-packet",
                "--runtime-root",
                "/runtime",
                "--s6-final-receipt",
                "/receipt",
                "--s6-final-receipt-sha256",
                "NOT-A-HASH",
                "--runtime-env",
                "/env",
                "--output-root",
                "/outputs",
                "--packet-out",
                "/packet",
                "--deployment-receipt-out",
                "/deployment-receipt",
            ],
            fact_collector=lambda **kwargs: collected.append(kwargs),
        )
        == 2
    )
    assert collected == []
    assert json.loads(capsys.readouterr().out)["error_type"] == "sha256_invalid"


def test_source_probe_binds_only_whitelisted_s607_evidence(gate, tmp_path: Path) -> None:
    source = tmp_path / "source"
    manifest = source / "data/manifests/jm_after_market_archive_s607_20260724_11111111.csv"
    reports = [
        source
        / "data/reports/jm_eod_incremental_s6_07/s607_20260724_11111111"
        / f"{name}.json"
        for name in ("completion_receipt", "execution_packet", "final_audit", "quality_gate")
    ]
    lock = source / "services/quant-api/uv.lock"
    source_runner = source / "scripts/run-local-service.sh"
    for path, content in (
        (manifest, "m"),
        *((report, report.name) for report in reports),
        (lock, "lock"),
        (source_runner, "#!/bin/bash\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    evidence_paths = [manifest, *reports]
    status = "".join(f"?? {path.relative_to(source)}\0" for path in evidence_paths)
    outputs = {
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): status,
        ("git", "branch", "--show-current"): "main\n",
        ("git", "rev-parse", "HEAD"): TARGET_COMMIT + "\n",
        ("git", "rev-parse", "refs/heads/main"): TARGET_COMMIT + "\n",
        ("git", "rev-parse", "refs/remotes/origin/main"): PREVIOUS_COMMIT + "\n",
        ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT): "",
        ("git", "rev-list", "--count", f"{PREVIOUS_COMMIT}..{TARGET_COMMIT}"): "1\n",
        ("git", "rev-parse", "HEAD^{tree}"): TARGET_TREE + "\n",
        ("git", "rev-parse", "--git-dir"): str(source / ".git") + "\n",
        ("git", "rev-parse", "--git-common-dir"): str(source / ".git") + "\n",
        ("git", "show", f"{TARGET_COMMIT}:scripts/run-local-service.sh"): "#!/bin/bash\n",
    }

    facts = gate.probe_source_git(
        source,
        foundation_receipt=_foundation_receipt(),
        command_runner=RecordingRunner(outputs=outputs),
    )

    files = facts["untracked_evidence"]["files"]
    assert [item["path"] for item in files] == sorted(
        str(path.relative_to(source)) for path in evidence_paths
    )
    assert files[0]["sha256"] == hashlib.sha256((source / files[0]["path"]).read_bytes()).hexdigest()
    assert facts["untracked_evidence"]["aggregate_sha256"] == gate.canonical_json_sha256(files)
    assert facts["tracked_clean"] is True


@pytest.mark.parametrize(
    ("status", "path", "executable", "error_type"),
    [
        (" M services/quant-api/app/main.py\0", "services/quant-api/app/main.py", False, "source_tracked_not_clean"),
        ("?? scripts/rogue.py\0", "scripts/rogue.py", True, "source_untracked_executable"),
        ("?? notes/outside.txt\0", "notes/outside.txt", False, "source_untracked_path_invalid"),
    ],
)
def test_source_probe_rejects_tracked_or_nonwhitelisted_untracked_files(
    gate,
    tmp_path: Path,
    status: str,
    path: str,
    executable: bool,
    error_type: str,
) -> None:
    source = tmp_path / "source"
    candidate = source / path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("unsafe", encoding="utf-8")
    if executable:
        candidate.chmod(0o755)
    lock = source / "services/quant-api/uv.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("lock", encoding="utf-8")
    runner = RecordingRunner(
        outputs={
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): status,
            ("git", "rev-parse", "HEAD"): TARGET_COMMIT,
            ("git", "rev-parse", "HEAD^{tree}"): TARGET_TREE,
        }
    )

    with pytest.raises(gate.DeploymentGateError, match=error_type):
        gate.probe_source_git(
            source,
            foundation_receipt=_foundation_receipt(),
            command_runner=runner,
        )


def test_runtime_probe_rejects_nonvenv_untracked_executable_but_allows_venv(gate, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    lock = runtime / "services/quant-api/uv.lock"
    venv_python = runtime / "services/quant-api/.venv/bin/python"
    rogue = runtime / "tmp/rogue"
    for path in (lock, venv_python, rogue):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    venv_python.chmod(0o755)
    rogue.chmod(0o755)
    base_outputs = {
        ("git", "rev-parse", "HEAD"): PREVIOUS_COMMIT,
        ("git", "rev-parse", "HEAD^{tree}"): PREVIOUS_TREE,
    }
    allowed = RecordingRunner(
        outputs={
            **base_outputs,
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): (
                "?? services/quant-api/.venv/bin/python\0"
            ),
        }
    )
    facts = gate.probe_runtime_git(runtime, command_runner=allowed)
    assert facts["untracked_executable_clean"] is True

    rejected = RecordingRunner(
        outputs={
            **base_outputs,
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): (
                "?? services/quant-api/.venv/bin/python\0?? tmp/rogue\0"
            ),
        }
    )
    with pytest.raises(gate.DeploymentGateError, match="runtime_untracked_executable"):
        gate.probe_runtime_git(runtime, command_runner=rejected)


def test_collect_facts_delegates_exact_foundation_sha_and_checks_local_ancestry(
    gate,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, str]] = []
    runner = RecordingRunner()
    expected, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root, _foundation: deepcopy(expected["source_git"]),
        runtime_probe=lambda _root: deepcopy(expected["runtime"]),
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=_environment(),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: deepcopy(expected["launchd"]),
        health_probe=lambda: deepcopy(expected["runtime_health"]),
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda path, sha: (
            calls.append((path, sha)) or deepcopy(_foundation_artifact())
        ),
        uid=501,
    )

    result = gate.collect_deployment_bound_facts(
        source_root=Path("/source"),
        runtime_root=Path("/runtime"),
        s6_final_receipt=Path("/evidence/s6-final.json"),
        s6_final_receipt_sha256=FOUNDATION_SHA256,
        runtime_env=Path(_environment()["path"]),
        output_root=Path(expected["output_scope"]["root"]),
        packet_path=packet_path,
        deployment_receipt_path=receipt_path,
        dependencies=deps,
    )

    assert calls == [(Path("/evidence/s6-final.json"), FOUNDATION_SHA256)]
    assert result == expected
    commands = [call[0] for call in runner.calls]
    assert ("git", "cat-file", "-e", f"{TARGET_COMMIT}^{{commit}}") in commands
    assert ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, PREVIOUS_COMMIT) in commands
    assert ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT) in commands
    assert not any(command[:2] in {("git", "fetch"), ("git", "pull"), ("git", "push")} for command in commands)


def test_collect_facts_rejects_runtime_that_is_not_target_ancestor(
    gate,
    tmp_path: Path,
) -> None:
    ancestry = ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT)
    runner = RecordingRunner(returncodes={ancestry: 1})
    expected, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root, _foundation: deepcopy(expected["source_git"]),
        runtime_probe=lambda _root: deepcopy(expected["runtime"]),
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=_environment(),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: _launchd(),
        health_probe=_health,
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda _path, _sha: deepcopy(_foundation_artifact()),
        uid=501,
    )

    with pytest.raises(gate.DeploymentGateError, match="runtime_not_ancestor"):
        gate.collect_deployment_bound_facts(
            source_root=Path("/source"),
            runtime_root=Path("/runtime"),
            s6_final_receipt=Path("/evidence/s6-final.json"),
            s6_final_receipt_sha256=FOUNDATION_SHA256,
            runtime_env=Path(_environment()["path"]),
            output_root=Path(expected["output_scope"]["root"]),
            packet_path=packet_path,
            deployment_receipt_path=receipt_path,
            dependencies=deps,
        )


def test_collect_facts_rejects_foundation_that_is_not_runtime_ancestor(
    gate,
    tmp_path: Path,
) -> None:
    current_commit = "a" * 40
    ancestry = ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, current_commit)
    runner = RecordingRunner(returncodes={ancestry: 1})
    expected, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    expected["runtime"]["current_commit"] = current_commit
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root, _foundation: deepcopy(expected["source_git"]),
        runtime_probe=lambda _root: deepcopy(expected["runtime"]),
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=_environment(),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: _launchd(),
        health_probe=_health,
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda _path, _sha: deepcopy(_foundation_artifact()),
        uid=501,
    )

    with pytest.raises(gate.DeploymentGateError, match="foundation_runtime_not_ancestor"):
        gate.collect_deployment_bound_facts(
            source_root=Path("/source"),
            runtime_root=Path("/runtime"),
            s6_final_receipt=Path("/evidence/s6-final.json"),
            s6_final_receipt_sha256=FOUNDATION_SHA256,
            runtime_env=Path(_environment()["path"]),
            output_root=Path(expected["output_scope"]["root"]),
            packet_path=packet_path,
            deployment_receipt_path=receipt_path,
            dependencies=deps,
        )


def test_collect_facts_rejects_foundation_outer_hash_drift(
    gate,
    tmp_path: Path,
) -> None:
    drifted = _foundation_artifact()
    drifted["sha256"] = "c" * 64
    expected, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    deps = gate.GateDependencies(
        command_runner=RecordingRunner(),
        source_probe=lambda _root, _foundation: deepcopy(expected["source_git"]),
        runtime_probe=lambda _root: deepcopy(expected["runtime"]),
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=_environment(),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: _launchd(),
        health_probe=_health,
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda _path, _sha: deepcopy(drifted),
        uid=501,
    )

    with pytest.raises(gate.DeploymentGateError, match="foundation_receipt_hash_mismatch"):
        gate.collect_deployment_bound_facts(
            source_root=Path("/source"),
            runtime_root=Path("/runtime"),
            s6_final_receipt=Path("/evidence/s6-final.json"),
            s6_final_receipt_sha256=FOUNDATION_SHA256,
            runtime_env=Path(_environment()["path"]),
            output_root=Path(expected["output_scope"]["root"]),
            packet_path=packet_path,
            deployment_receipt_path=receipt_path,
            dependencies=deps,
        )


@pytest.mark.parametrize(
    ("mutation", "error_type"),
    [
        (
            lambda facts: facts["source_git"].update(commit="a" * 40, local_main="a" * 40),
            "source_target_mismatch",
        ),
        (
            lambda facts: facts["foundation_receipt"].update(runtime_commit="not-a-commit"),
            "foundation_receipt_invalid",
        ),
        (lambda facts: facts["runtime"].update(uv_lock_sha256="c" * 64), "dependency_lock_mismatch"),
        (lambda facts: facts["database"].update(revision="old"), "database_revision_invalid"),
        (
            lambda facts: facts["runtime_environment"]["flags"].update(
                GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=True
            ),
            "runtime_flags_unsafe",
        ),
        (lambda facts: facts["launchd"].update(label="com.guiyi.quant-api"), "launchd_identity_invalid"),
        (lambda facts: facts["launchd"].update(loaded=False), "launchd_not_loaded"),
    ],
)
def test_bound_fact_validation_fails_closed_on_identity_drift(gate, mutation, error_type: str) -> None:
    facts = _facts()
    mutation(facts)
    with pytest.raises(gate.DeploymentGateError, match=error_type):
        gate.validate_bound_facts(facts)


def test_bound_fact_validation_accepts_foundation_ancestor_runtime(gate) -> None:
    facts = _facts()
    facts["runtime"]["current_commit"] = "a" * 40

    gate.validate_bound_facts(facts)


def test_collect_database_facts_uses_postgresql_read_only_and_rolls_back(gate) -> None:
    statements: list[str] = []

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def scalar_one_or_none(self):
            return self.value

    class URL:
        drivername = "postgresql+psycopg"
        host = "db.internal"
        port = 5432
        database = "guiyi_quant"

    class Bind:
        url = URL()
        dialect = SimpleNamespace(name="postgresql")

    class Session:
        rolled_back = False
        closed = False

        def get_bind(self):
            return Bind()

        def execute(self, statement):
            statements.append(str(statement))
            if str(statement) == "SHOW transaction_read_only":
                return Result("on")
            return Result("20260721_0025")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = Session()
    facts = gate.collect_database_facts(
        DATABASE_URL,
        session_factory=lambda _database_url: session,
        text_factory=lambda value: value,
    )

    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SHOW transaction_read_only",
        "SELECT version_num FROM alembic_version",
    ]
    assert session.rolled_back is True
    assert session.closed is True
    assert facts["driver"].startswith("postgresql")
    assert facts["identity_sha256"] == hashlib.sha256(
        b"postgresql+psycopg|db.internal|5432|guiyi_quant"
    ).hexdigest()
    assert "db.internal" not in json.dumps(facts)


def test_runtime_env_probe_binds_hash_and_safe_flags_without_serializing_secrets(
    gate,
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "\n".join(
            [
                f"DATABASE_URL={DATABASE_URL}",
                "POSTGRES_PASSWORD=super-secret-password",
                "GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=0",
                "UNRELATED_TOKEN=token-value",
            ]
        ),
        encoding="utf-8",
    )

    result = gate.probe_runtime_environment(runtime_env)
    facts = result.facts

    assert facts["flags"] == SAFE_FLAGS
    serialized = json.dumps(facts)
    assert "super-secret-password" not in serialized
    assert "token-value" not in serialized
    assert "POSTGRES_PASSWORD" not in serialized
    assert set(facts) == {
        "path",
        "file_sha256",
        "device",
        "inode",
        "size",
        "flags",
    }
    assert result.database_url == DATABASE_URL


def test_launchd_probe_binds_exact_plist_identity_without_other_env_values(gate, tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime").resolve()
    runtime.mkdir()
    home = (tmp_path / "home").resolve()
    home.mkdir()
    runner_path = home / "Library/Application Support/GuiyiQuant/run-local-service.sh"
    runner_path.parent.mkdir(parents=True)
    runner_path.write_text("#!/bin/bash\n", encoding="utf-8")
    plist_path = tmp_path / "com.guiyi.quant-runtime-scheduler.plist"
    environment = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "GUIYI_PROJECT_ROOT": str(runtime),
    }
    plist_path.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.guiyi.quant-runtime-scheduler",
                "ProgramArguments": ["/bin/bash", str(runner_path), "scheduler"],
                "WorkingDirectory": str(home),
                "EnvironmentVariables": environment,
            }
        )
    )
    runner = RecordingRunner(
        outputs={
            (
                "launchctl",
                "print",
                "gui/501/com.guiyi.quant-runtime-scheduler",
            ): _launchctl_fixture(
                plist_path=plist_path,
                runner_path=runner_path,
                runtime_root=runtime,
                working_directory=home,
            )
        }
    )

    facts = gate.probe_launchd(
        "com.guiyi.quant-runtime-scheduler",
        runtime,
        command_runner=runner,
        uid=501,
        plist_path=plist_path,
        runner_path=runner_path,
        working_directory=home,
    )

    assert facts["label"] == "com.guiyi.quant-runtime-scheduler"
    assert facts["loaded"] is True
    assert facts["pid"] == 4321
    assert facts["plist_sha256"] == hashlib.sha256(plist_path.read_bytes()).hexdigest()
    assert facts["project_root"] == str(runtime.resolve())
    assert facts["environment"] == environment


def test_build_packet_uses_schema_v1_exact_hash_and_strict_operation_scope(gate) -> None:
    packet = gate.build_deployment_packet(_facts())

    assert packet["schema_version"] == 1
    assert packet["task_id"] == "JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY"
    assert packet["status"] == "approval_required"
    assert packet["writes_authorized"] is False
    assert packet["authorization_mode"] == "exact_packet_hash"
    assert packet["packet_hash"] == gate.canonical_packet_hash(packet)
    assert packet["allowed_operations"] == [
        "runtime_detach_to_approved_commit",
        "purge_non_venv_python_bytecode",
        "kickstart_exact_runtime_scheduler",
        "read_only_post_deployment_verification",
        "create_only_deployment_receipt",
    ]
    serialized_allowed = json.dumps(packet["allowed_operations"])
    assert all(term not in serialized_allowed for term in ("migration", "api", "worker", "eod"))
    assert {
        "database_write",
        "runtime_env_write",
        "signal_event_enable",
        "wechat_or_notification",
        "eod_scheduler",
        "api_restart",
        "worker_restart",
        "repo_fetch_or_push",
    }.issubset(set(packet["forbidden_operations"]))


@pytest.mark.parametrize(
    "path",
    [
        ("foundation_receipt", "sha256"),
        ("source_git", "tree"),
        ("runtime", "tree"),
        ("runtime", "uv_lock_sha256"),
        ("database", "revision"),
        ("runtime_environment", "flags", "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"),
        ("launchd", "plist_sha256"),
    ],
)
def test_verify_packet_rejects_foundation_source_runtime_uv_db_flag_or_launchd_drift(gate, path) -> None:
    packet = gate.build_deployment_packet(_facts())
    current = deepcopy(_facts())
    target = current
    for key in path[:-1]:
        target = target[key]
    leaf = path[-1]
    target[leaf] = not target[leaf] if isinstance(target[leaf], bool) else "drift"

    with pytest.raises(gate.DeploymentGateError, match="bound_fact_drift"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
        )


def test_verify_packet_allows_monotonic_heartbeat_and_safe_cycle_transition(gate) -> None:
    packet = gate.build_deployment_packet(_facts())
    current = deepcopy(_facts())
    current["runtime_health"]["heartbeat_at"] = "2026-07-24T11:01:00+00:00"
    current["runtime_health"]["last_cycle_status"] = "running"

    gate.verify_deployment_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=current,
    )

    current["runtime_health"]["heartbeat_at"] = "2026-07-24T10:59:00+00:00"
    with pytest.raises(gate.DeploymentGateError, match="bound_fact_drift"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
        )

    current["runtime_health"]["heartbeat_at"] = "2026-07-24T11:01:00+00:00"
    current["runtime_health"]["last_cycle_status"] = "lock_busy"
    with pytest.raises(gate.DeploymentGateError, match="runtime_health_invalid"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda facts: facts["runtime_health"].pop(
            "signal_event_authorization_hash"
        ),
        lambda facts: facts["runtime_health"].update({"unexpected": None}),
        lambda facts: facts.update({"unexpected": None}),
    ],
)
def test_verify_packet_rejects_missing_or_added_bound_fact_keys(gate, mutate) -> None:
    packet = gate.build_deployment_packet(_facts())
    current = deepcopy(_facts())
    mutate(current)

    with pytest.raises(gate.DeploymentGateError, match="bound_fact_drift"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
        )


@pytest.mark.parametrize("heartbeat", [None, "invalid", "2026-07-24T11:01:00"])
def test_verify_packet_rejects_missing_invalid_or_naive_heartbeat(
    gate,
    heartbeat,
) -> None:
    packet = gate.build_deployment_packet(_facts())
    current = deepcopy(_facts())
    current["runtime_health"]["heartbeat_at"] = heartbeat

    with pytest.raises(gate.DeploymentGateError, match="bound_fact_drift"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
        )


def test_verify_packet_accepts_same_heartbeat_in_another_timezone(gate) -> None:
    packet = gate.build_deployment_packet(_facts())
    current = deepcopy(_facts())
    current["runtime_health"]["heartbeat_at"] = "2026-07-24T19:00:00+08:00"

    gate.verify_deployment_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=current,
    )


def test_verify_packet_rejects_missing_or_inexact_approval_hash(gate) -> None:
    packet = gate.build_deployment_packet(_facts())
    with pytest.raises(gate.DeploymentGateError, match="approval_hash_invalid"):
        gate.verify_deployment_packet(packet, approval_hash="0" * 64, current_facts=_facts())
    packet["status"] = "completed"
    with pytest.raises(gate.DeploymentGateError, match="packet_identity_invalid"):
        gate.verify_deployment_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=_facts(),
        )


def test_unapproved_cli_never_collects_facts_or_runs_commands(gate, tmp_path: Path, capsys) -> None:
    packet = gate.build_deployment_packet(_facts())
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    runner = RecordingRunner()
    collected = []
    deps = _dependencies(gate, runner=runner)

    result = gate.main(
        [
            "--verify-deploy-packet",
            "--runtime-root",
            "/runtime",
            "--s6-final-receipt",
            "/evidence/s6-final.json",
            "--s6-final-receipt-sha256",
            FOUNDATION_SHA256,
            "--runtime-env",
            str(Path(_environment()["path"])),
            "--output-root",
            str(tmp_path),
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            "0" * 64,
        ],
        dependencies=deps,
        fact_collector=lambda **kwargs: collected.append(kwargs),
    )

    assert result == 2
    assert json.loads(capsys.readouterr().out)["error_type"] == "approval_hash_invalid"
    assert collected == []
    assert runner.calls == []


def test_prepare_and_verify_are_read_only_and_prepare_is_create_only(gate, tmp_path: Path, capsys) -> None:
    facts, packet_out, receipt_out = _output_bound_facts(_facts(), tmp_path)
    runner = RecordingRunner()
    deps = _dependencies(gate, runner=runner)
    collector_calls: list[dict[str, Any]] = []

    def collect(**kwargs):
        collector_calls.append(kwargs)
        return deepcopy(facts)

    base = [
        "--runtime-root",
        "/runtime",
        "--s6-final-receipt",
        "/evidence/s6-final.json",
        "--s6-final-receipt-sha256",
        FOUNDATION_SHA256,
        "--runtime-env",
        str(Path(_environment()["path"])),
        "--output-root",
        facts["output_scope"]["root"],
    ]
    assert (
        gate.main(
            [
                "--prepare-deploy-packet",
                *base,
                "--packet-out",
                str(packet_out),
                "--deployment-receipt-out",
                str(receipt_out),
            ],
            dependencies=deps,
            fact_collector=collect,
        )
        == 0
    )
    packet = json.loads(packet_out.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out)["status"] == "approval_required"
    assert runner.calls == []
    assert (
        gate.main(
            [
                "--verify-deploy-packet",
                *base,
                "--approval-packet",
                str(packet_out),
                "--approval-hash",
                packet["packet_hash"],
            ],
            dependencies=deps,
            fact_collector=collect,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert runner.calls == []
    assert len(collector_calls) == 2
    assert (
        gate.main(
            [
                "--prepare-deploy-packet",
                *base,
                "--packet-out",
                str(packet_out),
                "--deployment-receipt-out",
                str(receipt_out),
            ],
            dependencies=deps,
            fact_collector=collect,
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error_type"] == "output_already_exists"


def test_purge_removes_only_nonvenv_python_artifacts(gate, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    outside_cache = runtime / "services/app/__pycache__"
    outside_pyc = runtime / "services/loose.pyc"
    venv_cache = runtime / "services/quant-api/.venv/lib/python/__pycache__"
    for path in (outside_cache / "x.pyc", outside_pyc, venv_cache / "keep.pyc"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    gate.purge_nonvenv_python_artifacts(runtime)

    assert not outside_cache.exists()
    assert not outside_pyc.exists()
    assert (venv_cache / "keep.pyc").is_file()


def test_confirm_uses_exact_safe_argv_and_writes_success_receipt(gate, tmp_path: Path) -> None:
    runner = RecordingRunner()
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=[_post_runtime(), _post_runtime(), _post_runtime()],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[_launchd_for_facts(facts, 202)],
        health_rows=[_health()],
    )
    packet = gate.build_deployment_packet(facts)

    receipt = gate.execute_confirmed_deployment(
        packet=packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
        receipt_out=receipt_out,
        dependencies=deps,
    )

    commands = [call[0] for call in runner.calls]
    assert commands == [
        ("git", "switch", "--detach", TARGET_COMMIT),
        (
            "launchctl",
            "kickstart",
            "-k",
            "gui/501/com.guiyi.quant-runtime-scheduler",
        ),
    ]
    serialized_calls = json.dumps(commands)
    assert "secret" not in serialized_calls.lower()
    assert "fetch" not in serialized_calls
    assert receipt["status"] == "completed"
    assert receipt["approval_packet_hash"] == packet["packet_hash"]
    assert receipt["previous_commit"] == PREVIOUS_COMMIT
    assert receipt["target_commit"] == TARGET_COMMIT
    assert receipt["scheduler_restart"]["previous_pid"] == 101
    assert receipt["scheduler_restart"]["new_pid"] == 202
    assert receipt["database_unchanged"] is True
    assert receipt["flags_safe"] is True
    assert receipt["rollback"] is False
    assert json.loads(receipt_out.read_text(encoding="utf-8")) == receipt


@pytest.mark.parametrize("failure_point", ["switch", "kickstart", "post_health"])
def test_confirm_failure_rolls_back_only_runtime_scheduler_and_writes_redacted_failure_receipt(
    gate,
    tmp_path: Path,
    failure_point: str,
    monkeypatch,
) -> None:
    switch = ("git", "switch", "--detach", TARGET_COMMIT)
    rollback_switch = ("git", "switch", "--detach", PREVIOUS_COMMIT)
    kickstart = (
        "launchctl",
        "kickstart",
        "-k",
        "gui/501/com.guiyi.quant-runtime-scheduler",
    )
    failures = {}
    if failure_point == "switch":
        failures[switch] = {1}
    elif failure_point == "kickstart":
        failures[kickstart] = {1}
    runner = RecordingRunner(failures=failures)
    if failure_point == "switch":
        runtime_rows = [_post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)]
        database_rows: list[dict[str, Any]] = []
        environment_rows: list[dict[str, Any]] = []
        launchd_rows: list[dict[str, Any]] = []
        health_rows: list[dict[str, Any]] = []
    elif failure_point == "kickstart":
        runtime_rows = [
            _post_runtime(),
            _post_runtime(),
            _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE),
            _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE),
        ]
        database_rows = [_database()]
        environment_rows = [_environment()]
        launchd_pids = [202, 303]
        health_rows = [
            _health(heartbeat_at="2026-07-24T11:01:00+00:00"),
            _health(heartbeat_at="2026-07-24T11:02:00+00:00"),
        ]
    else:
        monkeypatch.setattr(gate, "POST_VERIFY_ATTEMPTS", 1)
        runtime_rows = [
            _post_runtime(),
            _post_runtime(),
            _post_runtime(),
            _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE),
            _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE),
        ]
        database_rows = [_database()]
        environment_rows = [_environment()]
        launchd_pids = [202, 202, 303]
        health_rows = [
            _health("failed"),
            _health(heartbeat_at="2026-07-24T11:01:00+00:00"),
            _health(heartbeat_at="2026-07-24T11:02:00+00:00"),
        ]
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    if failure_point == "switch":
        launchd_rows = []
    else:
        launchd_rows = [
            _launchd_for_facts(facts, pid)
            for pid in launchd_pids
        ]
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=runtime_rows,
        database_rows=database_rows,
        environment_rows=environment_rows,
        launchd_rows=launchd_rows,
        health_rows=health_rows,
    )
    packet = gate.build_deployment_packet(facts)

    with pytest.raises(gate.DeploymentGateError):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=facts,
            receipt_out=receipt_out,
            dependencies=deps,
        )

    commands = [call[0] for call in runner.calls]
    if failure_point == "switch":
        assert rollback_switch not in commands
        assert kickstart not in commands
    else:
        assert rollback_switch in commands
        assert commands.count(kickstart) >= 2
    assert all(
        "com.guiyi.quant-api" not in command
        and "com.guiyi.quant-worker" not in command
        and "com.guiyi.quant-after-market-scheduler" not in command
        for command in commands
    )
    failed = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["rollback"]["attempted"] is (failure_point != "switch")
    assert failed["rollback"]["succeeded"] is (failure_point != "switch")
    if failure_point == "switch":
        assert failed["rollback"]["restart"] == {}
    else:
        assert failed["rollback"]["restart"] == {
            "previous_pid": 202,
            "previous_heartbeat_at": "2026-07-24T11:01:00+00:00",
            "new_pid": 303,
            "new_heartbeat_at": "2026-07-24T11:02:00+00:00",
        }
    serialized = json.dumps(failed)
    assert "do-not-print" not in serialized
    assert "/runtime" not in serialized
    assert "/safe/project.env" not in serialized


def test_rollback_failure_is_fail_closed_and_recorded(gate, tmp_path: Path) -> None:
    kickstart = (
        "launchctl",
        "kickstart",
        "-k",
        "gui/501/com.guiyi.quant-runtime-scheduler",
    )
    previous_switch = ("git", "switch", "--detach", PREVIOUS_COMMIT)
    runner = RecordingRunner(failures={kickstart: {1}, previous_switch: {1}})
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=[_post_runtime(), _post_runtime()],
    )
    packet = gate.build_deployment_packet(facts)

    with pytest.raises(gate.DeploymentGateError, match="rollback_failed"):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=facts,
            receipt_out=receipt_out,
            dependencies=deps,
        )

    failed = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert failed["error_type"] == "rollback_failed"
    assert failed["rollback"] == {
        "attempted": True,
        "succeeded": False,
        "restart": {},
    }


def test_post_switch_commit_tree_db_flags_launchd_and_health_must_match(gate) -> None:
    with pytest.raises(gate.DeploymentGateError, match="post_runtime_identity_invalid"):
        gate._validate_post_runtime(
            _post_runtime(commit="a" * 40),
            expected_commit=TARGET_COMMIT,
            expected_tree=TARGET_TREE,
            expected_uv=UV_SHA256,
        )
    with pytest.raises(gate.DeploymentGateError, match="runtime_flags_unsafe"):
        gate._validate_safe_flags(
            {**SAFE_FLAGS, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": True}
        )
    with pytest.raises(gate.DeploymentGateError, match="scheduler_pid_not_restarted"):
        gate._validate_post_launchd(
            _launchd(101),
            previous=_launchd(101),
            require_new_pid=True,
        )
    with pytest.raises(gate.DeploymentGateError, match="post_health_failed"):
        gate.validate_post_health(
            _health("failed"),
            pre_health=_facts()["runtime_health"],
        )
    deps = _dependencies(
        gate,
        runtime_rows=[_post_runtime(), _post_runtime()],
        database_rows=[{**_database(), "revision": "drift"}],
        environment_rows=[_environment()],
        launchd_rows=[_launchd(202)],
        health_rows=[_health()],
    )
    with pytest.raises(gate.DeploymentGateError, match="post_database_drift"):
        gate._post_deployment_verification(
            facts=_facts(),
            dependencies=deps,
            runtime_root=Path("/runtime"),
        )


def test_existing_receipt_blocks_before_any_command(gate, tmp_path: Path) -> None:
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    receipt_out.write_text("immutable", encoding="utf-8")
    runner = RecordingRunner()
    packet = gate.build_deployment_packet(facts)

    with pytest.raises(gate.DeploymentGateError, match="output_already_exists"):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=facts,
            receipt_out=receipt_out,
            dependencies=_dependencies(gate, runner=runner),
        )

    assert runner.calls == []
    assert receipt_out.read_text(encoding="utf-8") == "immutable"


def test_cli_error_is_bounded_and_redacts_exception_secrets(
    gate,
    capsys,
    tmp_path: Path,
) -> None:
    facts, packet_path, _ = _output_bound_facts(_facts(), tmp_path)
    packet = gate.build_deployment_packet(facts)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    args = [
        "--verify-deploy-packet",
        "--runtime-root",
        "/runtime",
        "--s6-final-receipt",
        "/evidence/s6-final.json",
        "--s6-final-receipt-sha256",
        FOUNDATION_SHA256,
        "--runtime-env",
        str(Path(_environment()["path"])),
        "--output-root",
        facts["output_scope"]["root"],
        "--approval-packet",
        str(packet_path),
        "--approval-hash",
        packet["packet_hash"],
    ]

    assert (
        gate.main(
            args,
            fact_collector=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("postgresql://user:super-secret@host/db /private/runtime")
            ),
        )
        == 2
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload == {"status": "blocked", "error_type": "unexpected_error"}
    assert "super-secret" not in output
    assert "/private/runtime" not in output


def test_task_doc_records_code_only_deployment_gate_boundary() -> None:
    content = (ROOT / "docs/tasks/JM-LIVE-SIGNAL-EVENT-S6-08.md").read_text(encoding="utf-8")

    assert "## Code-only Runtime deployment Gate" in content
    assert "JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY" in content
    assert "不得执行真实 prepare / confirm" in content
    assert "com.guiyi.quant-runtime-scheduler" in content


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_source_repo(tmp_path: Path) -> tuple[Path, str, str]:
    remote = tmp_path / "origin.git"
    subprocess.run(("git", "init", "--bare", str(remote)), check=True, capture_output=True)
    source = tmp_path / "source"
    subprocess.run(("git", "init", "-b", "main", str(source)), check=True, capture_output=True)
    _git(source, "config", "user.email", "tests@example.invalid")
    _git(source, "config", "user.name", "Deployment Gate Tests")
    runner = source / "scripts/run-local-service.sh"
    lock = source / "services/quant-api/uv.lock"
    runner.parent.mkdir(parents=True)
    lock.parent.mkdir(parents=True)
    runner.write_text("#!/bin/bash\nset -eu\n", encoding="utf-8")
    lock.write_text("lock-v1\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "foundation")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    origin_commit = _git(source, "rev-parse", "origin/main")
    (source / "tracked.txt").write_text("local main ahead\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-m", "local main target")
    _write_source_evidence(
        source,
        [
            "data/reports/jm_eod_incremental_s6_07/"
            "s607_20260724_11111111/completion_receipt.json",
            "data/reports/jm_eod_incremental_s6_07/"
            "s607_20260724_11111111/execution_packet.json",
            "data/reports/jm_eod_incremental_s6_07/"
            "s607_20260724_11111111/final_audit.json",
            "data/reports/jm_eod_incremental_s6_07/"
            "s607_20260724_11111111/quality_gate.json",
        ],
    )
    return source, origin_commit, _git(source, "rev-parse", "HEAD")


def test_source_probe_requires_local_main_but_allows_main_ahead_of_origin(
    gate,
    tmp_path: Path,
) -> None:
    source, origin_commit, target_commit = _init_source_repo(tmp_path)

    facts = gate.probe_source_git(
        source,
        foundation_receipt=_foundation_receipt(),
    )

    assert facts["branch"] == "main"
    assert facts["commit"] == target_commit
    assert facts["local_main"] == target_commit
    assert facts["origin_main"] == origin_commit
    assert facts["ahead_of_origin"] == 1
    assert facts["runner_worktree_sha256"] == facts["runner_target_blob_sha256"]
    assert Path(facts["git_dir"]).is_absolute()
    assert Path(facts["git_common_dir"]).is_absolute()

    _git(source, "switch", "-c", "feature/not-deployable")
    with pytest.raises(gate.DeploymentGateError, match="source_branch_invalid"):
        gate.probe_source_git(
            source,
            foundation_receipt=_foundation_receipt(),
        )


def test_source_probe_accepts_only_exact_htdy_step4_branch(
    gate,
    tmp_path: Path,
) -> None:
    source, origin_commit, target_commit = _init_source_repo(tmp_path)
    _git(source, "switch", "-c", gate.HTDY_STEP4_SOURCE_BRANCH)

    facts = gate.probe_source_git(
        source,
        foundation_receipt=_foundation_receipt(),
    )

    assert facts["branch"] == gate.HTDY_STEP4_SOURCE_BRANCH
    assert facts["commit"] == target_commit
    assert facts["local_main"] == target_commit
    assert facts["origin_main"] == origin_commit


def test_htdy_schema_v3_output_scope_is_narrowly_allowed(
    gate,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = (
        source
        / "data/reports/jm_live_signal_event_s6_08/htdy_schema_v3"
        / "20260726-3cfa65a04b2a"
    )
    output.mkdir(parents=True)

    assert gate._is_htdy_schema_v3_output_root(
        output,
        source_root=source,
    )
    assert gate._allowed_source_evidence(
        output.relative_to(source).as_posix()
        + "/deployment_packet.json"
    )
    assert not gate._allowed_source_evidence(
        output.relative_to(source).as_posix() + "/unexpected.py"
    )


def test_source_probe_accepts_complete_d2_evidence_committed_in_target_tree(
    gate,
    tmp_path: Path,
) -> None:
    source, _, _ = _init_source_repo(tmp_path)
    _git(source, "add", "data")
    _git(source, "commit", "-m", "record D2 evidence")

    facts = gate.probe_source_git(
        source,
        foundation_receipt=_foundation_receipt(),
    )

    expected_paths = [
        "data/reports/jm_eod_incremental_s6_07/"
        f"s607_20260724_11111111/{name}.json"
        for name in sorted(("completion_receipt", "execution_packet", "final_audit", "quality_gate"))
    ]
    assert facts["untracked_evidence"]["files"] == []
    assert [item["path"] for item in facts["tracked_evidence"]["files"]] == expected_paths
    assert [item["tracking"] for item in facts["source_evidence"]["files"]] == ["tracked"] * 4


def _write_source_evidence(
    source: Path,
    relative_paths: list[str],
) -> str:
    status: list[str] = []
    for relative in relative_paths:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
        status.append(f"?? {relative}\0")
    return "".join(status)


def test_source_probe_accepts_only_d1_to_d2_lineage_named_evidence_and_full_d2_batch(
    gate,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "services/quant-api").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    (source / "services/quant-api/uv.lock").write_text("lock", encoding="utf-8")
    (source / "scripts/run-local-service.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    names = [
        "data/manifests/jm_after_market_archive_s607_20260722_aaaaaaaa.csv",
        "data/manifests/jm_after_market_archive_s607_20260724_11111111.csv",
        "data/reports/jm_eod_incremental_s6_07/s607_20260723_bbbbbbbb/execution_packet.json",
        "data/reports/jm_eod_incremental_s6_07/s607_20260724_11111111/completion_receipt.json",
        "data/reports/jm_eod_incremental_s6_07/s607_20260724_11111111/execution_packet.json",
        "data/reports/jm_eod_incremental_s6_07/s607_20260724_11111111/final_audit.json",
        "data/reports/jm_eod_incremental_s6_07/s607_20260724_11111111/quality_gate.json",
    ]
    status = _write_source_evidence(source, names)
    outputs = {
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): status,
        ("git", "branch", "--show-current"): "main\n",
        ("git", "rev-parse", "HEAD"): TARGET_COMMIT + "\n",
        ("git", "rev-parse", "refs/heads/main"): TARGET_COMMIT + "\n",
        ("git", "rev-parse", "refs/remotes/origin/main"): PREVIOUS_COMMIT + "\n",
        ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT): "",
        ("git", "rev-list", "--count", f"{PREVIOUS_COMMIT}..{TARGET_COMMIT}"): "1\n",
        ("git", "rev-parse", "HEAD^{tree}"): TARGET_TREE + "\n",
        ("git", "rev-parse", "--git-dir"): str(source / ".git") + "\n",
        ("git", "rev-parse", "--git-common-dir"): str(source / ".git") + "\n",
        ("git", "show", f"{TARGET_COMMIT}:scripts/run-local-service.sh"): "#!/bin/bash\n",
    }

    facts = gate.probe_source_git(
        source,
        foundation_receipt=_foundation_receipt(),
        command_runner=RecordingRunner(outputs=outputs),
    )

    assert [item["path"] for item in facts["untracked_evidence"]["files"]] == sorted(names)


@pytest.mark.parametrize(
    ("relative_paths", "error_type"),
    [
        (
            ["data/manifests/jm_after_market_archive_s607_20260721_aaaaaaaa.csv"],
            "source_evidence_date_invalid",
        ),
        (
            ["data/manifests/jm_after_market_archive_s607_20260723_deadbeef.csv"],
            "source_evidence_lineage_invalid",
        ),
        (
            [
                "data/reports/jm_eod_incremental_s6_07/"
                "s607_20260724_11111111/unexpected.json"
            ],
            "source_evidence_name_invalid",
        ),
        (
            [
                "data/reports/jm_eod_incremental_s6_07/"
                "s607_20260724_11111111/execution_packet.json"
            ],
            "source_d2_evidence_incomplete",
        ),
        (
            [
                "data/reports/jm_eod_incremental_s6_07/"
                "s607_20260723_bbbbbbbb/rogue.py"
            ],
            "source_evidence_name_invalid",
        ),
    ],
)
def test_source_probe_rejects_out_of_window_lineage_extra_type_or_incomplete_d2(
    gate,
    tmp_path: Path,
    relative_paths: list[str],
    error_type: str,
) -> None:
    source = tmp_path / "source"
    (source / "services/quant-api").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    (source / "services/quant-api/uv.lock").write_text("lock", encoding="utf-8")
    (source / "scripts/run-local-service.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    status = _write_source_evidence(source, relative_paths)
    runner = RecordingRunner(
        outputs={
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): status,
            ("git", "branch", "--show-current"): "main\n",
            ("git", "rev-parse", "HEAD"): TARGET_COMMIT,
            ("git", "rev-parse", "refs/heads/main"): TARGET_COMMIT,
            ("git", "rev-parse", "refs/remotes/origin/main"): PREVIOUS_COMMIT,
            ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT): "",
            ("git", "rev-list", "--count", f"{PREVIOUS_COMMIT}..{TARGET_COMMIT}"): "1",
            ("git", "rev-parse", "HEAD^{tree}"): TARGET_TREE,
            ("git", "rev-parse", "--git-dir"): str(source / ".git"),
            ("git", "rev-parse", "--git-common-dir"): str(source / ".git"),
            ("git", "show", f"{TARGET_COMMIT}:scripts/run-local-service.sh"): "#!/bin/bash\n",
        }
    )

    with pytest.raises(gate.DeploymentGateError, match=error_type):
        gate.probe_source_git(
            source,
            foundation_receipt=_foundation_receipt(),
            command_runner=runner,
        )


def _launchctl_fixture(
    *,
    plist_path: Path,
    runner_path: Path,
    runtime_root: Path,
    working_directory: Path,
    extra_environment: str = "",
    loaded_runner_path: Path | None = None,
) -> str:
    loaded_runner = loaded_runner_path or runner_path
    return "\n".join(
        (
            "gui/501/com.guiyi.quant-runtime-scheduler = {",
            f"\tpath = {plist_path}",
            "\tstate = running",
            "\tprogram = /bin/bash",
            "\targuments = {",
            "\t\t/bin/bash",
            f"\t\t{loaded_runner}",
            "\t\tscheduler",
            "\t}",
            f"\tworking directory = {working_directory}",
            "\tenvironment = {",
            "\t\tPATH => /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            f"\t\tGUIYI_PROJECT_ROOT => {runtime_root}",
            extra_environment,
            "\t}",
            "\tpid = 4321",
            "}",
            "",
        )
    )


def test_launchd_probe_uses_loaded_job_identity_and_exact_template_environment(
    gate,
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = (tmp_path / "runtime").resolve()
    runtime.mkdir()
    home = (tmp_path / "home").resolve()
    home.mkdir()
    support = home / "Library/Application Support/GuiyiQuant"
    support.mkdir(parents=True)
    runner_path = support / "run-local-service.sh"
    runner_path.write_text("#!/bin/bash\n", encoding="utf-8")
    plist_path = tmp_path / "com.guiyi.quant-runtime-scheduler.plist"
    environment = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "GUIYI_PROJECT_ROOT": str(runtime),
    }
    plist_path.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.guiyi.quant-runtime-scheduler",
                "ProgramArguments": ["/bin/bash", str(runner_path), "scheduler"],
                "WorkingDirectory": str(home),
                "EnvironmentVariables": environment,
            }
        )
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = print\n"
        "test \"$2\" = gui/501/com.guiyi.quant-runtime-scheduler\n"
        f"printf '%b' {json.dumps(_launchctl_fixture(plist_path=plist_path, runner_path=runner_path, runtime_root=runtime, working_directory=home, extra_environment='\\t\\tXPC_SERVICE_NAME => com.guiyi.quant-runtime-scheduler\\n\\t\\tOSLogRateLimit => 64'))}\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    facts = gate.probe_launchd(
        "com.guiyi.quant-runtime-scheduler",
        runtime,
        uid=501,
        plist_path=plist_path,
        runner_path=runner_path,
        working_directory=home,
    )

    assert facts["loaded_program"] == "/bin/bash"
    assert facts["program_arguments"] == ["/bin/bash", str(runner_path), "scheduler"]
    assert facts["environment"] == environment
    assert facts["working_directory"] == str(home)
    assert facts["runner_path"] == str(runner_path)
    assert facts["runner_sha256"] == hashlib.sha256(runner_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("extra_plist_env", "loaded_runner_name", "extra_loaded_env", "error_type"),
    [
        ({"BASH_ENV": "/unsafe"}, None, "\t\tBASH_ENV => /unsafe", "launchd_environment_invalid"),
        ({}, "other-runner.sh", "", "launchd_loaded_identity_mismatch"),
        ({}, None, "\t\tBASH_ENV => /unsafe", "launchd_loaded_identity_mismatch"),
    ],
)
def test_launchd_probe_rejects_unsafe_env_or_loaded_disk_drift(
    gate,
    tmp_path: Path,
    extra_plist_env: dict[str, str],
    loaded_runner_name: str | None,
    extra_loaded_env: str,
    error_type: str,
) -> None:
    runtime = (tmp_path / "runtime").resolve()
    runtime.mkdir()
    home = (tmp_path / "home").resolve()
    home.mkdir()
    support = home / "Library/Application Support/GuiyiQuant"
    support.mkdir(parents=True)
    runner_path = support / "run-local-service.sh"
    runner_path.write_text("#!/bin/bash\n", encoding="utf-8")
    loaded_runner = runner_path if loaded_runner_name is None else support / loaded_runner_name
    plist_path = tmp_path / "scheduler.plist"
    environment = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "GUIYI_PROJECT_ROOT": str(runtime),
        **extra_plist_env,
    }
    plist_path.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.guiyi.quant-runtime-scheduler",
                "ProgramArguments": ["/bin/bash", str(runner_path), "scheduler"],
                "WorkingDirectory": str(home),
                "EnvironmentVariables": environment,
            }
        )
    )
    output = _launchctl_fixture(
        plist_path=plist_path,
        runner_path=runner_path,
        runtime_root=runtime,
        working_directory=home,
        extra_environment=extra_loaded_env,
        loaded_runner_path=loaded_runner,
    )
    runner = RecordingRunner(
        outputs={
            ("launchctl", "print", "gui/501/com.guiyi.quant-runtime-scheduler"): output
        }
    )

    with pytest.raises(gate.DeploymentGateError, match=error_type):
        gate.probe_launchd(
            "com.guiyi.quant-runtime-scheduler",
            runtime,
            command_runner=runner,
            uid=501,
            plist_path=plist_path,
            runner_path=runner_path,
            working_directory=home,
        )


def test_runtime_env_is_strict_hash_bound_and_returns_database_url_out_of_packet(
    gate,
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "# managed runtime identity",
                f"DATABASE_URL='{DATABASE_URL}'",
                'GUIYI_LIVE_RUNTIME_ENABLED="true"',
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED='0'",
                "APP_ENV=development  # managed comment",
                "VITE_WS_URL=",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = gate.probe_runtime_environment(runtime_env)

    assert result.database_url == DATABASE_URL
    assert result.facts["flags"] == SAFE_FLAGS
    assert result.facts["file_sha256"] == hashlib.sha256(runtime_env.read_bytes()).hexdigest()
    serialized = json.dumps(result.facts)
    assert DATABASE_URL not in serialized
    assert "test-password" not in serialized


@pytest.mark.parametrize(
    ("line", "error_type"),
    [
        ("export GUIYI_LIVE_RUNTIME_ENABLED=true", "runtime_env_syntax_invalid"),
        ("source /tmp/unsafe", "runtime_env_syntax_invalid"),
        ("declare -x GUIYI_LIVE_RUNTIME_ENABLED=true", "runtime_env_syntax_invalid"),
        ("TOKEN=$(id)", "runtime_env_syntax_invalid"),
        ("TOKEN=`id`", "runtime_env_syntax_invalid"),
        ("DATABASE_URL=postgresql://other/db", "runtime_env_duplicate_key"),
    ],
)
def test_runtime_env_rejects_shell_syntax_command_substitution_and_duplicates(
    gate,
    tmp_path: Path,
    line: str,
    error_type: str,
) -> None:
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                f"DATABASE_URL={DATABASE_URL}",
                "GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                line,
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(gate.DeploymentGateError, match=error_type):
        gate.probe_runtime_environment(runtime_env)


def test_database_probe_uses_exact_runtime_env_url_for_read_only_session(gate) -> None:
    seen_urls: list[str] = []

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def scalar_one_or_none(self):
            return self.value

    class URL:
        drivername = "postgresql+psycopg"
        host = "db.internal"
        port = 5432
        database = "guiyi_quant"

    class Session:
        def get_bind(self):
            return SimpleNamespace(url=URL(), dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement):
            return Result("on" if str(statement) == "SHOW transaction_read_only" else "20260721_0025")

        def rollback(self):
            pass

        def close(self):
            pass

    facts = gate.collect_database_facts(
        DATABASE_URL,
        session_factory=lambda database_url: seen_urls.append(database_url) or Session(),
        text_factory=lambda value: value,
    )

    assert seen_urls == [DATABASE_URL]
    assert facts["read_only"] is True
    assert "test-password" not in json.dumps(facts)


def _output_bound_facts(facts: dict[str, Any], tmp_path: Path) -> tuple[dict[str, Any], Path, Path]:
    output_root = tmp_path / "approvals"
    packet_parent = output_root / "packets"
    receipt_parent = output_root / "receipts"
    packet_parent.mkdir(parents=True)
    receipt_parent.mkdir()
    packet_path = packet_parent / "approval.json"
    receipt_path = receipt_parent / "deployment.json"
    device = output_root.stat().st_dev
    runtime_support = tmp_path / "runtime-support"
    runtime_support.mkdir()
    runner = runtime_support / "run-local-service.sh"
    runner.write_text("#!/bin/bash\n", encoding="utf-8")
    facts["launchd"]["runner_path"] = str(runner.resolve())
    facts["launchd"]["program_arguments"][1] = str(runner.resolve())
    support_metadata = runtime_support.stat()
    facts["runtime_lock"] = _runtime_lock_facts(
        runtime_root=str(facts["runtime"]["root"]),
        runner_path=str(runner.resolve()),
        parent_device=int(support_metadata.st_dev),
        parent_inode=int(support_metadata.st_ino),
    )
    facts["output_scope"] = {
        "root": str(output_root.resolve()),
        "root_device": device,
        "packet_path": str(packet_path.resolve()),
        "packet_device": device,
        "packet_parent_inode": int(packet_parent.stat().st_ino),
        "receipt_path": str(receipt_path.resolve()),
        "receipt_device": device,
        "receipt_parent_inode": int(receipt_parent.stat().st_ino),
    }
    return facts, packet_path, receipt_path


def _launchd_for_facts(
    facts: dict[str, Any],
    pid: int,
) -> dict[str, Any]:
    launchd = deepcopy(facts["launchd"])
    launchd["pid"] = pid
    return launchd


def _rebind_runtime_lock(facts: dict[str, Any]) -> None:
    parent = Path(facts["launchd"]["runner_path"]).parent
    metadata = parent.stat()
    facts["runtime_lock"] = _runtime_lock_facts(
        runtime_root=str(facts["runtime"]["root"]),
        runner_path=str(facts["launchd"]["runner_path"]),
        parent_device=int(metadata.st_dev),
        parent_inode=int(metadata.st_ino),
    )


def test_output_scope_binds_existing_external_root_paths_devices_and_parent_inodes(
    gate,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "approvals"
    packet_parent = output_root / "packets"
    receipt_parent = output_root / "receipts"
    packet_parent.mkdir(parents=True)
    receipt_parent.mkdir()
    packet_path = packet_parent / "approval.json"
    receipt_path = receipt_parent / "deployment.json"

    facts = gate.collect_output_scope(
        output_root=output_root,
        packet_path=packet_path,
        receipt_path=receipt_path,
        protected_paths=[
            tmp_path / "source",
            tmp_path / "runtime",
            tmp_path / "runtime-support/project.env",
            tmp_path / "agents/scheduler.plist",
            tmp_path / "runtime-support/run-local-service.sh",
            tmp_path / "source/.git",
        ],
    )

    assert facts["root"] == str(output_root.resolve())
    assert facts["packet_path"] == str(packet_path.resolve())
    assert facts["receipt_path"] == str(receipt_path.resolve())
    assert facts["root_device"] == facts["packet_device"] == facts["receipt_device"]
    assert facts["packet_parent_inode"] == packet_parent.stat().st_ino
    assert facts["receipt_parent_inode"] == receipt_parent.stat().st_ino


@pytest.mark.parametrize("kind", ["source", "runtime", "runtime_env", "plist", "runner", "git"])
def test_output_scope_rejects_overlap_with_code_runtime_identity_or_git_metadata(
    gate,
    tmp_path: Path,
    kind: str,
) -> None:
    protected = {
        "source": tmp_path / "source",
        "runtime": tmp_path / "runtime",
        "runtime_env": tmp_path / "runtime-support/project.env",
        "plist": tmp_path / "agents/scheduler.plist",
        "runner": tmp_path / "runtime-support/run-local-service.sh",
        "git": tmp_path / "source/.git",
    }
    for path in protected.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("protected", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
    output_root = (
        protected[kind]
        if protected[kind].is_dir()
        else protected[kind].parent
    )
    packet_path = output_root / "approval.json"
    receipt_path = output_root / "deployment.json"

    with pytest.raises(gate.DeploymentGateError, match="output_scope_overlap"):
        gate.collect_output_scope(
            output_root=output_root,
            packet_path=packet_path,
            receipt_path=receipt_path,
            protected_paths=list(protected.values()),
        )


def test_runtime_env_cli_path_must_equal_path_derived_from_loaded_launchd(gate, tmp_path: Path) -> None:
    home = tmp_path / "home"
    launchd = _launchd()
    launchd["environment"] = {
        **launchd["environment"],
        "GUIYI_RUNTIME_DIR": str(tmp_path / "managed-runtime"),
    }
    expected = tmp_path / "managed-runtime/project.env"

    resolved = gate.resolve_runtime_environment_path(launchd, home=home)

    assert resolved == expected.resolve()
    gate.validate_runtime_environment_cli_path(expected, launchd, home=home)
    with pytest.raises(gate.DeploymentGateError, match="runtime_env_path_mismatch"):
        gate.validate_runtime_environment_cli_path(tmp_path / "other.env", launchd, home=home)


def test_bound_facts_reject_installed_runner_that_differs_from_target_commit(gate) -> None:
    facts = _facts()
    facts["launchd"]["runner_sha256"] = "f" * 64

    with pytest.raises(gate.DeploymentGateError, match="installed_runner_hash_mismatch"):
        gate.validate_bound_facts(facts)


def test_confirm_existing_receipt_precheck_runs_before_packet_or_fact_commands(
    gate,
    tmp_path: Path,
    capsys,
) -> None:
    output_root = tmp_path / "approvals"
    output_root.mkdir()
    receipt = output_root / "deployment.json"
    receipt.write_text("immutable", encoding="utf-8")
    runner = RecordingRunner()
    collected: list[dict[str, Any]] = []

    result = gate.main(
        [
            "--confirm-deploy",
            "--runtime-root",
            "/runtime",
            "--s6-final-receipt",
            "/evidence/final.json",
            "--s6-final-receipt-sha256",
            FOUNDATION_SHA256,
            "--runtime-env",
            "/Users/test/Library/Application Support/GuiyiQuant/project.env",
            "--output-root",
            str(output_root),
            "--approval-packet",
            str(output_root / "missing-approval.json"),
            "--approval-hash",
            "a" * 64,
            "--deployment-receipt-out",
            str(receipt),
        ],
        dependencies=_dependencies(gate, runner=runner),
        fact_collector=lambda **kwargs: collected.append(kwargs),
    )

    assert result == 2
    assert json.loads(capsys.readouterr().out)["error_type"] == "output_already_exists"
    assert collected == []
    assert runner.calls == []
    assert receipt.read_text(encoding="utf-8") == "immutable"


def test_confirm_rejects_unbound_receipt_path_without_writing_it(
    gate,
    tmp_path: Path,
    capsys,
) -> None:
    facts, packet_path, _ = _output_bound_facts(_facts(), tmp_path)
    packet = gate.build_deployment_packet(facts)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    unbound_receipt = tmp_path / "unbound-deployment.json"
    collected: list[dict[str, Any]] = []

    result = gate.main(
        [
            "--confirm-deploy",
            "--runtime-root",
            "/runtime",
            "--s6-final-receipt",
            "/evidence/final.json",
            "--s6-final-receipt-sha256",
            FOUNDATION_SHA256,
            "--runtime-env",
            str(Path(_environment()["path"])),
            "--output-root",
            facts["output_scope"]["root"],
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            packet["packet_hash"],
            "--deployment-receipt-out",
            str(unbound_receipt),
        ],
        fact_collector=lambda **kwargs: collected.append(kwargs),
    )

    assert result == 2
    assert json.loads(capsys.readouterr().out)["error_type"] == (
        "deployment_receipt_path_mismatch"
    )
    assert collected == []
    assert not unbound_receipt.exists()


def _init_runtime_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    runtime = tmp_path / "runtime"
    subprocess.run(("git", "init", "-b", "main", str(runtime)), check=True, capture_output=True)
    _git(runtime, "config", "user.email", "tests@example.invalid")
    _git(runtime, "config", "user.name", "Deployment Gate Tests")
    runner = runtime / "scripts/run-local-service.sh"
    lock = runtime / "services/quant-api/uv.lock"
    marker = runtime / "marker.txt"
    runner.parent.mkdir(parents=True)
    lock.parent.mkdir(parents=True)
    runner.write_text("#!/bin/bash\n", encoding="utf-8")
    lock.write_text("same-lock\n", encoding="utf-8")
    marker.write_text("previous\n", encoding="utf-8")
    _git(runtime, "add", ".")
    _git(runtime, "commit", "-m", "previous")
    previous = _git(runtime, "rev-parse", "HEAD")
    marker.write_text("target\n", encoding="utf-8")
    _git(runtime, "add", "marker.txt")
    _git(runtime, "commit", "-m", "target")
    target = _git(runtime, "rev-parse", "HEAD")
    marker.write_text("drift\n", encoding="utf-8")
    _git(runtime, "add", "marker.txt")
    _git(runtime, "commit", "-m", "drift")
    drift = _git(runtime, "rev-parse", "HEAD")
    _git(runtime, "switch", "--detach", previous)
    return runtime, previous, target, drift


class SwitchFailureRunner:
    def __init__(self, *, target: str, drift: str, mode: str) -> None:
        self.target = target
        self.drift = drift
        self.mode = mode
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, **kwargs):
        command = tuple(str(item) for item in argv)
        self.calls.append(command)
        if command == ("git", "switch", "--detach", self.target):
            if self.mode == "target":
                subprocess.run(command, **kwargs)
            elif self.mode == "drift":
                subprocess.run(("git", "switch", "--detach", self.drift), **kwargs)
            raise RuntimeError("simulated switch command failure")
        return subprocess.run(command, **kwargs)


@pytest.mark.parametrize(
    ("mode", "expected_error", "rollback_attempted", "expected_head"),
    [
        ("previous", "runtime_switch_failed", False, "previous"),
        ("target", "runtime_switch_failed", True, "previous"),
        ("drift", "runtime_switch_concurrent_drift", False, "drift"),
    ],
)
def test_real_git_switch_failure_rolls_back_only_when_target_is_owned_and_never_kickstarts(
    gate,
    tmp_path: Path,
    mode: str,
    expected_error: str,
    rollback_attempted: bool,
    expected_head: str,
) -> None:
    runtime, previous, target, drift = _init_runtime_repo(tmp_path)
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    facts["target_commit"] = target
    facts["source_git"].update(
        commit=target,
        local_main=target,
        tree=_git(runtime, "rev-parse", f"{target}^{{tree}}"),
        uv_lock_sha256=hashlib.sha256(
            (runtime / "services/quant-api/uv.lock").read_bytes()
        ).hexdigest(),
        runner_worktree_sha256=hashlib.sha256(
            (runtime / "scripts/run-local-service.sh").read_bytes()
        ).hexdigest(),
        runner_target_blob_sha256=hashlib.sha256(
            (runtime / "scripts/run-local-service.sh").read_bytes()
        ).hexdigest(),
    )
    facts["runtime"] = gate.probe_runtime_git(runtime)
    facts["foundation_receipt"]["runtime_commit"] = previous
    facts["launchd"].update(
        project_root=str(runtime.resolve()),
        environment={
            **facts["launchd"]["environment"],
            "GUIYI_PROJECT_ROOT": str(runtime.resolve()),
        },
    )
    runner_sha = facts["source_git"]["runner_target_blob_sha256"]
    facts["launchd"]["runner_sha256"] = runner_sha
    _rebind_runtime_lock(facts)
    runner = SwitchFailureRunner(target=target, drift=drift, mode=mode)
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root, _foundation: deepcopy(facts["source_git"]),
        runtime_probe=lambda root: gate.probe_runtime_git(root),
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=deepcopy(facts["runtime_environment"]),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: deepcopy(facts["launchd"]),
        health_probe=lambda: _health(),
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda _path, _sha: deepcopy(_foundation_artifact()),
        uid=501,
    )
    packet = gate.build_deployment_packet(facts)

    with pytest.raises(gate.DeploymentGateError, match=expected_error):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=facts,
            receipt_out=receipt_out,
            dependencies=deps,
        )

    expected_commit = {"previous": previous, "drift": drift}[expected_head]
    assert _git(runtime, "rev-parse", "HEAD") == expected_commit
    assert not any(command[:2] == ("launchctl", "kickstart") for command in runner.calls)
    failed = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert failed["rollback"]["attempted"] is rollback_attempted


def test_post_verification_polls_until_pid_changes_and_heartbeat_is_strictly_newer(
    gate,
    tmp_path: Path,
    monkeypatch,
) -> None:
    facts, _, receipt_out = _output_bound_facts(_facts(), tmp_path)
    packet = gate.build_deployment_packet(facts)
    runner = RecordingRunner()
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=[_post_runtime(), _post_runtime(), _post_runtime()],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[
            _launchd_for_facts(facts, 101),
            _launchd_for_facts(facts, 202),
            _launchd_for_facts(facts, 202),
        ],
        health_rows=[
            _health(heartbeat_at="2026-07-24T11:00:00+00:00"),
            _health(heartbeat_at="2026-07-24T11:01:00+00:00"),
        ],
    )
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)

    receipt = gate.execute_confirmed_deployment(
        packet=packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
        receipt_out=receipt_out,
        dependencies=deps,
    )

    assert receipt["scheduler_restart"]["new_pid"] == 202
    assert receipt["health"]["heartbeat_at"] == "2026-07-24T11:01:00+00:00"


@pytest.mark.parametrize(
    "health",
    [
        _health(status="failed"),
        _health(last_cycle_status="lock_busy"),
        _health(signal_events_enabled=True),
        _health(authorization_hash="a" * 64),
    ],
)
def test_post_health_requires_status_cycle_lock_safe_flags_and_empty_authorization(
    gate,
    health: dict[str, Any],
) -> None:
    with pytest.raises(gate.DeploymentGateError, match="post_health_failed"):
        gate.validate_post_health(
            health,
            pre_health=_facts()["runtime_health"],
        )


@pytest.mark.parametrize(
    "line",
    [
        "TOKEN=$USER",
        'TOKEN="${USER}"',
        r"TOKEN=escaped\ value",
        " GUIYI_LIVE_RUNTIME_ENABLED=true",
        "GUIYI_LIVE_RUNTIME_ENABLED=true ",
    ],
)
def test_runtime_env_rejects_variable_expansion_escape_and_assignment_whitespace(
    gate,
    tmp_path: Path,
    line: str,
) -> None:
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                f"DATABASE_URL={DATABASE_URL}",
                "GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                line,
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(gate.DeploymentGateError, match="runtime_env_syntax_invalid"):
        gate.probe_runtime_environment(runtime_env)


def test_runtime_env_cli_and_output_subpaths_reject_symlink_aliases(
    gate,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    managed = home / "Library/Application Support/GuiyiQuant"
    managed.mkdir(parents=True)
    actual_env = managed / "project.env"
    actual_env.write_text("DATABASE_URL=postgresql://example.invalid/db\n", encoding="utf-8")
    alias_env = tmp_path / "project-env-link"
    alias_env.symlink_to(actual_env)
    launchd = _launchd()
    launchd["environment"] = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "GUIYI_PROJECT_ROOT": "/runtime",
    }

    with pytest.raises(gate.DeploymentGateError, match="runtime_env_path_mismatch"):
        gate.validate_runtime_environment_cli_path(alias_env, launchd, home=home)

    output_root = tmp_path / "approvals"
    real_parent = output_root / "real"
    real_parent.mkdir(parents=True)
    alias_parent = output_root / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(gate.DeploymentGateError, match="output_parent_invalid"):
        gate.collect_output_scope(
            output_root=output_root,
            packet_path=alias_parent / "approval.json",
            receipt_path=real_parent / "deployment.json",
            protected_paths=[],
        )


def test_approved_packet_rejects_unbound_lock_path_before_lock_creation(gate) -> None:
    packet = gate.build_deployment_packet(_facts())
    packet["bound_facts"]["runtime_lock"]["path"] = "/tmp/unbound.lock"
    packet["packet_hash"] = gate.canonical_packet_hash(packet)

    with pytest.raises(gate.DeploymentGateError, match="deployment_lock_identity_invalid"):
        gate._validate_packet_identity_and_hash(packet, packet["packet_hash"])


def test_post_health_success_still_reprobes_runtime_head_before_acceptance(gate) -> None:
    deps = _dependencies(
        gate,
        runtime_rows=[_post_runtime(), _post_runtime(commit="a" * 40)],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[_launchd(202)],
        health_rows=[_health()],
    )

    with pytest.raises(gate.DeploymentGateError, match="post_runtime_identity_invalid"):
        gate._post_deployment_verification(
            facts=_facts(),
            dependencies=deps,
            runtime_root=Path("/runtime"),
        )


def test_confirm_final_fact_collection_occurs_once_while_persistent_lock_is_held(
    gate,
    tmp_path: Path,
    capsys,
) -> None:
    facts, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    packet = gate.build_deployment_packet(facts)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    calls = 0

    def collect(**_kwargs):
        nonlocal calls
        calls += 1
        with pytest.raises(gate.DeploymentGateError, match="deployment_lock_busy"):
            with gate.deployment_lock(facts["runtime_lock"]):
                pass
        return deepcopy(facts)

    deps = _dependencies(
        gate,
        runtime_rows=[_post_runtime(), _post_runtime(), _post_runtime()],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[_launchd_for_facts(facts, 202)],
        health_rows=[_health()],
    )
    result = gate.main(
        [
            "--confirm-deploy",
            "--runtime-root",
            "/runtime",
            "--s6-final-receipt",
            "/evidence/s6-final.json",
            "--s6-final-receipt-sha256",
            FOUNDATION_SHA256,
            "--runtime-env",
            str(Path(_environment()["path"])),
            "--output-root",
            facts["output_scope"]["root"],
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            packet["packet_hash"],
            "--deployment-receipt-out",
            str(receipt_path),
        ],
        dependencies=deps,
        fact_collector=collect,
    )

    assert result == 0
    assert calls == 1
    assert json.loads(capsys.readouterr().out)["status"] == "deployed"
    assert Path(facts["runtime_lock"]["path"]).is_file()


def test_real_main_source_and_linked_runtime_worktree_collect_without_fetch(
    gate,
    tmp_path: Path,
) -> None:
    source, previous, target = _init_source_repo(tmp_path)
    runtime = tmp_path / "runtime-worktree"
    _git(source, "worktree", "add", "--detach", str(runtime), previous)
    receipt = _foundation_receipt()
    receipt["runtime_commit"] = previous
    receipt["deployment_lineage"].update(
        deployment_commit=previous,
        runtime_commit=previous,
        legacy_evidence_commit=PREVIOUS_COMMIT,
    )
    artifact = {
        "path": "/evidence/s6-final.json",
        "sha256": FOUNDATION_SHA256,
        "receipt": receipt,
    }
    source_runner_sha = hashlib.sha256(
        (source / "scripts/run-local-service.sh").read_bytes()
    ).hexdigest()
    launchd = _launchd()
    launchd.update(
        project_root=str(runtime.resolve()),
        runner_sha256=source_runner_sha,
        environment={
            **launchd["environment"],
            "GUIYI_PROJECT_ROOT": str(runtime.resolve()),
        },
    )
    expected, packet_path, receipt_path = _output_bound_facts(_facts(), tmp_path)
    deps = gate.GateDependencies(
        command_runner=subprocess.run,
        source_probe=lambda root, foundation: gate.probe_source_git(
            root,
            foundation_receipt=foundation,
        ),
        runtime_probe=gate.probe_runtime_git,
        database_probe=lambda _url: _database(),
        runtime_env_probe=lambda _path: gate.RuntimeEnvironmentResult(
            facts=_environment(),
            database_url=DATABASE_URL,
        ),
        launchd_probe=lambda _label, _root: deepcopy(launchd),
        health_probe=lambda: deepcopy(_facts()["runtime_health"]),
        runtime_sanitizer=lambda _root: None,
        foundation_validator=lambda _path, _sha: deepcopy(artifact),
        uid=501,
    )

    facts = gate.collect_deployment_bound_facts(
        source_root=source,
        runtime_root=runtime,
        s6_final_receipt=Path("/evidence/s6-final.json"),
        s6_final_receipt_sha256=FOUNDATION_SHA256,
        runtime_env=Path(_environment()["path"]),
        output_root=Path(expected["output_scope"]["root"]),
        packet_path=packet_path,
        deployment_receipt_path=receipt_path,
        dependencies=deps,
    )

    assert facts["target_commit"] == target
    assert facts["source_git"]["origin_main"] == previous
    assert facts["source_git"]["ahead_of_origin"] == 1
    assert facts["runtime"]["current_commit"] == previous
    assert facts["runtime"]["git_dir"] != facts["runtime"]["git_common_dir"]


def _managed_launchd_identity(
    tmp_path: Path,
    *,
    runtime_root: Path,
    pid: int = 101,
) -> dict[str, Any]:
    support = tmp_path / "Library/Application Support/GuiyiQuant"
    support.mkdir(parents=True, exist_ok=True)
    runner = support / "run-local-service.sh"
    runner.write_text("#!/bin/bash\n", encoding="utf-8")
    launchd = _launchd(pid)
    launchd.update(
        project_root=str(runtime_root.resolve()),
        runner_path=str(runner.resolve()),
        program_arguments=["/bin/bash", str(runner.resolve()), "scheduler"],
        environment={
            **launchd["environment"],
            "GUIYI_PROJECT_ROOT": str(runtime_root.resolve()),
        },
        runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
    )
    return launchd


def test_runtime_global_lock_is_identical_across_two_output_roots_and_mutually_exclusive(
    gate,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    launchd = _managed_launchd_identity(tmp_path, runtime_root=runtime)
    first_output = tmp_path / "approvals-a"
    second_output = tmp_path / "approvals-b"
    first_output.mkdir()
    second_output.mkdir()

    first_output_scope = gate.collect_output_scope(
        output_root=first_output,
        packet_path=first_output / "approval.json",
        receipt_path=first_output / "deployment.json",
        protected_paths=[],
    )
    second_output_scope = gate.collect_output_scope(
        output_root=second_output,
        packet_path=second_output / "approval.json",
        receipt_path=second_output / "deployment.json",
        protected_paths=[],
    )
    first = gate.collect_runtime_lock_scope(runtime_root=runtime, launchd=launchd)
    second = gate.collect_runtime_lock_scope(runtime_root=runtime, launchd=launchd)

    assert first_output_scope["root"] != second_output_scope["root"]
    assert first == second
    assert Path(first["path"]).parent == Path(launchd["runner_path"]).parent
    assert not Path(first["path"]).is_relative_to(runtime)
    with gate.deployment_lock(first):
        with pytest.raises(gate.DeploymentGateError, match="deployment_lock_busy"):
            with gate.deployment_lock(second):
                pass


def test_runtime_global_lock_rejects_symlink_target(
    gate,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    launchd = _managed_launchd_identity(tmp_path, runtime_root=runtime)
    scope = gate.collect_runtime_lock_scope(runtime_root=runtime, launchd=launchd)
    target = tmp_path / "attacker.lock"
    target.write_text("attacker", encoding="utf-8")
    Path(scope["path"]).symlink_to(target)

    with pytest.raises(gate.DeploymentGateError, match="deployment_lock_invalid"):
        with gate.deployment_lock(scope):
            pass

    assert target.read_text(encoding="utf-8") == "attacker"


def test_runtime_env_parse_and_sha_use_one_nofollow_descriptor_despite_path_replacement(
    gate,
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_env = tmp_path / "project.env"
    original = "\n".join(
        (
            f"DATABASE_URL={DATABASE_URL}",
            "GUIYI_LIVE_RUNTIME_ENABLED=true",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
            "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
        )
    ).encode()
    replacement = original.replace(
        b"GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
        b"GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true",
    )
    runtime_env.write_bytes(original)
    replacement_path = tmp_path / "replacement.env"
    replacement_path.write_bytes(replacement)
    original_inode = runtime_env.stat().st_ino
    real_read = gate.os.read
    replaced = False

    def replacing_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        data = real_read(descriptor, size)
        if data and not replaced:
            replaced = True
            os.replace(replacement_path, runtime_env)
        return data

    monkeypatch.setattr(gate.os, "read", replacing_read)

    result = gate.probe_runtime_environment(runtime_env)

    assert result.database_url == DATABASE_URL
    assert result.facts["flags"] == SAFE_FLAGS
    assert result.facts["file_sha256"] == hashlib.sha256(original).hexdigest()
    assert result.facts["inode"] == original_inode
    assert result.facts["inode"] != runtime_env.stat().st_ino


@pytest.mark.parametrize(
    ("field", "mutator"),
    [
        ("runner_sha256", lambda value: value.update(runner_sha256="f" * 64)),
        ("environment", lambda value: value["environment"].update(PATH="/unsafe")),
        ("working_directory", lambda value: value.update(working_directory="/other")),
        ("loaded_program", lambda value: value.update(loaded_program="/bin/zsh")),
        ("runner_path", lambda value: value.update(runner_path="/other/runner.sh")),
        ("plist_path", lambda value: value.update(plist_path="/other/agent.plist")),
        ("plist_sha256", lambda value: value.update(plist_sha256="f" * 64)),
        (
            "program_arguments",
            lambda value: value.update(
                program_arguments=["/bin/bash", value["runner_path"], "other"]
            ),
        ),
        ("project_root", lambda value: value.update(project_root="/other/runtime")),
    ],
)
def test_post_launchd_revalidates_every_loaded_identity_field(
    gate,
    field: str,
    mutator,
) -> None:
    previous = _launchd(101)
    current = _launchd(202)
    mutator(current)

    with pytest.raises(gate.DeploymentGateError, match="post_launchd_drift"):
        gate._validate_post_launchd(
            current,
            previous=previous,
            require_new_pid=True,
        )


@pytest.mark.parametrize("stale_part", ["pid", "heartbeat"])
def test_rollback_rejects_stale_scheduler_restart_state(
    gate,
    monkeypatch,
    stale_part: str,
) -> None:
    baseline_launchd = _launchd(202)
    baseline_health = _health(heartbeat_at="2026-07-24T11:05:00+00:00")
    launchd = _launchd(202 if stale_part == "pid" else 303)
    health = _health(
        heartbeat_at=(
            "2026-07-24T11:05:00+00:00"
            if stale_part == "heartbeat"
            else "2026-07-24T11:06:00+00:00"
        )
    )
    deps = _dependencies(
        gate,
        runtime_rows=[_post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[launchd, launchd],
        health_rows=[health, health],
    )
    monkeypatch.setattr(gate, "POST_VERIFY_ATTEMPTS", 2)
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        gate.DeploymentGateError,
        match=(
            "scheduler_pid_not_restarted"
            if stale_part == "pid"
            else "post_health_failed"
        ),
    ):
        gate._verify_rollback(
            facts=_facts(),
            dependencies=deps,
            runtime_root=Path("/runtime"),
            restart_launchd=baseline_launchd,
            restart_health=baseline_health,
        )


def _parent_identity(parent: Path) -> tuple[int, int]:
    metadata = parent.stat()
    return int(metadata.st_dev), int(metadata.st_ino)


def test_create_only_receipt_rejects_parent_symlink_race_without_creating_parent(
    gate,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "receipts"
    parent.mkdir()
    device, inode = _parent_identity(parent)
    moved = tmp_path / "receipts-original"
    parent.rename(moved)
    parent.symlink_to(moved, target_is_directory=True)
    receipt = parent / "deployment.json"

    with pytest.raises(gate.DeploymentGateError, match="output_parent_drift"):
        gate.write_json_create_only(
            receipt,
            {"status": "failed"},
            parent_device=device,
            parent_inode=inode,
        )

    assert not (moved / "deployment.json").exists()

    missing = tmp_path / "missing" / "deployment.json"
    with pytest.raises(gate.DeploymentGateError, match="output_parent_invalid"):
        gate.write_json_create_only(
            missing,
            {"status": "failed"},
            parent_device=device,
            parent_inode=inode,
        )
    assert not missing.parent.exists()


def test_create_only_receipt_cleanup_preserves_replacement_inode_after_target_race(
    gate,
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent = tmp_path / "receipts"
    parent.mkdir()
    receipt = parent / "deployment.json"
    device, inode = _parent_identity(parent)

    def replace_target_then_fail(*_args, **_kwargs) -> None:
        receipt.unlink()
        receipt.write_text("attacker replacement", encoding="utf-8")
        raise OSError("simulated serialization failure")

    monkeypatch.setattr(gate.json, "dump", replace_target_then_fail)

    with pytest.raises(OSError, match="serialization failure"):
        gate.write_json_create_only(
            receipt,
            {"status": "completed"},
            parent_device=device,
            parent_inode=inode,
        )

    assert receipt.read_text(encoding="utf-8") == "attacker replacement"
