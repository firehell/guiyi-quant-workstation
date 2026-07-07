# 当前任务：STAGE-7-TDX-INDICATOR-RISK-REVIEW

生成时间：2026-07-07
任务性质：通达信指标本地化与未来函数 / 重绘风险审查

## 当前结论

`STAGE-7-TDX-INDICATOR-RISK-REVIEW` 已完成代码 / 文档级闭环。

本轮只审查并标注 `experiments/rqalpha_tdx_xma_bands` 通达信 XMA 通道 PoC 的指标风险，没有把 XMA 或派生信号接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。

核心结论：

- 原始 `XMA` 会读取当前 bar 之后的数据，存在未来函数和重绘风险。
- `ZK1 / ZD1 / ZD2`、`VAR23`、`XG`、`XG2` 均直接或间接依赖 `XMA`，不得作为可信回测或正式 signal 条件。
- `DDX`、`REF`、`MA`、`EMA` 当前实现不含未来函数，但只能作为 `candidate_after_rewrite`，后续必须经过 confirmed-bar 审查后才能进入候选。
- PoC 使用 RQAlpha bundle / `JM88`，不同于主项目 JM v2 active parquet，不可混作正式主链路证据。

## 本轮变更

### 1. PoC 风险元数据

更新：

- `experiments/rqalpha_tdx_xma_bands/xma_core.py`

新增：

- `indicator_risk_catalog()`

风险分类：

- `forbidden_for_backtest_signal`：`XMA`、`ZK1_ZD1_ZD2`、`VAR23`
- `observation_only`：`XG`、`XG2`、`CURRBARSCOUNT`
- `candidate_after_rewrite`：`DDX`、`REF`、`MA`、`EMA`

该函数只返回静态审查元数据，不改变任何指标计算结果。

### 2. Stage 7 审查文档

新增：

- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`

文档明确：

- 指标来源和文件范围。
- 每个指标是否存在未来函数、重绘、全序列预计算、`CURRBARSCOUNT` 语义风险。
- 原始 XMA / XMA 派生信号不得进入可信回测、正式 signal、live evaluator 或企业微信提醒。
- 如果后续要继续研究，需要另开 Stage 7.5 或 Stage 8 前置 Plan，把候选指标改写为 strictly backward-looking 版本。

### 3. 测试

新增：

- `services/quant-api/tests/test_tdx_xma_indicator_risk.py`

覆盖：

- `indicator_risk_catalog()` 明确标记 `XMA` 及派生信号风险。
- `xma()` 会读取未来 bar。
- 修改未来尾部数据会改变历史位置的 `XMA` 结果。
- `REF`、`MA`、`EMA` 不被误标为未来函数。

## 本轮没有做

- 没有实现 Cloudflare / Tunnel / Access / 远程访问。
- 没有做本地长期运行、worker、scheduler、health check 完整验收。
- 没有新增 Alembic migration。
- 没有写 `signal_events`。
- 没有接企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有接 WebSocket 推送。
- 没有把通达信 XMA 接入 `SignalScanner`、`LiveSignalEvaluator`、Backtest 或 Web Market。
- 没有运行 RQData 写入、下载、sync、ingest。
- 没有覆盖 JM v1 / JM v2 parquet。
- 没有自动下单或生成订单草稿。

## 验证结果

TDD 红灯：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
```

结果：

- 首次运行：`4 failed`，其中核心失败为缺少 `indicator_risk_catalog()`；同时暴露 `period=3` 断言不符合当前窗口实现。
- 修正测试窗口为 `period=5` 后再次运行：`2 failed, 2 passed`，仅剩缺少 `indicator_risk_catalog()` 的预期失败。

最终验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api ruff check experiments/rqalpha_tdx_xma_bands/xma_core.py services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

结果：

- `test_tdx_xma_indicator_risk.py`：`4 passed`。
- `test_live_signal_evaluator.py` + `test_signal_scanner_api.py`：`11 passed`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 风险与未完成项

- `XMA` 本质含未来 bar，不能通过风险标注或测试变成可信回测指标。
- `tdx_xma_bands_strategy.py` 仍是 RQAlpha 研究 PoC，不进入主项目正式报告链路。
- `CURRBARSCOUNT` 的通达信图表语义与当前 PoC 简化实现不完全一致，仍需单独验证。
- 若要继续迁移通达信指标，应另开小阶段设计 backward-looking 改写版本和独立策略版本号。

## 下一步

建议进入：

```text
Stage 8：signal_events 信号事件化
```

Stage 8 不应直接接入原始 XMA PoC；如需要 XMA 类观察指标，先做 Stage 7.5 改写 / 审查计划。

## GPT 同步文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
- `experiments/rqalpha_tdx_xma_bands/xma_core.py`
- `services/quant-api/tests/test_tdx_xma_indicator_risk.py`
