# V1 重构验收清单

> 范围：RQData + standard Parquet + DuckDB + vn.py CTA 回测 + FastAPI + Vue Web 研究闭环。  
> 边界：V1 不做实盘、不做自动下单、不接 CTP / TqSdk 交易接口。

---

## 0. 当前 V1-B 验收目标

当前阶段：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

V1-B 必须验收：

```text
JM 最近 3 年真实数据
→ 1d / 15m / 5m 标准 K线
→ 日线定方向
→ 15m 独立入场
→ 5m 独立入场
→ 持有 5-8 根本周期 K线
→ 止损退出
→ 回测报告入库
→ Web 资金曲线 / 回撤曲线 / 交易明细
→ K线买卖点 marker
→ 单笔交易复盘 note
→ 信号扫描提醒
```

V1-B 安全边界：

- 信号扫描只提醒，不自动下单。
- 不接 CTP / TqSdk 交易接口。
- 不把回测结果等同实盘结果。
- 不使用 `quality_status=failed` 或非 `primary` 数据做正式回测。

V1-B 验收清单：

```text
[ ] JM 3 年真实数据可查询
[ ] 日线方向只使用已确认日线
[ ] 15m 入场链路可独立回测
[ ] 5m 入场链路可独立回测
[ ] 15m 持有 5-8 根 15m K线
[ ] 5m 持有 5-8 根 5m K线
[ ] 行情不利时按止损退出
[ ] 回测报告、交易明细、资金曲线、回撤曲线入库
[ ] Web 展示报告、曲线和交易明细
[ ] K线显示买卖点 marker
[ ] 单笔交易可创建复盘 note
[ ] 信号扫描只提醒，不自动下单
```

---

## 1. 如何运行后端 demo

后端端到端 demo 位于：

```text
experiments/vnpy_rqdata_demo/
```

环境检查：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --check-env
```

样例模式：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --sample
```

说明：

- `--check-env` 只检查 RQData / vn.py 等环境状态。
- `--sample` 不需要真实 RQData 账号，不读取真实 `data/`。
- demo 输出写入 `experiments/vnpy_rqdata_demo/output/`。
- demo 是研究验证，不是正式回测结论。
- demo 不调用 CTP、TqSdk 实盘、vn.py gateway 或任何交易接口。

---

## 2. 如何创建回测任务

API：

```text
POST /api/backtests/tasks
```

最小请求示例：

```json
{
  "engine_type": "vnpy",
  "task_type": "single",
  "symbol": "rb2405",
  "exchange": "SHFE",
  "interval": "60m",
  "start": "2024-01-01T00:00:00Z",
  "end": "2024-06-30T00:00:00Z",
  "strategy_class_path": "guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy",
  "strategy_parameters": {
    "ema_period": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14
  },
  "rate": 0.0001,
  "slippage": 1,
  "size": 10,
  "pricetick": 1,
  "capital": 100000,
  "data_role": "primary",
  "research_only": false,
  "quality_status": "passed"
}
```

规则：

- 默认 `engine_type=vnpy`。
- 默认 `data_role=primary`。
- `validation` / `legacy_reference` 必须显式传入，并设置 `research_only=true`。
- `quality_status=failed` 的数据不得进入回测。
- `live` / `real` / `trading` / `auto_order` 类型任务会被拒绝。

---

## 3. 如何查看回测报告

API：

```text
GET /api/backtests/reports
GET /api/backtests/reports/{report_id}
GET /api/backtests/reports/{report_id}/trades
GET /api/backtests/reports/{report_id}/equity-curve
GET /api/backtests/reports/{report_id}/drawdown-curve
```

Web：

```text
http://127.0.0.1:5173/backtest
```

报告页应至少展示：

- 初始资金、最终权益、总收益率、年化收益。
- 最大回撤、胜率、盈亏比、交易次数、最大连续亏损。
- 总手续费、总滑点。
- 资金曲线、回撤曲线。
- 交易明细和 K线买卖点 marker。

必须显示：

```text
回测结果不等于实盘结果，实盘前必须模拟和小资金验证。
```

---

## 4. 当前不做实盘说明

V1 只做研究闭环：

