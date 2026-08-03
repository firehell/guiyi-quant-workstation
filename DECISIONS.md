# 架构决策记录

本文件只记录长期影响代码、数据口径或运行边界的有效决策；当前状态见 `STATUS.md`，过程资料由 Git 与 final receipt 追溯。

## 当前有效决策

| 主题 | 决策 | 边界 |
|---|---|---|
| 产品 | 本地单用户国内期货研究工作站 | 不做自动交易、SaaS、多用户或无人值守下单 |
| 迁移期 legacy compatibility 读取 | RQData/标准 Parquet → metadata/profile/lineage → 旧 consumers | 仅保留旧消费者保护：`rqdata/local_parquet + primary + quality != failed`，严格研究 passed-only；不是 V2 active selector，不再扩展 |
| 历史与 live | canonical historical 与 live observation 分层 | live 不直接成为正式历史 active |
| 指标 | 复用公共指标内核、逐调用方迁移 | Web/回测/实时不得长期各自实现一套算法 |
| 回测 | vn.py 引擎不改源码，策略/参数/数据/订单/trade/equity/lineage 可复算 | 可信度优先于收益；不覆盖旧报告 |
| 信号与通知 | `Strategy -> SignalEvent -> Notification Gate -> Channel` | 研究观察、幂等、默认关闭真实发送、无订单 |
| HTDY original | 精确 realtime first-seen observation-only exception | 不授权历史回测、收益、自动通知或交易；见指标与信号 canonical |
| 真实写入 | 按业务域使用 hash-bound、scope-bound approval packet/Gate | Issue 或测试通过均不能替代专用 Gate |
| worktree | canonical、集成、task 与 detached Runtime 物理隔离 | `main` 为 canonical/release，`develop` 为长期集成主干；task 经 PR/CI/独立 Review 后可自动 merge commit 合入 develop，只有 clean 且已合入才可清理 |
| task 自动集成 | Lane 1/2 与 code/test/dry-run/隔离 migration/disabled-only Lane 3 满足验收、CI、独立 Review、exact head 后由 Codex 编排层合入 `develop` | 不直推 develop；不授权生产 migration、真实数据写入、删除、main/release/tag、Runtime/live 或通知 |
| release | `release-flow.sh` 以精确 SHA 受控发布 | 用户批准、main/develop clean 且同 SHA 才可 apply；task→develop 自动集成不授权发布、tag 或 Runtime |
| 数据核心 V2 active target | RQData 是唯一上游；Canonical 持久化 provider-direct `1m/1d/1w` 与 preaggregated `5m/15m/30m/60m`，再经 Catalog/Manifest/Gap/MainContractMap 由 `MarketDataService` 同频读取 | canonical Parquet 是受治理存储而非第二上游；缺少同频 dataset/partition 必须 DataGap，不做历史跨频 fallback |
| Canonical 数据准入 | 只依赖自身 schema、coverage、Manifest digest、物理 checksum、Catalog、DataGap、MainContractMap 与代表性统一读取验证 | legacy 与 Canonical 全历史逐条一致不是正式准入条件；legacy Shadow 仅为可选诊断或 frozen compatibility，不是 Task 04 或 Task 05 前置 Gate |
| 数据身份 | `DatasetKey` 唯一定位；正式历史 allowlist 唯一为 `1m/5m/15m/30m/60m/1d/1w`；`continuous` 与 `actual_dominant` 显式且不可互换 | 新 active BarsResult 的 request/source/bars 必须同频且 `derived_frequency=null`；actual-dominant `1w` 使用该周最后交易日 rank=1 合约 |
| Task 07 冲突修复 | direct `1m/1d/1w` 只生成 exact-window `rqdata_redownload`；aggregate `5m/15m/30m/60m` 只生成 exact-window `canonical_1m_reaggregate` | 两类 action 默认未授权；不建 legacy/new 逐行对比、reconciliation 或多源仲裁；失败保留旧有效 Canonical 并登记 DataGap |
| Task 07 Runtime cutover | 代码仅提供 read-only plan/verify；最小 Gate 为 exact target/previous tag+SHA、DB `20260803_0032`、全部功能默认 disabled、health/smoke passed、rollback-ready 和 checkout/Runtime reference zero | 不提供 stop/switch/restart/apply；该 code-only 合同不解锁 retirement/deletion，本 PR 不执行 Runtime 或生产写入 |
| V2 迁移资产 | 只迁移 trusted historical bars 及最小 Catalog/Manifest/Gap/MainContractMap metadata | 旧 indicator/cache、Backtest、Signal/Review、live/EOD/Sample、permanent derived period、重复 bar layer 与 Profile/Binding/legacy lineage 均为 rebuild-only 或 compatibility-only，不得提升为 active migration asset |
| Profile/Binding 迁移 | 既有 Profile/ActiveBinding/复杂 lineage 仅作 legacy compatibility，按消费者切换、rollback、引用清除后再决定受控退出 | GY-CORE-02 Facade 与 GY-CORE-03 CLI 壳可复用；旧 active selector 不再扩展；退出不以 legacy Shadow 为前置条件 |
| GY-CORE 路线替换 | 旧 GY-CORE-04～08 superseded/paused；04 已合入代码保留为 legacy compatibility | 不按旧路线进入 Shadow、release、Runtime 或删除 |
| 运行明细留存 | live/decision/event/notification/reconciliation/snapshot/fingerprint 目标为统一 30 天；人工复盘后仅提取精简 ResearchSample | 目标未实现；清理需要独立 deletion Gate，修复/replay 永不补发通知 |
| 历史工件受控删除 | evidence/report/receipt 默认保护；只允许 exact deletion manifest + zero active references + independent Sol Review + owner exact-scope approval 后的受控删除 | 决策不直接授权任何删除；report 14/15 为 Git-traceable historical snapshots，不是 active Gate/regression，也不改写或删除历史证据 |
| Task 04 legacy 保留 | 已下载旧行情只读保留；PR #90～#94 的 Shadow/identity/session 实现可保留为可选诊断或 frozen compatibility | 不授权删除旧行情、Profile、Binding、Parquet、receipt、report、evidence 或 legacy reader；不授权继续生产 Shadow、重新生成 packet 或执行 apply |
| S6-10 收口 | 旧 schema-v4～v7 合同暂停并冻结为历史；恢复入口为 `GY-S6-10-R2` | 不生成新 C2/Approval D/daily child，不执行旧 mapping/deployment/Runtime/notification |
| JM Runtime 验收时长 | 一个完整 DCE 交易日 + 同一 exact release 独立恢复证据 | 单日覆盖夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、幂等与零非法写入；失败整日重启，Ledger append-only |
| Ready 语义 | 只允许用户最终批准 `JM_RUNTIME_READY` | `LONG_RUNNING_READY=false` 固定为 deprecated/not_applicable，单日 Gate 永不发布该状态 |
| ObservationPlan 首轮合同 | 文件型 Registry 只允许一个 JM dominant-rank1 15m HTDY realtime first-seen active plan | notification=false；disabled 不执行；非 JM/15m、第二 active plan 或合同漂移 fail-closed |
| StrategyAdapter 首轮边界 | 只包装既有 HTDY 纯 evaluator 并保留 observation identity | 不含 Session/writer，不写 SignalEvent/notification，不实现苏冰，不改变 HTDY policy/公式 |

