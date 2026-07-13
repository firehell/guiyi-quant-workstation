#!/usr/bin/env python3
"""WS-V2-007: Unified Result Bundle, Evidence Index & Redaction.

Core module providing:
  - RedactionPatterns / redact():  unified secret scrubbing
  - EvidenceEntry / generate_evidence_index():  per-file traceability
  - classify_statement():  fact | inference | unverified
  - pg_evidence_summary():  safe PostgreSQL evidence recording
  - handle_large_log():  index + summary for oversized logs
  - build_result_bundle():  R1/R2/R3 result bundle assembly
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# 1. Redaction Patterns
# ═══════════════════════════════════════════════════════════════════════


class RedactionPatterns:
    """Unified secret-detection patterns aligned with SECURITY_HANDBOOK §8/§11.
    Each pattern-group is a compiled regex; .sub(repl, text) produces
    redacted output.  Never captures the actual secret value.
    """

    # Key-level: captures the KEY name and the value *after* the separator.
    # Redacted output retains key + "[REDACTED]".
    KEY_PATTERN = re.compile(
        r"(?i)"
        r"(token|webhook|password|secret|api[_-]?key|access[_-]?key|"
        r"private[_-]?key|QYWX_WEBHOOK|DATABASE_URL|REDIS_URL|RQDATA_"
        r"(?:TOKEN|USERNAME|PASSWORD))"
        r"(\s*[:=]\s*)"
        r"(?!\$|\[REDACTED\])"
        r"([^\s,;}]+)"
    )

    # Webhook status: detect presence separately so we can replace the URL
    # with a status marker rather than just [REDACTED].
    WEBHOOK_STATUS = re.compile(
        r"(?i)(QYWX_WEBHOOK|webhook_url|notification_webhook)"
        r"(\s*[:=]\s*)"
        r"(?!\$|已设置|[REDACTED])"
        r"([^\s,;}]+)"
    )

    # URL credential: user:pass@host patterns (e.g. postgresql://user:pass@host/db)
    URL_CREDENTIAL = re.compile(
        r"(https?|postgres(?:ql)?|mysql|redis|mongodb|amqp)"
        r"://[^:@\s]+:[^@\s]+@"
    )

    # Bearer token in Authorization headers
    BEARER_TOKEN = re.compile(
        r"(?i)(authorization|auth)\s*[:=]\s*(bearer|basic)\s+[^\s,;]+"
    )

    # Query-string token (e.g. ?token=abc123&)
    QUERY_TOKEN = re.compile(
        r"[?&]token=[^&\s]+"
    )

    # Generic 4+ char suspicious value after sensitive keys (catch-all)
    SUSPICIOUS_VALUE = re.compile(
        r"(?i)(token|webhook|password|secret|api[_-]?key|access[_-]?key"
        r"|DATABASE_URL)"
        r"\s*[:=]\s*['\"]?(?!\$|\[REDACTED\])[^\s'\"]{4,}"
    )

    @classmethod
    def redact_text(cls, value: str) -> str:
        """Apply all redaction patterns to a single string value."""
        v = value
        # 1. URL credentials first (erase user:pass@)
        v = cls.URL_CREDENTIAL.sub(r"\1://[REDACTED_CREDENTIAL]@", v)
        # 2. Bearer tokens
        v = cls.BEARER_TOKEN.sub(r"\1: Bearer [REDACTED]", v)
        # 3. Query-string tokens
        v = cls.QUERY_TOKEN.sub("?token=[REDACTED]", v)
        # 4. Webhook status markers
        v = cls.WEBHOOK_STATUS.sub(r"\1\2已设置(true)", v)
        # 5. Key-value patterns (catch-all last)
        v = cls.KEY_PATTERN.sub(r"\1\2[REDACTED]", v)
        return v

    @classmethod
    def check_sensitive(cls, content: str) -> list[str]:
        """Return list of detected pattern names (for audit/check)."""
        hits: list[str] = []
        if cls.URL_CREDENTIAL.search(content):
            hits.append("url_credential")
        if cls.BEARER_TOKEN.search(content):
            hits.append("bearer_token")
        if cls.QUERY_TOKEN.search(content):
            hits.append("query_token")
        sens = cls.SUSPICIOUS_VALUE.search(content)
        if sens:
            hits.append("suspicious_value")
        return hits

    @classmethod
    def has_sensitive(cls, content: str) -> bool:
        """Quick check: does content contain ANY sensitive pattern?"""
        return cls.SUSPICIOUS_VALUE.search(content) is not None


# ═══════════════════════════════════════════════════════════════════════
# 2. Redact function (recursive)
# ═══════════════════════════════════════════════════════════════════════


def redact(value: Any) -> Any:
    """Recursively redact secrets in any Python object.

    Strings are pattern-scrubbed; lists and dicts are recursed;
    everything else is passed through unchanged.
    """
    if isinstance(value, str):
        return RedactionPatterns.redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, str) and RedactionPatterns.has_sensitive(f"{k}={v}"):
                result[str(k)] = "[REDACTED]"
            else:
                result[str(k)] = redact(v)
        return result
    return value


# ═══════════════════════════════════════════════════════════════════════
# 3. Evidence Index
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvidenceEntry:
    """One file in the evidence index."""
    path: str
    generated_by: str          # e.g. "collect_result.sh", "pytest", "pg_dump --schema-only"
    generated_at: str          # ISO 8601 UTC
    git_commit: str            # HEAD at time of generation
    data_version: str = ""     # e.g. "RQData-2026-07-13", "snapshot-1710921600"
    sha256_checksum: str = ""
    size_bytes: int = 0
    content_type: str = ""     # "text", "binary", "json", "log", "sql-summary"


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return ""


def _git_head(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, text=True, capture_output=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def generate_evidence_index(
    out_dir: Path,
    repo_root: Path | None = None,
    *,
    generated_by: str = "collect_result.sh",
    data_version: str = "",
) -> list[EvidenceEntry]:
    """Scan out_dir and produce an evidence index of every artifact file.

    Skips evidence_index.json itself and result_bundle.json/execution.json
    (which are the deliverable, not the evidence).
    """
    skip_names = {"evidence_index.json", "result_bundle.json", "result_bundle.md"}
    git_head = _git_head(repo_root or out_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    entries: list[EvidenceEntry] = []

    for fpath in sorted(out_dir.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.name in skip_names:
            continue
        rel = str(fpath.relative_to(out_dir))
        size = fpath.stat().st_size
        suffix = fpath.suffix.lower()
        ctype = "text"
        if suffix in {".json", ".jsonl"}:
            ctype = "json"
        elif suffix in {".log", ".txt"}:
            ctype = "log"
        elif suffix in {".tsv", ".csv"}:
            ctype = "text"
        elif suffix == "":
            ctype = "text"
        else:
            ctype = "binary"

        entries.append(EvidenceEntry(
            path=rel,
            generated_by=generated_by,
            generated_at=now,
            git_commit=git_head,
            data_version=data_version,
            sha256_checksum=_sha256(fpath),
            size_bytes=size,
            content_type=ctype,
        ))
    return entries


def build_evidence_index_json(
    out_dir: Path,
    repo_root: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build evidence_index.json as a standalone artifact."""
    entries = generate_evidence_index(out_dir, repo_root, **kwargs)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": _git_head(repo_root or out_dir),
        "total_files": len(entries),
        "entries": [asdict(e) for e in entries],
    }


