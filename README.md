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

工作站精简盘点：`docs/workstation/WORKSTATION_SIMPLIFICATION_INVENTORY.md`（执行中）。

## 当前状态（摘要）

业务 Gate 以 `STATUS.md` 为准。工作站侧当前为：

```text
WORKSTATION_SIMPLIFICATION_IN_PROGRESS
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

正式消费者数据契约已 Ready；全历史 residual 仍并列保留 `DATA_LAYER_REAUDIT_REQUIRED`。不可把 Ready 扩写为 live / OOS / 自动交易。

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

工程入口（Step 4 起推荐）：`scripts/engineering/`。旧 `scripts/ai/dispatch_task.sh` 等仅兼容，不再作为正式架构。

## 安全边界

- 密钥只存在于本机环境；禁止写入仓库。
- 不接实盘自动下单；不自动 push / merge / deploy。
- 企业微信只做观察提醒，不表达买卖指令。
