# NEXT_STEPS.md

生成时间：2026-07-06
用途：上传给新的 ChatGPT 项目，用于后续持续给 Codex 拆任务。
原则：按顺序单线程推进；不扩大范围；当前代码优先；不做全自动实盘。

## 1. 下一阶段总目标

下一阶段目标不是重搭项目，而是在现有 V1 研究闭环基础上，补齐 RQData / Local Standard Parquet 数据链路和本地长期运行前置能力，再回到可信回测主线。

当前仍然不做：

```text
自动实盘
AI 自动下单
无人值守交易
直接接 CTP / TqSdk 下单
信号扫描触发下单
多品种批量参数优化
Web 大屏扩展
```

## 2. 当前已完成检查点

| 检查点 | 状态 |
|---|---|
| DATA-001 数据源瘦身 | 已完成，active 入口收敛为 RQData / Local Standard Parquet primary |
| 旧 TqSdk / 交易练习者 active 数据 | 已移除，当前 `find data '*tqsdk*/*trader*/*Future*'` 无输出 |
| RQData licence 初步只读确认 | 2026-07-03 可用，FULL，剩余约 361 天，未记录真实 key |
| 本地工作站 `/healthz` | 已补充，返回 `local-workstation` |
| Cloudflare Tunnel + Access 文档 | 已补充，见 `docs/CLOUDFLARE_WORKSTATION_ACCESS.md` |
| RQAlpha / XMA PoC | 实验目录已存在，但不属于正式 V1 报告链路 |

## 3. 顺序任务表

| 顺序 | 阶段 | 任务 | 任务目标 | 推荐执行模式 | 新会话 | checkpoint | 风险等级 | 验收标准 |
|---:|---|---|---|---|---|---|---|---|
| 1 | 阶段 1 | RQData 权限与接口能力 PoC | 只读确认 RQData 本地环境、权限、接口和字段能力 | Plan 模式 | 是 | 是 | medium | 输出可用接口、字段、限制和后续任务设计 |
| 2 | 阶段 2 | JM 历史数据更新到最新交易日 | 设计并执行受控数据更新，把 JM 数据补到最新可用交易日 | 先审查后执行 | 是 | 是 | high | 明确数据范围、版本、质量状态，不混入 legacy |
| 3 | 阶段 3 | 数据版本 / manifest / checksum / quality_status 收敛 | 统一 standard parquet 的版本、校验和质量标识 | Plan 模式 | 是 | 是 | high | manifest 可追溯，failed 数据不进正式回测 |
| 4 | 阶段 4 | RQData 实时 1m 入库设计 | 设计本地 1m 增量采集和落库/落盘边界 | Plan 模式 | 是 | 是 | high | 明确不写实盘、不自动下单、失败恢复和去重规则 |
| 5 | 阶段 5 | 1m 聚合 5m / 15m / 30m | 设计分钟聚合规则和交易时段边界 | Plan 模式 | 是 | 是 | medium | 聚合规则可测试，避免未来函数和错位 |
| 6 | 阶段 6 | TDX XMA 指标本地实现 | 复刻指标并标注未来函数/重绘风险 | Plan 模式 | 是 | 是 | medium | confirmed / preview 模式区分清楚，不作为可信回测依据 |
| 7 | 阶段 7 | K线指标绘制和 marker | 在 Web K线上展示指标、买卖点和状态 | 先审查后执行 | 可选 | 是 | medium | 页面渲染、marker 可见、控制台无应用错误 |
| 8 | 阶段 8 | signal_events 信号事件化 | 把信号记录为可查询、可复盘、可通知的事件 | Plan 模式 | 是 | 是 | high | 信号只提醒，有来源、版本、状态和风险字段 |
| 9 | 阶段 9 | 企业微信只读提醒 | 接入只读提醒，不触发下单 | 先审查后执行 | 是 | 是 | high | webhook 不入库不入文档，提醒内容可追溯 |
| 10 | 阶段 10 | 本地长期运行 / worker / scheduler / health check | 设计并验证 worker、scheduler 和健康检查 | Plan 模式 | 是 | 是 | high | 任务可观测、可重试、可停止，不无人值守交易 |
| 11 | 阶段 11 | Data / Market / Signal / Review 页面 smoke | 浏览器验收核心页面 | 直接执行 | 可选 | 是 | medium | 页面路径、操作步骤、控制台和截图结论明确 |
| 12 | 阶段 12 | 回到可信回测主线 | 处理 rollover-safe、trusted metrics、score2of4 消融 | Plan 模式 | 是 | 是 | high | raw/trusted/excluded 分开，旧版本行为不被静默修改 |