# ═══════════════════════════════════════════════════════════════════════
# 4. Statement Classification
# ═══════════════════════════════════════════════════════════════════════


def classify_statement(
    text: str,
    *,
    has_git_trace: bool = False,
    has_checksum: bool = False,
    is_ai_generated: bool = False,
    source_file: str = "",
) -> str:
    """Classify a deliverable statement as fact, inference, or unverified.

    Rules:
      - fact:  has git trace AND checksum AND not AI-generated
      - inference:  AI-generated OR implied from data
      - unverified:  no git trace, no checksum, no source
    """
    if has_git_trace and has_checksum and not is_ai_generated:
        return "fact"
    if is_ai_generated:
        return "inference"
    return "unverified"


def classify_deliverables(
    evidence_entries: list[EvidenceEntry],
    *,
    ai_generated_patterns: tuple[str, ...] = ("plan_result.md", "review.md", "execution_summary.md"),
) -> list[dict[str, str]]:
    """Classify a batch of evidence entries."""
    results: list[dict[str, str]] = []
    for e in evidence_entries:
        has_checksum = bool(e.sha256_checksum and len(e.sha256_checksum) >= 8)
        has_git = bool(e.git_commit and len(e.git_commit) >= 7)
        is_ai = any(p in e.path for p in ai_generated_patterns)
        cls = classify_statement(
            e.path,
            has_git_trace=has_git,
            has_checksum=has_checksum,
            is_ai_generated=is_ai,
            source_file=e.path,
        )
        results.append({"path": e.path, "classification": cls})
    return results


