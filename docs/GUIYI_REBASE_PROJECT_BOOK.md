# 归一量化 V1 重构项目书

生成时间：2026-07-06
用途：冻结“归一量化 V1 重构版本”的 canonical baseline，供 ChatGPT / Codex / Cursor 后续拆任务和接手使用。
敏感信息：本文不包含账号、密码、Token、API Key、license、webhook URL 或交易密钥。

## 1. 新项目定位

归一量化是本地运行的国内期货量化研究、行情观察、策略信号提醒、回测复盘工作站。当前不是从零开始，而是在已有 MVP 上收敛重构。

V1 第一版目标是：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL / vn.py CTA BacktestingEngine
-> FastAPI
-> Vue Web
-> K线展示 / 策略信号 / 回测报告 / 单笔复盘 / 人工观察
```

V1 不自动下单，不做模拟盘自动接单，不做无人值守交易。

## 2. 用户开发约束

- 用户兼职开发，工作日可投入时间有限，任务必须小步、可验证、可回滚。
- 用户通过 RemoteView 远程控制家中 Mac mini，让 Codex 在本地仓库执行开发。
- ChatGPT 负责需求分析、阶段拆分、Prompt 和外部审查；Codex 负责仓库内修改、测试和交付摘要；Cursor / GitHub Desktop 做人工检查和 checkpoint。
- 后续任务必须减少人工搬运，每轮只覆盖一个功能域。

## 3. 现有 MVP 可复用资产

已有资产应优先复用，不推倒重来：

- FastAPI 后端、SQLAlchemy 模型、Alembic 基础、Redis/RQ 任务骨架。
- Vue 3 + Vite + TypeScript + Naive UI Web 工作台。
- RQData ingest、标准 Parquet、DuckDB、PostgreSQL 数据链路。
- vn.py CTA 回测适配、ResultConverter、回测报告入库。
- Market K线查询、K线 marker、回测交易明细、复盘 note。
- 信号扫描页面和后端扫描入口。
- 本地 `/healthz` 访问准备和 Cloudflare Access 文档。

这些能力是重构基线，不代表实时 1m 入库、`signal_events`、企业微信提醒或 Cloudflare 外部访问已经全部完成。

## 4. V1 第一版产品目标

V1 第一版聚焦：

- RQData / Local Standard Parquet 主链路。
- JM 数据更新到最新交易日。
- 实时 1m 行情观察规划与后续实现。
- 5m / 15m / 30m / 1h / 日线 / 周线确认收盘后的策略判断。
- 策略买卖点只读提醒。
- Web Market 工作台展示合约 K线、主图 marker、副图指标和策略切换。
- 回测报告入库、Web 展示和单笔交易复盘。

## 5. V1 不做项

V1 明确不做：

- 自动下单。
- 模拟盘自动接单。
- 无人值守交易。
- AI 自动生成策略并直接交易。
- CTP / TqSdk 实盘执行。
- 多用户 SaaS、手机 App、云端生产部署。
- tick 高频回测和复杂盘口队列撮合。
- 把实时提醒表现写成可信回测结论。

## 6. 目标架构

目标架构保持本地优先：

```text
RQData / Local Standard Parquet
-> raw parquet / standard parquet
-> manifest / checksum / quality report
-> DuckDB 查询与周期合成
-> PostgreSQL 业务事实归档
-> vn.py CTA 回测
-> FastAPI API / WebSocket
-> Vue Web Market / Backtest / Signal / Review
-> 企业微信只读提醒
-> 人工观察和复盘
```

核心顺序：

```text
先数据，后信号；
先事件，后提醒；
先后端稳定，后 Web 美化；
先只读观察，后考虑交易辅助；
V1 不自动下单。
```

## 7. 数据链路设计

V1 active 数据入口只允许：

```text
source = rqdata / local_parquet
data_role = primary
quality_status != failed
```

旧 TqSdk / 天勤数据最多作为历史交叉验证材料，不作为 V1 active 数据源。交易练习者数据最多作为历史 `legacy_reference`，不得进入正式回测或信号输入。

## 8. 实时 1m 入库规划

实时 1m 入库是后续任务，不是当前已完成能力。

后续设计必须明确：

- 数据来源和权限检查。
- 写入路径、数据版本、manifest、checksum。
- 重复 K线、缺口、非交易时间和异常值处理。
- 任务日志、失败恢复、checkpoint。
- 不触发任何交易执行。

## 9. 多周期聚合规划

1m 聚合 5m / 15m / 30m / 1h / 1d / 1w 是后续任务。

聚合规则必须：

- 使用已确认收盘 K线。
- 保持交易时段边界可测试。
- 避免未来函数和信号错位。
- 输出可追溯的数据版本和质量状态。

## 10. 策略中心规划

后续每个策略必须记录：

- `strategy_code`
- `strategy_version`
- 参数和参数版本
- 数据范围
- 数据源、`data_role`、`quality_status`
- 回测配置
- 信号来源
- 报告 ID 和可信指标

策略修改不得静默覆盖历史版本。

## 11. 苏冰策略接入规划

苏冰课程策略是 V1 优先策略来源之一。后续接入应先把规则转成稳定规格，再接入 live evaluator 和回测。

要求：

- 日线方向只能使用已确认日线。
- 15m / 5m 信号不得读取未来 bar。
- 回测、实时观察、Web 展示使用同一策略版本口径。

## 12. 通达信指标策略接入规划

通达信指标后续需要本地化和策略化。若指标存在未来函数或重绘风险，必须明确区分：

- preview 状态。
- confirmed 状态。
- 是否可用于可信回测。
- 是否仅可用于观察辅助。

不得把含未来函数或重绘风险的结果包装成可信策略收益。

## 13. signal_events 事件中心规划

`signal_events` 是后续信号事件化目标，不是当前已完成能力。

后续事件应记录：

- 合约、周期、K线时间。
- 策略代码、版本、参数。
- 信号方向、信号等级、来源。
- 数据源、数据角色、质量状态。
- 是否已通知、通知结果、失败原因。
- 人工观察和复盘状态。

## 14. 企业微信只读提醒规划

企业微信提醒只做通知，不做交易。

要求：

- 只从环境变量读取通知地址，例如 `QYWX_WEBHOOK_URL`。
- 不写入仓库、文档、数据库或日志。
- 不打印真实通知地址。
- 提醒内容必须包含策略版本、合约、周期、信号时间和风险提示。

## 15. Web Market 工作台规划

Web Market 后续目标：

- 搜索期货品种 / 合约。
- 显示主 K线图。
- 主图显示策略买卖点 marker。
- 支持副图指标。
- 支持选择策略并切换当前合约上的策略效果。
- 与回测报告和复盘 note 联动。

第一版以可读、可追溯、可验证为主，不做大屏炫技。

## 16. Cloudflare Access 本地部署规划

Cloudflare Access 是本地 Web 外部访问方案，需要后续单独部署验收。

当前只能写为本地 health check 和访问文档准备；不得宣称隧道、域名、Access policy 已经完整上线，除非后续有命令和浏览器验证证据。

## 17. 长期运行与 health check 规划

后续 worker / scheduler / health check 必须可观测：

- 任务状态明确。
- stdout / stderr 可追踪。
- 失败原因可查看。
- 不能长期假装 running。
- 支持 checkpoint 和重试次数记录。

## 18. Git / Codex 自动化规划

后续可在用户授权、测试通过、范围明确、无敏感文件时，由 Codex 对 `codex/*` 分支执行 commit / push。

默认限制：

- 不 push 到 `main`。
- 不提交 `.env` 或凭据。
- 数据、数据库、策略、回测指标、worker、scheduler、通知相关任务必须先 Plan 或暂停确认。

## 19. 分阶段路线

后续按单线程推进：

| 阶段 | 名称 |
|---|---|
| 阶段 0 | V1 重构基线冻结 |
| 阶段 1 | RQData 权限与接口能力 PoC |
| 阶段 2 | JM 历史数据更新到最新交易日 |
| 阶段 3 | 数据版本 / manifest / checksum / quality_status 收敛 |
| 阶段 4 | RQData 实时 1m 入库设计与实现 |
| 阶段 5 | 1m 聚合多周期 |
| 阶段 6 | 策略中心重构与苏冰 live_evaluator 接入 |
| 阶段 7 | 通达信指标本地化 |
| 阶段 8 | signal_events 信号事件化 |
| 阶段 9 | 企业微信只读提醒 |
| 阶段 10 | Web Market 策略展示 |
| 阶段 11 | 本地长期运行 / worker / scheduler / health check |
| 阶段 12 | Cloudflare Access 本地 Web 访问 |
| 阶段 13 | Codex git commit / push 自动化 |
| 阶段 14 | 可信回测主线复核 |

## 20. 风险与边界

主要风险：

- 把未完成能力写成已完成。
- 旧数据源重新污染 active 链路。
- 策略版本和数据版本不可追溯。
- 实时提醒被误解为交易指令。
- Cloudflare / RemoteView 状态被过度宣称。
- 回测 raw 指标与 trusted 指标混用。

默认边界：

- 数据可信度优先。
- 可追溯和可复算优先。
- 小步交付优先。
- 信号只提醒。
- 实盘后置。
