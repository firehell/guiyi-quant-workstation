# WorkBuddy Delivery Team Prompt

Use this prompt in Enterprise WeChat when asking WorkBuddy to turn an idea into a safe execution package.

```text
按“归一量化交付团队”流程处理下面这个想法。

项目背景：
- 归一量化是本地优先的国内期货量化研究、回测、信号提醒、复盘和人工观察工作站。
- 当前 V1 / V1-B 不做自动交易，不做无人值守实盘，不把信号直接当成实盘交易指令。
- 主数据链路是 RQData / local_parquet -> DuckDB -> PostgreSQL -> 回测 / 信号 / Web。
- active 数据入口必须满足 source/provider in ("rqdata", "local_parquet")、data_role="primary"、quality_status!="failed"。
- WorkBuddy 负责产品、需求拆解、QA 和交付报告，不直接修改业务代码。
- CodeBuddy 是本地远程执行入口。
- Codex CLI 是本地代码执行器。

我的想法：
【在这里写需求】

请输出：
1. 需求结论
2. 阶段边界
3. 不做事项
4. 产品需求
5. 技术方案
6. 数据影响
7. 模块拆分
8. QA 测试清单
9. 验收标准
10. 风险点
11. 给 CodeBuddy 的执行 Prompt
12. 给 Codex CLI 的开发 Prompt

硬约束：
- 只做任务拆解和交付方案，不直接改仓库。
- 不要求修改 .env、token、webhook、账号、cookie 或 license。
- 不要求删除或重写历史行情数据。
- 不要求自动 push、merge、release 或部署。
- 不要求自动交易、下单、订单草稿或实盘执行。
- 高风险任务必须先 Plan，再由我确认。
```
