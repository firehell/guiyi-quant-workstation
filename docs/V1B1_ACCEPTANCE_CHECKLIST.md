# 归一量化 V1-B.1 验收清单

本清单用于验收：

```text
归一量化 V1-B.1：可信研究闭环收口阶段
```

验收原则：

- 只验收 V1 Web 研究闭环。
- 只以 RQData / local standard parquet 正式数据口径作为正式回测依据。
- 不把 validation / legacy_reference 数据混入正式回测。
- 不把信号扫描解释为自动下单。
- 不把回测结果解释为实盘收益承诺。
- 不把历史文档结论替代当前实测结果。

## 1. Git / 工作区验收

必须检查：

```bash
git status --short
```

要求：

- 没有未解释的删除文件。
- 测试文件删除必须有明确说明。
- 业务代码修改必须和当前任务有关。
- 文档修改必须说明目的和影响范围。
- 不得出现 `.env`、账号、密码、token、license、API Key、米筐账号、天勤账号或 CTP 密码进入待提交文件。

记录模板：

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| `git status --short` 已执行 | 待填写 |  |
| 删除文件已解释 | 待填写 |  |
| 测试文件删除已确认 | 待填写 |  |
| 业务代码修改与任务相关 | 待填写 |  |
| 敏感配置未进入待提交文件 | 待填写 |  |

## 2. 后端验收

必须检查：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
```

要求：

- pytest 通过。
- ruff 通过。
- 如果 pytest 因测试文件删除、数据库未启动、Redis 未启动、RQ worker 未启动或本地凭据缺失失败，必须记录原因。
- 不允许用“未运行”替代验收通过。

记录模板：

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `uv run --project services/quant-api pytest -q` | 待填写 |  |
| `uv run --project services/quant-api ruff check .` | 待填写 |  |

## 3. 前端验收

必须检查：

```bash
cd apps/quant-web && pnpm build
cd apps/quant-web && pnpm test:indicators
```

要求：

- 前端 build 通过。
- 指标测试通过。
- 如果存在 chunk warning，必须记录但不自动判定失败。
- 如果依赖未安装或本地环境缺失，必须记录原因。

记录模板：

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `cd apps/quant-web && pnpm build` | 待填写 |  |
| `cd apps/quant-web && pnpm test:indicators` | 待填写 |  |

## 4. 数据验收

必须确认：

- JM 数据来自 primary / passed 数据。
- validation / legacy_reference 不进入正式回测。
- 5m / 15m / 1d 数据覆盖完整。
- price_tick、合约乘数、手续费、保证金参数可解析。

验收要点：

- 正式回测默认读取 `source=rqdata / local_parquet`。
- 正式回测默认读取 `data_role=primary`。
- 正式回测默认排除 `quality_status=failed`。
- TqSdk 旧数据只能作为 validation source。
- 交易练习者数据只能作为 legacy_reference。
- JM 交易参数必须能按实际主力合约和交易日解析。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| JM 1d 数据覆盖完整 | 待填写 |  |
| JM 15m 数据覆盖完整 | 待填写 |  |
| JM 5m 数据覆盖完整 | 待填写 |  |
| 数据角色为 primary | 待填写 |  |
| 质量状态为 passed / 非 failed | 待填写 |  |
| validation 未进入正式回测 | 待填写 |  |
| legacy_reference 未进入正式回测 | 待填写 |  |
| price_tick 可解析 | 待填写 |  |
| 合约乘数可解析 | 待填写 |  |
| 手续费参数可解析 | 待填写 |  |
| 保证金参数可解析 | 待填写 |  |

## 5. 回测验收

必须确认：

- 15m 回测任务可创建。
- 5m 回测任务可创建。
- RQ worker 可执行。
- 回测报告可入库。
- 交易明细可查询。
- equity curve 可查询。
- drawdown curve 可查询。

验收要点：

- 15m / 5m 都必须走 JM V1-B 固定任务口径。
- worker 执行应产生明确成功或失败状态。
- 失败任务必须记录失败原因。
- 成功任务必须能关联 report_id。
- report_id 对应的 trades、equity curve、drawdown curve 均可查询。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| 15m 回测任务可创建 | 待填写 |  |
| 5m 回测任务可创建 | 待填写 |  |
| RQ worker 可执行 | 待填写 |  |
| 任务状态正确流转 | 待填写 |  |
| 回测报告可入库 | 待填写 |  |
| 交易明细可查询 | 待填写 |  |
| equity curve 可查询 | 待填写 |  |
| drawdown curve 可查询 | 待填写 |  |

## 6. 报告口径验收

必须逐项检查：

- `summary.total_net_pnl = trades.net_pnl 汇总`
- `summary.total_commission = trades.commission 汇总`
- `summary.total_slippage = trades.slippage 汇总`
- `summary.final_equity = equity_curve 最后一项`
- `summary.max_drawdown = drawdown_curve 最大回撤`
- `win_rate` 与逐笔交易统计一致
- `max_consecutive_losses` 与逐笔交易统计一致
- Web 展示字段与后端字段含义一致

验收要点：

- 年化收益必须说明计算口径。
- 最大回撤金额和最大回撤百分比必须能从曲线复算。
- 保证金占用必须说明是逐笔、最大值还是区间统计。
- 胜率必须说明是按平仓交易、完整 trade 还是其他单位统计。
- 盈亏比必须说明分子分母口径。
- summary、trades、equity curve、drawdown curve 任一不一致，都不能判定为可信报告。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| `summary.total_net_pnl = sum(trades.net_pnl)` | 待填写 |  |
| `summary.total_commission = sum(trades.commission)` | 待填写 |  |
| `summary.total_slippage = sum(trades.slippage)` | 待填写 |  |
| `summary.final_equity = equity_curve[-1]` | 待填写 |  |
| `summary.max_drawdown = max(drawdown_curve)` | 待填写 |  |
| `summary.max_drawdown_pct` 与 drawdown curve 一致 | 待填写 |  |
| `win_rate` 与逐笔交易统计一致 | 待填写 |  |
| `profit_loss_ratio` 与逐笔交易统计一致 | 待填写 |  |
| `max_consecutive_losses` 与逐笔交易统计一致 | 待填写 |  |
| Web 展示字段与后端字段含义一致 | 待填写 |  |

## 7. Web smoke 验收

必须逐页验收：

- `/backtest`
- `/market`
- `/review`
- `/signal`

每个页面记录：

- 是否打开。
- 是否报错。
- 是否有 404。
- 是否有截图。
- 是否有数据。
- 是否符合预期。

验收要点：

- 浏览器控制台无应用错误。
- Network 中核心 API 无 404。
- 页面不应只显示空壳或 mock 数据，除非该页面明确不属于 V1-B.1 验收范围。
- 截图应保存到可追溯位置，或在验收记录中说明截图路径。

记录模板：

| 页面 | 是否打开 | 控制台是否报错 | API 是否 404 | 是否有截图 | 是否有数据 | 是否符合预期 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/backtest` | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |  |
| `/market` | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |  |
| `/review` | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |  |
| `/signal` | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |  |

