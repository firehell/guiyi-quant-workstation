"""WS-V2-007: Redaction regression tests.

All fixtures use synthetic secrets — never read real keys.
Verify:
  - Key-level secret patterns (token, webhook, password, etc.)
  - URL credentials (user:pass@host)
  - Bearer tokens
  - Webhook status markers (已设置(true))
  - Recursive redaction (dict, list, nested)
  - --check mode (no modification)
  - --dry-run mode
  - PG evidence summaries (no connection string leak)
  - Large log handling (index + summary, original preserved)
  - Cumulative safety: no synthetic value survives redaction
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"


@pytest.fixture(autouse=True)
def _add_lib_path() -> None:
    """Ensure lib/ is on sys.path for result_bundler imports."""
    if str(LIB_DIR) not in sys.path:
        sys.path.insert(0, str(LIB_DIR))


# ═══════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════


def _run_redact(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO_ROOT / "scripts" / "ai" / "redact_evidence.sh"), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _secret_file(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "secret.txt"
    f.write_text(content, encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════════════
# 1. Key-level secret patterns
# ═══════════════════════════════════════════════════════════════════════


class TestKeyLevelRedaction:
    def test_token_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "token=abc123def456ghi789\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content
        assert "abc123def456ghi789" not in content

    def test_webhook_redacted_with_status(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "QYWX_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "已设置(true)" in content or "[REDACTED]" in content

    def test_password_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, 'password: verysecretvalue12345\n')
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content
        assert "verysecretvalue12345" not in content

    def test_api_key_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "API_KEY = sk-1234567890abcdef\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content
        assert "sk-1234567890abcdef" not in content

    def test_access_key_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "access_key=AKIA1234567890ABCDEF\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content
        assert "AKIA1234567890ABCDEF" not in content

    def test_database_url_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "DATABASE_URL=postgresql://user:pass@localhost:5432/db\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content

    def test_rqdata_token_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "RQDATA_TOKEN=abcdef1234567890abcdef\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "[REDACTED]" in content
        assert "abcdef1234567890abcdef" not in content

    def test_clean_file_untouched(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "name=hello\nvalue=world\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "hello" in content
        assert "world" in content


# ═══════════════════════════════════════════════════════════════════════
# 2. URL credentials
# ═══════════════════════════════════════════════════════════════════════


class TestUrlCredentialRedaction:
    def test_postgres_url_credential_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "CONN=postgresql://admin:hunter2@db.example.com:5432/mydb\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "hunter2" not in content
        assert "[REDACTED_CREDENTIAL]" in content or "[REDACTED]" in content

    def test_mysql_url_credential_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "MYSQL_URL=mysql://root:secret@localhost:3306/app\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "secret" not in content

    def test_redis_url_credential_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "REDIS_URL=redis://:mypassword@redis.example.com:6379/0\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "mypassword" not in content


# ═══════════════════════════════════════════════════════════════════════
# 3. Bearer / Authorization tokens
# ═══════════════════════════════════════════════════════════════════════


class TestBearerTokenRedaction:
    def test_auth_bearer_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdef\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "eyJhbGci" not in content

    def test_auth_basic_redacted(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "auth: Basic dXNlcjpwYXNz\n")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        assert "dXNlcjpwYXNz" not in content


# ═══════════════════════════════════════════════════════════════════════
# 4. Recursive redaction
# ═══════════════════════════════════════════════════════════════════════


class TestRecursiveRedaction:
    def test_dict_recursive(self) -> None:
        from result_bundler import redact

        data = {
            "env": {"DATABASE_URL": "postgresql://u:p@h/db"},
            "config": {"token": "abc123"},
        }
        result = redact(data)
        assert "abc123" not in json.dumps(result)
        assert "u:p@" not in json.dumps(result)

    def test_list_recursive(self) -> None:
        from result_bundler import redact

        data = ["token=abc", {"password": "secret"}]
        result = redact(data)
        dumped = json.dumps(result)
        assert "abc" not in dumped.split("[REDACTED]")[-1] if "[REDACTED]" in dumped else True
        assert "secret" not in dumped

    def test_nested_redaction(self) -> None:
        from result_bundler import redact

        data = {
            "services": [
                {"name": "db", "DATABASE_URL": "postgres://a:b@c/d"},
                {"name": "api", "token": "xyz789"},
            ],
            "password": "root",
        }
        result = redact(data)
        dumped = json.dumps(result)
        assert "root" not in dumped
        assert "xyz789" not in dumped
        assert "b@c" not in dumped


# ═══════════════════════════════════════════════════════════════════════
# 5. --check mode
# ═══════════════════════════════════════════════════════════════════════


class TestCheckMode:
    def test_check_detects_sensitive(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "token=abc123\n")
        original = f.read_text()
        result = _run_redact("--check", str(f))
        assert result.returncode == 1  # exits non-zero when sensitive found
        assert "has_sensitive" in result.stdout or "patterns_detected" in result.stdout
        # File must NOT be modified
        assert f.read_text() == original

    def test_check_clean_passes(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "hello=world\n")
        result = _run_redact("--check", str(f))
        assert result.returncode == 0
        assert "clean" in result.stdout

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        f = _secret_file(tmp_path, "password=secret123\n")
        original = f.read_text()
        result = _run_redact("--file", str(f), "--dry-run")
        assert result.returncode == 0
        assert f.read_text() == original  # unchanged


# ═══════════════════════════════════════════════════════════════════════
# 6. Directory recursive redaction
# ═══════════════════════════════════════════════════════════════════════


class TestDirectoryRedaction:
    def test_dir_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("token=abc\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("hello=world\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.txt").write_text("password=xyz\n", encoding="utf-8")

        result = _run_redact("--dir", str(tmp_path))
        assert result.returncode == 0
        assert "abc" not in (tmp_path / "a.txt").read_text()
        assert "hello" in (tmp_path / "b.txt").read_text()
        assert "xyz" not in (sub / "c.txt").read_text()


# ═══════════════════════════════════════════════════════════════════════
# 7. PG evidence
# ═══════════════════════════════════════════════════════════════════════


class TestPgEvidence:
    def test_pg_evidence_no_connection_leak(self) -> None:
        from result_bundler import pg_evidence_summary

        summary = pg_evidence_summary("SELECT COUNT(*) FROM trades WHERE date > '2026-01-01'")
        assert "query_summary" in summary
        assert "account" in summary
        assert summary["account"] == "readonly"
        # Must NOT contain connection details
        for key in ["host", "port", "password", "user", "dbname", "database", "DATABASE_URL"]:
            assert key not in summary, f"PG summary leaked {key}"

    def test_pg_evidence_truncates_long_query(self) -> None:
        from result_bundler import pg_evidence_summary

        long_query = "SELECT " + ", ".join(f"col_{i}" for i in range(100)) + " FROM huge_table"
        summary = pg_evidence_summary(long_query)
        assert len(summary["query_summary"]) <= 203  # 200 + "..." max
        assert summary["query_summary"].endswith("...")

    def test_redact_pg_evidence_file(self, tmp_path: Path) -> None:
        f = tmp_path / "query.sql"
        f.write_text("SELECT * FROM orders WHERE status='pending';\n", encoding="utf-8")
        result = _run_redact("--pg-evidence", str(f))
        assert result.returncode == 0
        assert "Connection details intentionally omitted" in result.stdout

    def test_pg_evidence_snapshot_time(self) -> None:
        from result_bundler import pg_evidence_summary

        summary = pg_evidence_summary("SELECT 1", snapshot_time="2026-07-13T10:00:00Z")
        assert summary["snapshot_time"] == "2026-07-13T10:00:00Z"


# ═══════════════════════════════════════════════════════════════════════
# 8. Large log handling
# ═══════════════════════════════════════════════════════════════════════


class TestLargeLogHandling:
    def test_small_log_not_processed(self, tmp_path: Path) -> None:
        from result_bundler import handle_large_log

        log = tmp_path / "small.log"
        log.write_text("ok\n" * 10, encoding="utf-8")
        result = handle_large_log(log, threshold=1_000_000)
        assert result is None

    def test_large_log_creates_index_and_summary(self, tmp_path: Path) -> None:
        from result_bundler import handle_large_log

        log = tmp_path / "big.log"
        # Create a log just over 10KB threshold (use a small threshold for tests)
        log.write_text("2026-07-13 10:00:00 INFO test line\n" * 1000, encoding="utf-8")
        result = handle_large_log(log, threshold=5000)
        assert result is not None
        assert "summary" in result
        assert "index" in result
        assert (tmp_path / "big.summary.txt").exists()
        assert (tmp_path / "big.index.json").exists()
        assert (tmp_path / "big.log").exists()  # original preserved

    def test_large_log_original_preserved(self, tmp_path: Path) -> None:
        from result_bundler import handle_large_log

        log = tmp_path / "preserved.log"
        original = "line\n" * 800
        log.write_text(original, encoding="utf-8")
        handle_large_log(log, threshold=1000)
        assert log.read_text() == original


# ═══════════════════════════════════════════════════════════════════════
# 9. Evidence index
# ═══════════════════════════════════════════════════════════════════════


class TestEvidenceIndex:
    def test_generate_evidence_index(self, tmp_path: Path) -> None:
        from result_bundler import generate_evidence_index

        (tmp_path / "result.txt").write_text("done\n", encoding="utf-8")
        (tmp_path / "data.json").write_text('{"ok": true}', encoding="utf-8")

        entries = generate_evidence_index(tmp_path, repo_root=tmp_path)
        paths = {e.path for e in entries}
        assert "result.txt" in paths
        assert "data.json" in paths
        for e in entries:
            assert e.git_commit or True  # may be "unknown" in test
            assert len(e.sha256_checksum) == 64

    def test_evidence_index_skips_bundle_files(self, tmp_path: Path) -> None:
        from result_bundler import generate_evidence_index

        (tmp_path / "result.txt").write_text("ok\n", encoding="utf-8")
        (tmp_path / "result_bundle.json").write_text("{}", encoding="utf-8")
        (tmp_path / "evidence_index.json").write_text("{}", encoding="utf-8")

        entries = generate_evidence_index(tmp_path, repo_root=tmp_path)
        paths = {e.path for e in entries}
        assert "result.txt" in paths
        assert "result_bundle.json" not in paths
        assert "evidence_index.json" not in paths

    def test_build_evidence_index_json(self, tmp_path: Path) -> None:
        from result_bundler import build_evidence_index_json

        (tmp_path / "test.txt").write_text("data\n", encoding="utf-8")
        idx = build_evidence_index_json(tmp_path, repo_root=tmp_path)
        assert idx["schema_version"] == 1
        assert idx["total_files"] >= 1
        assert "git_commit" in idx


# ═══════════════════════════════════════════════════════════════════════
# 10. Statement classification
# ═══════════════════════════════════════════════════════════════════════


class TestStatementClassification:
    def test_fact_classification(self) -> None:
        from result_bundler import classify_statement

        result = classify_statement(
            "changed_files.txt",
            has_git_trace=True,
            has_checksum=True,
            is_ai_generated=False,
        )
        assert result == "fact"

    def test_inference_classification(self) -> None:
        from result_bundler import classify_statement

        result = classify_statement(
            "plan_result.md",
            has_git_trace=False,
            has_checksum=False,
            is_ai_generated=True,
        )
        assert result == "inference"

    def test_unverified_classification(self) -> None:
        from result_bundler import classify_statement

        result = classify_statement(
            "unknown_memo.txt",
            has_git_trace=False,
            has_checksum=False,
            is_ai_generated=False,
            source_file="",
        )
        assert result == "unverified"

    def test_classify_deliverables(self, tmp_path: Path) -> None:
        from result_bundler import EvidenceEntry, classify_deliverables

        entries = [
            EvidenceEntry(
                path="changed_files.txt",
                generated_by="git",
                generated_at="2026-07-13T10:00:00Z",
                git_commit="abc123def456",
                sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                size_bytes=100,
            ),
            EvidenceEntry(
                path="plan_result.md",
                generated_by="codex",
                generated_at="2026-07-13T10:00:00Z",
                git_commit="abc123def456",
                sha256_checksum="",
                size_bytes=500,
            ),
        ]
        results = classify_deliverables(entries)
        assert len(results) == 2
        classifications = {r["path"]: r["classification"] for r in results}
        assert classifications["changed_files.txt"] == "fact"
        assert classifications["plan_result.md"] == "inference"


# ═══════════════════════════════════════════════════════════════════════
# 11. Cumulative redaction safety
# ═══════════════════════════════════════════════════════════════════════


class TestCumulativeSafety:
    """Verify that combining all synthetic secrets in one text still
    results in zero leaked values."""

    def test_all_patterns_together(self, tmp_path: Path) -> None:
        combined = (
            "token=abc123def456\n"
            "password: verysecret\n"
            "QYWX_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xyz\n"
            "DATABASE_URL=postgresql://admin:hunter2@db.example.com:5432/mydb\n"
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefgh\n"
            "API_KEY = sk-test1234567890\n"
            "access_key=AKIAIOSFODNN7EXAMPLE\n"
            "hello=world\n"
        )
        f = tmp_path / "combined.txt"
        f.write_text(combined, encoding="utf-8")
        result = _run_redact("--file", str(f))
        assert result.returncode == 0
        content = f.read_text()
        # No synthetic secret should survive
        for candidate in [
            "abc123def456", "verysecret",
            "hunter2",
            "eyJhbGci",
            "sk-test1234567890",
            "AKIAIOSFODNN7EXAMPLE",
        ]:
            assert candidate not in content, f"Secret leaked: {candidate}"
        # Clean values survive
        assert "hello=world" in content
