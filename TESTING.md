# 测试与验证入口

更新时间：2026-08-09

所有数据写入测试使用 `tmp_path`、临时 Canonical root 和隔离数据库；测试 URL 不得指向
Runtime/生产数据库。

## DFD-01 文档合同验证

```bash
openspec validate converge-canonical-data-foundation --strict --no-interactive
openspec status --change converge-canonical-data-foundation --json
git diff --check
```

对 `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`、
`docs/DATA_CENTER.md`、`docs/tasks/GY-DATA-CORE-V2.md` 和 active OpenSpec 扫描已退出的旧术语。允许
出现“已退出”“历史”或“未执行”的边界说明；不得仍作为 active contract。

## 后端与前端基线

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py

npm --prefix apps/quant-web test
npm --prefix apps/quant-web run build
```

## Market Runtime V1（本地/无外部副作用）

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_runtime_health.py

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
uv run pytest -q tests/engineering/test_market_runtime_launchd.py
```

上述仅覆盖 fixture、mock、仓库 `.run` 渲染和 plist 语法；不得作为 Runtime 启用或数据写入授权。禁止在
本地验证中调用 `--confirm-market-runtime`、`guiyi runtime live` 或 `guiyi data after-market`。
`--render-only` 与 `--confirm-load` 不会创建或改变 `.run/market-runtime-enabled`；只有成功执行
`--confirm-market-runtime` 才会原子写入该固定本地标记，供 API 健康端点跨进程判断 Live Runtime 已启用。

DFD-03 之后补充 `20260808_0035:20260808_0036 --sql` 和隔离 PostgreSQL migration 测试。DFD-05
完成后，最终无写入 CLI smoke 为：

```bash
uv run --project services/quant-api guiyi data update --universe active --through 2026-08-07
uv run --project services/quant-api guiyi data refresh --symbol jm --since 2024-03-01 --through 2024-03-31
uv run --project services/quant-api guiyi data audit --symbol jm
uv run --project services/quant-api guiyi data audit --universe active
```

在 DFD-05 前，这三条 target CLI 不构成当前实现已完成的证据。真实 `--apply`、正式数据库、
Canonical 或 RQData 均不属于本地验证。

## 最终检查

```bash
git diff --check
git status --short
```

DFD-06 负责最终 active-reference 扫描；Alembic history、归档 OpenSpec 和 Git history 可以保留历史名称。
