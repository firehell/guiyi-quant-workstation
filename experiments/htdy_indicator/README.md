# HTDY 原始 Observation-Only PoC

本目录复刻 `huotian_dayou_original_v0` 通达信原始公式的数值输出，用于后续 Web 观察层对齐和 Golden Sample 比对。

边界：

- `status=observation_only`
- `repainting_risk=known`
- `backtest_capable=false`
- `live_capable=false`
- `alert_capable=false`
- 不生成订单、不写 `signal_events`、不触发企业微信、不接正式策略链路

## 输出字段

PoC 输出完整原始观察字段：

```text
ZK1, ZD1, ZD2, 黄K, 白K, 买多信号, 卖空信号,
VAR23, 回调买, XG, DDX, V2, V5, V10, V20, DY, DY2, XG2, XG2_DRAWTEXT
```

`CAPITAL` 默认按期货场景 `0` 分支；`FROMOPEN` 默认固定为 `1.0`，两者都会写入 metadata。`CURRBARSCOUNT` 在本 PoC 中按“每一行都视为图表末 bar”处理，只用于复刻观察字段，不代表 live 或回测语义。

## 运行

无输入文件时使用 synthetic sample：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/export_htdy_original.py --format json
```

读取本地 CSV：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/export_htdy_original.py \
  --input /path/to/bars.csv \
  --output /path/to/htdy_original.csv \
  --format csv
```

CSV 需要字段：

```text
datetime,open,high,low,close,volume
```

## 风险说明

本 PoC 故意保留 `XMA(XMA(...))` 原始形态。未来尾部变化会改变历史位置的 `ZK1/ZD1/VAR23` 等值，因此输出只能作为人工观察和对齐基准，不得进入可信回测、历史扫描、live evaluator、正式报告或提醒链路。

## Strict V1 研究候选

第 3 步新增：

- `htdy_strict_core.py`
- `huotian_dayou_strict_v1`
- `status=strict_research_candidate`
- `xma_replacement_policy=double_trailing_ema`

strict v1 使用 trailing double EMA 替代原始 `XMA(XMA(...))`：

```text
XMA(XMA(H,25),25) -> trailing EMA(trailing EMA(H,25),25)
XMA(XMA(L,25),25) -> trailing EMA(trailing EMA(L,25),25)
VAR23 双层 XMA -> trailing double EMA
```

输出字段仅限：

```text
ZK1, ZD1, ZD2, 黄K观察, 白K观察, 三连黄K观察, 三连白K观察,
VAR23_STRICT, 回调买观察, XG观察
```

`XG2`、`DY/DY2`、`DDX/V2/V5/V10/V20` 暂不进入 strict v1。strict v1 仍不接入正式策略、回测、扫描、live、数据库、报告或通知链路。

验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_strict_core.py
```

## Golden Sample

第 4 步固定 `JM.MAIN 15m`、`2026-06-24 22:30` 至 `2026-07-09 23:00` 的 256 根 `primary/passed` 真实 K 线。真实 RQData 文件只读引用，不提交到 Git。

```bash
uv run --project services/quant-api python experiments/htdy_indicator/golden_sample.py \
  --export-web-bundle /tmp/htdy_golden_web_bundle.json

HTDY_GOLDEN_BUNDLE=/tmp/htdy_golden_web_bundle.json \
  pnpm --dir apps/quant-web exec node --test tests/htdyGoldenSample.test.ts
```

当前状态为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。自动数值验收和通达信截图视觉 oracle 已通过；未提供通达信数值导出，因此不声明逐点数值 oracle pass。详见 `docs/strategy_specs/htdy/GOLDEN_SAMPLE_ACCEPTANCE.md`。

## Offline Candidate Eval

第 5 步新增只读离线候选评估：

- `offline_candidate_eval.py`
- `strategy_code=huotian_dayou_strict`
- `strategy_version=v0.1.0-offline`
- `candidate_policy=strict_v1_15m_offline_v0`
- `execution_scope=offline_comparison_only`

运行：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/offline_candidate_eval.py \
  --output-json /tmp/htdy_strict_offline_candidate.json \
  --output-markdown /tmp/htdy_strict_offline_candidate.md
```

该 runner 只读现有 `primary/passed` JM 15m parquet，输出 candidate events、lineage、checksum 和能力边界；不写 DB、不创建 backtest task、不写信号事件、不接 scanner / live / 企业微信。

## Formal Backtest Candidate Dry-Run

第 6 步新增只读正式回测候选 dry-run：

- `formal_backtest_candidate.py`
- `strategy_code=huotian_dayou_strict`
- `strategy_version=v0.1.0-backtest-candidate`
- `candidate_policy=strict_v1_15m_formal_candidate_v0`
- `execution_scope=formal_backtest_candidate`
- `fill_policy=signal_on_close_fill_next_bar_open`

运行：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/formal_backtest_candidate.py \
  --output-json /tmp/htdy_formal_candidate_dry_run.json \
  --output-markdown /tmp/htdy_formal_candidate_dry_run.md
```

该 helper 只读现有 `primary/passed` JM 15m parquet，校验 lineage 后运行 `huotian_dayou_strict / v0.1.0-backtest-candidate`，输出 normalized `trades / orders / strategy_execution_events / summary`，用于后续人工和 GPT 安全复核。它不创建 backtest task，不写 `BacktestReport`，不接 `strategy_signals`、`signal_events`、scanner、live evaluator 或企业微信；`report_id=14` 只作为冻结历史基线，不是 HTDY 写入目标。
