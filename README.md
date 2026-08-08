# 归一量化工作站

本地、单用户的国内期货量化研究工作站。当前可执行面是 Market Web、Canonical 历史行情、
Market API、data CLI 和 Runtime 只读状态。项目不实现自动交易或自动下单。

## 快速导航

| 用途 | 文件 |
|---|---|
| 工程执行规则 | `AGENTS.md` |
| 当前状态 | `STATUS.md` |
| 项目边界 | `PROJECT_SOURCE.md` |
| 长期决策 | `DECISIONS.md` |
| 分层架构 | `docs/ARCHITECTURE.md` |
| Canonical 数据合同 | `docs/DATA_CENTER.md` |
| active 数据任务 | `docs/tasks/GY-DATA-CORE-V2.md` |
| 测试入口 | `TESTING.md` |

## 数据主链路

```text
RQData
-> temporary staging
-> normalization + six hard validations
-> Canonical Parquet
-> PostgreSQL 八表 Catalog / MainContractMap
-> MarketDataService
-> Market Web / Indicator / future research
```

active universe 固定 69 品种，正式周期只有 `1m/5m/15m/30m/60m/1d/1w`。

## 本地启动

```bash
cp .env.example .env
./scripts/dev/dev-up.sh
```

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000/docs
```

## 统一 CLI

```bash
# 精确增量规划；缺省不写入
uv run --project services/quant-api guiyi data update \
  --universe active --since 2026-08-01 --through 2026-08-07

# 指定窗口的强制月度重建规划
uv run --project services/quant-api guiyi data refresh \
  --symbol jm --since 2026-08-01 --through 2026-08-07

# 当前 Canonical/Catalog 只读审计
uv run --project services/quant-api guiyi data audit --universe active

uv run --project services/quant-api guiyi runtime status
```

`update/refresh` 只有显式 `--apply` 才进入写入路径；参数本身不授权正式数据或生产环境 mutation。

## 安全边界

- 凭据只来自本机环境，不写入仓库。
- 普通代码可在 `develop` 实现、测试、commit/push。
- 真实 RQData、正式 Canonical、生产 DB、Runtime/live、通知和 release/tag 只接受范围明确的一次性执行意图。
- 所有行情、指标和未来信号只用于研究观察，不是交易指令；`auto_order=false`。
