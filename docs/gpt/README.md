# GPT handoff package

生成时间：2026-07-11

本目录是浏览器 GPT 的当前项目事实包。这里保留的是当前可继续讨论和拆任务的文件，不再保留旧阶段 PoC 原始报告。

## 推荐阅读顺序

1. `WEB_INDICATORS_C2_REVIEW_PACKAGE.md`
2. `CURRENT_STATE.md`
3. `PROJECT_SNAPSHOT.md`
4. `NEXT_STEPS.md`
5. `tasks_current.md`
6. `../DATA_UNIVERSE_AND_ARCHIVE.md`

## 当前结论

- Stage 2C / 2D / 2E 已完成。
- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- 当前 JM `1m` data_version 为 `rqdata_jm_standard_1m_20230103_20260710_v2`；`5m/15m/30m/60m/1d` 均由该 passed `1m` 本地聚合。
- 六周期 DB 登记均为 `data_role=primary`、`quality_status=passed`；派生周期使用 `provider=local_parquet` 并保留 `source_interval=1m`。
- coverage audit 结论为 `can_enter_stage3=true`。
- Stage 8 `signal_events` 已完成代码级闭环。
- Stage 8.5 已完成到 8.5-9 final Gate：schema 最小实现、JM2609 actual-contract 写入试点、Web / live / evaluator 只读收敛和 Stage 9 前准入 Gate。
- Stage 8.6 全品种 `1d` Gate 为 90 products、82 `active_passed`、8 `active_partial`；JM 最新主连六周期 Gate 为 1 product、6 assets 全部 `active_passed`。
- Stage 13-G `report_id=14` trust audit 已通过；可信通过不代表策略盈利或可实盘。
- Stage 9-A 企业微信只读 preview / dry-run adapter 已完成。
- Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成。
- Stage 9-B2 单条历史回放 smoke 已通过（event_id=1, HTTP 200, sent）。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 中的 RQData 结构化元数据。
- 全品种下载已出现一批 manifest / processed summary，但仍处于"进行中 / 待审计"，不能直接写成全部可进入 active。
- Web 托管当前主线改为阿里云方案，Cloudflare Access 保留为历史备选。
- Web C2 主图指标统一 EMA 接入已进入 `DELIVERY_READY`，请先审 `WEB_INDICATORS_C2_REVIEW_PACKAGE.md`；C3 实时跟随/增量计算必须等 C2 审查通过后单独开题。

## 下一步

1. 在独立 Plan 中完成公网 TLS、访问控制及 5432/6379 外网不可达的真实远端验收。
2. 解决 macOS LaunchAgent 读取外置盘项目目录的隐私权限 Gate，再做重启恢复验收。
3. 仅设计 `report_id=14` 样本外验证，不修改策略参数改善收益。
4. live ingest / scheduler 另开独立 Plan，只允许观察与提醒，不自动下单。

当前默认读取仍严格使用：

```text
rqdata / local_parquet + primary + quality_status != failed
```

## 仍需注意

- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因仍待后续确认。
- 公网 TLS / 认证 / 端口不可达仍未在远端主机实测；本地只有安全配置和脚本级验证。
- macOS LaunchAgent 因项目位于外置盘而被系统隐私策略拒绝读取 `.env`，已卸载失败 job，不能写成长期运行已通过。
- V1 不做自动下单，不接实盘交易。

## GPT 同步文件

- `docs/gpt/WEB_INDICATORS_C2_REVIEW_PACKAGE.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/tasks_current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/ALIYUN_WEB_HOSTING_PLAN.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/PROJECT_INVENTORY.md`
