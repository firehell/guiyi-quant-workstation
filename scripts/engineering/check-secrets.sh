#!/usr/bin/env bash
# Secret scan — fail-closed by default; never prints secret values.
# Output: path, line, pattern family only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

WARN_ONLY=false
PATHS=()

usage() {
  cat <<'EOF'
Usage: scripts/engineering/check-secrets.sh [--warn-only] [--path PATH]...

Scan tracked files (git ls-files) for high-confidence secrets.
Default: fail-closed (exit 1 on hits).
--warn-only: report hits but exit 0 (must NOT be used in CI).
--path: scan specific file(s)/dir(s) instead of the whole repo (for tests).

Never prints secret values — only path, line, and pattern family.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --warn-only) WARN_ONLY=true; shift ;;
    --path)
      [[ $# -ge 2 ]] || { echo "Missing value for --path" >&2; exit 2; }
      PATHS+=("$2")
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

PY_ARGS=("$WARN_ONLY" "$REPO_ROOT")
if [[ ${#PATHS[@]} -gt 0 ]]; then
  PY_ARGS+=("${PATHS[@]}")
fi

# argv: warn_only, repo_root, optional scan paths.
python3 - "${PY_ARGS[@]}" <<'PY'
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

warn_only = sys.argv[1] == "true"
repo = Path(sys.argv[2]).resolve()
extra_paths = [Path(p) for p in sys.argv[3:]]

# Binary / large / known generated — do NOT blanket-skip docs/ or .md
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".parquet", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
    ".zip", ".gz", ".bz2", ".xz", ".7z", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".lock",
    ".pdf", ".bin", ".dat",
}
SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
SKIP_PREFIXES = ("data/raw/", "data/parquet/")
# Known generated / example templates (not live secrets).
SKIP_REL_SUBSTR = ("/cache/api_docs/",)
SKIP_NAME_SUFFIXES = (".example",)
MAX_BYTES = 1_000_000

FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "wechat_webhook",
        re.compile(
            r"qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{8,}",
            re.I,
        ),
    ),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("github_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # Quoted literal assignments only (avoid code identifiers / function calls).
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:DATABASE_URL|QYWX_WEBHOOK(?:_URL)?|API[_-]?KEY|ACCESS[_-]?TOKEN|"
            r"PASSWORD|SECRET|WEBHOOK(?:_URL)?|TOKEN)\b\s*[:=]\s*"
            r"(['\"])([^'\"]{16,})\1"
        ),
    ),
    # Unquoted DB URLs with embedded credentials.
    (
        "database_url",
        re.compile(
            r"(?i)\bDATABASE_URL\b\s*[:=]\s*(postgres(?:ql)?://[^\s'\"\\]{12,})"
        ),
    ),
]

PLACEHOLDER_TOKENS = (
    "replace-with-",
    "example",
    "redacted",
    "os.getenv",
    "environ",
    "getenv(",
    "your-",
    "your_",
    "xxx",
    "todo",
    "placeholder",
    "${",
    "settings.",
    "config.",
    "changeme",
    "dummy",
    "sample",
    "fake-",
    "test-only",
    "<your",
    "not-a-real",
    "localstorage",
    "normalize_database_url",
)


def is_placeholder(line: str) -> bool:
    lower = line.lower()
    if any(tok in lower for tok in PLACEHOLDER_TOKENS):
        return True
    if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", line):
        return True
    return False


def should_skip(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo).as_posix()
        parts = path.resolve().relative_to(repo).parts
    except ValueError:
        rel = path.as_posix()
        parts = path.parts
    if any(part in SKIP_DIR_NAMES for part in parts):
        return True
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in SKIP_PREFIXES):
        return True
    if any(s in rel for s in SKIP_REL_SUBSTR):
        return True
    if any(path.name.endswith(suf) for suf in SKIP_NAME_SUFFIXES):
        return True
    if path.suffix.lower() in SKIP_SUFFIX:
        return True
    try:
        if path.stat().st_size > MAX_BYTES:
            return True
    except OSError:
        return True
    return False


def collect_targets() -> list[Path]:
    if extra_paths:
        out: list[Path] = []
        for item in extra_paths:
            p = item if item.is_absolute() else (repo / item)
            p = p.resolve()
            if p.is_dir():
                for child in p.rglob("*"):
                    if child.is_file() and not should_skip(child):
                        out.append(child)
            elif p.is_file() and not should_skip(p):
                out.append(p)
        return out

    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    out: list[Path] = []
    for rel in result.stdout.split(b"\0"):
        if not rel:
            continue
        path = repo / rel.decode("utf-8", errors="surrogateescape")
        if path.is_file() and not should_skip(path):
            out.append(path)
    return out


hits: list[str] = []
scanned = 0
for path in collect_targets():
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    scanned += 1
    try:
        rel = path.relative_to(repo)
    except ValueError:
        rel = path
    for i, line in enumerate(text.splitlines(), 1):
        if is_placeholder(line):
            continue
        for family, pattern in FAMILY_PATTERNS:
            if pattern.search(line):
                hits.append(f"{rel}:{i}: family={family}")
                break

print(f"[OK] scanned_files={scanned}")
if hits:
    print(f"[FAIL] potential_secrets={len(hits)} (values not printed)")
    for h in hits[:50]:
        print(f"  {h}")
    if len(hits) > 50:
        print(f"  ... and {len(hits) - 50} more")
    sys.exit(0 if warn_only else 1)

print("[OK] no high-confidence secrets found")
sys.exit(0)
PY
