# 测试与验证入口

更新时间：2026-08-12

所有写入测试必须使用 `tmp_path`、临时 Canonical root 和隔离数据库；测试 URL 不得指向 Runtime 或
生产数据库。真实数据、Runtime switch 和通知不属于测试命令的隐含权限。

## 工程与仓库检查

```bash
python3 scripts/engineering/secret_scan.py --json
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q tests/engineering
find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
git diff --check
```

Secret scan 默认只扫描 `git ls-files`，只报告文件、行号和规则类别，不输出命中内容。

## 后端与前端基线

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

## OpenSpec

```bash
openspec validate --specs --strict --no-interactive
openspec list --json
```

已归档 change 只保留历史意图；当前行为合同只看 `openspec/specs/`。

## Data Foundation 只读验证

```bash
uv run --project services/quant-api guiyi data update --universe active --through 2026-08-11
uv run --project services/quant-api guiyi data refresh --symbol jm --since 2024-03-01 --through 2024-03-31
uv run --project services/quant-api guiyi data audit --symbol jm --through 2026-08-11
uv run --project services/quant-api guiyi data audit --universe active --through 2026-08-11
```

无 `--apply` 的 update/refresh 只规划，audit 始终只读。任何真实 RQData、PostgreSQL 或 Canonical 写入
仍需执行前范围明确的单次意图。

## Market Runtime V1

### 无副作用验证

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_operational_universe.py \
  services/quant-api/tests/data_foundation/test_live_market.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_market_read.py \
  services/quant-api/tests/data_foundation/test_market_websocket.py

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
```

`--render-only` 不安装、重载或启用 Runtime。禁止用 fixture、手工 after-market 或旧状态冒充自然触发。

### 最终隔离 Runtime 验收

部署属于受控外部操作。取得本次明确意图后，将 Runtime worktree 固定到已验证 commit，构建 Web，安装
API 依赖并仅执行一次对应 Runtime switch。部署后至少读回：

- Runtime clean/detached 且等于批准 commit；
- API/Web/Live/after-market 的 launchd 根只指向该 worktree；
- `operational_products.txt` 与 active 60 完全一致，Live subscription/heartbeat 与 after-market status
  均报告同一 60 品种集合；
- API、Web、Runtime health 和实际 Market 业务字段可读；
- Historical/Live seam 保持分离，Live 不写 Parquet，`auto_order=false`。

`--confirm-market-runtime` 才会启用或重载 Market Runtime 并更新 marker。完成或失败后，本次执行意图即
消耗；重试必须取得新的明确请求。

### 17:00 自然盘后验收

不得手工执行 `guiyi data after-market` 代替 launchd 证据。自然触发后只读核对：

- launchd `runs` 增加且 `.run/after-market-status.json` 的 products 精确为 operational 60；
- `status=passed`、`attempts=1|2`，或在真实非交易日精确为 `NON_TRADING_DAY`；
- 当天 TradingSession / MainContractMap 已推进，正式 rank1 与同日 Live snapshot 一致；
- Canonical edge 与 Web Historical/Live seam 随正式发布更新，Live 从未写入 Parquet；
- intended same-day Live 清理完成，随后 Runtime health 不再因旧 Session 报 `UNKNOWN=56`。

代码、fixture、render-only 或手工命令只能证明实现，不得写成自然盘后通过。

## 最终检查

```bash
git diff --check
git status --short
```
