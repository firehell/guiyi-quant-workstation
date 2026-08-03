"""Engineering entrypoint tests without retired orchestration dependencies."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENG = REPO_ROOT / "scripts" / "engineering"
WORKTREE_FLOW = ENG / "worktree_flow.py"
RELEASE_FLOW = ENG / "release-flow.sh"


def run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=merged,
        capture_output=True,
        text=True,
    )


def test_preflight_exits_zero_json() -> None:
    result = run(["bash", str(ENG / "preflight.sh"), "--json"])
    assert result.returncode == 0, result.stderr
    assert '"tool": "scripts/engineering/preflight.sh"' in result.stdout
    assert "branch_not_main" in result.stdout
    # Never dump env secret values
    assert "PASSWORD=" not in result.stdout
    assert "TOKEN=" not in result.stdout


def test_preflight_strict_fails_on_main_or_dirty(tmp_path: Path) -> None:
    # On this feature branch with clean worktree, --strict should pass branch check.
    # Simulate dirty tree by creating an untracked file then restoring.
    marker = REPO_ROOT / ".engineering_preflight_dirty_probe"
    try:
        marker.write_text("probe\n", encoding="utf-8")
        result = run(["bash", str(ENG / "preflight.sh"), "--strict", "--json"])
        assert result.returncode != 0
        assert "dirty_worktree" in result.stdout
        assert result.stdout.count('"status": "failed"') >= 1
    finally:
        if marker.exists():
            marker.unlink()


def test_preflight_ci_skips_branch_gate_but_fails_dirty() -> None:
    # Branch gate is skipped under --ci even if the worktree is already dirty
    # from local edits; dirty remains a hard fail.
    result = run(["bash", str(ENG / "preflight.sh"), "--ci", "--json"])
    payload = json.loads(result.stdout)
    assert payload.get("ci") is True
    assert payload.get("strict") is False
    branch = next(c for c in payload["checks"] if c["name"] == "branch_not_main")
    assert branch["status"] == "passed"
    assert "ci mode" in branch["detail"]

    dirty_check = next(c for c in payload["checks"] if c["name"] == "dirty_worktree")
    if dirty_check["status"] == "failed":
        assert result.returncode != 0
        return

    assert result.returncode == 0, result.stderr + result.stdout
    marker = REPO_ROOT / ".engineering_preflight_ci_dirty_probe"
    try:
        marker.write_text("probe\n", encoding="utf-8")
        dirty = run(["bash", str(ENG / "preflight.sh"), "--ci", "--json"])
        assert dirty.returncode != 0
        assert "dirty_worktree" in dirty.stdout
        assert '"status": "failed"' in dirty.stdout
    finally:
        if marker.exists():
            marker.unlink()


def test_preflight_rejects_strict_and_ci_together() -> None:
    result = run(["bash", str(ENG / "preflight.sh"), "--strict", "--ci"])
    assert result.returncode == 2
    assert "mutually exclusive" in (result.stderr + result.stdout)


def test_preflight_strict_rejects_develop_but_ci_allows_it(tmp_path: Path) -> None:
    """Direct edits in the integration branch must be rejected locally."""
    repo = tmp_path / "repo"
    script_dir = repo / "scripts" / "engineering"
    script_dir.mkdir(parents=True)
    target = script_dir / "preflight.sh"
    shutil.copy2(ENG / "preflight.sh", target)
    target.chmod(0o755)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "Engineering tests")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    git("checkout", "-b", "develop")

    strict = subprocess.run(
        ["bash", str(target), "--strict", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert strict.returncode != 0
    strict_payload = json.loads(strict.stdout)
    protected = next(c for c in strict_payload["checks"] if c["name"] == "branch_not_protected")
    assert protected["status"] == "failed"
    assert "develop" in protected["detail"]

    ci = subprocess.run(
        ["bash", str(target), "--ci", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert ci.returncode == 0, ci.stderr + ci.stdout
    ci_payload = json.loads(ci.stdout)
    protected = next(c for c in ci_payload["checks"] if c["name"] == "branch_not_protected")
    assert protected["status"] == "passed"


def test_worktree_flow_creates_and_cleans_merged_task_worktree(tmp_path: Path) -> None:
    """A clean task branch may be removed only after develop contains its HEAD."""
    repo = tmp_path / "repo"
    trees = tmp_path / "trees"
    repo.mkdir()
    trees.mkdir()

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "Engineering tests")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    git("branch", "develop")

    create = subprocess.run(
        [
            "python3", str(WORKTREE_FLOW), "task-create", "--apply", "--json",
            "--repo", str(repo), "--worktree-root", str(trees), "--base-ref", "develop",
            "--kind", "docs", "--task-id", "WS-001", "--slug", "governance",
        ],
        capture_output=True,
        text=True,
    )
    assert create.returncode == 0, create.stderr + create.stdout
    payload = json.loads(create.stdout)
    task_path = Path(payload["bound_facts"]["task_path"])
    task_branch = payload["bound_facts"]["task_branch"]
    assert task_path.is_dir()
    assert task_branch == "docs/WS-001-governance"

    git("checkout", "develop")
    git("merge", "--ff-only", task_branch)
    cleanup = subprocess.run(
        [
            "python3", str(WORKTREE_FLOW), "task-cleanup", "--apply", "--json",
            "--repo", str(repo), "--worktree-root", str(trees), "--integration-branch", "develop",
            "--task-path", str(task_path),
        ],
        capture_output=True,
        text=True,
    )
    assert cleanup.returncode == 0, cleanup.stderr + cleanup.stdout
    assert not task_path.exists()
    assert subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{task_branch}"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).returncode != 0


# --- release-flow ----------------------------------------------------------


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    develop_tree = tmp_path / "develop"
    script_dir = repo / "scripts" / "engineering"
    script_dir.mkdir(parents=True)
    target = script_dir / "release-flow.sh"
    shutil.copy2(RELEASE_FLOW, target)
    target.chmod(0o755)

    def git(*args: str, cwd: Path = repo) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "Engineering tests")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture")
    sha = git("rev-parse", "HEAD").stdout.strip()
    git("branch", "develop")
    git("worktree", "add", str(develop_tree), "develop")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    git("remote", "add", "origin", str(remote))
    return repo, remote, develop_tree, sha


def test_release_flow_is_hash_bound_and_dry_run_by_default(tmp_path: Path) -> None:
    repo, remote, _develop_tree, sha = _release_fixture(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "engineering" / "release-flow.sh"), "publish", "--expected-sha", sha, "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["bound_facts"]["expected_sha"] == sha
    assert subprocess.run(["git", "--git-dir", str(remote), "show-ref"], capture_output=True, text=True).returncode != 0


def test_release_flow_atomically_publishes_matching_main_and_develop(tmp_path: Path) -> None:
    repo, remote, _develop_tree, sha = _release_fixture(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "engineering" / "release-flow.sh"), "publish", "--expected-sha", sha, "--apply", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "apply"
    refs = subprocess.run(
        ["git", "--git-dir", str(remote), "show-ref", "--heads"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert f"{sha} refs/heads/main" in refs
    assert f"{sha} refs/heads/develop" in refs
    assert subprocess.run(
        ["git", "config", "--get", "branch.develop.merge"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip() == "refs/heads/develop"


def test_release_flow_rejects_divergent_protected_branches(tmp_path: Path) -> None:
    repo, remote, develop_tree, sha = _release_fixture(tmp_path)
    (develop_tree / "CHANGELOG.md").write_text("diverged\n", encoding="utf-8")
    subprocess.run(["git", "add", "CHANGELOG.md"], cwd=develop_tree, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "diverge"], cwd=develop_tree, check=True, capture_output=True, text=True)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "engineering" / "release-flow.sh"), "publish", "--expected-sha", sha, "--apply"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "develop does not match" in result.stderr
    assert subprocess.run(["git", "--git-dir", str(remote), "show-ref"], capture_output=True, text=True).returncode != 0


# --- check-secrets ---------------------------------------------------------


def test_check_secrets_clean_repo_passes() -> None:
    result = run(["bash", str(ENG / "check-secrets.sh")])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no high-confidence secrets found" in result.stdout


def test_check_secrets_fake_token_fails(tmp_path: Path) -> None:
    secret = "ghp_" + ("A" * 36)
    fixture = tmp_path / "leak.env"
    fixture.write_text(f"# leaked pat\nexport GH={secret}\n", encoding="utf-8")
    result = run(["bash", str(ENG / "check-secrets.sh"), "--path", str(fixture)])
    assert result.returncode == 1
    assert "family=" in result.stdout
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_check_secrets_markdown_webhook_fails(tmp_path: Path) -> None:
    key = "abcdefghijklmnopqrstuvwxyz012345"
    webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    fixture = tmp_path / "notes.md"
    fixture.write_text(f"# ops\nwebhook: {webhook}\n", encoding="utf-8")
    result = run(["bash", str(ENG / "check-secrets.sh"), "--path", str(fixture)])
    assert result.returncode == 1
    assert "family=wechat_webhook" in result.stdout
    assert key not in result.stdout
    assert webhook not in result.stdout


def test_check_secrets_output_omits_secret_value(tmp_path: Path) -> None:
    value = "SuperSecretValue999999"
    fixture = tmp_path / "cfg.txt"
    fixture.write_text(f'API_KEY="{value}"\n', encoding="utf-8")
    result = run(["bash", str(ENG / "check-secrets.sh"), "--path", str(fixture)])
    assert result.returncode == 1
    assert value not in result.stdout
    assert value not in result.stderr
    assert "family=secret_assignment" in result.stdout


def test_check_secrets_placeholder_passes(tmp_path: Path) -> None:
    fixture = tmp_path / "ok.env"
    fixture.write_text(
        "\n".join(
            [
                'API_KEY="replace-with-your-key-here-xx"',
                'PASSWORD="${DB_PASSWORD}"',
                'TOKEN = os.getenv("TOKEN")',
                'QYWX_WEBHOOK_URL="https://example.com/placeholder-webhook"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run(["bash", str(ENG / "check-secrets.sh"), "--path", str(fixture)])
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_secrets_warn_only_exits_zero(tmp_path: Path) -> None:
    secret = "ghp_" + ("B" * 36)
    fixture = tmp_path / "leak2.env"
    fixture.write_text(f"# warn-only fixture\n{secret}\n", encoding="utf-8")
    result = run(
        ["bash", str(ENG / "check-secrets.sh"), "--warn-only", "--path", str(fixture)]
    )
    assert result.returncode == 0
    assert "family=" in result.stdout
    assert secret not in result.stdout


# --- test.sh profiles ------------------------------------------------------


def test_test_sh_rejects_unknown_profile() -> None:
    result = run(["bash", str(ENG / "test.sh"), "not-a-real-profile"])
    assert result.returncode == 2
    assert "REJECTED" in result.stderr or "unknown profile" in result.stderr


def test_test_sh_rejects_free_shell_args() -> None:
    result = run(["bash", str(ENG / "test.sh"), "engineering", "git push origin HEAD"])
    assert result.returncode == 2
    assert "REJECTED" in result.stderr or "free-shell" in result.stderr


def test_test_sh_no_bash_c_user_string_path() -> None:
    # Source must not execute user strings via bash -c.
    text = (ENG / "test.sh").read_text(encoding="utf-8")
    assert "bash --noprofile --norc -c" not in text
    assert 'bash -c "$' not in text


def test_test_sh_engineering_profile_smoke() -> None:
    # Avoid recursion: engineering profile runs pytest tests/engineering.
    # Call docs profile instead for a lightweight fixed-profile smoke, plus
    # verify engineering script syntax via bash -n separately.
    syntax = run(["bash", "-n", str(ENG / "test.sh")])
    assert syntax.returncode == 0
    result = run(["bash", str(ENG / "test.sh"), "docs"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "profile=docs" in result.stdout


def test_test_sh_all_safe_has_no_write_actions() -> None:
    text = (ENG / "test.sh").read_text(encoding="utf-8")
    for forbidden in ("git push", "git merge", "confirm-production-write"):
        assert forbidden not in text
    assert "production-write-check.sh" not in text or "must remain deleted" in text
    assert not (ENG / "production-write-check.sh").exists()


def test_test_sh_propagates_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Unknown profile already fails; also verify docs fails if rule missing —
    # here we just assert engineering rejects bad argv with non-zero.
    result = run(["bash", str(ENG / "test.sh")])
    assert result.returncode == 2


# --- runtime-health --------------------------------------------------------


class _HealthHandler(BaseHTTPRequestHandler):
    payload: bytes = b'{"status":"ok","service":"guiyi-quant-api","readonly":true}'
    runtime_payload: bytes = json.dumps(
        {
            "status": "ok",
            "readonly": True,
            "components": {
                "after_market_scheduler": {
                    "status": "disabled",
                    "enabled": False,
                    "last_successful_trading_day": None,
                    "latest_completed_trading_day": None,
                    "latest_eligible_trading_day": None,
                    "archive_lag_trading_days": None,
                    "current_task": None,
                    "last_error_type": None,
                    "last_error_at": None,
                    "retry_count": 0,
                    "scheduler_heartbeat": None,
                    "active_binding_end": None,
                    "active_binding_ends": [],
                    "next_retry_at": None,
                    "authorization_hash": None,
                    "lock_status": None,
                }
            },
        }
    ).encode()
    status_code: int = 200

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/runtime/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.runtime_payload)
            return
        if self.path not in ("/health", "/api/health"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, int, threading.Thread]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def test_runtime_health_good_payload_passes() -> None:
    class H(_HealthHandler):
        payload = b'{"status":"ok","service":"guiyi-quant-api","readonly":true}'

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["readonly"] is True
        assert report["summary"]["failed"] == 0
        statuses = {c["name"]: c["status"] for c in report["checks"]}
        assert statuses["api_health_contract"] == "passed"
    finally:
        server.shutdown()


def test_runtime_health_accepts_json_payload_larger_than_4096_bytes() -> None:
    class H(_HealthHandler):
        runtime_payload = json.dumps(
            {
                **json.loads(_HealthHandler.runtime_payload),
                "bounded_test_padding": "x" * 5000,
            }
        ).encode()

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        statuses = {c["name"]: c["status"] for c in report["checks"]}
        assert statuses["after_market_scheduler_health"] == "passed"
    finally:
        server.shutdown()


def test_runtime_health_rejects_payload_over_one_mebibyte() -> None:
    class H(_HealthHandler):
        runtime_payload = json.dumps(
            {
                **json.loads(_HealthHandler.runtime_payload),
                "bounded_test_padding": "x" * (1024 * 1024),
            }
        ).encode()

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 1
        assert "payload_too_large" in result.stdout
    finally:
        server.shutdown()


def test_runtime_health_missing_readonly_fails() -> None:
    class H(_HealthHandler):
        payload = b'{"status":"ok","service":"guiyi-quant-api"}'

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 1
        assert "readonly_not_true" in result.stdout
        # Top-level tool readonly must not mask API failure
        report = json.loads(result.stdout)
        assert report["readonly"] is True
        assert report["summary"]["failed"] >= 1
    finally:
        server.shutdown()


def test_runtime_health_readonly_false_fails() -> None:
    class H(_HealthHandler):
        payload = b'{"status":"ok","service":"guiyi-quant-api","readonly":false}'

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 1
        assert "readonly_not_true" in result.stdout
    finally:
        server.shutdown()


def test_runtime_health_non_json_fails() -> None:
    class H(_HealthHandler):
        payload = b"OK-NOT-JSON"

    server, port, _ = _serve(H)
    try:
        result = run(
            [
                "bash",
                str(ENG / "runtime-health.sh"),
                "--json",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        )
        assert result.returncode == 1
        assert "non_json" in result.stdout or "failed" in result.stdout
    finally:
        server.shutdown()


def test_runtime_health_port_closed_warn_by_default() -> None:
    # Bind then close to pick a free port that is closed.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    result = run(
        [
            "bash",
            str(ENG / "runtime-health.sh"),
            "--json",
            "--host",
            "127.0.0.1",
            "--port",
            str(closed_port),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["failed"] == 0
    assert report["summary"]["warn"] >= 1


def test_runtime_health_port_closed_strict_fails() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    result = run(
        [
            "bash",
            str(ENG / "runtime-health.sh"),
            "--json",
            "--strict",
            "--host",
            "127.0.0.1",
            "--port",
            str(closed_port),
        ]
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["summary"]["failed"] >= 1


def test_production_write_check_deleted() -> None:
    assert not (ENG / "production-write-check.sh").exists()
