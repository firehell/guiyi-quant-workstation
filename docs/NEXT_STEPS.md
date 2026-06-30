# NEXT_STEPS.md

生成时间：2026-06-30，最近更新：2026-06-30 文档入口清理后
用途：上传给新的 ChatGPT 项目，用于后续持续给 Codex 拆任务。  
原则：按顺序单线程推进；不扩大范围；当前代码优先；不做全自动实盘。

## 1. 下一阶段最终目标

下一阶段最终目标：

```text
在不扩大到实盘、不扩多品种、不引入新依赖的前提下，
把 JM 策略研究推进到可信回测、报告可追溯、K线可复盘、信号只提醒的稳定闭环。
```

短期核心是：

1. 关闭 rollover-safe / cross-contract 可信指标风险。
2. 对 `v0.3.0-daily-score2of4` 做条件组合消融和规则收敛。
3. 形成下一版可解释、可复盘、可审查的策略版本。

当前前置状态：

- 新 ChatGPT 项目上下文包已经建立。
- 旧入口文档已经清理，后续不再读取 `docs/AI_WORKFLOW.md`、`docs/CODEX_PROMPT_TEMPLATE.md`、`docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`、`docs/PROJECT_PROGRESS.md`。
- `tasks/current.md` 仍是上一轮 score2of4 任务记录，下一轮业务修改前应先更新任务文件或提供等价任务包。

## 2. 按顺序列出的任务

| 顺序 | 任务 | 目标 | 验收标准 | 建议执行模式 | 建议新会话 |
|---:|---|---|---|---|---|
| 1 | 更新任务文件并建立 checkpoint | 让 `tasks/current.md` 与下一步一致 | `git status` 清楚；任务包含 allowed / forbidden / steps / gates / tests | 直接执行 | 否 |
| 2 | rollover-safe / cross-contract 审查 | 找出 report 11 排除 8 笔跨合约交易的根因和处理路径 | 输出受影响 trade、原因、是否需要新数据任务或强制退出规则 | Plan 模式 | 是 |
| 3 | trusted-only 指标复核 | 确认 report 11 的 trusted 指标可以复算 | raw/trusted/excluded 指标可由 trade 明细复算；结论一致 | 先审查后执行 | 是 |
| 4 | score2of4 条件组合消融设计 | 设计不污染旧版本的新实验矩阵 | 有 strategy_version 命名、参数冻结、测试清单、报告字段 | Plan 模式 | 是 |
| 5 | 实现第一个收敛版本 | 例如 score>=3 或 no-volume-only | 新策略包或版本化任务；旧版本测试保持通过 | Plan 模式 | 是 |
| 6 | 3 年 JM 日线复跑 | 生成新 report，并输出 raw/trusted 对比 | report_id、trade 明细、score/tag 分布、v0.2/v0.3/v0.3.1 对比 | 先审查后执行 | 是 |
| 7 | 外部 ChatGPT 风控审查 | 审查未来函数、数据泄露、过拟合、成本、滑点、合约映射 | 输出 P0/P1/P2 反馈清单 | 只审查不修改 | 是 |
| 8 | Web 报告/K线复盘 smoke | 确认新 report 能在 Web 展示和 K线显示买卖点 | 浏览器页面、操作路径、控制台结论明确 | 直接执行 | 可选 |
| 9 | 复盘 note 样本创建 | 从代表性 trade 创建复盘 note | note 可创建、标签完整、可回链 report/trade | 直接执行 | 可选 |
| 10 | 信号扫描只读接入评估 | 判断新版本是否值得接入信号提醒 | 明确只提醒、不下单；有 no_signal reason 和风控字段 | Plan 模式 | 是 |

## 3. 任务细化

### 任务 1：更新任务文件并建立 checkpoint

目标：

- 把下一轮任务沉淀到 `tasks/current.md`。
- 明确允许/禁止修改范围。
- 先由用户或 Cursor 做 checkpoint。
- 使用 `docs/AI_DEVELOPMENT_WORKFLOW.md` 的标准 Prompt 模板。

