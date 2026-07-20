# 归一量化 AGENTS.md

更新时间：2026-07-20

本地单用户国内期货量化研究工作站的工程规则。开发流程见 `docs/DEVELOPMENT.md`；当前状态见 `STATUS.md`；长期定位见 `PROJECT_SOURCE.md`。

## 1. 项目边界

- 做：数据、K 线、策略、回测、报告、复盘、信号提醒、人工观察。
- 不做：无人值守自动实盘、信号直接下单、SaaS、多用户权限、手机 App。
- 当前阶段：V1-B（JM 短持有研究闭环）+ 指标/策略可信验证主线；工作站：`WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY`。

## 2. 技术栈（固定）

| 层 | 选择 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript + Naive UI |
| 后端 | FastAPI + PostgreSQL + Redis/RQ |
| 数据 | RQData → Parquet → DuckDB；业务事实在 PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine（不改 vn.py 源码） |

正式回测默认：`data_role=primary`，`source=rqdata/local_parquet`，`quality_status != failed`；严格研究默认 `passed`。

## 3. 工具模型

```text
GPT（浏览器）+ GitHub（Issue / PR / canonical docs）+ Codex（编码）+ 用户（批准 / merge）
```

- iPhone ChatGPT 仅可作为 Codex 远程入口，不另建控制面。
- 不把 WorkBuddy / CodeBuddy / dispatcher stage 机作为正式架构。
- 旧脚本若仍存在：仅兼容 shim；新工作用 `scripts/engineering/*` 与 GitHub Issue/PR。

## 4. 状态源（唯一）

| 源 | 职责 |
|---|---|
| `STATUS.md` | 项目当前状态与 Gate |
| GitHub Issue / PR | 任务生命周期 |
| `DECISIONS.md` / ADR | 长期决策 |
| `docs/tasks/<TASK_ID>.md` | 仅高风险任务执行契约 |
| 版本化报告 / PR evidence | 运行证据 |

`.ai/results`、对话 memory、已删除的旧任务池/摘要 **不是** active canonical。

## 5. 工程硬规则

1. 不修改 `main` 上的正式交付；在任务分支 / worktree 开发。
2. 不自动 push、merge、deploy、关闭 Issue/PR。
3. 不读取、显示或提交凭据；禁止改 `.env`；禁止触碰真实数据目录做破坏性操作。
4. 环境 / 挂载 / 数据源缺失时 fail-closed，禁止静默降级数据源。
5. 策略、回测、信号禁止未来函数与数据泄露。
6. 资金相关计算使用 `Decimal`；交易相关逻辑必须可解释、可回测、可复盘。
7. 高风险改动（策略公式、回测口径、DB/migration、live 写入、企业微信真实发送）须用户明确批准。
8. 禁止改：`data/raw/` 原始数据、report 14/15 历史结论、task 23 冻结项（除非用户明示）。
9. 小步修改；交付说明变更文件、测试、风险、未完成项。
10. 大改前先 Git checkpoint；多 Agent 不同时写同一 worktree。

## 6. 安全与风控摘要

```text
MAX_POSITION_RATIO / MAX_DAILY_LOSS / MAX_DRAWDOWN 从环境读取
生产下单路径：V1 不做；任何后续实盘必须风控检查 + 人工确认
```

提交涉及交易逻辑的改动前自检：仓位上限、单日亏损、最大回撤、断线异常、幂等、Decimal。

## 7. V1 必做 / 不做

**必做方向**：数据中心、合约/品种、RQData 标准化、Parquet/DuckDB、质量检查、K 线、策略版本、vn.py 回测适配、报告与买卖点、信号扫描（只提醒）、单笔复盘、风控统计、系统设置。

**明确不做**：全自动实盘、tick 高频、复杂盘口撮合、Web 策略编辑器、AI 自动生成并直接跑策略、多账户资金管理、云 SaaS、多用户、手机 App、无人值守交易。

## 8. 推荐入口

```bash
# 工程入口（优先）
scripts/engineering/preflight.sh
scripts/engineering/test.sh engineering   # 或 docs / backend-health / all-safe
scripts/engineering/check-secrets.sh      # 默认 fail-closed；CI 禁用 --warn-only
scripts/engineering/runtime-health.sh

# 本地开发
./scripts/dev-up.sh
./scripts/dev-healthcheck.sh --json --no-start
```

高风险真实写入必须使用业务专用、hash-bound、scope-bound approval packet / Gate。
没有专用 Gate 就禁止真实写入，先独立设计 Gate。
Issue 中用户批准是决策记录，但不能替代代码层 hash 校验。
（JM T3/T4 等业务专用 Gate 保持不变；已删除通用 `production-write-check.sh`。）

详细流程：`docs/DEVELOPMENT.md`。业务 deep canonical：`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`。

## 9. 接手最小阅读

1. `STATUS.md`
2. `AGENTS.md`（本文件）
3. `docs/DEVELOPMENT.md`
4. `PROJECT_SOURCE.md`
5. `DECISIONS.md`
6. 任务相关 deep canonical 或 Issue/PR

不要依赖已删除的旧工作站协议 / GPT 摘要 / 多状态源；以本文件与 GitHub Issue/PR 为准。
