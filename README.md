# 归一量化工作站

本地、单用户的国内期货量化研究工作站：治理数据、查看 K 线、研究策略、回测与复盘、观察信号。它不提供无人值守自动实盘或自动下单。

## 快速导航

| 用途 | 文件 |
|---|---|
| 工程执行规则 | `AGENTS.md` |
| 当前状态与未关闭 Gate | `STATUS.md` |
| 项目定位与边界 | `PROJECT_SOURCE.md` |
| 长期决策 | `DECISIONS.md` |
| 测试入口 | `TESTING.md` |
| 个人开发工作流 | `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md` |
| 数据、架构、回测、信号、指标 | `docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/INDICATOR_KERNEL.md` |

接手时先读 `AGENTS.md` 和 `STATUS.md`，再按任务读取对应 deep canonical 或受控任务合同。

## 主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

正式 active 数据仅限 `rqdata/local_parquet + primary + quality_status != failed`；严格研究默认 `quality_status=passed`。

## 本地启动

```bash
cp .env.example .env
./scripts/dev-up.sh
```

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000/docs
```

## 统一 CLI（首轮只读）

```bash
uv run --project services/quant-api guiyi data verify \
  --symbol jm --contract jm.MAIN --period 15m --provider rqdata
uv run --project services/quant-api guiyi runtime status
uv run --project services/quant-api guiyi runtime plan --product jm
```

首轮 `guiyi` 只提供验证、状态和 dry-run plan；不包含 data sync、EOD、Runtime 执行、
通知、backup 或任何真实写入。旧 CLI/脚本仅按任务范围逐个保留兼容 Shim。

## 工程入口（Windows）

```powershell
pwsh -NoProfile -File .\scripts\engineering\preflight.ps1
pwsh -NoProfile -File .\scripts\engineering\validate.ps1 -Profile Engineering
pwsh -NoProfile -File .\scripts\engineering\secret-scan.ps1
```

普通仓库变更直接在 `develop` 编辑、本地验证、可选 commit/push。受控外部操作（正式数据/DB 写入删除、远端 release/tag、Runtime/live、真实通知、GitHub rules）需要范围明确的一次性执行意图；`-WhatIf`/dry-run 不授权真实 mutation。

## 安全边界

- 密钥只存在于本机环境；禁止写入仓库。`scripts/engineering/secret-scan.ps1` 默认 fail-closed。
- 不自动 push、merge、deploy 或下单。
- 真实数据、数据库、Runtime 或企业微信写入只接受范围明确的一次性执行意图；不得用 backup、packet、hash、receipt 或二次确认冒充授权。
- 信号和企业微信仅供研究观察，不是交易指令，也不自动下单。
