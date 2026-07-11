# 归一量化系统架构

更新时间：2026-07-10

## 1. 定位

归一量化是单用户、本地优先的国内期货研究工作站。V1 服务“数据 → 回测 → 报告 → 复盘 → 信号提醒 → 人工观察”，不做自动交易。

## 2. 主链路

```text
RQData 1m
-> raw parquet
-> standard 1m parquet + quality Gate
-> local aggregation 5m / 15m / 30m / 60m / 1d
-> manifest / checksum / PostgreSQL metadata
-> DuckDB read_parquet
-> vn.py CTA / FastAPI
-> PostgreSQL report / trade / order / signal / review facts
-> Vue Web
```

live 数据是独立观察层：

```text
RQData live 1m -> live_minute_bars
-> confirmed 5m/15m/30m/60m/1d/1w
-> preview (zero write)
-> optional formal live_confirmed event
-> optional guiyi-notifications queue -> observation-only WeCom
```

单 APScheduler 由 Redis singleton lock 防重复，交易 session clock 控制夜盘、午休、节假日和 close grace。live 表不自动登记为 historical active，不进入可信回测；formal event、盘后归档和企业微信分别由默认关闭的独立 Gate 控制，永不生成订单。

## 3. 模块

| 模块 | 职责 |
|---|---|
| `apps/quant-web` | Vue 3、Naive UI、Lightweight Charts；Data/Market/Backtest/Signal/Review/Runtime |
| `services/quant-api` | FastAPI、SQLAlchemy、Alembic、RQ、DuckDB、数据/回测/信号/复盘服务 |
| `packages/quant-core` | vn.py `CtaTemplate` 策略、配置和复盘标签 |
| `data` | raw/canonical parquet、manifest、质量与 Gate 报告 |
| `scripts` | 数据、审计、开发启停和受控运维入口 |
| `workstation` / `tasks` | WorkBuddy → CodeBuddy → Codex 状态机、任务与交接 |

## 4. 数据边界

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。禁止 validation、legacy_reference、candidate、failed、旧 TqSdk / 天勤和交易练习者数据进入默认 active 链路。

- `continuous_contract`：研究图、日线方向、回测上下文。
- `actual_contract`：真实合约成本、触发价、提醒和复盘上下文。
- `signal_events` 必须保留 product、continuous/actual contract、bar_end、trigger_price、provider、data_role 和 quality lineage。

## 5. 回测边界

```text
Backtest API
-> BacktestService
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit
```

- 信号收盘后仅允许 `next_bar_open` 成交口径。
- 手续费、滑点、乘数、最小变动和保证金必须可追溯。
- 报告曲线从 closed trades 派生，不信任外部传入曲线。
- Stage 13-G `report_id=14` 当前 trust audit 为 passed；收益为负，不能推导策略有效。

## 6. 运行与部署

### 本地开发

- Docker Compose：PostgreSQL、带密码 Redis，均只绑定 `127.0.0.1`。
- `dev-up.sh`：开发用途，可运行 Vite dev 和 uvicorn reload，不作为长期部署。
- `dev-status.sh` / `dev-healthcheck.sh`：只读检查，不自动启动或发送。

### macOS 长期运行

- `deploy/launchd` 提供 API、Web preview、backtest/signal worker、JM scheduler、notification worker 和日志轮转模板。
- 实施前运行态为 API/Web loaded、两个基础 worker missing；本轮没有加载/卸载 LaunchAgent。
- 当前仓库位于外接卷，后台权限仍需先解决；optional scheduler/notification 只有对应 flag 开启且人工 `--confirm-load` 才加载。
- 需要人工授予后台进程外接卷访问权限，或将长期运行副本放到本机磁盘后再加载。

### 公网入口

- 腾讯云 Nginx 443：TLS + Basic Auth，经 FRPS `18080/18000` 转发到 Mac mini 的静态 Web 与 FastAPI。
- Mac mini 使用 launchd 作为当前监督主线；仓库中的 systemd 单元仅是 Linux 同机运行候选，不是腾讯云当前运行事实。
- PostgreSQL、Redis、API、Web 和 FRPS 业务端口不得直接暴露公网。
- 当前只有配置级闭环，真实域名、证书、防火墙、隧道限制和远程恢复必须另做 smoke。

## 7. 当前未完成

- 全品种 8 个 `active_partial` 修复。
- live/after-market/formal event/notification 的真实 smoke 和 5 日长稳。
- API/Web/backtest/signal worker 的实际 launchd kill/restart 验收。
- 样本外 / walk-forward 验证。
- 真实公网部署验收。

以上未完成项均不得扩大为自动交易、SaaS、多用户或大型平台重构。
