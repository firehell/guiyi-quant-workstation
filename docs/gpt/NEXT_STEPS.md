# NEXT_STEPS.md

生成时间：2026-07-07
用途：冻结当前阶段顺序，供浏览器 GPT 持续拆 Codex 任务。

## 1. 总原则

```text
先数据，后信号；
先事件，后提醒；
先真实合约绑定，后企业微信；
先后端稳定，后 Web 美化；
先只读观察，后考虑交易辅助；
V1 不自动下单。
```

## 2. 阶段路线

| 阶段 | 名称 | 状态 | 建议新会话 |
|---|---|---|---|
| 阶段 0 | 重构基线冻结 | done | 否 |
| 阶段 1 | RQData 权限与接口能力 PoC | done / partial accepted | 是 |
| 阶段 2 | JM 历史数据更新到最新交易日 | done | 是 |
| 阶段 3A | active 数据过滤测试 | done | 是 |
| 阶段 3B | Web Data 页面 smoke | done / code-level smoke | 是 |
| 阶段 4A | RQData 实时 1m 入库设计 | done / design complete | 是 |
| 阶段 4B | RQData 实时 1m 最小入库实现 | done / code-level complete | 是 |
| 阶段 5 | 1m 聚合多周期 | done / code-level complete | 是 |
| 阶段 6A | Web Market 显式 live 查看 | done / code-level complete | 是 |
| 阶段 6B | 策略中心 live_evaluator 只读接入 | done / code-level complete | 是 |
| 阶段 7 | 通达信指标本地化，标注未来函数 / 重绘风险 | done / code-doc risk review | 是 |
| 阶段 8 | `signal_events` 信号事件化 | done / code-level complete | 是 |
| 阶段 8.5 | 数据主链路扩展 Gate | active / 8.5-0..8.5-7 done | 是 |
| 阶段 9 | 企业微信只读提醒 | blocked until Stage 8.5 Gate passes | 是 |
| 阶段 10 | Web Market 策略展示增强 | pending | 是 |
| 阶段 11 | 本地长期运行 / worker / scheduler / health check | pending | 是 |
| 阶段 12 | Cloudflare Access 本地 Web 访问部署验收 | pending | 是 |
| 阶段 13 | Codex git commit / push 自动化 | optional | 可选 |
| 阶段 14 | 可信回测主线复核 | pending | 是 |

## 3. 最近完成阶段

Stage 2 已完成：

- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- data_version 为全窗口 `20230103_20260707_v2`。
- 六周期均登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- coverage audit 结论为 `can_enter_stage3=true`。

Stage 3 已完成代码级闭环：

- `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`：默认读取只允许 `rqdata/local_parquet + primary + quality_status != failed`。
- `WEB-DATA-3B-DATA-PAGE-SMOKE`：Web Data 页面可查看覆盖、质量、行数、data_version 和文件路径。

Stage 4A / 4B / 5 已完成 live 数据骨架：

- live 1m 入库设计与最小实现已完成。
- live 多周期聚合已完成。
- live 表不登记 `market_data_files`，默认 Market / Backtest / Signal 读取行为保持不变。
- live 数据不自动混入 historical active。

Stage 6A / 6B 已完成显式 live 查看和只读 evaluator：

- Web Market 支持 `historical` / `live` 显式模式，默认仍为 historical。
- `live_signal_evaluator` 只返回 preview，不写 `StrategySignal` / `SignalNotification` / `SignalEvent`。
- entry bars 来自 live DB，日线方向来自 active primary historical `1d`。

Stage 7 已完成通达信 XMA 风险审查：

- 原始 `XMA`、`ZK1/ZD1/ZD2`、`VAR23` 标记为 `forbidden_for_backtest_signal`。
- Stage 7 没有把 XMA PoC 接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。

Stage 8 已完成 `signal_events`：

