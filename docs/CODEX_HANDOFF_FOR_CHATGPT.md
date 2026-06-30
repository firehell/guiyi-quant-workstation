# CODEX_HANDOFF_FOR_CHATGPT.md

用途：上传给新的 ChatGPT 项目，使其长期作为“归一量化开发主控台”，负责理解项目、拆分任务、生成 Codex Prompt 和组织外部审查。
生成时间：2026-06-30，最近更新：2026-06-30 文档入口清理后
敏感信息：本文不包含任何账号、密码、Token、API Key、交易密钥或 license。

## 1. 给 ChatGPT 的项目背景说明

归一量化是本地运行的国内期货量化研究、回测、复盘、信号扫描和人工观察系统。当前 V1 的目标是打通：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘
```

项目不是全自动实盘系统，不做 AI 自动下单，不做无人值守交易，不做云端 SaaS。

当前主链路：

```text
RQData / Local Parquet
-> DuckDB
-> vn.py CTA BacktestingEngine
-> ResultConverter
-> PostgreSQL
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

## 2. 当前不是从零设计阶段

新 ChatGPT 项目不要把归一量化当成空白项目重新设计。

当前已经具备：

- FastAPI 后端。
- Vue 3 Web 工作台。
- RQData / Parquet / DuckDB 数据链路。
- vn.py 回测适配。
- JM 3 年真实数据回测样板。
- 回测报告入库和 Web 展示。
- K线 marker 和复盘 note 能力。
- 信号扫描提醒能力。
- 多个苏冰/JM 策略版本和报告。
- 新 ChatGPT 项目长期上下文包和日常 Codex Prompt 模板。

后续重点是策略优化、可信回测验证、报告口径收敛和复盘闭环，而不是重搭技术架构。

当前不再使用的旧入口文档已经删除：

- `docs/AI_WORKFLOW.md`
- `docs/CODEX_PROMPT_TEMPLATE.md`
- `docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`
- `docs/PROJECT_PROGRESS.md`

新 ChatGPT 项目应优先读取：

- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/ROADMAP.md`

## 3. 当前有效路线

有效路线按以下顺序推进：

1. 当前代码事实确认。
2. RQData / local standard Parquet 数据质量确认。
3. 策略 spec 冻结。
4. vn.py 回测任务执行。
5. BacktestResult / trade 事实源一致性检查。
6. trusted excluding cross-contract 指标确认。
7. Web 报告与 K线 marker 验收。
8. 单笔复盘与标签归因。
9. 信号扫描只读提醒。
10. 人工观察和下一轮策略版本设计。

每个策略版本必须可追溯：

- `strategy_code`
- `strategy_version`
- 参数
- 数据范围
- data source / data role / quality status
- 回测配置
- 报告 ID
- raw metrics
- trusted metrics
- excluded trades

## 4. 不应继续作为当前方案的旧路线

以下路线只作为历史参考，不应作为当前 V1 方案：

- 从零自研完整回测引擎替代 vn.py。
- 把 TqSdk 当成 V1 主数据源。
- 把 TuShare / AKShare 当成 V1 期货分钟数据主链路。
- 使用 VeighNa Studio 作为最终 Web。
- 直接接 CTP / TqSdk 实盘下单。
- 信号扫描直接触发下单。
- AI 自动生成策略并直接运行。
- 多品种参数寻优先行。
- 在未关闭 future leak / data leakage / overfit 风险前讨论实盘。

## 5. ChatGPT 后续如何给 Codex 拆任务

ChatGPT 应把讨论结果整理成单一、清晰、可验证的 Codex Prompt。每轮只覆盖一个功能域。

日常可复制模板以 `docs/AI_DEVELOPMENT_WORKFLOW.md` 为准。该文件已经固化：

- ChatGPT 给 Codex 的标准任务 Prompt 模板。
- Codex 完成后的标准输出模板。
- `PROJECT_SNAPSHOT.md` / `CURRENT_STATE.md` / `STRATEGY_CURRENT_STATE.md` 更新触发条件。
- 新会话 / 继续旧会话规则。
- git checkpoint 规则。
- 推荐 git commit message 格式。
- 新 ChatGPT 项目文件维护规则。

Prompt 必须至少包含：

- 本轮目标。
- 当前事实依据文件。
- 推荐执行模式。
- 是否需要 Plan。
- 是否需要新会话。
- 允许修改范围。
- 禁止修改范围。
- 验收标准。
- 测试命令。
- 回滚建议。
- 敏感信息规则。
- 回测防未来函数、数据泄露和过拟合约束。
- 策略版本、参数、数据范围、回测配置和报告结果追溯约束。
- 完成后的固定输出格式。

涉及策略、回测、数据库、数据中心、worker、scheduler、风控时，默认使用 Plan 模式或先审查后执行。

## 6. Codex 每轮完成后应该输出什么

Codex 完成后必须输出以下字段；完整模板以 `docs/AI_DEVELOPMENT_WORKFLOW.md` 为准：

```markdown
## 本轮目标
## 修改摘要
## 变更文件
## 运行命令
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
## 是否建议更新 PROJECT_SNAPSHOT.md / CURRENT_STATE.md
```

如果没有运行某项测试，必须说明原因。

如果修改了任务文件或文档，还要说明哪些文件适合上传给 ChatGPT 项目。

如果涉及前端页面、K线图、回测报告页面、信号页面或复盘页面，且条件允许，还必须补充浏览器验收：

```markdown
## 浏览器验收
- 是否需要：
- 页面：
- 操作路径：
- 控制台结论：
- 视觉结论：
```

## 7. 什么时候应该开新 Codex 会话

建议开新 Codex 会话的情况：

- 从文档任务切换到策略代码实现。
- 从策略实现切换到数据库 migration。
- 从后端任务切换到前端页面验收和修复。
- 需要长时间跑回测、导出报告或外部审查。
- 当前会话上下文过长，容易混淆旧结论。
- 要处理高风险 Gate，例如 migration、真实数据写入、worker 调度、实盘候选接口。

开新会话前应先更新 `tasks/current.md` 或准备完整任务包，并运行 `git status --short`。

注意：`tasks/current.md` 当前仍是上一轮 score2of4 任务记录，下一轮业务修改前应先更新。

## 8. 什么时候应该继续旧 Codex 会话

可以继续旧会话的情况：

- 同一任务的测试失败修复。
- 同一文档包的小修。
- 同一 PR / diff 的代码 review 反馈处理。
- 同一页面的浏览器 smoke 后小范围修正。
- 未触发 Gate，且修改范围仍在原允许文件内。

## 9. 什么时候必须 git checkpoint

必须 checkpoint 或至少由 Cursor / 用户确认 Git 状态的情况：

- 准备修改策略、回测、数据库、数据中心、worker、scheduler、风控代码前。
- 准备运行会写入数据库或数据目录的脚本前。
- 准备做 migration 前。
- 准备跨多个模块修改前。
- 完成一个可运行闭环任务后。
- 外部审查前需要固定 diff 时。

checkpoint 前必须先运行：

```bash
git status --short
git branch --show-current
```

推荐 commit message 使用：

```text
<type>(<scope>): <summary>
```

示例：

```text
docs(workflow): add ChatGPT Codex daily task templates
backtest(jm): verify trusted metrics excluding cross-contract trades
strategy(jm): add daily score3 research variant
```

## 10. 后续最重要的开发方向

短期最重要方向：

1. 关闭 rollover-safe / cross-contract 可信指标问题。
2. 对 `v0.3.0-daily-score2of4` 做 trusted trades 条件组合消融。
3. 限制或重构 `score=2`、`volume_only_confirm`、`range_risk`、`no_macd_cross` 的噪声信号。
4. 如继续优化，必须创建新 `strategy_version`，不得静默覆盖旧版本。
5. 回测报告继续向 trade 事实源一致性收敛。
6. Web 只做服务于回测报告、K线 marker、复盘 note、信号提醒的必要改动。
7. 所有回测结论必须检查未来函数、数据泄露和过拟合。

当前不建议：

- 自动实盘。
- 模拟盘接单。
- 多品种批量参数优化。
- 大规模前端重构。
- 新增外部依赖。
