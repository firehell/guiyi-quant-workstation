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