# ═══════════════════════════════════════════════════════════════════════
# 5. PostgreSQL Evidence
# ═══════════════════════════════════════════════════════════════════════


def pg_evidence_summary(
    query_text: str,
    *,
    account: str = "readonly",
    snapshot_time: str = "",
) -> dict[str, str]:
    """Produce a safe PostgreSQL evidence summary.

    Records SQL query summary (first 200 chars), read-only account name,
    and snapshot time.  NEVER records connection strings, host, port, or
    database name.
    """
    summary = query_text.strip()
    if len(summary) > 200:
        summary = summary[:197] + "..."

    return {
        "query_summary": summary,
        "account": account,
        "snapshot_time": snapshot_time or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "note": "Connection details intentionally omitted per redaction policy",
    }


# ═══════════════════════════════════════════════════════════════════════
# 6. Large Log Handling
# ═══════════════════════════════════════════════════════════════════════


_LOG_LINE_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
)


def handle_large_log(
    file_path: Path,
    *,
    threshold: int = 1_000_000,  # 1 MB
) -> dict[str, Any] | None:
    """Handle oversized logs: create index + summary, preserve original.

    Returns None if file is under threshold.
    Returns a dict with index and summary paths when processed.
    """
    if not file_path.is_file():
        return None
    size = file_path.stat().st_size
    if size < threshold:
        return None

    # Generate summary: first 10 + last 5 lines
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = raw.splitlines()
    head = lines[:10]
    tail = lines[-5:] if len(lines) > 10 else []

    # Line-range index: bucket by 500-line ranges, map to category
    index_entries: list[dict[str, object]] = []
    chunk_size = 500
    for start in range(0, len(lines), chunk_size):
        end = min(start + chunk_size, len(lines))
        chunk = "\n".join(lines[start:end])
        category = "general"
        if "ERROR" in chunk or "FATAL" in chunk:
            category = "error"
        elif "WARN" in chunk:
            category = "warn"
        elif "DEBUG" in chunk:
            category = "debug"
        elif "INFO" in chunk:
            category = "info"
        # Check for timestamps at line start
        first_line = lines[start].strip() if start < len(lines) else ""
        ts_match = _LOG_LINE_PATTERN.match(first_line)
        index_entries.append({
            "line_start": start + 1,
            "line_end": end,
            "category": category,
            "timestamp_estimate": ts_match.group("ts") if ts_match else "",
        })

    stem = file_path.stem
    parent = file_path.parent

    # Write summary
    summary_path = parent / f"{stem}.summary.txt"
    summary_text = (
        f"# Log Summary — {file_path.name}\n\n"
        f"Total lines: {len(lines)}\n"
        f"Total size: {size:,} bytes\n"
        f"Threshold: {threshold:,} bytes\n\n"
        f"## First 10 lines\n\n"
        + "\n".join(head)
        + "\n\n## Last 5 lines\n\n"
        + "\n".join(tail)
        + "\n"
    )
    summary_path.write_text(summary_text, encoding="utf-8")

    # Write index
    index_path = parent / f"{stem}.index.json"
    index_data = {
        "source_file": str(file_path),
        "total_lines": len(lines),
        "total_size_bytes": size,
        "chunk_size": chunk_size,
        "entries": index_entries,
    }
    index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "source": str(file_path),
        "summary": str(summary_path),
        "index": str(index_path),
        "total_lines": len(lines),
        "total_size_bytes": size,
    }


