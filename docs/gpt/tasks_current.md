# 当前任务同步：STAGE-7-TDX-INDICATOR-RISK-REVIEW

生成时间：2026-07-07

## 最新状态

`STAGE-7-TDX-INDICATOR-RISK-REVIEW` 已完成代码 / 文档级闭环。

本轮只审查通达信 XMA 通道 PoC 的指标风险，没有把 XMA 或派生信号接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。

## 关键输出

新增：

- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
- `services/quant-api/tests/test_tdx_xma_indicator_risk.py`

更新：

- `experiments/rqalpha_tdx_xma_bands/xma_core.py`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 实现结论

新增 `indicator_risk_catalog()`，作为通达信 XMA PoC 的静态风险元数据：

- `forbidden_for_backtest_signal`：`XMA`、`ZK1_ZD1_ZD2`、`VAR23`
- `observation_only`：`XG`、`XG2`、`CURRBARSCOUNT`
- `candidate_after_rewrite`：`DDX`、`REF`、`MA`、`EMA`

核心边界：

- 原始 XMA / XMA 派生信号不得进入可信回测或正式 signal。
- PoC 结果不可写入正式报告链路。
- 后续如要迁移，需要先改写为 strictly backward-looking 版本并单独审查。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api ruff check experiments/rqalpha_tdx_xma_bands/xma_core.py services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

阶段 TDD 记录：

- 红灯确认：缺少 `indicator_risk_catalog()` 时新增测试失败。
- 绿灯确认：新增风险元数据后 `test_tdx_xma_indicator_risk.py` 通过。

结果：

- `test_tdx_xma_indicator_risk.py`：`4 passed`。
- `test_live_signal_evaluator.py` + `test_signal_scanner_api.py`：`11 passed`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 本轮没有做

- 没有实现 Cloudflare / Tunnel / Access / 远程访问。
- 没有新增 migration。
- 没有写 `signal_events`。
- 没有接企业微信。
- 没有接 WebSocket 推送。
- 没有把通达信 XMA 接入正式信号、回测、live evaluator 或 Web Market。
- 没有运行 RQData 写入或覆盖任何 JM parquet。
- 没有自动下单或生成订单草稿。

## 下一步建议

下一步进入 Stage 8 `signal_events` 信号事件化；不要直接把原始 XMA PoC 接入 Stage 8。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
- `experiments/rqalpha_tdx_xma_bands/xma_core.py`
- `services/quant-api/tests/test_tdx_xma_indicator_risk.py`
