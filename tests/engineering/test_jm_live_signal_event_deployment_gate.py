from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
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
PACKET_PATH = "/safe/approval.json"
SAFE_FLAGS = {
    "GUIYI_LIVE_RUNTIME_ENABLED": True,
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
    "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
}


def _foundation_artifact() -> dict[str, Any]:
    return {
        "path": "/evidence/s6-final.json",
        "sha256": FOUNDATION_SHA256,
        "receipt": {
            "schema_version": 2,
            "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
            "gate": "JM_EOD_INCREMENTAL_AUTOMATION_READY",
            "status": "completed",
            "runtime_commit": PREVIOUS_COMMIT,
            "database_revision": "20260721_0025",
            "authorization_hash": "9" * 64,
        },
    }


def _launchd(pid: int = 101) -> dict[str, Any]:
    return {
        "label": "com.guiyi.quant-runtime-scheduler",
        "loaded": True,
        "pid": pid,
        "plist_path": "/Users/test/Library/LaunchAgents/com.guiyi.quant-runtime-scheduler.plist",
        "plist_sha256": PLIST_SHA256,
        "program_arguments": ["/bin/bash", "/safe/run-local-service.sh", "scheduler"],
        "project_root": "/runtime",
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
            "commit": TARGET_COMMIT,
            "tree": TARGET_TREE,
            "tracked_clean": True,
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
        },
        "database": {
            "driver": "postgresql+psycopg",
            "identity_sha256": DB_IDENTITY_SHA256,
            "revision": "20260721_0025",
            "read_only": True,
            "rolled_back": True,
        },
        "runtime_environment": {
            "path": "/safe/project.env",
            "flags": dict(SAFE_FLAGS),
        },
        "launchd": _launchd(),
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
        source_probe=lambda _root: deepcopy(_facts()["source_git"]),
        runtime_probe=lambda _root: deepcopy(next(runtime_values)),
        database_probe=lambda: deepcopy(next(database_values)),
        runtime_env_probe=lambda _path: deepcopy(next(environment_values)),
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
        "uv_lock_sha256": UV_SHA256,
    }


def _database() -> dict[str, Any]:
    return deepcopy(_facts()["database"])


def _environment() -> dict[str, Any]:
    return deepcopy(_facts()["runtime_environment"])


def _health(status: str = "ok") -> dict[str, Any]:
    return {"status": status, "scheduler_status": status}


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
                "--packet-out",
                "/packet",
            ],
            fact_collector=lambda **kwargs: collected.append(kwargs),
        )
        == 2
    )
    assert collected == []
    assert json.loads(capsys.readouterr().out)["error_type"] == "sha256_invalid"


def test_source_probe_binds_only_whitelisted_s607_evidence(gate, tmp_path: Path) -> None:
    source = tmp_path / "source"
    manifest = source / "data/manifests/jm_after_market_archive_s607_20260724_deadbeef.csv"
    report = source / "data/reports/jm_eod_incremental_s6_07/run/final.json"
    lock = source / "services/quant-api/uv.lock"
    for path, content in ((manifest, "m"), (report, "r"), (lock, "lock")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    status = f"?? {manifest.relative_to(source)}\0?? {report.relative_to(source)}\0"
    outputs = {
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"): status,
        ("git", "rev-parse", "HEAD"): TARGET_COMMIT + "\n",
        ("git", "rev-parse", "HEAD^{tree}"): TARGET_TREE + "\n",
    }

    facts = gate.probe_source_git(source, command_runner=RecordingRunner(outputs=outputs))

    files = facts["untracked_evidence"]["files"]
    assert [item["path"] for item in files] == sorted(
        [str(manifest.relative_to(source)), str(report.relative_to(source))]
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
        gate.probe_source_git(source, command_runner=runner)


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


def test_collect_facts_delegates_exact_foundation_sha_and_checks_local_ancestry(gate) -> None:
    calls: list[tuple[Path, str]] = []
    runner = RecordingRunner()
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root: deepcopy(_facts()["source_git"]),
        runtime_probe=lambda _root: deepcopy(_facts()["runtime"]),
        database_probe=_database,
        runtime_env_probe=lambda _path: _environment(),
        launchd_probe=lambda _label, _root: _launchd(),
        health_probe=_health,
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
        runtime_env=Path("/safe/project.env"),
        dependencies=deps,
    )

    assert calls == [(Path("/evidence/s6-final.json"), FOUNDATION_SHA256)]
    assert result == _facts()
    commands = [call[0] for call in runner.calls]
    assert ("git", "cat-file", "-e", f"{TARGET_COMMIT}^{{commit}}") in commands
    assert ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT) in commands
    assert not any(command[:2] in {("git", "fetch"), ("git", "pull"), ("git", "push")} for command in commands)