## 8. K线与复盘验收

必须确认：

- K线显示。
- 买点 marker 显示。
- 卖点 marker 显示。
- report_id 切换刷新。
- 点击交易能定位 K线。
- 主图和副图十字星同步。
- 复盘 note 可创建。
- 复盘标签可读取。

验收要点：

- marker 必须来自当前 report_id 对应交易明细。
- report_id 切换后不能继续显示旧报告 marker。
- 交易定位必须能让用户从交易明细回到对应 K线位置。
- 复盘 note 必须关联具体交易或明确来源。
- 复盘标签只能用于交易后诊断，不得回写为当时信号条件。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| K线显示 | 待填写 |  |
| 买点 marker 显示 | 待填写 |  |
| 卖点 marker 显示 | 待填写 |  |
| report_id 切换刷新 | 待填写 |  |
| 点击交易能定位 K线 | 待填写 |  |
| 主图和副图十字星同步 | 待填写 |  |
| 复盘 note 可创建 | 待填写 |  |
| 复盘标签可读取 | 待填写 |  |

## 9. 信号扫描验收

必须确认：

- 非 inline worker 可执行。
- task 状态正确流转。
- 信号写入数据库。
- Web 可展示。
- 不下单。

验收要点：

- 扫描任务应由 RQ worker 消费。
- `run_inline=true` 只能作为辅助调试路径，不能替代 V1-B.1 worker 验收。
- 任务失败必须记录失败原因。
- 信号应能通过 API 和 `/signal` 页面查看。
- 信号扫描不得调用实盘下单、CTP 下单、天勤下单或任何自动交易逻辑。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| 非 inline worker 可执行 | 待填写 |  |
| task 状态正确流转 | 待填写 |  |
| 信号写入数据库 | 待填写 |  |
| Web 可展示信号 | 待填写 |  |
| 未触发下单逻辑 | 待填写 |  |

## 10. V1 不做实盘验收

必须确认：

- 没有自动下单入口。
- 信号扫描不触发下单。
- 没有 CTP 实盘配置进入 V1 主流程。
- 没有天勤实盘账号写入代码库。
- 没有交易密码/API Key 写入代码库。

验收要点：

- V1-B.1 只做研究闭环和提醒。
- CTP、天勤、模拟交易、人工确认下单属于后续阶段候选，不进入 V1-B.1 主流程。
- `.env.example` 中候选字段不代表 V1 主链路配置。
- 任何涉及实盘、账户、下单、成交回报的能力都必须单独走后续阶段设计和审查。

记录模板：

| 检查项 | 结果 | 证据 / 说明 |
| --- | --- | --- |
| 没有自动下单入口 | 待填写 |  |
| 信号扫描不触发下单 | 待填写 |  |
| CTP 实盘配置未进入 V1 主流程 | 待填写 |  |
| 天勤实盘账号未写入代码库 | 待填写 |  |
| 交易密码/API Key 未写入代码库 | 待填写 |  |

## 11. 最终验收结论模板

```text
V1-B.1 验收结论：
- 是否通过：
- 未通过原因：
- 阻塞问题：
- 可接受遗留问题：
- 下一步建议：
```

建议补充记录：

```text
验收日期：
验收人：
当前 git commit：
当前分支：
15m report_id：
5m report_id：
后端测试结果：
前端测试结果：
Web smoke 截图位置：
敏感信息检查结论：
是否修改业务代码：
```