## 4. 阶段 1：RQData 权限与接口能力 PoC

任务目标：

- 只读确认本机 RQData 环境是否可用。
- 确认可访问的期货接口、合约基础信息、分钟数据、主力映射、复权因子、手续费、保证金、合约乘数字段。
- 明确接口限制、错误类型、字段缺口和后续数据任务设计。

推荐 Codex 执行模式：Plan 模式。
是否建议新 Codex 会话：是。
是否需要 checkpoint：是。
风险等级：medium。

允许范围：

- 读取 `.env` 或环境变量时不得打印真实 licence/key。
- 只运行只读检查命令。
- 可新增或更新 PoC 文档、任务记录、只读检查脚本草案。

禁止范围：

- 不写入 `data/`。
- 不写数据库。
- 不运行正式数据下载。
- 不把 PoC 结果写成生产数据已更新。
- 不恢复 TqSdk / 交易练习者 active 数据入口。

验收标准：

- 输出实际检查命令和结果摘要。
- 输出接口能力矩阵。
- 输出字段缺口和错误类型。
- 输出阶段 2 JM 数据更新任务包。

## 5. 阶段 2：JM 历史数据更新到最新交易日

任务目标：

- 在阶段 1 确认可用后，再设计并执行 JM 数据更新。
- 明确 raw parquet、standard parquet、manifest、quality report 的写入路径和版本。

推荐 Codex 执行模式：先审查后执行。
是否建议新 Codex 会话：是。
是否需要 checkpoint：是。
风险等级：high。

验收标准：

- 输出新增数据范围。
- 输出 data_version。
- 输出 quality_status。
- 输出 row_count、min_datetime、max_datetime。
- 失败数据不能进入正式回测。
- 不混入天勤旧数据或交易练习者数据。

## 6. 阶段 3：数据版本 / manifest / checksum / quality_status 收敛

任务目标：

- 让正式数据文件可追溯、可校验、可复跑。
- 固化 `source`、`data_role`、`quality_status` 的筛选原则。

推荐 Codex 执行模式：Plan 模式。
是否建议新 Codex 会话：是。
是否需要 checkpoint：是。
风险等级：high。

验收标准：

- manifest 包含版本、范围、周期、行数、checksum 和质量状态。
- 正式回测默认只读取 `source = rqdata / local_parquet`、`data_role = primary`、`quality_status != failed`。
- 严格研究可使用 `quality_status = passed`。

## 7. 阶段 4-10：实时观察和长期运行

这些任务仍是后续设计和实现任务，不要写成已完成：

- RQData 实时 1m 入库设计。
- 1m 聚合 5m / 15m / 30m。
- TDX XMA 指标本地实现，必须标注未来函数 / 重绘风险。
- K线指标绘制和 marker。
- signal_events 事件化。
- 企业微信只读提醒。
- 本地长期运行 / worker / scheduler / health check。

共同边界：

- 信号只提醒，不下单。
- 通知不包含敏感信息。
- 任务状态、失败原因、日志和 checkpoint 必须可追踪。
- 任何写库、写数据目录、scheduler、worker 改动都需要 Plan 模式或先审查后执行。

## 8. 阶段 11：核心页面 smoke

任务目标：

- 验收 Data / Market / Backtest / Signal / Review 页面。
- 记录页面 URL、操作路径、控制台结论和视觉结论。

推荐 Codex 执行模式：直接执行。
是否建议新 Codex 会话：可选。
是否需要 checkpoint：是。
风险等级：medium。

## 9. 阶段 12：回到可信回测主线

任务目标：

- 关闭 rollover-safe / cross-contract 可信指标问题。
- 复核 trusted metrics。
- 做 `v0.3.0-daily-score2of4` 条件组合消融和下一版规则收敛。

推荐 Codex 执行模式：Plan 模式。
是否建议新 Codex 会话：是。
是否需要 checkpoint：是。
风险等级：high。

验收标准：

- raw metrics、trusted metrics、excluded trades 分开。
- 不静默修改 `v0.2.0-daily` 或 `v0.3.0-daily-score2of4`。
- 新参数或规则必须创建新 `strategy_version`。
- 不进入模拟盘、实盘或自动下单。