验收标准：

- `tasks/current.md` 不再停留在上一轮已完成任务。
- `git status --short` 可解释。
- 高风险 Gate 写清楚。
- 不重新引入已删除的旧入口文档。

建议 Codex 模式：直接执行。  
是否建议开新会话：否。

### 任务 2：rollover-safe / cross-contract 审查

目标：

- 找出 `v0.3` 8 笔 excluded cross-contract trades。
- 判断应采用强制换月退出、剔除统计、还是数据任务修复。

验收标准：

- 输出受影响 trade id。
- 输出 entry_contract / exit_contract / 日期 / PnL。
- 明确 trusted 指标不能混入跨合约收益。

建议 Codex 模式：Plan 模式。  
是否建议开新会话：是。

### 任务 3：trusted-only 指标复核

目标：

- 用 trade 事实源复算 report 11 的 trusted metrics。

验收标准：

- 复算 trade_count、net_pnl、win_rate、profit_loss_ratio、max_drawdown、max_consecutive_losses。
- 与文档指标一致或解释差异。
- 不修改策略行为。

建议 Codex 模式：先审查后执行。  
是否建议开新会话：是。

### 任务 4：score2of4 条件组合消融设计

目标：

- 设计新版本矩阵，重点验证 score=2 噪声。

验收标准：

- 每个实验都有 version 名称。
- 每个实验只改变一个主要变量。
- 明确测试和报告字段。

建议 Codex 模式：Plan 模式。  
是否建议开新会话：是。

### 任务 5：实现第一个收敛版本

目标：

- 版本化实现一个最小策略改动，例如 `score>=3` 或禁止弱组合。

验收标准：

- 新版本不修改 `v0.2.0-daily` 和 `v0.3.0-daily-score2of4` 历史行为。
- 单元测试覆盖入场、拒绝、方向冲突、未来函数边界。
- 固定任务入口可选择新版本。

建议 Codex 模式：Plan 模式。  
是否建议开新会话：是。

### 任务 6：3 年 JM 日线复跑

目标：

- 对新版本跑同窗口回测。

验收标准：

- 输出 report_id。
- 输出 raw / trusted / excluded 指标。
- 输出 v0.2 / v0.3 / 新版本对比。
- 可信结论只基于 trusted metrics。

建议 Codex 模式：先审查后执行。  
是否建议开新会话：是。

### 任务 7：外部 ChatGPT 风控审查

目标：

- 人工粘贴 diff、报告和关键代码，让 ChatGPT 外部审查。

验收标准：

- 反馈按 P0 / P1 / P2 分类。
- P0 必须先处理或明确暂停。

建议 Codex 模式：只审查不修改。  
是否建议开新会话：是。

### 任务 8：Web 报告/K线复盘 smoke

目标：

- 确认新 report 可在 Web 查看，并能在 K线上看到买卖点。

验收标准：

- `/backtest?report_id=...` 可显示报告和交易明细。
- `/market?symbol=jm&contract=jm.MAIN&period=1d&report_id=...` canvas 非空，marker 可见。
- 控制台无应用错误。

建议 Codex 模式：直接执行。  
是否建议开新会话：可选。

### 任务 9：复盘 note 样本创建

目标：

- 为代表性盈利、亏损、跨合约剔除 trade 创建复盘样本。

验收标准：

- review note 可创建。
- 标签、entry_reason、exit_reason、score/tag 元数据可追溯。

建议 Codex 模式：直接执行。  
是否建议开新会话：可选。

### 任务 10：信号扫描只读接入评估

目标：

- 判断新版本是否值得接入信号扫描。

验收标准：

- 明确只提醒、不下单。
- 输出 no_signal reason、风险字段和人工观察路径。
- 不触碰实盘、模拟盘或 CTP/TqSdk 下单接口。

建议 Codex 模式：Plan 模式。  
是否建议开新会话：是。