def test_collect_facts_rejects_runtime_that_is_not_target_ancestor(gate) -> None:
    ancestry = ("git", "merge-base", "--is-ancestor", PREVIOUS_COMMIT, TARGET_COMMIT)
    runner = RecordingRunner(returncodes={ancestry: 1})
    deps = gate.GateDependencies(
        command_runner=runner,
        source_probe=lambda _root: deepcopy(_facts()["source_git"]),
        runtime_probe=lambda _root: deepcopy(_facts()["runtime"]),
        database_probe=_database,
        runtime_env_probe=lambda _path: _environment(),
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
            runtime_env=Path("/safe/project.env"),
            dependencies=deps,
        )


def test_collect_facts_rejects_foundation_outer_hash_drift(gate) -> None:
    drifted = _foundation_artifact()
    drifted["sha256"] = "c" * 64
    deps = gate.GateDependencies(
        command_runner=RecordingRunner(),
        source_probe=lambda _root: deepcopy(_facts()["source_git"]),
        runtime_probe=lambda _root: deepcopy(_facts()["runtime"]),
        database_probe=_database,
        runtime_env_probe=lambda _path: _environment(),
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
            runtime_env=Path("/safe/project.env"),
            dependencies=deps,
        )


@pytest.mark.parametrize(
    ("mutation", "error_type"),
    [
        (lambda facts: facts["source_git"].update(commit="a" * 40), "source_target_mismatch"),
        (lambda facts: facts["runtime"].update(current_commit="a" * 40), "foundation_runtime_mismatch"),
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
        session_factory=lambda: session,
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


def test_runtime_env_probe_binds_only_three_safe_flags_and_ignores_secrets(gate, tmp_path: Path) -> None:
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=super-secret-password",
                "export GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=0",
                "UNRELATED_TOKEN=token-value",
            ]
        ),
        encoding="utf-8",
    )

    facts = gate.probe_runtime_environment(runtime_env)

    assert facts["flags"] == SAFE_FLAGS
    serialized = json.dumps(facts)
    assert "super-secret-password" not in serialized
    assert "token-value" not in serialized
    assert "POSTGRES_PASSWORD" not in serialized
    assert set(facts) == {"path", "flags"}


def test_launchd_probe_binds_exact_plist_identity_without_other_env_values(gate, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    plist_path = tmp_path / "com.guiyi.quant-runtime-scheduler.plist"
    plist_path.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.guiyi.quant-runtime-scheduler",
                "ProgramArguments": ["/bin/bash", "/safe/run-local-service.sh", "scheduler"],
                "EnvironmentVariables": {
                    "GUIYI_PROJECT_ROOT": str(runtime),
                    "POSTGRES_PASSWORD": "never-output-this",
                },
            }
        )
    )
    runner = RecordingRunner(
        outputs={
            (
                "launchctl",
                "print",
                "gui/501/com.guiyi.quant-runtime-scheduler",
            ): "state = running\npid = 4321\n"
        }
    )

    facts = gate.probe_launchd(
        "com.guiyi.quant-runtime-scheduler",
        runtime,
        command_runner=runner,
        uid=501,
        plist_path=plist_path,
    )

    assert facts["label"] == "com.guiyi.quant-runtime-scheduler"
    assert facts["loaded"] is True
    assert facts["pid"] == 4321
    assert facts["plist_sha256"] == hashlib.sha256(plist_path.read_bytes()).hexdigest()
    assert facts["project_root"] == str(runtime.resolve())
    assert "never-output-this" not in json.dumps(facts)


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
            "/safe/project.env",
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
    packet_out = tmp_path / "packet.json"
    runner = RecordingRunner()
    deps = _dependencies(gate, runner=runner)
    collector_calls: list[dict[str, Any]] = []

    def collect(**kwargs):
        collector_calls.append(kwargs)
        return _facts()

    base = [
        "--runtime-root",
        "/runtime",
        "--s6-final-receipt",
        "/evidence/s6-final.json",
        "--s6-final-receipt-sha256",
        FOUNDATION_SHA256,
        "--runtime-env",
        "/safe/project.env",
    ]
    assert (
        gate.main(
            ["--prepare-deploy-packet", *base, "--packet-out", str(packet_out)],
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
            ["--prepare-deploy-packet", *base, "--packet-out", str(packet_out)],
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
    receipt_out = tmp_path / "deployment.json"
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=[_post_runtime()],
        database_rows=[_database()],
        environment_rows=[_environment()],
        launchd_rows=[_launchd(202)],
        health_rows=[_health()],
    )
    packet = gate.build_deployment_packet(_facts())

    receipt = gate.execute_confirmed_deployment(
        packet=packet,
        approval_hash=packet["packet_hash"],
        current_facts=_facts(),
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
    runtime_rows = [_post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)]
    database_rows = [_database()]
    environment_rows = [_environment()]
    launchd_rows = [_launchd(303)]
    health_rows = [_health()]
    if failure_point == "post_health":
        runtime_rows.insert(0, _post_runtime())
        database_rows.insert(0, _database())
        environment_rows.insert(0, _environment())
        launchd_rows.insert(0, _launchd(202))
        health_rows.insert(0, _health("failed"))
    receipt_out = tmp_path / f"{failure_point}.json"
    deps = _dependencies(
        gate,
        runner=runner,
        runtime_rows=runtime_rows,
        database_rows=database_rows,
        environment_rows=environment_rows,
        launchd_rows=launchd_rows,
        health_rows=health_rows,
    )
    packet = gate.build_deployment_packet(_facts())

    with pytest.raises(gate.DeploymentGateError):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=_facts(),
            receipt_out=receipt_out,
            dependencies=deps,
        )

    commands = [call[0] for call in runner.calls]
    assert rollback_switch in commands
    assert commands.count(kickstart) >= 1
    assert all(
        "com.guiyi.quant-api" not in command
        and "com.guiyi.quant-worker" not in command
        and "com.guiyi.quant-after-market-scheduler" not in command
        for command in commands
    )
    failed = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["rollback"] == {"attempted": True, "succeeded": True}
    serialized = json.dumps(failed)
    assert "do-not-print" not in serialized
    assert "/runtime" not in serialized
    assert "/safe/project.env" not in serialized


