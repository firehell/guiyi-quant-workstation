# CODEX_HANDOFF_FOR_CHATGPT.md

用途：上传给新的 ChatGPT 项目，使其长期作为“归一量化开发主控台”，负责理解项目、拆分任务、生成 Codex Prompt 和组织外部审查。
生成时间：2026-07-06
敏感信息：本文不包含账号、密码、Token、API Key、交易密钥或 license。

## 1. Canonical Baseline

旧聊天只作历史参考。本轮“阶段 0：V1 重构基线冻结”是新的 canonical baseline。

归一量化不是从零开始，而是在现有 MVP 上收敛重构。后续 ChatGPT 生成 Prompt 时必须围绕：

```text
现有 MVP 重构
+ RQData / Local Standard Parquet 主链路
+ 实时 1m 行情观察规划
+ signal_events 信号事件化
+ 企业微信只读提醒
+ Web Market 策略展示
+ 人工观察和复盘
```

V1 不自动下单，不做模拟盘自动接单，不做无人值守交易。

## 2. 当前项目定位

归一量化是本地运行的国内期货量化研究、实时行情观察规划、策略信号提醒规划和 Web 复盘工作站。

V1 主链路：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL / vn.py CTA BacktestingEngine
-> FastAPI
-> Vue Web
-> K线展示 / 策略信号 / 回测报告 / 单笔复盘 / 人工观察
```

## 3. 现有 MVP 可复用资产

新 ChatGPT 项目不要把归一量化当成空白项目重新设计。

当前可复用：

- FastAPI 后端。
- Vue 3 Web 工作台。
- RQData / Parquet / DuckDB / PostgreSQL 数据链路。
- vn.py 回测适配。
- JM 真实数据回测样板。
- 回测报告入库和 Web 展示。
- K线 marker 和复盘 note。
- 信号扫描入口。
- 本地 `/healthz` 和 Cloudflare Access 文档准备项。

以上能力不代表实时 1m 入库、`signal_events`、企业微信提醒或 Web Market 策略展示已经完成。

## 4. 后续有效路线

后续按 `docs/NEXT_STEPS.md` 单线程推进：

1. RQData 权限与接口能力 PoC。
2. JM 历史数据更新到最新交易日。
3. 数据版本 / manifest / checksum / quality_status 收敛。
4. RQData 实时 1m 入库设计与实现。
5. 1m 聚合 5m / 15m / 30m / 1h / 1d / 1w。
6. 策略中心重构和苏冰策略 live_evaluator 接入。
7. 通达信指标本地化，标注未来函数 / 重绘风险。
8. `signal_events` 信号事件化。
9. 企业微信只读提醒。
10. Web Market 策略展示。
11. 本地长期运行 / worker / scheduler / health check。
12. Cloudflare Access 本地 Web 访问。
13. Codex git commit / push 自动化。
14. 可信回测主线复核。

## 5. 不应恢复的旧路线

以下只作为历史参考，不应作为 V1 当前方案：

- 从零自研完整回测引擎替代 vn.py。
- 把 TqSdk 当成 V1 主数据源。
- 把 TuShare / AKShare 当成 V1 期货分钟数据主链路。
- 使用 VeighNa Studio 作为最终 Web。
- 直接接 CTP / TqSdk 实盘下单。
- 信号扫描直接触发下单。
- AI 自动生成策略并直接运行。
- 多品种参数寻优先行。
- 把 RQAlpha / XMA 实验结果写成 V1 正式可信回测结论。

## 6. Prompt 拆分规则

每轮任务必须单功能域。Prompt 必须包含：

- 本轮目标。
- 当前事实依据。
- 推荐执行模式。
- 是否需要 Plan。
- 是否建议新会话。
- 允许修改范围。
- 禁止修改范围。
- Gates。
- 验收标准。
- 测试命令。
- 回滚建议。
- 敏感信息规则。
- 完成后固定输出格式。

策略、数据、回测、worker、scheduler、通知、数据库任务必须 Plan 模式或先审查后执行。

不得将未完成能力描述为已完成。

## 7. 策略追溯规则

每个策略必须追溯：

- `strategy_code`
- `strategy_version`
- 参数和参数版本
- 数据范围
- 数据源、`data_role`、`quality_status`
- 回测配置
- 信号来源
- 报告 ID
- raw metrics
- trusted metrics
- excluded trades

参数、入场、出场、止损、止盈或过滤条件变化，必须新建版本或参数版本，不得静默覆盖旧版本。

## 8. Codex 完成后输出

Codex 完成后必须输出：

```markdown
### 结论
### 修改内容
### 测试与验证
### 风险与未完成项
### 建议下一步
### 协作建议
```

如果没有运行某项测试，必须说明原因。如果修改了任务文件或文档，还要说明哪些文件适合上传给 ChatGPT 项目。

## 9. 下一步

下一步应进入：

```text
阶段 1：RQData 权限与接口能力 PoC
```

阶段 1 建议新 Codex 会话 + Plan 模式。默认只读，不写 `data/`，不写数据库，不运行真实数据写入任务，不打印 licence。
