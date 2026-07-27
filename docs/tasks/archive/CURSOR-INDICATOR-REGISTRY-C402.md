# CURSOR-INDICATOR-REGISTRY-C402

更新时间：2026-07-19

## 结论

状态：`COMPLETED / CURSOR_INDICATOR_REGISTRY_IMPLEMENTED`

扩展指标生命周期与 Registry V1 契约；未改数值算法、策略参数、report 14、DB、Parquet、Profile binding、live evaluator、SignalEvent 或企业微信。

**不得**宣称 `INDICATOR_REGISTRY_V1_READY`（留给 Codex 独立复核）。

## 变更摘要

- 生命周期：`draft|compatibility_validated|validated|strategy_candidate|live_candidate|alert_capable|observation_only|retired`
- 注册：EMA validated；MACD/ATR `compatibility_validated`；HTDY original / strict 双 code；JM frozen policy
- API：`require_formal_policy` / `definition_to_metadata` / capability 校验 fail-closed
- 算法文件 `ema.py` / `macd.py` / `atr.py` 未改；输出 version 字符串不变

## 验证

```text
37 passed
git diff --check
```

## 下一入口

Cursor Wave `C4-03`（低风险调用方条件迁移或 observation 降级）。
