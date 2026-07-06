# ROADMAP.md — 归一量化 V1 重构路线图

生成时间：2026-07-06
版本：V1 重构基线冻结版
当前阶段：阶段 1-D，固化 RQData PoC 结论；下一步进入阶段 2 JM 历史数据更新方案。

## 1. 当前总路线

归一量化 V1 是本地运行的期货量化研究、实时观察、信号提醒和 Web 复盘工作台。

当前路线：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL / vn.py CTA BacktestingEngine
-> FastAPI
-> Vue Web
-> K线展示 / 策略信号 / 回测报告 / 单笔复盘 / 人工观察
```

当前项目不是从零开始。已有 FastAPI、Vue Web、RQData ingest、Parquet/DuckDB/PostgreSQL、vn.py、K线 marker、信号扫描和复盘 note 等 MVP 资产，后续应优先复用。

## 2. V1 范围

V1 做：

- 研究和回测。
- 实时行情观察规划与后续实现。
- 策略信号只读提醒。
- Web Market 策略展示。
- 回测报告和单笔复盘。
- 人工观察。

V1 不做：

- 自动交易。
- 模拟盘自动接单。
- 无人值守交易。
- CTP / TqSdk 实盘执行。
- 云端 SaaS。
- 多用户权限。
- tick 高频和复杂盘口撮合。

V1.5 可远期考虑人工确认后的交易辅助；V2 才能讨论实盘执行候选，并且必须经过风控、模拟观察和人工确认机制。

## 3. 数据源口径

V1 active 数据入口只允许：

```text
source = rqdata / local_parquet
data_role = primary
quality_status != failed
```

TqSdk / CTP / TuShare / AKShare 不作为 V1 主链路。旧 TqSdk / 天勤数据最多作为历史 validation source；交易练习者数据最多作为 legacy_reference。

## 4. 当前历史资产

历史 V1-B / V1-Final 是可复用资产，不是当前执行主线。

已可复用：

- JM 2023-01-03 至 2025-12-31 的 1d / 15m / 5m / 1m 研究数据。
- JM 15m / 5m 短持有回测样板。
- vn.py CTA 回测适配、报告转换和入库链路。
- Web 报告、K线 marker、信号扫描和复盘 note 入口。
- Cloudflare Access 相关本地 health check 和文档准备项。

仍需注意：

- JM 数据需要后续更新到最新交易日。
- RQData 权限和接口能力阶段 1 只读 PoC 已完成，判定为 `PARTIAL`；核心历史数据权限可支撑阶段 2，但 sessions / continuous / ex_factor 空样本和 realtime wrapper 仍需后续确认。
- 实时 1m 入库、`signal_events`、企业微信提醒、Web Market 策略展示仍是后续任务。
- Cloudflare Access 本地 Web 访问仍需单独部署验收。

## 5. 当前阶段顺序

| 阶段 | 名称 | 状态 |
|---|---|---|
| 阶段 0 | V1 重构基线冻结 | done |
| 阶段 1 | RQData 权限与接口能力 PoC | done / partial accepted |
| 阶段 2 | JM 历史数据更新到最新交易日 | next |
| 阶段 3 | 数据版本 / manifest / checksum / quality_status 收敛 | 待做 |
| 阶段 4 | RQData 实时 1m 入库设计与实现 | 待做 |
| 阶段 5 | 1m 聚合多周期 | 待做 |
| 阶段 6 | 策略中心重构和苏冰 live_evaluator 接入 | 待做 |
| 阶段 7 | 通达信指标本地化 | 待做 |
| 阶段 8 | signal_events 信号事件化 | 待做 |
| 阶段 9 | 企业微信只读提醒 | 待做 |
| 阶段 10 | Web Market 策略展示 | 待做 |
| 阶段 11 | 本地长期运行 / worker / scheduler / health check | 待做 |
| 阶段 12 | Cloudflare Access 本地 Web 访问 | 待做 |
| 阶段 13 | Codex git commit / push 自动化 | 待做 |
| 阶段 14 | 可信回测主线复核 | 待做 |

完整阶段说明见 `docs/NEXT_STEPS.md`。

## 6. 策略路线

V1 优先策略方向：

- 苏冰课程策略。
- EMA21 趋势系统。
- 均线突破 + 趋势过滤。
- N 字结构 / 分型。
- 通达信指标本地化候选。

每个策略必须可追溯：

- `strategy_code`
- `strategy_version`
- 参数和参数版本
- 数据范围
- 数据源、`data_role`、`quality_status`
- 回测配置
- 信号来源
- 报告 ID

不得静默修改旧策略版本。

## 7. 风控和可信回测

策略和回测任务默认检查：

- 未来函数。
- 数据泄露。
- 过拟合。
- 成交时点。
- 手续费和滑点。
- 合约乘数和保证金。
- 最大回撤和连续亏损。
- raw metrics 与 trusted metrics 区分。
- cross-contract PnL 排除口径。

回测结果不等于实盘结果；实时提醒不等于可信回测结论。

## 8. Git / Codex 自动化

后续可在用户授权、测试通过、范围明确、无敏感文件时，由 Codex commit / push 到 `codex/*` 分支。

默认不允许：

- push 到 `main`。
- 提交 `.env`。
- 提交账号、密码、Token、API Key、license、通知地址或交易密钥。
- 在高风险任务中跳过 Plan 或用户确认。