def test_rollback_failure_is_fail_closed_and_recorded(gate, tmp_path: Path) -> None:
    target_switch = ("git", "switch", "--detach", TARGET_COMMIT)
    previous_switch = ("git", "switch", "--detach", PREVIOUS_COMMIT)
    runner = RecordingRunner(failures={target_switch: {1}, previous_switch: {1}})
    receipt_out = tmp_path / "rollback-failed.json"
    deps = _dependencies(gate, runner=runner)
    packet = gate.build_deployment_packet(_facts())

    with pytest.raises(gate.DeploymentGateError, match="rollback_failed"):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=_facts(),
            receipt_out=receipt_out,
            dependencies=deps,
        )

    failed = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert failed["error_type"] == "rollback_failed"
    assert failed["rollback"] == {"attempted": True, "succeeded": False}


def test_post_switch_commit_tree_db_flags_launchd_and_health_must_match(gate, tmp_path: Path) -> None:
    packet = gate.build_deployment_packet(_facts())
    cases = [
        (
            [_post_runtime(commit="a" * 40), _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
            [_database(), _database()],
            [_environment(), _environment()],
            [_launchd(202), _launchd(303)],
            [_health(), _health()],
            "post_runtime_identity_invalid",
        ),
        (
            [_post_runtime(), _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
            [{**_database(), "revision": "drift"}, _database()],
            [_environment(), _environment()],
            [_launchd(202), _launchd(303)],
            [_health(), _health()],
            "post_database_drift",
        ),
        (
            [_post_runtime(), _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
            [_database(), _database()],
            [
                {
                    **_environment(),
                    "flags": {**SAFE_FLAGS, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": True},
                },
                _environment(),
            ],
            [_launchd(202), _launchd(303)],
            [_health(), _health()],
            "runtime_flags_unsafe",
        ),
        (
            [_post_runtime(), _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
            [_database(), _database()],
            [_environment(), _environment()],
            [_launchd(101), _launchd(303)],
            [_health(), _health()],
            "scheduler_pid_not_restarted",
        ),
        (
            [_post_runtime(), _post_runtime(commit=PREVIOUS_COMMIT, tree=PREVIOUS_TREE)],
            [_database(), _database()],
            [_environment(), _environment()],
            [_launchd(202), _launchd(303)],
            [_health("failed"), _health()],
            "post_health_failed",
        ),
    ]
    for index, (runtimes, databases, environments, launchds, healths, error_type) in enumerate(cases):
        receipt_out = tmp_path / f"post-{index}.json"
        deps = _dependencies(
            gate,
            runtime_rows=runtimes,
            database_rows=databases,
            environment_rows=environments,
            launchd_rows=launchds,
            health_rows=healths,
        )
        with pytest.raises(gate.DeploymentGateError, match=error_type):
            gate.execute_confirmed_deployment(
                packet=packet,
                approval_hash=packet["packet_hash"],
                current_facts=_facts(),
                receipt_out=receipt_out,
                dependencies=deps,
            )


def test_existing_receipt_blocks_before_any_command(gate, tmp_path: Path) -> None:
    receipt_out = tmp_path / "existing.json"
    receipt_out.write_text("immutable", encoding="utf-8")
    runner = RecordingRunner()
    packet = gate.build_deployment_packet(_facts())

    with pytest.raises(gate.DeploymentGateError, match="output_already_exists"):
        gate.execute_confirmed_deployment(
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=_facts(),
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
    packet = gate.build_deployment_packet(_facts())
    packet_path = tmp_path / "approval.json"
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
        "/safe/project.env",
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
