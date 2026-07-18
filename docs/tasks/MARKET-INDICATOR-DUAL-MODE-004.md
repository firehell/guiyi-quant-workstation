# MARKET-INDICATOR-DUAL-MODE-004

## Task Metadata

| Field | Value |
|---|---|
| Task ID | `MARKET-INDICATOR-DUAL-MODE-004` |
| Task branch | `codex/market-indicator-dual-mode-004` |
| Risk Level | L2 |
| Status | `COMPLETED / MARKET_RESEARCH_MODE_READY / INDICATOR_BINDING_CONSISTENT` |

## 目标

将 Market / Indicator 收口为明确的 Browser observation 与 Research strict 两种访问契约，同时保证 bars、EMA、MACD 和 warm-up 使用同一冻结行情 lineage。

## 实现结果

- coverage、bars、EMA、MACD 增加 `access_mode=browser|research`，默认 Browser；`data_mode=historical|live` 保持独立。
- Browser 使用 non-failed observation quality，warning/unchecked 可展示但不标记严格研究可用。
- Research 强制 Profile，由 `ProfileLineageResolver` 校验 binding、passed quality、identity、文件和 range；稳定错误码返回 422，lineage 漂移返回 409。
- 统一响应 lineage 包含 file ID/version、quality policy、immutable snapshot、token、source/view role 和 actual/continuous contract。
- EMA/MACD 请求必须回传 bars 的 expected file ID/token；visible 与 warm-up 使用固定资产。
- 后端仅合并同 key 同值重复；不同值冲突返回脱敏 asset evidence。Web 分页遇到异值重复保持原图并提示冲突。
- Web 支持模式与 Profile 选择、route 恢复、warning/strict 状态；Live 强制 Browser 并清除 Profile。

## 验证

```text
backend pytest: 38 passed, 0 failed, 0 skipped
frontend node tests: 59 passed, 0 failed, 1 skipped
frontend build: passed
ruff: passed
browser smoke: Browser warning / Research no-Profile blocked / Research passed / route reload / Live isolation passed
browser console: 0 errors, 0 warnings
git diff --check: passed
```

前端唯一 skip 是既有的可选 `HTDY_GOLDEN_BUNDLE` 环境项，与本任务无关。

## 边界

未新增 migration，未写 canonical PostgreSQL、Parquet、manifest、Profile binding 或 live runtime；未修改 Signal、Review、Backtest、actual mapping、策略参数、历史报告或行情资产。全局状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。
