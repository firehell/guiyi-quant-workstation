# 测试与验证命令

更新时间：2026-08-23

## 依赖

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

## RQAlpha 研究工作台（无真实 RQAlpha 副作用）

Fake runner 最小端到端：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/backtest/test_fake_runner_e2e.py
```

Local app 六路由、DTO、CORS/Host/JSON 边界与脱敏错误（FastAPI TestClient，不绑定端口）：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/backtest/test_local_api.py
```

完整工作台代码路径：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/backtest
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app/backtest services/quant-api/tests/backtest
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/backtest
pnpm --dir apps/quant-web exec node --test tests/backtests.test.ts tests/backtestCapability.test.ts tests/backtestPresentation.test.ts
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/backtests.spec.mjs
pnpm --dir apps/quant-web build
```

以上命令只使用临时目录、fake runner、TestClient 和 browser route interception；不启动
`127.0.0.1:8011`，不导入本机真实 RQAlpha，不访问真实 Bundle，也不写仓库外正式
runs root。

## RQAlpha 本机真实 smoke（独立单次外部 Gate）

下面的 preflight 只读：不创建文件/目录、不启停进程、不运行策略，因此无需外部执行
意图。它只验证当前环境，不能转换、复用或推导为后续 smoke 授权。命令不输出环境
变量值、Bundle/runs 内部路径或 runner 版本：

```bash
set -eu
: "${GUIYI_BACKTEST_PYTHON_EXECUTABLE:?}"
: "${GUIYI_BACKTEST_BUNDLE_PATH:?}"
: "${GUIYI_BACKTEST_RUNS_ROOT:?}"
: "${GUIYI_BACKTEST_CORS_ORIGINS:?}"
command -v curl >/dev/null
command -v jq >/dev/null
command -v rg >/dev/null
command -v cmp >/dev/null
command -v find >/dev/null
command -v sort >/dev/null
command -v stat >/dev/null
command -v awk >/dev/null
command -v unzip >/dev/null
command -v realpath >/dev/null
test -x /usr/sbin/lsof
test -x "$GUIYI_BACKTEST_PYTHON_EXECUTABLE"
test -d "$GUIYI_BACKTEST_BUNDLE_PATH"
test -r "$GUIYI_BACKTEST_BUNDLE_PATH"
case "$GUIYI_BACKTEST_PYTHON_EXECUTABLE:$GUIYI_BACKTEST_BUNDLE_PATH:$GUIYI_BACKTEST_RUNS_ROOT" in
  /*:/*:/*) ;;
  *) exit 1 ;;
esac

task8_repo_root="$(git rev-parse --show-toplevel)"
task8_repository_commit="$(git rev-parse HEAD)"
task8_sidecar_python="$(realpath \
  "$task8_repo_root/services/quant-api/.venv/bin/python")"
task8_registry="$task8_repo_root/services/quant-api/app/backtest/strategies/registry.json"
task8_strategy_rel="services/quant-api/app/backtest/strategies/example_future_smoke_v1.py"
task8_strategy_source="$task8_repo_root/$task8_strategy_rel"
task8_formal_snapshot_script="$task8_repo_root/scripts/engineering/backtest_formal_surface_snapshot.py"
task8_bundle_root="$(cd "$GUIYI_BACKTEST_BUNDLE_PATH" && pwd -P)"
task8_runs_parent_input="$(dirname -- "$GUIYI_BACKTEST_RUNS_ROOT")"
task8_runs_name="$(basename -- "$GUIYI_BACKTEST_RUNS_ROOT")"
case "$task8_runs_name" in ''|.|..) exit 1 ;; esac
test -x "$task8_sidecar_python"
test -f "$task8_strategy_source"
test -f "$task8_formal_snapshot_script"
git -C "$task8_repo_root" diff --quiet -- "$task8_strategy_rel"
git -C "$task8_repo_root" diff --cached --quiet -- "$task8_strategy_rel"
git -C "$task8_repo_root" cat-file -e \
  "$task8_repository_commit:$task8_strategy_rel"
task8_expected_strategy_sha256="$(
  git -C "$task8_repo_root" show \
    "$task8_repository_commit:$task8_strategy_rel" | shasum -a 256 | awk '{print $1}'
)"
test "$(shasum -a 256 "$task8_strategy_source" | awk '{print $1}')" \
  = "$task8_expected_strategy_sha256"
test -d "$task8_runs_parent_input"
test -w "$task8_runs_parent_input"
task8_runs_parent="$(cd "$task8_runs_parent_input" && pwd -P)"
task8_runs_root="$task8_runs_parent/$task8_runs_name"
test ! -e "$task8_runs_root"
case "$task8_runs_root/" in "$task8_bundle_root/"*) exit 1 ;; esac
case "$task8_bundle_root/" in "$task8_runs_root/"*) exit 1 ;; esac
jq -e '
  .schema_version == 1 and
  any(.strategies[];
    .id == "example_future_smoke_v1" and .enabled == true and
    (.supported_frequencies | index("1d") != null) and
    any(.parameters[]; .name == "order_book_id" and .default == "IF1606")
  )
' "$task8_registry" >/dev/null
if /usr/sbin/lsof -nP -iTCP:8011 -sTCP:LISTEN >/dev/null 2>&1; then
  exit 1
fi
```

以下是一次完整的、非交互且有界的真实 smoke。只能在操作者针对当次精确本机、
Bundle、外部 Python、`example_future_smoke_v1 + IF1606 + 2016-06-01..03`
与唯一且不存在的外部 runs root 给出**新的、范围明确的单次执行意图后**运行。
`mktemp` 是本序列第一个外部 mutation；若尚未获得该意图，必须在它之前停止。成功、
失败、中止都消耗该意图，重试需要新意图。本序列不包含也禁止运行 `rqsdk update-data`、
`download-data` 或任何 Bundle mutation：

```bash
set -euo pipefail
: "${GUIYI_BACKTEST_PYTHON_EXECUTABLE:?}"
: "${GUIYI_BACKTEST_BUNDLE_PATH:?}"
: "${GUIYI_BACKTEST_RUNS_ROOT:?}"
: "${GUIYI_BACKTEST_CORS_ORIGINS:?}"

task8_repo_root="$(git rev-parse --show-toplevel)"
task8_repository_commit="$(git rev-parse HEAD)"
task8_sidecar_python="$(realpath \
  "$task8_repo_root/services/quant-api/.venv/bin/python")"
task8_registry="$task8_repo_root/services/quant-api/app/backtest/strategies/registry.json"
task8_strategy_rel="services/quant-api/app/backtest/strategies/example_future_smoke_v1.py"
task8_strategy_source="$task8_repo_root/$task8_strategy_rel"
task8_formal_snapshot_script="$task8_repo_root/scripts/engineering/backtest_formal_surface_snapshot.py"
task8_external_python="$(realpath "$GUIYI_BACKTEST_PYTHON_EXECUTABLE")"
task8_runner_entry="$(realpath \
  "$task8_repo_root/services/quant-api/app/backtest/runner_entry.py")"
task8_bundle_root="$(cd "$GUIYI_BACKTEST_BUNDLE_PATH" && pwd -P)"
task8_runs_parent_input="$(dirname -- "$GUIYI_BACKTEST_RUNS_ROOT")"
task8_runs_name="$(basename -- "$GUIYI_BACKTEST_RUNS_ROOT")"
case "$task8_runs_name" in ''|.|..) exit 1 ;; esac
task8_runs_parent="$(cd "$task8_runs_parent_input" && pwd -P)"
task8_runs_root="$task8_runs_parent/$task8_runs_name"
test -x "$task8_external_python"
test -x "$task8_sidecar_python"
test -f "$task8_strategy_source"
test -f "$task8_formal_snapshot_script"
git -C "$task8_repo_root" diff --quiet -- "$task8_strategy_rel"
git -C "$task8_repo_root" diff --cached --quiet -- "$task8_strategy_rel"
git -C "$task8_repo_root" cat-file -e \
  "$task8_repository_commit:$task8_strategy_rel"
task8_expected_strategy_sha256="$(
  git -C "$task8_repo_root" show \
    "$task8_repository_commit:$task8_strategy_rel" | shasum -a 256 | awk '{print $1}'
)"
test "$(shasum -a 256 "$task8_strategy_source" | awk '{print $1}')" \
  = "$task8_expected_strategy_sha256"
test -d "$task8_bundle_root"
test -r "$task8_bundle_root"
test -w "$task8_runs_parent"
test ! -e "$task8_runs_root"
case "$task8_runs_root/" in "$task8_bundle_root/"*) exit 1 ;; esac
case "$task8_bundle_root/" in "$task8_runs_root/"*) exit 1 ;; esac
if /usr/sbin/lsof -nP -iTCP:8011 -sTCP:LISTEN >/dev/null 2>&1; then
  exit 1
fi
jq -e '
  .schema_version == 1 and
  any(.strategies[];
    .id == "example_future_smoke_v1" and .enabled == true and
    (.supported_frequencies | index("1d") != null) and
    any(.parameters[]; .name == "order_book_id" and .default == "IF1606")
  )
' "$task8_registry" >/dev/null

task8_tmp_dir="$(mktemp -d /private/tmp/guiyi-rqalpha-smoke.XXXXXX)"
test ! -L "$task8_tmp_dir"
case "$(cd "$task8_tmp_dir" && pwd -P)" in
  /private/tmp/guiyi-rqalpha-smoke.*) ;;
  *) exit 1 ;;
esac
task8_sidecar_pid=""
task8_sidecar_identity_captured=0
task8_sidecar_executable=""
task8_sidecar_command=""
task8_sidecar_cwd=""
task8_sidecar_started=""
task8_sidecar_pgid=""
task8_runner_pid=""
task8_run_id=""
task8_post_inflight=0
task8_post_response_received=0
task8_post_http_status=""
task8_post_identity_captured=0
task8_cleanup_safe=1
task8_cleanup_fail() {
  task8_cleanup_safe=0
  printf '%s\n' "FAIL: $1; smoke evidence and runs root retained" >&2
  return 1
}
task8_read_sidecar_identity() {
  task8_observed_sidecar_executable="$(/usr/sbin/lsof -a -p "$task8_sidecar_pid" \
    -d txt -Fn 2>/dev/null | awk '
      /^n/ && !found {sub(/^n/, ""); executable=$0; found=1}
      END {if (found) print executable}
    ')" || return 1
  task8_observed_sidecar_executable="$(
    realpath "$task8_observed_sidecar_executable" 2>/dev/null
  )" || return 1
  task8_observed_sidecar_command="$(
    /bin/ps -ww -p "$task8_sidecar_pid" -o command= 2>/dev/null
  )" || return 1
  task8_observed_sidecar_cwd="$(/usr/sbin/lsof -a -p "$task8_sidecar_pid" \
    -d cwd -Fn 2>/dev/null | awk '
      /^n/ && !found {sub(/^n/, ""); cwd=$0; found=1}
      END {if (found) print cwd}
    ')" || return 1
  task8_observed_sidecar_cwd="$(
    realpath "$task8_observed_sidecar_cwd" 2>/dev/null
  )" || return 1
  task8_observed_sidecar_started="$(
    /bin/ps -ww -p "$task8_sidecar_pid" -o lstart= 2>/dev/null
  )" || return 1
  task8_observed_sidecar_pgid="$(
    /bin/ps -ww -p "$task8_sidecar_pid" -o pgid= 2>/dev/null | tr -d ' '
  )" || return 1
  test -n "$task8_observed_sidecar_executable"
  test -n "$task8_observed_sidecar_command"
  test -n "$task8_observed_sidecar_cwd"
  test -n "$task8_observed_sidecar_started"
  test -n "$task8_observed_sidecar_pgid"
}
task8_capture_sidecar_identity() {
  task8_capture_attempt=0
  while test "$task8_capture_attempt" -lt 20; do
    task8_capture_attempt=$((task8_capture_attempt + 1))
    if kill -0 "$task8_sidecar_pid" 2>/dev/null \
        && task8_read_sidecar_identity \
        && test "$task8_observed_sidecar_executable" = "$task8_sidecar_python" \
        && test "$task8_observed_sidecar_command" \
          = "$task8_sidecar_python -m app.backtest.local_app" \
        && test "$task8_observed_sidecar_cwd" \
          = "$task8_repo_root/services/quant-api"; then
      task8_sidecar_executable="$task8_observed_sidecar_executable"
      task8_sidecar_command="$task8_observed_sidecar_command"
      task8_sidecar_cwd="$task8_observed_sidecar_cwd"
      task8_sidecar_started="$task8_observed_sidecar_started"
      task8_sidecar_pgid="$task8_observed_sidecar_pgid"
      task8_sidecar_identity_captured=1
      return 0
    fi
    sleep 0.1
  done
  task8_cleanup_fail BACKTEST_SMOKE_SIDECAR_IDENTITY_UNRESOLVED
}
task8_verify_sidecar_identity() {
  if test "$task8_sidecar_identity_captured" -ne 1 \
      || ! kill -0 "$task8_sidecar_pid" 2>/dev/null \
      || ! task8_read_sidecar_identity \
      || test "$task8_observed_sidecar_executable" != "$task8_sidecar_executable" \
      || test "$task8_observed_sidecar_command" != "$task8_sidecar_command" \
      || test "$task8_observed_sidecar_cwd" != "$task8_sidecar_cwd" \
      || test "$task8_observed_sidecar_started" != "$task8_sidecar_started" \
      || test "$task8_observed_sidecar_pgid" != "$task8_sidecar_pgid"; then
    task8_cleanup_fail BACKTEST_SMOKE_SIDECAR_IDENTITY_CHANGED
    return 1
  fi
}
task8_formal_snapshot() {
  task8_formal_output="$1"
  if ! PYTHONPATH="$task8_repo_root/services/quant-api" \
      UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
      uv run --offline --project "$task8_repo_root/services/quant-api" \
      python "$task8_formal_snapshot_script" >"$task8_formal_output"; then
    printf '%s\n' 'NOT_VERIFIED: formal surface snapshot unavailable' >&2
    return 1
  fi
  jq -e '.schema_version == 1 and .status == "VERIFIED"' \
    "$task8_formal_output" >/dev/null || {
      printf '%s\n' 'NOT_VERIFIED: formal surface snapshot invalid' >&2
      return 1
    }
}
task8_confirm_runner_absent() {
  if test "$task8_post_inflight" -eq 0 \
      && test "$task8_post_identity_captured" -eq 0; then
    return 0
  fi
  if test "$task8_post_response_received" -ne 1; then
    return 1
  fi
  task8_root_node_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
    -print | wc -l | tr -d ' ')" || return 1
  if test "$task8_root_node_count" -eq 0; then
    if test "$task8_post_http_status" != "202"; then
      return 0
    fi
    return 1
  fi
  task8_run_node_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
    -type d ! -type l -print | wc -l | tr -d ' ')" || return 1
  if test "$task8_root_node_count" -ne 1 || test "$task8_run_node_count" -ne 1; then
    return 1
  fi
  task8_observed_run_dir="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
    -type d ! -type l -print -quit)" || return 1
  task8_observed_run_id="$(basename -- "$task8_observed_run_dir")"
  if ! printf '%s\n' "$task8_observed_run_id" \
      | rg -q '^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}$' \
      || test ! -f "$task8_observed_run_dir/run.json" \
      || test -L "$task8_observed_run_dir/run.json" \
      || ! jq -e --arg task8_observed_run_id "$task8_observed_run_id" '
        .run_id == $task8_observed_run_id and
        (.status | IN("succeeded", "failed", "timed_out", "interrupted")) and
        (.finished_at | type == "string" and length > 0)
      ' "$task8_observed_run_dir/run.json" >/dev/null 2>&1; then
    return 1
  fi
  if test -n "$task8_run_id" && test "$task8_run_id" != "$task8_observed_run_id"; then
    return 1
  fi
  task8_run_id="$task8_observed_run_id"
  task8_run_dir="$task8_observed_run_dir"
  return 0
}
task8_stop_runner() {
  if test ! -e "$task8_runs_root"; then
    if test "$task8_post_inflight" -eq 1 \
        || test "$task8_post_identity_captured" -eq 1 \
        || { test -n "$task8_runner_pid" \
          && kill -0 "$task8_runner_pid" 2>/dev/null; }; then
      task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_ROOT_MISSING
      return 1
    fi
    return 0
  fi
  if test ! -d "$task8_runs_root" || test -L "$task8_runs_root" \
      || test "$(stat -f '%u' "$task8_runs_root")" != "$(id -u)" \
      || test "$(stat -f '%Lp' "$task8_runs_root")" != "700"; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_ROOT_IDENTITY_INVALID
    return 1
  fi

  task8_lock_node_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
    -name active.lock -print | wc -l | tr -d ' ')" || {
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LOCK_SCAN_FAILED
    return 1
  }
  if test "$task8_post_inflight" -eq 1 && test -z "$task8_runner_pid" \
      && test "$task8_lock_node_count" -eq 0; then
    task8_launch_wait_attempt=0
    while test "$task8_launch_wait_attempt" -lt 20 \
        && test "$task8_lock_node_count" -eq 0; do
      if task8_confirm_runner_absent; then
        task8_post_inflight=0
        task8_runner_pid=""
        return 0
      fi
      task8_launch_wait_attempt=$((task8_launch_wait_attempt + 1))
      sleep 0.25
      task8_lock_node_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
        -name active.lock -print | wc -l | tr -d ' ')" || {
        task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LOCK_SCAN_FAILED
        return 1
      }
    done
    if test "$task8_lock_node_count" -eq 0; then
      if task8_confirm_runner_absent; then
        task8_post_inflight=0
        task8_runner_pid=""
        return 0
      fi
      task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LAUNCH_IDENTITY_UNRESOLVED
      return 1
    fi
  fi
  if test "$task8_lock_node_count" -eq 0; then
    if test -n "$task8_runner_pid" && kill -0 "$task8_runner_pid" 2>/dev/null; then
      task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LIVE_PID_WITHOUT_LOCK
      return 1
    fi
    if task8_confirm_runner_absent; then
      task8_runner_pid=""
      return 0
    fi
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_RUNNER_ABSENCE_UNPROVEN
    return 1
  fi
  task8_regular_lock_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 \
    -name active.lock -type f ! -type l -print | wc -l | tr -d ' ')" || {
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LOCK_SCAN_FAILED
    return 1
  }
  if test "$task8_lock_node_count" -ne 1 || test "$task8_regular_lock_count" -ne 1 \
      || test -L "$task8_runs_root/active.lock"; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LOCK_IDENTITY_INVALID
    return 1
  fi

  task8_lock_fields="$(jq -er '
    select(type == "object") |
    select((keys | sort) == ["pid", "run_id", "started_at"]) |
    select(.run_id | type == "string" and
      test("^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}$")) |
    select(.pid | type == "number" and floor == . and . > 1) |
    select(.started_at | type == "string" and
      test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+\\+00:00$")) |
    [.run_id, (.pid | tostring), .started_at] | @tsv
  ' "$task8_runs_root/active.lock" 2>/dev/null)" || {
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_LOCK_PAYLOAD_INVALID
    return 1
  }
  IFS=$'\t' read -r task8_lock_run_id task8_lock_pid task8_lock_started_at \
    <<<"$task8_lock_fields"
  if test -n "$task8_run_id" && test "$task8_run_id" != "$task8_lock_run_id"; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_ASSIGNED_RUN_MISMATCH
    return 1
  fi
  if test -n "$task8_runner_pid" && test "$task8_runner_pid" != "$task8_lock_pid"; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_ASSIGNED_PID_MISMATCH
    return 1
  fi
  task8_run_id="$task8_lock_run_id"
  task8_runner_pid="$task8_lock_pid"
  task8_run_dir="$task8_runs_root/$task8_run_id"

  if test ! -d "$task8_run_dir" || test -L "$task8_run_dir" \
      || test "$(stat -f '%u' "$task8_run_dir")" != "$(id -u)" \
      || test ! -f "$task8_run_dir/run.json" \
      || test -L "$task8_run_dir/run.json" \
      || ! jq -e --arg task8_run_id "$task8_run_id" \
        --arg task8_lock_started_at "$task8_lock_started_at" '
          .run_id == $task8_run_id and
          .started_at == $task8_lock_started_at and
          (.status | IN("running", "succeeded", "failed", "timed_out", "interrupted"))
        ' "$task8_run_dir/run.json" >/dev/null 2>&1; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_RUN_IDENTITY_INVALID
    return 1
  fi

  if ! kill -0 "$task8_runner_pid" 2>/dev/null; then
    task8_runner_pid=""
    return 0
  fi
  task8_runner_pgid="$(ps -o pgid= -p "$task8_runner_pid" 2>/dev/null \
    | tr -d ' ' || true)"
  task8_self_pgid="$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ' || true)"
  task8_runner_executable="$(/usr/sbin/lsof -a -p "$task8_runner_pid" \
    -d txt -Fn 2>/dev/null | awk '
      /^n/ && !found {sub(/^n/, ""); executable=$0; found=1}
      END {if (found) print executable}
    ')" || true
  if test -n "$task8_runner_executable"; then
    task8_runner_executable="$(realpath "$task8_runner_executable" 2>/dev/null || true)"
  else
    task8_runner_executable=""
  fi
  task8_run_dir="$(realpath "$task8_run_dir" 2>/dev/null || true)"
  task8_runner_command="$(/bin/ps -ww -p "$task8_runner_pid" \
    -o command= 2>/dev/null || true)"
  task8_expected_runner_prefix="$task8_runner_executable $task8_runner_entry --run-root $task8_run_dir --launch-fd "
  task8_runner_launch_fd="${task8_runner_command#"$task8_expected_runner_prefix"}"
  if ! printf '%s\n' "$task8_runner_launch_fd" | rg -q '^[0-9]+$'; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_PROCESS_IDENTITY_INVALID
    return 1
  fi
  task8_expected_runner_command="$task8_expected_runner_prefix$task8_runner_launch_fd"
  if test "$task8_runner_pid" -eq $$ || test "$task8_runner_pid" -eq "$PPID" \
      || test -z "$task8_runner_pgid" || test "$task8_runner_pgid" != "$task8_runner_pid" \
      || test "$task8_runner_pgid" = "$task8_self_pgid" \
      || test -z "$task8_runner_executable" \
      || test "$task8_runner_executable" != "$task8_external_python" \
      || test "$task8_runner_command" != "$task8_expected_runner_command"; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_PROCESS_IDENTITY_INVALID
    return 1
  fi

  kill -TERM -- "-$task8_runner_pid" 2>/dev/null || {
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_TERM_FAILED
    return 1
  }
  task8_runner_stop_attempt=0
  while kill -0 -- "-$task8_runner_pid" 2>/dev/null \
      && test "$task8_runner_stop_attempt" -lt 20; do
    task8_runner_stop_attempt=$((task8_runner_stop_attempt + 1))
    sleep 0.25
  done
  if kill -0 -- "-$task8_runner_pid" 2>/dev/null; then
    kill -KILL -- "-$task8_runner_pid" 2>/dev/null || {
      task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_KILL_FAILED
      return 1
    }
    task8_runner_stop_attempt=0
    while kill -0 -- "-$task8_runner_pid" 2>/dev/null \
        && test "$task8_runner_stop_attempt" -lt 20; do
      task8_runner_stop_attempt=$((task8_runner_stop_attempt + 1))
      sleep 0.25
    done
  fi
  if kill -0 -- "-$task8_runner_pid" 2>/dev/null; then
    task8_cleanup_fail BACKTEST_SMOKE_CLEANUP_PROCESS_STILL_LIVE
    return 1
  fi
  task8_runner_pid=""
}
task8_stop_sidecar() {
  if test -n "$task8_sidecar_pid" && kill -0 "$task8_sidecar_pid" 2>/dev/null; then
    task8_verify_sidecar_identity || return 1
    kill -TERM "$task8_sidecar_pid" 2>/dev/null || {
      task8_cleanup_fail BACKTEST_SMOKE_SIDECAR_TERM_FAILED
      return 1
    }
    task8_stop_attempt=0
    while kill -0 "$task8_sidecar_pid" 2>/dev/null && test "$task8_stop_attempt" -lt 20; do
      task8_stop_attempt=$((task8_stop_attempt + 1))
      sleep 0.25
    done
    if kill -0 "$task8_sidecar_pid" 2>/dev/null; then
      task8_verify_sidecar_identity || return 1
      kill -KILL "$task8_sidecar_pid" 2>/dev/null || {
        task8_cleanup_fail BACKTEST_SMOKE_SIDECAR_KILL_FAILED
        return 1
      }
      task8_stop_attempt=0
      while kill -0 "$task8_sidecar_pid" 2>/dev/null \
          && test "$task8_stop_attempt" -lt 20; do
        task8_stop_attempt=$((task8_stop_attempt + 1))
        sleep 0.25
      done
    fi
    if kill -0 "$task8_sidecar_pid" 2>/dev/null; then
      task8_cleanup_fail BACKTEST_SMOKE_SIDECAR_STILL_LIVE
      return 1
    fi
  fi
  if test -n "$task8_sidecar_pid"; then
    wait "$task8_sidecar_pid" 2>/dev/null || true
    task8_sidecar_pid=""
  fi
}
task8_cleanup() {
  task8_original_status="$1"
  task8_cleanup_status=0
  task8_stop_runner || task8_cleanup_status=1
  if test "$task8_cleanup_status" -eq 0 && test "$task8_cleanup_safe" -eq 1; then
    task8_stop_sidecar || task8_cleanup_status=1
  else
    printf '%s\n' \
      'FAIL: BACKTEST_SMOKE_CLEANUP_UNSAFE; sidecar and evidence retained' >&2
  fi
  if test "$task8_cleanup_status" -ne 0 || test "$task8_cleanup_safe" -ne 1; then
    printf '%s\n' 'FAIL: BACKTEST_SMOKE_CLEANUP_INCOMPLETE; evidence retained' >&2
    return 1
  fi
  return "$task8_original_status"
}
trap 'task8_exit_status=$?; trap - EXIT; task8_cleanup "$task8_exit_status"; exit $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

find "$task8_bundle_root" -xdev -type f -exec stat -f '%N|%z|%m' {} + \
  | LC_ALL=C sort >"$task8_tmp_dir/bundle.before"
test -s "$task8_tmp_dir/bundle.before"
task8_formal_snapshot "$task8_tmp_dir/formal.before.json"
mkdir -m 700 "$task8_runs_root"
task8_runs_root="$(realpath "$task8_runs_root")"
export GUIYI_BACKTEST_RUNS_ROOT="$task8_runs_root"

jq -n '{
  strategy_id: "example_future_smoke_v1",
  start_date: "2016-06-01",
  end_date: "2016-06-03",
  frequency: "1d",
  future_cash: "1000000",
  matching_type: "current_bar",
  margin_multiplier: "1",
  futures_commission_multiplier: "1",
  slippage_model: "PriceRatioSlippage",
  slippage: "0",
  parameters: {order_book_id: "IF1606", quantity: 1}
}' >"$task8_tmp_dir/request.json"

(
  cd "$task8_repo_root/services/quant-api"
  exec "$task8_sidecar_python" -m app.backtest.local_app
) >"$task8_tmp_dir/sidecar.stdout.log" 2>"$task8_tmp_dir/sidecar.stderr.log" &
task8_sidecar_pid=$!
task8_capture_sidecar_identity

task8_health_ready=0
task8_health_attempt=0
while test "$task8_health_attempt" -lt 30; do
  task8_health_attempt=$((task8_health_attempt + 1))
  if curl --noproxy '*' -fsS --connect-timeout 1 --max-time 3 \
      -o "$task8_tmp_dir/health.json" \
      http://127.0.0.1:8011/api/v1/backtests/health \
      && jq -e '
        .status == "ready" and .busy == false and
        .runner.available == true and .bundle_available == true and
        .runs_root_available == true and .registry_available == true and
        .research_only == true and .formal_evidence == false and
        .promotion_eligible == false and .error == null
      ' "$task8_tmp_dir/health.json" >/dev/null; then
    task8_health_ready=1
    break
  fi
  kill -0 "$task8_sidecar_pid" 2>/dev/null
  sleep 1
done
test "$task8_health_ready" -eq 1

task8_post_inflight=1
task8_post_curl_status=0
task8_post_http_status="$(curl --noproxy '*' -sS --connect-timeout 2 --max-time 10 \
  -H 'Content-Type: application/json' \
  --data-binary @"$task8_tmp_dir/request.json" \
  -o "$task8_tmp_dir/start.json" \
  -w '%{http_code}' \
  http://127.0.0.1:8011/api/v1/backtests/runs)" || task8_post_curl_status=$?
if test "$task8_post_curl_status" -ne 0; then
  exit "$task8_post_curl_status"
fi
task8_post_response_received=1
if test "$task8_post_http_status" != "202"; then
  exit 1
fi
task8_run_id="$(jq -er '.run_id' "$task8_tmp_dir/start.json")"
jq -e '.run_id | test("^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}$")' \
  "$task8_tmp_dir/start.json" >/dev/null
task8_run_dir="$task8_runs_root/$task8_run_id"
if test -f "$task8_runs_root/active.lock" \
    && test ! -L "$task8_runs_root/active.lock"; then
  task8_runner_pid="$(jq -er --arg task8_run_id "$task8_run_id" '
    select(.run_id == $task8_run_id) | .pid | select(type == "number" and . > 1)
  ' "$task8_runs_root/active.lock")"
  task8_runner_pgid="$(ps -o pgid= -p "$task8_runner_pid" | tr -d ' ')"
  test "$task8_runner_pgid" = "$task8_runner_pid"
fi
task8_post_identity_captured=1
task8_post_inflight=0

task8_terminal=0
task8_poll_attempt=0
while test "$task8_poll_attempt" -lt 180; do
  task8_poll_attempt=$((task8_poll_attempt + 1))
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 \
    -o "$task8_tmp_dir/detail.json" \
    "http://127.0.0.1:8011/api/v1/backtests/runs/$task8_run_id"
  task8_status="$(jq -er '.status' "$task8_tmp_dir/detail.json")"
  case "$task8_status" in
    running) sleep 1 ;;
    succeeded|failed|timed_out|interrupted) task8_terminal=1; break ;;
    *) exit 1 ;;
  esac
done
test "$task8_terminal" -eq 1

jq -e --arg task8_run_id "$task8_run_id" --arg task8_run_dir "$task8_run_dir" \
  --arg task8_repository_commit "$task8_repository_commit" \
  --arg task8_expected_strategy_sha256 "$task8_expected_strategy_sha256" '
  .run_id == $task8_run_id and .status == "succeeded" and
  .exit_code == 0 and .failure_code == null and
  .research_only == true and .formal_evidence == false and
  .promotion_eligible == false and
  .repository_commit == $task8_repository_commit and
  .strategy_sha256 == $task8_expected_strategy_sha256 and
  .strategy_id == "example_future_smoke_v1" and
  .requested_config == {
    strategy_id: "example_future_smoke_v1",
    start_date: "2016-06-01", end_date: "2016-06-03", frequency: "1d",
    future_cash: "1000000", matching_type: "current_bar",
    margin_multiplier: "1", futures_commission_multiplier: "1",
    slippage_model: "PriceRatioSlippage", slippage: "0",
    parameters: {order_book_id: "IF1606", quantity: 1}
  } and
  .effective_parameters == {order_book_id: "IF1606", quantity: 1} and
  .effective_config.base.start_date == "2016-06-01" and
  .effective_config.base.end_date == "2016-06-03" and
  .effective_config.base.frequency == "1d" and
  .effective_config.base.run_type == "b" and
  .effective_config.base.accounts.FUTURE == "1000000" and
  .effective_config.base.auto_update_bundle == false and
  .effective_config.base.rqdatac_uri == "disabled" and
  .effective_config.mod.sys_simulation.enabled == true and
  .effective_config.mod.sys_simulation.signal == false and
  .effective_config.mod.sys_transaction_cost.enabled == true and
  .effective_config.mod.sys_analyser.enabled == true and
  .effective_config.mod.sys_analyser.output_file == ($task8_run_dir + "/result.pkl") and
  .effective_config.mod.sys_analyser.report_save_path == ($task8_run_dir + "/report") and
  .effective_config.mod.sys_analyser.plot_save_file == ($task8_run_dir + "/equity.png") and
  .effective_config.mod.ams.enabled == false and
  .effective_config.mod.incremental.enabled == false and
  .result != null and (.result.trade_count | type) == "string" and
  .result.artifacts == {
    report_zip: true, result_pickle: true, equity_png: true,
    stdout_log: true, stderr_log: true, run_json: true
  }
' "$task8_tmp_dir/detail.json" >/dev/null

curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 \
  -o "$task8_tmp_dir/runs.json" \
  'http://127.0.0.1:8011/api/v1/backtests/runs?limit=100'
jq -e --arg task8_run_id "$task8_run_id" '
  length == 1 and .[0].run_id == $task8_run_id and .[0].status == "succeeded"
' "$task8_tmp_dir/runs.json" >/dev/null

test -d "$task8_run_dir"
test ! -L "$task8_run_dir"
for task8_required_file in \
  run.json result.json result.pkl equity.png stdout.log stderr.log strategy.py strategy_params.json; do
  test -f "$task8_run_dir/$task8_required_file"
  test ! -L "$task8_run_dir/$task8_required_file"
done
test -d "$task8_run_dir/report"
test ! -L "$task8_run_dir/report"
test -n "$(find "$task8_run_dir/report" -type f -print -quit)"
test ! -e "$task8_runs_root/active.lock"
test "$(shasum -a 256 "$task8_run_dir/strategy.py" | awk '{print $1}')" \
  = "$task8_expected_strategy_sha256"
cmp -s "$task8_strategy_source" "$task8_run_dir/strategy.py"
task8_run_count="$(find "$task8_runs_root" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
test "$task8_run_count" -eq 1

curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 \
  -o "$task8_tmp_dir/report.zip" \
  "http://127.0.0.1:8011/api/v1/backtests/runs/$task8_run_id/artifacts/report_zip"
test -s "$task8_tmp_dir/report.zip"
unzip -tq "$task8_tmp_dir/report.zip" >/dev/null

task8_stop_runner
task8_stop_sidecar
task8_formal_snapshot "$task8_tmp_dir/formal.after.json"
cmp -s "$task8_tmp_dir/formal.before.json" \
  "$task8_tmp_dir/formal.after.json"
find "$task8_bundle_root" -xdev -type f -exec stat -f '%N|%z|%m' {} + \
  | LC_ALL=C sort >"$task8_tmp_dir/bundle.after"
cmp -s "$task8_tmp_dir/bundle.before" "$task8_tmp_dir/bundle.after"
printf '%s\n' "RQALPHA_SMOKE_SUCCEEDED run_id=$task8_run_id"
```

该命令只读 Bundle，仅在授权的唯一 runs root 下产生一个 run，并通过强制
`auto_update_bundle=false` / `rqdatac_uri=disabled` / simulation-only / `signal=false` /
`ams=false` / `incremental=false` 配置将数据更新、真实订单与外部 application/runtime 路径
保持关闭。EXIT trap 总是先清理 runner、再停 sidecar；即使 POST 后尚未赋值
`task8_run_id/task8_runner_pid`，也只从本次新建且原先为空的 runs root 中恢复唯一
regular non-symlink lock，并在发送信号前交叉校验 lock/run/process-group 身份。
runner executable 必须等于规范化后的 configured external Python，`ps` 的完整 command
必须精确等于 `<python> <runner_entry> --run-root <run_root> --launch-fd <digits>`；
launch fd 必须是纯数字，不接受 suffix 匹配、任意 prefix 或额外参数。任一身份
无法唯一确认时只输出 `FAIL` 诊断，不向未确认 PID 发送信号。POST transport
尚在 inflight 且 lock 尚未出现时，cleanup 会有界等待；窗口结束后仍不能用终态
`run.json` 或明确的非 202 空根证明 runner 不存在时，必须保留 sidecar 由它继续拥有/
回收可能的子进程，且整次 smoke 以非零失败，绝不声称成功。外部 runs root 与
`/private/tmp/guiyi-rqalpha-smoke.*` 验收目录保留作当次证据，
清理属于另一次精确外部操作，不在本 smoke 授权内。真实 smoke 通过仍不表示 release、
Runtime-ready、策略有效、OOS 通过或 Candidate 可晋升。

## 工程、版本与文档一致性

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_health.py services/quant-api/tests/test_runtime_entry.py
python3 scripts/engineering/secret_scan.py --json
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
find deploy/launchd -type f -name '*.plist.template' -print0 | xargs -0 -n1 plutil -lint
git diff --check
git status --short
```

## 后端基线与拆分目录

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m "not isolated_postgresql" services/quant-api/tests
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='<isolated-postgresql-url>' UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q -m isolated_postgresql services/quant-api/tests
```

## Ruff 与 Mypy

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app/backtest services/quant-api/app/market_data services/quant-api/app/research services/quant-api/app/guiyi_cli services/quant-api/app/alerts services/quant-api/app/execution_review services/quant-api/app/runtime_entry.py services/quant-api/app/services/runtime_health.py services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py
```

## Research split tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_research_cli_parser_requests.py services/quant-api/tests/research/test_research_cli_candidate.py services/quant-api/tests/research/test_research_cli_convergence.py services/quant-api/tests/research/test_research_cli_mirror_robustness.py services/quant-api/tests/test_research_composition.py services/quant-api/tests/test_research_cli_boundaries.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_subing_lifecycle_contracts.py services/quant-api/tests/research/test_subing_lifecycle_transitions.py services/quant-api/tests/research/test_subing_lifecycle_causality.py services/quant-api/tests/research/test_subing_lifecycle_research_service.py services/quant-api/tests/research/test_subing_calibration_service.py services/quant-api/tests/research/test_subing_candidate_validation_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_n_structure_research_service.py services/quant-api/tests/research/test_n_candidate_validation_service.py services/quant-api/tests/research/test_jdj_research_service.py services/quant-api/tests/research/test_jdj_candidate_validation_service.py services/quant-api/tests/research/test_jdj_candidate_validation_calendar.py services/quant-api/tests/research/test_jdj_robustness_service.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/research/test_multi_candidate_robustness_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py
```

## Execution Review split tests

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache PYTHONPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review/test_mutations.py services/quant-api/tests/execution_review/test_corrections_reviews.py services/quant-api/tests/execution_review/test_queries.py services/quant-api/tests/test_execution_review_contracts.py services/quant-api/tests/test_execution_review_pnl.py services/quant-api/tests/test_execution_review_models.py services/quant-api/tests/test_execution_review_api.py services/quant-api/tests/test_execution_review_reconstruction.py services/quant-api/tests/test_execution_review_reconciler.py
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='<isolated-postgresql-url>' UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache PYTHONPATH=services/quant-api:packages/quant-core uv run --offline --project services/quant-api pytest -q services/quant-api/tests/execution_review/test_isolated_postgresql_concurrency.py services/quant-api/tests/alembic/test_execution_review_v1_migration.py
```

## 九个只读 Research CLI

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research subing-calibration --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research subing-lifecycle --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research n-structure --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research jdj-1m --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-validation --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-robustness --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-dossier --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research candidate-relationships --help
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --help
```

## MFM sequence forensic code path

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_main_force_mirror_v2.py services/quant-api/tests/test_indicator_registry_v1.py services/quant-api/tests/data_foundation/test_member_rank_snapshot.py services/quant-api/tests/data_foundation/test_member_rank_snapshot_builder.py services/quant-api/tests/data_foundation/test_main_force_mirror_v2_service.py services/quant-api/tests/research/test_main_force_mirror_v2_research_service.py services/quant-api/tests/data_foundation/test_market_api.py services/quant-api/tests/data_foundation/test_cli.py services/quant-api/tests/research/test_research_cli_parser_requests.py services/quant-api/tests/research/test_research_cli_mirror_robustness.py
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --symbol jm --series-kind actual_dominant --frequency 60m --since 2026-03-10 --through 2026-03-30 --forensic
```

## MFM sequence forensic active60 read-only evidence Gate

```bash
set -eu
tmp_dir="$(mktemp -d /private/tmp/guiyi-mfm-v2-sequence-forensic.XXXXXX)"
test -n "$tmp_dir"
test ! -L "$tmp_dir"
case "$(cd "$tmp_dir" && pwd -P)" in
  /private/tmp/guiyi-mfm-v2-sequence-forensic.*) ;;
  *) exit 1 ;;
esac
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  case "$symbol" in
    *[!a-z0-9_]*) exit 1 ;;
  esac
done < data/universe/active_products.txt
duplicate_symbol="$(awk 'NF { print }' data/universe/active_products.txt | sort | uniq -d | head -n 1)"
test -z "$duplicate_symbol"
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  command_status=0
  UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api guiyi research main-force-mirror-v2 --symbol "$symbol" --series-kind actual_dominant --frequency 60m --since 2023-01-01 --through 2026-08-20 >"$tmp_dir/$symbol.json" 2>"$tmp_dir/$symbol.stderr" || command_status=$?
  printf '%s\n' "$command_status" >"$tmp_dir/$symbol.status"
done < data/universe/active_products.txt
printf '%s\n' "$tmp_dir"
```

## MFM sequence forensic OS-temp fail-closed cleanup

```bash
set -eu
test ! -L "$tmp_dir"
real_dir="$(cd "$tmp_dir" && pwd -P)"
case "$real_dir" in
  /private/tmp/guiyi-mfm-v2-sequence-forensic.*) ;;
  *) exit 1 ;;
esac
unexpected_node="$(find "$real_dir" -mindepth 1 -maxdepth 1 ! -type f -print -quit)"
test -z "$unexpected_node"
unexpected_name="$(find "$real_dir" -mindepth 1 -maxdepth 1 -type f ! \( -name '*.json' -o -name '*.stderr' -o -name '*.status' \) -print -quit)"
test -z "$unexpected_name"
active_count="$(awk 'NF { count += 1 } END { print count + 0 }' data/universe/active_products.txt)"
file_count="$(find "$real_dir" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')"
test "$file_count" -eq "$((active_count * 3))"
while IFS= read -r symbol || [ -n "$symbol" ]; do
  [ -z "$symbol" ] && continue
  rg -qx "$symbol" data/universe/active_products.txt
  test -f "$real_dir/$symbol.json"
  test ! -L "$real_dir/$symbol.json"
  test -f "$real_dir/$symbol.stderr"
  test ! -L "$real_dir/$symbol.stderr"
  test -f "$real_dir/$symbol.status"
  test ! -L "$real_dir/$symbol.status"
done < data/universe/active_products.txt
rm -rf -- "$real_dir"
```

## Web

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
```

## OpenSpec

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

## Runtime 无副作用入口测试

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_runtime_entry.py services/quant-api/tests/test_runtime_health.py services/quant-api/tests/data_foundation/test_operational_universe.py services/quant-api/tests/data_foundation/test_live_market.py services/quant-api/tests/data_foundation/test_after_market.py services/quant-api/tests/data_foundation/test_market_read.py services/quant-api/tests/data_foundation/test_market_websocket.py
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```