## 重要取舍

- 数据质量、lineage 与可复算性优先于产品扩展和性能优化。
- 独立 Gate 只证明其精确范围；不得由数据、回测、单次通知或 smoke 推导盈利、Runtime、长稳或交易 Ready。
- GitHub Issue/PR 用于 backlog、跨模块审查和保护模式；普通立即执行任务不必增加协作仪式。
- 当前树保留 canonical、未关闭受控合同和业务证据；已完成协作过程由 Git 历史提供。
- `docs/tasks/GY-DATA-CORE-V2.md` 是当前数据交互收口的 active 执行合同；
  `docs/tasks/GY-CORE-CONVERGENCE.md` 只作为 superseded/frozen historical 来源保留。
- ADR-WS-004 保持两层边界：`task-worktree.sh` 自动化只到 Draft PR；Codex 编排层在任务验收、
  CI、独立 Review 和 exact head Gate 后可自动 merge commit 到 `develop`。Lane 3 只有代码、
  测试、dry-run、隔离 migration 与默认 disabled 功能可自动集成；真实副作用仍停在人工 Gate。
- 恢复验证与单日自然运行分离：Runtime 进程重启、RQData/网络短故障和 Mac 重启可以在
  验收日前后受控执行，但必须绑定同一 exact release、配置与 DB revision 并经独立 Review。

## 现行 ADR

- `docs/decisions/ADR-WS-003-develop-release-worktree-lifecycle.md`：本地 worktree 生命周期。
- `docs/decisions/ADR-WS-004-five-layer-manual-pr.md`：受控 task PR 与 Codex 自动集成
  `develop` 边界；不改变 release、Runtime 与真实副作用人工 Gate。

未来涉及产品边界、数据/回测口径、live/通知或 worktree/发布模型的长期变化，先在此处或对应 deep canonical 固化；普通实现细节不新增 ADR。
