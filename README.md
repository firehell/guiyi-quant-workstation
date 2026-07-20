# 归一量化工作站

更新时间：2026-07-20

本地单用户国内期货量化研究工作站。当前重点是 V1 / V1-B：数据、K 线、策略回测、报告、复盘、信号提醒与人工观察。不做 SaaS，不做无人值守自动实盘。

## 快速导航

| 用途 | 文件 |
|---|---|
| 工程规则 | `AGENTS.md` |
| 开发流程 | `docs/DEVELOPMENT.md` |
| 当前状态 | `STATUS.md` |
| 长期定位 | `PROJECT_SOURCE.md` |
| 架构决策 | `DECISIONS.md` |
| 测试与 Gate | `TESTING.md` |
| 数据中心 | `docs/DATA_CENTER.md` |
| 系统架构 | `docs/ARCHITECTURE.md` |
| 回测口径 | `docs/BACKTEST_ENGINE.md` |
| 信号事件 | `docs/SIGNAL_EVENTS.md` |

接手阅读顺序：`STATUS.md` → `AGENTS.md` → `docs/DEVELOPMENT.md` → `PROJECT_SOURCE.md` → `DECISIONS.md` → 任务相关 deep canonical / Issue / PR。

## 当前状态（摘要）

业务 Gate 以 `STATUS.md` 为准。工作站侧当前为：

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
```

正式消费者数据契约已 Ready；全历史 residual 仍并列保留 `DATA_LAYER_REAUDIT_REQUIRED`。不可把 Ready 扩写为 live / OOS / 自动交易。业务下一入口见 `STATUS.md`（当前为 `S6-05` T3：`CODE_COMPLETE` / `REAL_WRITE_APPROVAL_PENDING` / `T3_REAL_PENDING`）。

## 主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 入口：`provider in (rqdata, local_parquet)` + `data_role=primary` + `quality_status != failed`。严格研究默认 `quality_status=passed`。

## 本地启动

```bash
cp .env.example .env   # 替换 replace-with-*；.env 严禁提交
./scripts/dev-up.sh
```

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000/docs
```

工程入口（推荐）：`scripts/engineering/`（`preflight` / `check-secrets` / `test.sh <profile>` / `runtime-health`）。Agent 规则见 `AGENTS.md`。

## 安全边界

- 密钥只存在于本机环境；禁止写入仓库。`check-secrets.sh` 默认 fail-closed。
- 不接实盘自动下单；不自动 push / merge / deploy。
- 高风险真实写入必须使用业务专用、hash-bound、scope-bound approval packet / Gate；没有专用 Gate 就禁止真实写入。Issue 批准不能替代代码层 hash 校验。
- 企业微信只做观察提醒，不表达买卖指令。
