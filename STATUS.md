# 当前状态

更新时间：2026-08-02

本文件是项目当前状态仪表盘：只列当前任务、未关闭 Gate、必要事实锚点与防过度宣称红线。
历史过程由 Git、任务合同及既有 receipt/report/evidence 追溯。

## 当前在做什么

当前 active 执行合同为 `docs/tasks/GY-DATA-CORE-V2.md`。Task 00～03 已按各自 PR、测试、
独立 Review 与 CI 合入 `develop`。Task 04 已完成 JM historical canonical 数据落库、
Catalog/Manifest/checksum/Gap、统一 `MarketDataService` 读取，以及普通 Web/API/指标消费者
切换和回归；本 closeout commit 经 Draft PR 的 exact-head CI、独立 Review 与 GitHub
merge commit 合入 `develop` 后，Task 04 状态生效为 `completed on develop`。

Task 04 的正式验收只依赖 Canonical 自身：

```text
canonical schema + coverage
-> Catalog / Manifest / physical checksum
-> DataGap fail-closed
-> MainContractMap completeness
-> MarketDataService representative reads
-> ordinary Web / API / indicator consumer regression
```

legacy 与 Canonical 全历史逐条 OHLCV 一致、13/13 legacy historical Shadow、旧 Profile/Binding
兼容扩展，以及因 Shadow plan digest 变化重新生成 packet/preflight/apply receipt，均不再是
Task 04 或 Task 05 的准入 Gate。PR #90～#94、既有 Shadow 失败、identity/session compatibility
实现、旧 packet 与 receipt 继续作为 frozen historical evidence 或可选诊断能力保留，不删除、
不改写，也不继续执行生产 Shadow。

2026-08-02 Task 04 closeout 只读现场对账（其后 Task 06 migration incident 已使 revision 变化）：

- PostgreSQL revision：`20260730_0027`；
- Catalog：`85 datasets / 85 partitions / 0 gaps`；
- physical：`85 Parquet + 85 Manifest + 85 prepared metadata = 255 canonical files`；
- staging：`0 files`；
- 85/85 partitions 的物理 checksum、Manifest digest、Catalog identity、coverage 与 row count
  全部复验一致；
- MainContractMap 目标窗口 `2013-03-22..2026-07-30` 有 3395 条保留版本的物理 view rows，
  解析为 3245 个唯一 DCE 交易日，缺失 0、歧义 0；
- `continuous / JM.MAIN` 的 provider-direct `1m/1d/1w` 与 canonical 1m 确定性聚合
  `5m/15m/30m/60m` 通过；
- `actual_dominant / JM2609` 的 provider-direct `1m/1d` 与 canonical 1m 确定性聚合
  `5m/15m/30m/60m` 通过；无显式合约的 resolver 查询也解析到 JM2609；
- 所有现场读取均报告 `calls_rqdata=false / writes_parquet=false / writes_postgresql=false`。

本次不重新下载 RQData、不重写 Canonical Parquet、不修改生产 PostgreSQL、不生成或批准新
packet、不执行 preflight/apply/legacy Shadow，也不删除旧行情、Profile、Binding、receipt、
report、evidence 或 legacy reader。

Task 05 的 Backtest / Signal / Review canonical consumer 切换、synthetic/golden 回归与
derived/reference 只读 inventory 已在独立 task worktree 完成，exact-head independent Review
返回 `CLEAN_FOR_INTEGRATION`。本状态只在 task PR 可从 `develop` 到达且 post-merge CI 成功后生效；
真实 PostgreSQL/data root 只读盘点仍是 Task 07 的 external Gate，不阻塞 Task 05，也不授权删除。

Task 06 clean-start live/review loop 已完成代码、生产 migration 与 empty/disabled 验收。实现
新增 additive `20260802_0028` + identity correction `20260802_0029` + create-only trigger
`20260802_0030` + provider-lineage `20260802_0031`、immutable live
observation/SignalDecision、EOD 四类对账、
人工 Review → ResearchSample 与 exact 30 天 retention；全部开关默认关闭。隔离 PostgreSQL
upgrade/downgrade/upgrade 已通过。独立 Review 阻断了未授权的 centered-XMA 新 policy；该实现
已撤回。Owner 随后冻结唯一允许的 `jm_data_core_v2_ema21_direction_observation/v1.0`：confirmed
15m close 对因果 `ema21/v1`，policy=`ema_sma_window_v1`，固定参数与 recipe，equal=no_signal。
trusted builder 不再接受任意 identity/parameters，Runtime 与 EOD 均绑定该 evaluator，且 Task 06
health 已接入 `/api/runtime/health`。Owner 选择保留并追认 empty/disabled `0028` incident，但不把
事故改写为事前批准。随后对 PR #105 head `300cccbd` 给出 exact approval；database-only backup
`task06-pre0031-6c747ab6` 完成校验，production 已升级到 `0031`，五张 Task 06 表仍空、既有
SignalEvent 仍 6 行且 decision link 全空、六个 flags 全 false、health 仍 disabled。PR #105 合入
`develop` 后 Task 06 完成状态生效；本次仍不授权真实 RQData、scheduler、Runtime、
SignalEvent、通知、删除或交易。

