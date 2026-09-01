# 归一量化工作站

本地优先、单用户的国内期货研究工作站。行情事实链为 RQData → Canonical Parquet → 八表 Catalog + MainContractMap → MarketDataService；Web、指标、研究和 Alert 都在该边界内工作。不做自动交易。

## 怎么用

日常看盘走 Market Web（本机 launchd，或见 [deploy/README.md](deploy/README.md) 的 HTTPS 入口）：

- `/market`：行情看板，展示 Runtime 健康、苏冰 Daily Watch、当日苏冰策略动作。
- `/market/chart`：主力连续 K 线、当日 Live、主图 Overlay、提醒开关、苏冰当前状态与全历史效果、当日 Formal Event。

主图 Overlay 只有 **无 / 苏冰 / 火天大有**。

提醒在图表页打开，改的是 Alert Scope（受控写入）：

- **火天大有**：当前品种 × 当前周期。七个正式周期都能开；一次全开会很吵，按需要逐个加。
- **苏冰**：当前品种整品开关，只服务 15m 策略动作，推给 owner。Stage 2 会对研究池全算，开关只决定谁发 Event / 推送。

本机是否在跑：

```bash
./scripts/ops/macos/local-services-status.sh
uv run --project services/quant-api guiyi runtime status
```

缺数、审计才碰数据 CLI（`--apply` 另需明确写入授权）。优化苏冰公式才用 `guiyi research subing-calibration` / `subing-lifecycle`。`alert-canary` 是真实发送，不是试用按钮。

不要：自动下单、把 AlertEvent 当苏冰仓位、为「完成度」一次打开全部火天大有品种×周期、在公式未锁版本时把苏冰推送扩到全品种、恢复已退役的 N 字 / 日进斗金或其他旧产品面。

当前开了哪些提醒、Runtime 与 pending Gate 只看 [STATUS.md](STATUS.md)；产品边界只看 [PROJECT_SOURCE.md](PROJECT_SOURCE.md)。

## 快速导航

- [当前状态](STATUS.md)：release、Runtime、evidence 与 pending Gate。
- [稳定产品边界](PROJECT_SOURCE.md)：SuBing、HTDY、Alert 与研究边界。
- [工程规则](AGENTS.md) 与 [验证命令](TESTING.md)。
- [系统架构](docs/ARCHITECTURE.md) 与 [数据合同](docs/DATA_CENTER.md)。

## 当前产品面

苏冰保留 Daily Context、Current Signal State、Formal Event 与 Historical Projection，互不替代。火天大有是七周期观察，Scope 按品种 × 周期。苏冰 Candidate Validation 无 Web/CLI，不是日常入口。N 字、日进斗金、RQAlpha 与 Execution Review 已退役。

## 本地开发

```bash
uv sync --project services/quant-api --locked
uv run --project services/quant-api guiyi --help
pnpm --dir apps/quant-web install --frozen-lockfile
pnpm --dir apps/quant-web build
```

统一 CLI 的 Research 子命令为 `subing-calibration`、`subing-lifecycle` 与受独立数据写入 Gate 约束的 `subing-strategy-performance --warm-cache`。真实数据、生产 DB、Runtime、Scope、通知与 release/tag 均需独立明确授权。