```text
数据下载
→ 数据清洗
→ 策略配置
→ 回测验证
→ 回测报告
→ 单笔复盘
→ 信号扫描
→ 人工观察
→ 策略迭代
```

V1 禁止：

- 自动实盘。
- 自动下单。
- 信号直接触发实盘委托。
- 接 CTP / TqSdk 交易接口。
- tick 高频回测。
- 复杂盘口撮合。
- 修改 vn.py 源码。

信号扫描只记录信号快照并展示解释；复盘中心只记录交易复盘备注。

---

## 5. 依赖清理结论

当前 `services/quant-api/pyproject.toml` 中：

| 依赖 | V1 状态 | 处理 |
|---|---|---|
| `rqdatac` | V1 主数据源 SDK | 保留默认依赖 |
| `vnpy` | V1 CTA 回测底座 | 保留默认依赖 |
| `tqsdk` | V2 候选 / 历史 validation 工具 | 暂保留默认依赖，并在 pyproject 注释标记 candidate / legacy |
| `tushare` | 后期辅助数据候选 | 暂保留默认依赖，并在 pyproject 注释标记 candidate |

本次不移动到 optional dependencies，原因：

- 仓库仍保留 `services/quant-api/app/services/tqsdk_ingest/` 历史模块和测试。
- 移除或 optional 化会改变安装和 CI 语义，需要单独依赖专项任务。
- 当前 V1 主链路不会默认调用 TqSdk / TuShare。

后续建议：

```text
P2-deps: 把 tqsdk / tushare 拆到 optional dependency group，并给历史脚本加显式安装说明。
```

---

## 6. 敏感词扫描口径

建议每次交接前运行：

```bash
rg -n "password|token|api_key|secret|CTP|AuthCode|TqAuth|TqAccount" . \
  --glob '!data/**' \
  --glob '!apps/quant-web/dist/**' \
  --glob '!services/quant-api/.venv/**' \
  --glob '!**/__pycache__/**'
```

解释：

- 文档和 `.env.example` 中允许出现占位符和禁止事项说明。
- 不允许出现真实账号、密码、API Key、交易密码、AuthCode。
- `.env` 不提交、不纳入文档示例正文。

---

## 7. 最终 V1 重构验收清单

### 数据

- [x] RQData 明确为 V1 主数据源。
- [x] `data_role=primary` 是正式回测默认口径。
- [x] `validation` / `legacy_reference` 必须显式选择并标记研究用途。
- [x] `quality_status=failed` 不进入默认回测。
- [x] TqSdk / TuShare 不作为 V1 主链路。

### 回测

- [x] vn.py CTA 明确为 V1 回测底座。
- [x] vn.py adapter / runner / result converter 已有测试覆盖。
- [x] 回测任务 API 支持创建和查询。
- [x] 报告 API 支持报告详情、交易明细、资金曲线、回撤曲线。
- [x] 回测报告展示“不等于实盘结果”的提示。

### 策略

- [x] 苏冰 EMA21 vn.py 策略草稿存在。
- [x] 策略默认参数 JSON 可加载并通过 schema 校验。
- [x] 策略测试覆盖未来函数风险：当前决策不依赖未来 K 线。

### Web

- [x] Web 回测页面可创建任务和查看任务状态。
- [x] Web 报告页可展示指标、曲线、交易明细和 K线 marker。
- [x] 信号扫描页展示信号解释并明确不自动下单。
- [x] 复盘中心可从回测交易创建单笔复盘。

### 安全

- [x] V1 不接实盘。
- [x] V1 不写自动下单逻辑。
- [x] V1 不调用 CTP / TqSdk 实盘交易接口。
- [x] 不修改 vn.py 源码。
- [x] 不提交真实凭据。

### 验证命令

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```

---

## 8. 剩余风险

1. `.env.example` 已统一为 RQData / Local Parquet V1 主链路；TqSdk / TuShare / CTP 字段保留为默认禁用的候选占位。
2. `tqsdk` / `tushare` 仍是默认依赖，后续建议拆为 optional dependency。
3. vn.py 在不同本地环境下可能存在安装或底层依赖差异，需要保留清晰错误提示。
4. 真实 RQData 下载、夜盘周期合成、主力映射和交易参数质量仍需要更大样本验证。
5. 回测结果只能作为研究证据，不可直接等同实盘表现。
