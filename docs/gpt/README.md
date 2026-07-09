# GPT handoff package

生成时间：2026-07-09

本目录是浏览器 GPT 的当前项目事实包。这里保留的是当前可继续讨论和拆任务的文件，不再保留旧阶段 PoC 原始报告。

## 推荐阅读顺序

1. `CURRENT_STATE.md`
2. `PROJECT_SNAPSHOT.md`
3. `NEXT_STEPS.md`
4. `../../tasks/current.md`
5. `../DATA_UNIVERSE_AND_ARCHIVE.md`

## 当前结论

- Stage 2C / 2D / 2E 已完成。
- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- 当前 JM v2 data_version 为全窗口 `20230103_20260707_v2`。
- 六周期 DB 登记均为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- coverage audit 结论为 `can_enter_stage3=true`。
- Stage 8 `signal_events` 已完成代码级闭环。
- Stage 8.5 已完成到 8.5-9 final Gate：schema 最小实现、JM2609 actual-contract 写入试点、Web / live / evaluator 只读收敛和 Stage 9 前准入 Gate。
- Stage 8.6 全品种 active Gate 只读审计已完成代码级闭环（90 products, active_passed=82, active_partial=8）。
- Stage 9-A 企业微信只读 preview / dry-run adapter 已完成。
- Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成。
- Stage 9-B2 单条历史回放 smoke 已通过（event_id=1, HTTP 200, sent）。
- Stage 10-A / 10-B Web Market 策略展示增强、signal marker 点击联动和 notification 只读状态展示已完成。
- Stage 11-B / 11-C / 11-D 本地运行脚本增强、runtime health API 和 Web `/runtime` 只读 dashboard 已完成。
- Stage 13 可信回测主线复核已收口；`report_id=14` 当前样本 trust audit passed，但不代表所有历史报告或所有策略完全可信。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 中的 RQData 结构化元数据。
- 全品种下载已出现一批 manifest / processed summary，但仍处于"进行中 / 待审计"，不能直接写成全部可进入 active。
- Web 托管当前主线改为阿里云方案，Cloudflare Access 不再保留为当前执行文档；如需重启需另开设计任务。

## 下一步

1. `Stage 14`：Web 复盘闭环增强，基于 `report_id=14` 可信样本做只读展示和复盘链路增强。
2. `Stage 12`：阿里云 Web 托管设计与远程 health smoke，仍为 pending。
3. 企业微信 worker / scheduler / 批量重试、全品种 active Gate 最终确认、盘后归档真实写入仍需独立授权任务。

当前默认读取仍严格使用：

```text
rqdata / local_parquet + primary + quality_status != failed
```

## 仍需注意

- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因仍待后续确认。
- 企业微信真实发送 worker / scheduler、全品种 active Gate 最终确认、盘后归档真实写入、阿里云 Web 托管验收未完成。
- Stage 13 不是收益优化阶段；`report_id=14` 通过审计只代表当前样本。
- V1 不做自动下单，不接实盘交易。

## GPT 同步文件

- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/ALIYUN_WEB_HOSTING_PLAN.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/PROJECT_INVENTORY.md`