# ═══════════════════════════════════════════════════════════════════════
# 7. Result Bundle Assembly
# ═══════════════════════════════════════════════════════════════════════


def build_result_bundle(
    task_id: str,
    level: str,
    *,
    execution: dict[str, Any],
    payload: dict[str, Any],
    evidence_index: list[EvidenceEntry] | None = None,
    statement_classifications: list[dict[str, str]] | None = None,
    out_dir: Path | None = None,
    **extras: Any,
) -> dict[str, Any]:
    """Assemble the full result bundle.

    R1 (economy):  execution + plan + test + evidence-index + result
    R2 (balanced): + audit + dry-run + approval + apply + post-verify + rollback-plan
    R3 (deep):     + preflight + runtime-approval + checkpoint-before/after + safe-defaults-restored
    """
    bundle: dict[str, Any] = {
        "schema_version": 2,
        "task_id": task_id,
        "level": level,
        "execution": redact(execution),
        "payload": redact(payload),
    }

    # Evidence index (always present)
    if evidence_index:
        bundle["evidence_index"] = {
            "total_files": len(evidence_index),
            "entries": [asdict(e) for e in evidence_index],
        }
    elif out_dir and out_dir.is_dir():
        idx = build_evidence_index_json(out_dir)
        bundle["evidence_index"] = idx

    # Statement classification (always present)
    if statement_classifications:
        bundle["statement_classifications"] = statement_classifications
    elif evidence_index:
        bundle["statement_classifications"] = classify_deliverables(evidence_index)

    # R2 extensions
    if level in ("balanced", "deep", "L1", "L2"):
        bundle["audit"] = extras.get("audit", {})
        bundle["dry_run"] = extras.get("dry_run", {})
        bundle["approval"] = extras.get("approval", {})
        bundle["apply"] = extras.get("apply", {})
        bundle["post_verify"] = extras.get("post_verify", {})
        bundle["rollback_plan"] = extras.get("rollback_plan", "")

    # R3 extensions
    if level in ("deep", "L1"):
        bundle["preflight"] = extras.get("preflight", {})
        bundle["runtime_approval"] = extras.get("runtime_approval", {})
        bundle["checkpoint_before"] = extras.get("checkpoint_before", {})
        bundle["checkpoint_after"] = extras.get("checkpoint_after", {})
        bundle["safe_defaults_restored"] = extras.get("safe_defaults_restored", False)

    return bundle


# ═══════════════════════════════════════════════════════════════════════
# 8. Redact evidence tool (CLI entry-point logic)
# ═══════════════════════════════════════════════════════════════════════


def redact_file(file_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Redact a single file. Returns report dict."""
    if not file_path.is_file():
        return {"path": str(file_path), "status": "not_found", "changes": 0}

    try:
        original = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"path": str(file_path), "status": "unreadable", "changes": 0}

    redacted_text = RedactionPatterns.redact_text(original)

    changed = original != redacted_text
    if changed and not dry_run:
        file_path.write_text(redacted_text, encoding="utf-8")

    hits = RedactionPatterns.check_sensitive(original)

    return {
        "path": str(file_path),
        "status": "redacted" if changed else "clean",
        "changes": 1 if changed else 0,
        "patterns_detected": hits,
        "dry_run": dry_run,
    }


def redact_directory(dir_path: Path, *, dry_run: bool = False) -> list[dict[str, Any]]:
    """Recursively redact all files in a directory."""
    results: list[dict[str, Any]] = []
    for fpath in sorted(dir_path.rglob("*")):
        if fpath.is_file() and fpath.suffix not in {".pyc", ".pyo", ".so", ".dylib", ".bin"}:
            r = redact_file(fpath, dry_run=dry_run)
            results.append(r)
    return results