Task 07 仍为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`，且任何生产写入均未授权。生产收口
preflight 发现原 code-only closeout 的 generic inventory、retirement apply 与文件 quarantine
超出永久合同；当前 Lane 3 修复 candidate 从 `develop@672877a8` 建立，收窄为
七周期 K 线 `kline-manifest -> plan/preflight/apply/verify`，取消 checkout/Runtime 通用
reference inventory、retirement/deletion/quarantine 公共入口和 raw 逐行比较。该 candidate
现使用专用 manifest schema 与 sibling-directory atomic bundle publish；evidence root 与
project/data/canonical root（含 symlink 解析）重叠即 fail-closed，四类 Direct trading-day
conflict 均只形成未授权的 RQData 重下动作。验证为 focused 122 passed、backend
2684 passed / 44 skipped、frontend 191 passed / 1 skipped、frontend build、Ruff、secret scan
和 engineering all-safe 385 + health 6 全通过。独立 Review round 1 为
`0 Critical / 4 Important`，原四项均已修复；round 2 确认原四项关闭，但发现非 RQData
Direct 冲突 provider mismatch 与遗漏 bounded WeCom 真实发送开关两个新 Important。当前修复将
公共请求强制绑定 `provider=rqdata`、原 provider 仅作诊断并增加 integrity 一致性校验，同时将
`GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=false` 纳入 Runtime receipt 强制合同；仍须
对新 exact head 复审。第三轮随后发现 action/request 只绑定 provider 而未绑定完整身份这一
Important；当前已将 symbol、contract、dataset kind、frequency、adjustment、schema、window 与
provider/original provider 全部逐字段绑定，并增加 forged identity/window 拒绝测试。仍须第四轮
exact-head Review、PR/CI 与 develop ancestry 回读，未通过复审前不得形成 release candidate。

旧 v8 生产只读 snapshot 的 103,481 assets、2,791 conflicts、4,297 retirement candidates
与引用数字均为 superseded 历史诊断，不能用于任何 approval。
绑定 clean `e01784ff` 与 production `20260802_0031` 的 v9 诊断已采集：103,481 assets
未截断，内容冲突为零，2,817 项显式进入 DataGap；但正在提供 API 的 detached Runtime
`10351ccd` 仍有 300 active 与 1,581 review-required 命中，因此 migration plan 正确返回
`approval_eligible=false / writes_authorized=false`。项目所有者于 2026-08-03 确认已删除的
`/Volumes/扩展盘/GuiyiApprovals` 不再作为必需 protected root；evidence root 改为自动受保护，
该路径不再是 Gate。protected 分类同时覆盖登记路径和符号链接解析后的物理路径。v9 的 base SHA
已被后续 hardening supersede，且 Runtime active-reference
仍非零，所以它仍是 blocker diagnosis，不是最终 approval inventory。当前未调用 RQData、
未写 Canonical/PostgreSQL，也未执行
retirement DML。脱敏 ledger 见 `docs/tasks/GY-DATA-CORE-V2-TASK07-EVIDENCE.md`。

初步 checksum-drift 对照曾发现 45 个品种共 78,210 根 bar 的 `trading_day` 冲突；最终 v8 内容
Gate 进一步直接识别出 2,791 个文件至少包含一个周末 trading day。因此不得把 checksum drift
当作纯 metadata 修复，也不得让现有 `quality_status=passed` 绕过 session Gate。

## 数据核心任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| GY-DATA-CORE-V2 Task 00 | completed on develop | PR #76；治理和 canonical target 冻结 |
| GY-DATA-CORE-V2 Task 01 | completed on develop | PR #78；数据合同与 golden vectors |
| GY-DATA-CORE-V2 Task 02 | completed on develop | PR #80；Catalog/Manifest/Gap schema 与隔离 migration 验证；生产 revision 已是 0027 |
| GY-DATA-CORE-V2 Task 03 | completed on develop | PR #82；staging、quality 与 canonical writer |
| GY-DATA-CORE-V2 Task 04 | completed on develop（本 closeout commit 可从 develop 到达时生效） | Canonical 自身 Gate、统一读取与普通消费者回归；legacy Shadow 不再是准入 Gate |
| GY-DATA-CORE-V2 Task 05 | completed on develop（本 task PR merge 后生效） | canonical trusted consumers、synthetic/golden tests、fail-closed derived/reference inventory；不含真实删除或外部 DB/data-root inventory |
| GY-DATA-CORE-V2 Task 06 | completed on develop（PR #105 merge 后生效） | 固定 EMA21 evaluator + `0028..0031` + live/decision/EOD/Review/Sample/retention；production=`0031`，empty/disabled smoke passed |
| GY-DATA-CORE-V2 Task 07 | `CODE_COMPLETE_EXTERNAL_GATE_PENDING` / production `BLOCKED_ACTIVE_REFERENCE` | code-only closeout 的 checkout scan=0/0；旧 v9 detached Runtime 300/1,581 仅为未重采 blocker evidence；无生产读取、写入或删除 |
| GY-DATA-CORE-V2 Task 08 | pending | 仅在 Task 07=`READY_FOR_TASK_08` 后进入 release/Runtime Gate |

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产 residual 为零 |
| Task 05 可信消费者切换 | independent Review passed；develop integration pending | `CLEAN_FOR_INTEGRATION`；仍须 task PR、post-merge CI 与 ancestry readback，不是 release 或 Runtime Gate |
| Task 07 code-only closeout | `CODE_COMPLETE_EXTERNAL_GATE_PENDING` | 七周期专用、atomic K 线 manifest candidate 已验证；round 1 的 4 Important、round 2 的 2 Important、round 3 的完整 request/action identity Important 均已修复，fourth exact-head review、PR/CI 与 develop 集成仍 pending |
| Task 07 K-line data Gate | blocked by prerequisite | v9 内容冲突为零、7,232 trusted sources / 411 batches，但该 snapshot 已被代码变更 supersede，且未取得 exact apply approval，不得写入 |
| Task 07 active-reference Gate | `BLOCKED_ACTIVE_REFERENCE` | 当前 checkout active=0 / review-required=0；旧 v9 detached Runtime 300/1,581 与 DB before-image 4,297 未在本轮重采，仍不得据此执行 retirement |
| Task 06 live/EOD contract | passed | 已冻结并验证单一 EMA21 confirmed-close observation 合同；不得注入其他 evaluator，且不扩展 centered-XMA 白名单 |
| Task 06 production migration | passed | exact backup + approval 后完成 `0028 -> 0031`；empty/disabled smoke passed，不授权 Runtime/live enable |
| 旧行情与 legacy 工件删除 | not authorized | 旧行情只读保留；任何删除需独立 exact deletion Gate |
| release / main / tag | not authorized | 本 closeout 只合入 develop |
| Runtime promotion | not authorized | Runtime 保持独立 detached，不同步本任务 |
| JM Runtime 验收 | pending redesign | 单日自然运行、同一 exact release 恢复证据、独立 Review 与用户最终批准 |
| 长稳 / 通知 / 交易 Ready | not ready | 本任务不启用 live、不发送通知、不授权订单或自动交易 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

task 自动集成只适用于通过验收、CI、独立 Review 且 exact head 匹配的可逆开发变更。
生产 migration、真实数据/DB 写入、删除、`main`/release/tag、Runtime/live enable 和真实通知
仍是人工 Gate；代码进入 `develop` 不构成这些操作的批准。

## 必要事实锚点

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | `20260802_0031`（Task 06 exact Gate；五张新表全空、flags false） | backup、migration 与 disabled smoke 见 Task 06 approval/receipt packet |
| Canonical current state | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 closeout DB、Manifest 与物理 checksum 只读复验 |
| MainContractMap | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 closeout 只读 mapping audit |
| legacy compatibility | PR #90～#94 实现与历史 evidence 保留；不再扩展或作为准入 Gate | `docs/tasks/GY-DATA-CORE-V2.md` |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | `docs/tasks/JM-LIVE-STABILITY-S6-10.md` |
| Task 05 | completed on develop（本 task PR merge 后生效） | trusted consumers and fail-closed inventory complete；real DB/data-root inventory remains a Task 07 external Gate |
| Task 07 | `CODE_COMPLETE_EXTERNAL_GATE_PENDING` / production Gate 未重开 | permanent-contract remediation 基于 `develop@672877a8`；Review round 1 未通过且修复后复审 pending；v9 生产数字未重采；production apply/readback、Runtime cutover、retirement/deletion 未执行；`READY_FOR_TASK_08=false` |

## 不可宣称

- 不可宣称所有历史资产 residual 为零。
- 不可把 Task 04 完成扩写为 release、Runtime promotion、Runtime Ready、长稳 Ready、通知 Ready
  或交易 Ready。
- 不可把 Canonical 数据验收写成旧 Profile/Binding 已删除，或写成旧行情、receipt、report、
  evidence 已获删除授权。
- 不可把既有 legacy Shadow 失败、PR #90～#94 或历史 packet/receipt 改写成新的生产授权。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 Task 05 branch-local 完成写成 `develop` merge、release、Runtime、notification、deletion 或
  profitability；Task 07 删除前仍须 exact manifest、zero active refs、independent Sol Review 与 owner approval。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；
  `REJECTED_RESEARCH_CANDIDATE` 不得被翻转。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、
`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
