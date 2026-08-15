# 归一量化工作站

本地、单用户的国内期货量化研究工作站。当前代码版本身份为 `v1.3.1`；main/tag、production Runtime、
数据库 migration 与 Alert Scope 的实际状态以 `STATUS.md` 为准。当前可执行代码面包括 Market Web、
Canonical 历史行情、Market API、data CLI、Runtime 只读状态、Alert V2、当前交易日 Formal Signal、
Product 双 Rule Scope/今日记录，以及苏冰 Factor/Calibration/Signal 研究观察。项目不实现自动交易或
自动下单，`auto_order=false`。

## 快速导航

| 用途 | 文件 |
|---|---|
| 工程执行规则 | `AGENTS.md` |
| 当前状态 | `STATUS.md` |
| 项目边界 | `PROJECT_SOURCE.md` |
| 长期决策 | `DECISIONS.md` |
| 分层架构 | `docs/ARCHITECTURE.md` |
| Canonical 数据合同 | `docs/DATA_CENTER.md` |
| 行为规范 | `openspec/specs/` |
| 测试入口 | `TESTING.md` |
| 运维拓扑与只读检查 | `deploy/README.md` |

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

active universe 固定 60 品种，正式周期只有 `1m/5m/15m/30m/60m/1d/1w`。

## 本地状态与开发

```bash
./scripts/ops/macos/local-services-status.sh
```

这是唯一只读本地 Runtime 状态入口，不会启动、停止或重载服务。开发与验证命令见 `TESTING.md`；
仓库不提供会隐式执行 migration 或聚合切换多服务的一键开发启动器。

## 开发态 launchd 部署

当前本机 launchd 的实际部署根只以 `STATUS.md` 为准。开发期可临时直接运行主 `develop` 工作区，但修改源码不等于已部署：Web 重载前必须运行 `pnpm --dir apps/quant-web build`，API/Live 也需要重载才会采用新代码。

重载会改变 Runtime 状态，只在用户对当次目标和服务面给出明确执行意图后进行，不把 `--confirm-*` 当作日常无条件命令。功能收口后重新创建绑定精确提交的独立 Runtime worktree，再进行最终自然时点验收。

唯一 active 运维链是 Mac launchd → FRPC → 腾讯云 FRPS/Nginx；local/tunnel/public 三段只读检查及
配置入口统一见 `deploy/README.md`。

## Runtime 恢复验收

1. 先读 `STATUS.md`，再运行 `./scripts/ops/macos/local-services-status.sh`；不要用聊天记录推断当前 Runtime。
2. 核对 Runtime checkout 为 clean/detached 精确提交、五个应用 launchd 根与 loaded commit 一致、
   active/operational 均为 60，Alert Scope 未从 Market Runtime 范围自动扩大。
3. 核对 `/api/health`、`/api/runtime/health` 与真实 Market 业务字段；健康接口 200 不替代业务读回。
4. 盘后失败只读检查 launchd run count 与 `.run/after-market-status.json`，不得手工触发冒充自然成功。
5. 任何重载、Runtime switch、真实数据/DB 写入或 release/tag 均重新取得单次明确意图。

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

# SuBing Calibration 只读研究入口；实际运行需显式 phase/mode/frequency/window
uv run --project services/quant-api guiyi research subing-calibration --help
```

`update/refresh` 只有显式 `--apply` 才进入写入路径；参数本身不授权正式数据或生产环境 mutation。

`guiyi research subing-calibration` 的 Historical 输入只通过 `MarketDataService`，结果只以 JSON
写入 stdout。它不直接读取 provider，不写 PostgreSQL、Canonical Parquet 或 Redis，也不自动选择、批准
或晋升参数。Discovery/Validation 的临时 stdout 不是正式 artifact；当前唯一 accepted intraday
Calibration 是 Git-tracked 的 slope-only 文件
`data/research_policies/subing_calibration_intraday_v1.json`。

## 安全边界

- 凭据只来自本机环境，不写入仓库。
- 普通代码可在 `develop` 实现、测试、commit/push。
- 真实 RQData、正式 Canonical、生产 DB、Runtime/live、通知和 release/tag 只接受范围明确的一次性执行意图。
- 所有行情、指标和未来信号只用于研究观察，不是交易指令；`auto_order=false`。
