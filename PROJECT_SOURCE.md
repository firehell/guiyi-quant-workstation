# 归一量化项目事实源

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。它支持数据治理、K 线与指标、策略研究、历史回测、报告、复盘、信号观察与前向验证。

项目不是 SaaS、不是无人值守自动交易机器人、不连接实盘账户自动下单，也不把预警或回测结论表达成交易指令。

## Active target 与数据边界

```text
RQData
-> temporary staging
-> schema/session/duplicate/OHLCV/coverage validation
-> one historical canonical Parquet root (provider 1m / 1d / 1w)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService
-> Market / Web / Indicator / Backtest / Signal / Review
```

这是已冻结的目标，不表示迁移或消费者切换已经完成。目标数据身份使用不可歧义的
`DatasetKey`；`continuous` 与 `actual_dominant` 必须由消费者显式声明，禁止静默互换。
5m/15m/30m/60m 只从 canonical 1m 按交易时段确定性聚合，缓存不形成新的数据真相。

迁移期间既有 Profile/ActiveBinding/复杂 lineage 只作为 legacy compatibility。旧
`GY-CORE-02` Facade 与 `GY-CORE-03` CLI 壳允许复用，但不得继续扩展旧 active selector；
旧 `GY-CORE-04～08` 路线已 superseded/paused。迁移顺序与当前 Gate 见
`docs/tasks/GY-DATA-CORE-V2.md`。

legacy compatibility 数据入口仍必须满足：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、正式回测与正式信号默认使用 `quality_status=passed`。`validation`、`legacy_reference`、`candidate`、旧 TqSdk/天勤与来源不明数据不得进入默认 active 链路。

historical canonical 与 live observation 分离。live 只能用于观察、confirmed bar 聚合、
前向判断和盘后核对，不能复制或晋升为 historical canonical；EOD 必须重新获取 RQData
provider-final 数据并进行指纹与结果对账。

## 模块责任

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则与风险边界 |
| `STATUS.md` | 当前阶段、未关闭 Gate、必要锚点与红线 |
| `DECISIONS.md` | 长期架构、数据、回测与运行决策 |
| `TESTING.md` | 当前可执行的验证入口 |
| `docs/DATA_CENTER.md` | 数据资产、quality、profile 与 lineage |
| `docs/ARCHITECTURE.md` | 运行架构与组件边界 |
| `docs/BACKTEST_ENGINE.md` | 回测口径与可复算要求 |
| `docs/SIGNAL_EVENTS.md` | SignalEvent、通知与观察边界 |
| `docs/INDICATOR_KERNEL.md` | 指标版本、契约与 HTDY policy |
| `docs/DEVELOPMENT.md` | Lane、会话、worktree、PR 与人工 Gate |
| `docs/tasks/GY-DATA-CORE-V2.md` | 数据核心 V2 active 迁移合同与任务顺序 |

`docs/tasks/` 只存放尚未关闭的高风险合同，或仍被 Gate 哈希绑定的受控证据。
`GY-CORE-CONVERGENCE.md` 作为 superseded/frozen historical 迁移来源保留，不再是 active
执行手册。过程计划、历史任务与协作交接由 Git 历史追溯。

工作tree 生命周期由 ADR-WS-003 约束：`main` 是 canonical/release，`develop` 是长期集成主干，task 与 detached Runtime 物理隔离；task 从 develop 创建并由用户手动 PR merge 回 develop。`worktree_flow.py` 只管理本地已验证操作，`release-flow.sh` 仅在用户批准的精确 SHA 上更新远端；两者不替代 GitHub 审查、tag、Runtime promotion 或业务 Gate。

## 不做事项

- 自动交易、自动生成或发送订单。
- 将企业微信提醒表达为买卖指令。
- 用单次 smoke、数据文件存在或历史 replay 冒充长稳、数据可信或 live-confirmed 结论。
- 将可信回测或数据质量结论扩写为策略盈利、稳定或实盘准入。
- 在代码、文档、测试或日志中保存 webhook、token、密码、cookie、license 或账号信息。
