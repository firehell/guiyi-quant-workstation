#!/usr/bin/env bash
# Engineering test runner — fixed profiles only; never free-shell user strings.
# Never push / merge / deploy / real production writes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage: scripts/engineering/test.sh <profile>

Profiles (fixed command arrays; no free-shell args):
  engineering      bash -n engineering scripts + pytest tests/engineering + git diff --check
  docs             verify canonical engineering docs exist
  backend-health   pytest services/quant-api/tests/test_health.py
  all-safe         engineering + docs + backend-health

Other suites: run pytest/npm directly via Codex — do not extend this runner
with free-form commands.
EOF
}

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  [[ $# -eq 0 ]] && exit 2
  exit 0
fi

if [[ $# -ne 1 ]]; then
  echo "[REJECTED] exactly one profile required; free-shell args are forbidden" >&2
  usage >&2
  exit 2
fi

PROFILE="$1"

run_fixed() {
  # Execute a fixed argv array — never bash -c with user strings.
  local -a cmd=("$@")
  echo "[TEST] ${cmd[*]}"
  set +e
  "${cmd[@]}"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    echo "[FAIL] exit=$rc" >&2
    return "$rc"
  fi
  echo "[OK]"
  return 0
}

profile_engineering() {
  local overall=0
  local f
  for f in preflight.sh test.sh check-secrets.sh runtime-health.sh; do
    run_fixed bash -n "scripts/engineering/$f" || overall=1
  done
  run_fixed python3 -c 'import ast, pathlib; ast.parse(pathlib.Path("scripts/engineering/worktree_flow.py").read_text(encoding="utf-8"))' || overall=1
  # production-write-check.sh must stay deleted — fail if it reappears.
  if [[ -e scripts/engineering/production-write-check.sh ]]; then
    echo "[FAIL] production-write-check.sh must remain deleted" >&2
    overall=1
  else
    echo "[OK] production-write-check.sh absent"
  fi
  run_fixed git diff --check || overall=1
  run_fixed python3 -m pytest -q tests/engineering || overall=1
  return "$overall"
}

profile_docs() {
  local overall=0
  local required=(
    AGENTS.md
    docs/DEVELOPMENT.md
    TESTING.md
    README.md
  )
  local f
  for f in "${required[@]}"; do
    if [[ -f "$f" ]]; then
      echo "[OK] docs present: $f"
    else
      echo "[FAIL] missing required doc: $f" >&2
      overall=1
    fi
  done
  # Gate rule must be documented (business-scoped approval, not generic confirm flag).
  # Use portable grep — Actions runners may not have ripgrep (rg).
  if grep -E -q "hash-bound|scope-bound approval|没有专用 Gate 就禁止真实写入" \
      AGENTS.md docs/DEVELOPMENT.md TESTING.md README.md; then
    echo "[OK] production-write gate rule present in docs"
  else
    echo "[FAIL] missing production-write gate rule in docs" >&2
    overall=1
  fi
  # Makefile / active entrypoints must not still invoke the deleted script.
  # Allow the intentional absence-guard inside test.sh itself.
  stale="$(
    grep -R -n "scripts/engineering/production-write-check\.sh" Makefile scripts/engineering 2>/dev/null \
      | grep -v "must remain deleted" \
      | grep -v "production-write-check\.sh must remain deleted" \
      | grep -v '\[\[ -e scripts/engineering/production-write-check\.sh \]\]' \
      || true
  )"
  if [[ -n "$stale" ]]; then
    echo "[FAIL] stale production-write-check.sh invocation remains" >&2
    echo "$stale" >&2
    overall=1
  else
    echo "[OK] no stale production-write-check.sh invocations"
  fi
  return "$overall"
}

profile_backend_health() {
  local -a cmd=(
    python3 -m pytest -q
    services/quant-api/tests/test_health.py
  )
  # Prefer uv when available; fall back to PYTHONPATH.
  if command -v uv >/dev/null 2>&1; then
    run_fixed env PYTHONPATH=services/quant-api:packages/quant-core \
      uv run --project services/quant-api pytest -q services/quant-api/tests/test_health.py
  else
    run_fixed env PYTHONPATH=services/quant-api:packages/quant-core "${cmd[@]}"
  fi
}

profile_all_safe() {
  local overall=0
  profile_engineering || overall=1
  profile_docs || overall=1
  profile_backend_health || overall=1
  # Explicit safety: these strings must never appear as executed write actions.
  if [[ "$overall" -eq 0 ]]; then
    echo "[OK] all-safe completed without push/merge/deploy/real-write actions"
  fi
  return "$overall"
}

overall=0
case "$PROFILE" in
  engineering) profile_engineering || overall=$? ;;
  docs) profile_docs || overall=$? ;;
  backend-health) profile_backend_health || overall=$? ;;
  all-safe) profile_all_safe || overall=$? ;;
  *)
    echo "[REJECTED] unknown profile: $PROFILE" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ $overall -eq 0 ]]; then
  echo "[OK] engineering tests passed (profile=$PROFILE)"
else
  echo "[FAIL] engineering tests failed (profile=$PROFILE)" >&2
fi
exit "$overall"
