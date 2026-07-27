# TASK-2026-07-12-010：105 条 quality_warning 消费边界 Plan

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-010-quality-warning-consumption-boundary |
| 日期 | 2026-07-12 |
| 分支 | `codex/quality-warning-consumption-boundary-plan` |
| Base | TASK-2026-07-12-009-reference-metadata-gap-apply |
| 状态 | `DELIVERY_READY_PLAN_NO_WRITE` → 已由 TASK-011 实现 |
| 类型 | Plan only — 不改代码、不写 DB/Parquet |

## 目标

在 Stage 5-B reference metadata gap 已收口的前提下，为剩余 **105 条 `quality_warning`** 定义 Market / Backtest / Signal / Review 的消费边界，作为 TASK-011 代码实现的验收标准。

## 背景

Target coverage 当前状态：

```text
covered_passed=17203
covered_warning=105
metadata_gap=0
issue_register_rows=105
quality_warning=105
```

105 条 warning 来自 TASK-007 根因审计：15 个唯一 Parquet 文件的 stale processed summary 误报已修正为 warning 口径；**不得为覆盖率升级为 `passed`**。

Active 入口（不变）：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究默认使用 `quality_status=passed`。

## 核心决策

### Market（K 线工作台 / 行情 API）

| 规则 | 说明 |
|---|---|
| 允许读取 warning | `MarketDataReader` 默认 active 入口（`!= failed`），warning 资产可展示 K 线 |
| 必须返回质量字段 | API 响应包含 `quality.status`、`abnormal_price_count` 等；不静默吞掉 warning |
| 必须有质量提示 | 当 `quality.status=warning` 时，API `message` 与前端必须展示 warning 提示条 |
| 默认选中偏好 passed | 工作台默认合约选择优先 `quality_status=passed`（如 JM 15m passed） |

### Backtest（回测）

| 规则 | 说明 |
|---|---|
| 默认严格 passed-only | vnpy runner、V1-B 固定任务、bar 加载路径默认只接受 `passed` |
| warning 需显式 opt-in | `/backtests/run`、batch backtest 须 `allow_warning_quality=true` 才允许 warning |
| 任务配置 | `BacktestTaskConfig.quality_status=warning` 仅用于显式标记；vnpy 执行层仍拒绝非 passed bar |
| Trust audit | `strict_quality=True` 时对 warning 产出 audit warning，不包装为 passed |
| 报告持久化 | warning 回测若被允许，summary 必须保留 `quality_status: warning` |

### Signal（信号扫描 / Stage 9 前）

| 规则 | 说明 |
|---|---|
| 默认阻断 warning | `allow_warning_quality=false`（默认）；warning 返回 `data_quality_warning_blocked` |
| Stage 9 前不得静默放行 | 不得因 target coverage 有 warning 资产而自动进入提醒或企业微信 |
| JM V1-B 正式数据 | 正式 JM 扫描路径使用 passed 主连数据；warning 仅可在显式 opt-in 下测试 |

### Review（复盘）

| 规则 | 说明 |
|---|---|
| 可展示历史 note | 已有复盘记录不因数据 warning 被隐藏 |
| 记录来源质量 | review extra 写入 `data_quality_status`（来自 backtest report） |
| 不可作为信号证据 | warning 数据须在 extra 中带 `data_quality_caveat`，不得当作可信信号依据 |

### 全局禁止

- 不把 105 条 warning 升级为 `passed`
- 不写 DB / Parquet / manifest
- 不修改 `quality_status`
- 不授权 Stage 9、企业微信发送、live、自动交易

## TASK-011 代码改动范围

### 允许修改

| 文件 | 改动 |
|---|---|
| `services/quant-api/app/services/market_data_reader.py` | 增加 `passed_only` 参数 |
| `services/quant-api/app/services/market_workbench.py` | warning 时设置 API message |
| `services/quant-api/app/schemas/market.py` | 扩展 `MarketBarsQuality`（可选 warning reasons） |
| `services/quant-api/app/schemas/backtest.py` | warning 配置校验与 opt-in 语义 |
| `services/quant-api/app/backtest/service.py` | create_task 与 warning 边界一致 |
| `services/quant-api/app/services/review_center.py` | extra 写入 data_quality_status |
| `services/quant-api/tests/test_market_data_reader.py` | passed_only 测试 |
| `services/quant-api/tests/test_backtest_service_runner.py` | warning 边界测试 |
| `services/quant-api/tests/test_signal_scanner_api.py` | warning block 测试 |
| `apps/quant-web/src/pages/market/chart.vue` | warning 提示条 |
| `apps/quant-web/src/types/market.ts` | 类型同步（若扩展 schema） |

### 禁止修改

- ingest / quality repair / reference metadata apply
- 105 条 warning 的 Parquet 或 DB quality_status
- 策略逻辑、Stage 9、企业微信、live runtime、scheduler

## 验收标准（TASK-011）

1. `passed_only=True` 时 MarketDataReader 不读 warning 文件
2. Market API 在 warning 时返回可读 message，前端展示提示
3. Backtest 默认路径拒绝 warning；opt-in 路径保留 warning 标记
4. Signal 默认阻断 warning；opt-in 才放行
5. Review extra 含 data_quality_status 与 caveat
6. 105 条 warning 数量与 status 不变

## 测试命令

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_target_coverage_audit.py
uv run --project services/quant-api pytest -q services/quant-api/tests
git diff --check
```

## 关联任务

- 前置：TASK-009 reference metadata gap apply
- 后续：TASK-011 代码实现、TASK-012 Stage 8.6 pending 复核、TASK-013 数据部分总验收