- 新增 `SignalEvent` / `signal_events` append-only 事件账本。
- 支持 `signal_created`、`signal_changed`、`signal_status_changed`。
- 新增只读 API：`GET /api/signals/events` 和 `GET /api/signals/{signal_id}/events`。
- Stage 8 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`，没有生成订单或自动下单。

Stage 8.5-0 / 8.5-1 / 8.5-2 / 8.5-3 / 8.5-4 / 8.5-5 / 8.5-6 / 8.5-6B / 8.5-7 已完成数据主链路 Gate 的审查、口径冻结、schema Plan、schema 最小实现、RQData 元数据只读方案、historical bars 设计冻结、JM2609 真实写入试点和 Web 只读消费扩展：

- `strategy_signals` 与 `signal_events` 已具备显式 contract context 字段。
- `.MAIN` 主连只写入 `continuous_contract`，不伪装为 `actual_contract`。
- API 已输出并支持过滤 `product`、`continuous_contract`、`actual_contract`、`provider`、`source`、`data_role`。
- 8.5-4 已锁定 V1-B 默认目标品种池为 `jm`，metadata 源复用 `FuturesContractUniverse`、`MainContractMap`、`FuturesContinuousContractMap`、`FuturesTradingParameter` 和 `FeeMarginRule`。
- 8.5-5 已锁定 `jm.MAIN` 只作为研究主连资产；当前真实主力合约 historical bars 后续必须独立写入、独立质量报告、独立 active Gate。

## 4. 当前阶段：Stage 8.5

目标：在 Stage 9 前补齐数据主链路口径，保证提醒事件能明确表达 product、研究主连、真实主力合约、触发价、数据源、质量状态和 confirmed bar 边界。

已完成：

- `8.5-0 Stage 8 输出审查`：done / docs-level。
- `8.5-1 数据新口径冻结与文档更新`：done / docs-level。
- `8.5-2 schema / model 变更 Plan`：done / docs-level。
- `8.5-3 schema / model 最小实现`：done / code-level。
- `8.5-4 RQData 元数据与目标品种池只读 Plan`：done / docs-level。
- `8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结`：done / docs-level。

关键文档：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`

当前结论：

- 当前 `signal_events` 已具备 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source` 等显式字段。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约，`actual_contract` 缺少真实映射证据时保持 `NULL`，`trigger_price` 仍来自主连 bar close，不足以承接 Stage 9。
- 8.5-4 已明确 `actual_contract` 只能来自 `MainContractMap.rank=1`，`dominant_mapping_date` 对应 `MainContractMap.trade_date`，trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission。
- 8.5-5 已明确 `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 只能作为研究背景。
- 8.5-6 已完成代码 + dry-run + fixture 测试闭环；默认 dry-run 不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- 8.5-6B 已完成 JM-only 当前真实主力合约 historical bars 真实最小写入试点：`actual_contract=JM2609`、`dominant_mapping_date=2026-07-07`、`1m/5m/15m/30m/60m/1d` 六周期均已登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- 8.5-7 已完成 Web Data / Web Market actual-contract 只读消费扩展：Market coverage 输出 `view_role`、`continuous_contract`、`actual_contract`、`latest_bar_time`、`data_version`、`data_role`、`file_path`，Web Data / Web Market 已显式展示 `jm.MAIN` 与 `JM2609` 的视图差异和覆盖边界。
- Stage 9 在 Stage 8.5 Gate 通过前保持 blocked。

## 5. 下一步任务

### Stage 8.5-8：live 监听目标合约池 + evaluator 数据源收敛

目标是让 live 监听目标合约池和 evaluator 数据源显式对齐 `MainContractMap.rank=1` 解析出的真实合约，并继续保持 preview / readonly 边界。

允许范围：

- 只读解析目标真实合约和本地 coverage。
- 显式区分 continuous historical view、actual-contract historical view 和 live observation。
- 目标品种仍限 `jm`，默认不扩全品种。
- evaluator 仍只返回 preview，不写 `StrategySignal` / `SignalEvent` / 企业微信。

禁止范围：

- 不运行真实 RQData 写入。
- 不修改已生成 parquet / manifest 资产。
- 不把 `jm.MAIN` close 当作真实合约 trigger price。
- 不接企业微信。
- 不修改策略逻辑和回测口径。
- 不把 live evaluator preview 直接持久化为正式事件。
- 不把 `JM2609` 硬编码为长期真实主力。

建议测试：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_live_market_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_market_dominant_reader.py
uv run --project services/quant-api ruff check <changed python files>
git diff --check
```

## 6. Stage 9 前置 Gate

进入企业微信前必须满足：

- `signal_events` 能显式区分 product / continuous contract / actual contract。
- `trigger_price` 明确来自 actual contract。
- `bar_end` 已确认。
- `quality_status != failed`，严格场景优先 `passed`。
- 企业微信 payload 能显示真实合约，不表达实盘指令。
- webhook 只从环境变量读取，不进文档、DB、日志或 payload。
- V1 仍不自动下单。
- 真实 RQData `--run-readonly` 或 historical write 均需单独授权。

## 7. 下一轮 GPT 上传文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/CURRENT_STATE.md`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/alembic/versions/20260707_0016_signal_contract_context.py`
