# 测试与验证入口

更新时间：2026-08-11

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

## Market Runtime V1 验证分级

### 1. 本地渲染与测试（无外部副作用）

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/test_runtime_health.py

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-live.plist
plutil -lint .run/launchd/com.guiyi.quant-after-market.plist
uv run pytest -q tests/engineering/test_market_runtime_launchd.py
```

上述仅覆盖 fixture、mock、仓库 `.run` 渲染和 plist 语法；不得作为 Runtime 启用、重载或数据写入授权。禁止在
该级验证中调用 `--confirm-market-runtime`、`guiyi runtime live` 或 `guiyi data after-market`。
`--render-only` 与 `--confirm-load` 不会创建或改变 `.run/market-runtime-enabled`；只有成功执行
`--confirm-market-runtime` 才会原子写入该固定本地标记，供 API 健康端点跨进程判断 Live Runtime 已启用。

### 2. 临时 develop 部署重载（受控外部操作）

当前开发期 launchd 临时直接运行主 `develop` 工作区。源码修改不会自动进入正在运行的进程：Web 变更需先完成
测试和构建，再重载 Web；API 或 Live 变更需先完成对应测试，再重载目标服务。每一次重载都必须取得新的、范围明确
的一次性执行意图；不得把前一次启用、重载或只读检查复用为本次授权。

重载后至少读回：

- launchd 实际工作目录仍是主 `develop` 工作区；
- 目标服务健康端点和根页面可用；
- 未修改 `operational_products.txt`、`auto_order=false`、Canonical/Live 边界或其他受控范围。

该级证据只说明当前开发副本已加载指定变更。由于 `develop` 可继续移动或处于 dirty 状态，不能替代最终隔离 Runtime
的 exact-commit 验收，也不能据此声明 release、Runtime promotion 或设计文档闭环。

### 3. 最终隔离 Runtime 验收（独立人工 Gate）

代码与文档收口后，重新创建独立、clean、detached 于精确批准 commit/tag 的 Runtime worktree，再执行最终验收。除即时
测试和浏览器检查外，至少保留以下自然证据：

- 10:15 BREAK 与 10:31 首根 completed bar 自然恢复；
- 17:00 launchd 自然任务完整结束、清理、rank1 reconciliation 与前端 seam；
- 周末或非交易日自然行为。

手工执行 `guiyi data after-market`、fixture、旧状态或受控重跑不能代替 17:00 自然完成证据。最终验收通过也不自动授权
合并 `main`、创建 tag/release 或 Runtime promotion。

2026-08-11 已在临时直连 `develop@839d11ad` 的开发副本形成 10:15 BREAK / 10:31 恢复与 17:00
盘后完整收口的自然 canary：盘后一次尝试通过、四品种 Canonical 前进、rank1 reconciliation、Live
清理和已打开 Web 页面的 seam 自动更新均已读回。该证据用于关闭开发态 canary，不替代本节要求的最终
clean detached exact-commit Runtime 复验。真实浏览器在同一 AG2610 actual_dominant 15m 页面连续
拖拽，已从 1237 bars 加载到 24037 bars，coverage 起点进入 `2023-11-20T01:46:00Z`，console 无
warning/error；周末/非交易日证据仍待自然形成。

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
