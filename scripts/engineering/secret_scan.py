#!/usr/bin/env python3
"""Scan repository text without disclosing matched secret values."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable, Sequence


MAX_BYTES = 1_000_000
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)
SKIP_SUFFIXES = frozenset(
    {
        ".7z",
        ".bin",
        ".bz2",
        ".dat",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lock",
        ".otf",
        ".parquet",
        ".pdf",
        ".png",
        ".pyc",
        ".pyo",
        ".so",
        ".tar",
        ".ttf",
        ".webp",
        ".woff",
        ".woff2",
        ".xz",
        ".zip",
    }
)
PLACEHOLDER_MARKERS = (
    "<your",
    "${",
    "changeme",
    "dummy",
    "example",
    "fake-",
    "not-a-real",
    "os.getenv",
    "placeholder",
    "redacted",
    "replace-with-",
    "sample",
    "test-only",
    "your-",
    "your_",
)
PATTERNS = (
    (
        "wechat_webhook",
        re.compile(r"qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{8,}"),
    ),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    (
        "github_fine_grained",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "database_url",
        re.compile(
            r"\bDATABASE_URL\b\s*[:=]\s*postgres(?:ql)?://[^\s'\"\\]{12,}",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_assignment",
        re.compile(
            r"\b(?:DATABASE_URL|QYWX_WEBHOOK(?:_URL)?|API[_-]?KEY|ACCESS[_-]?TOKEN|PASSWORD|SECRET|WEBHOOK(?:_URL)?|TOKEN)\b\s*[:=]\s*(['\"])[^'\"]{16,}\1",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    family: str


class InvalidInvocation(ValueError):
    """Raised when a requested scan cannot be contained in the repository."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan tracked or explicitly selected repository text for secrets."
    )
    parser.add_argument("paths", nargs="*", help="repository-relative file or directory")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        root = _repository_root()
        targets = _explicit_targets(root, args.paths) if args.paths else _tracked_targets(root)
        findings = scan_files(root, targets)
    except InvalidInvocation:
        _emit("invalid", (), args.as_json)
        return 2

    status = "warning" if findings and args.warn_only else "failed" if findings else "passed"
    _emit(status, findings, args.as_json)
    if findings and not args.warn_only:
        return 1
    return 0


def scan_files(root: Path, targets: Iterable[Path]) -> tuple[Finding, ...]:
    findings: set[Finding] = set()
    for path in sorted(set(targets)):
        if _skip(path) or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > MAX_BYTES or b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="ignore")
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
                continue
            for family, pattern in PATTERNS:
                if pattern.search(line):
                    findings.add(Finding(relative, line_number, family))
    return tuple(sorted(findings))


def _repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise InvalidInvocation("repository unavailable")
    return Path(result.stdout.strip()).resolve()


def _tracked_targets(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise InvalidInvocation("tracked file inventory unavailable")
    return tuple(root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


def _explicit_targets(root: Path, candidates: Sequence[str]) -> tuple[Path, ...]:
    targets: list[Path] = []
    for candidate in candidates:
        raw = Path(candidate)
        if raw.is_absolute():
            raise InvalidInvocation("absolute paths are not supported")
        resolved = (root / raw).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            raise InvalidInvocation("path outside repository")
        if resolved.is_dir():
            targets.extend(path for path in resolved.rglob("*") if path.is_file())
        else:
            targets.append(resolved)
    return tuple(targets)


def _skip(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        path.suffix.lower() in SKIP_SUFFIXES
        or "/cache/api_docs/" in normalized
        or any(part in SKIP_DIRECTORIES for part in path.parts)
    )


def _emit(status: str, findings: Sequence[Finding], as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "tool": "scripts/engineering/secret_scan.py",
                    "status": status,
                    "finding_count": len(findings),
                    "findings": [asdict(finding) for finding in findings],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return
    print(f"[secret-scan] status={status} findings={len(findings)}")
    for finding in findings:
        print(f"  {finding.path}:{finding.line} family={finding.family}")


if __name__ == "__main__":
    raise SystemExit(main())
