# 架构决策记录

本文件只记录长期影响代码、数据口径或运行边界的有效决策；当前状态见 `STATUS.md`。历史协作材料可作为事实存在，但不构成当前授权（协作门禁边界见「个人开发」与 `AGENTS.md`）。

## 当前有效决策

| 主题　　　　　　　　　　　　　　 | 决策　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 边界　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| ----------------------------------| -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 产品　　　　　　　　　　　　　　 | 本地单用户国内期货研究工作站　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 不做自动交易、SaaS、多用户或无人值守下单　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| 个人开发　　　　　　　　　　　　 | 普通仓库变更直接在 `develop` 编辑、按影响本地验证、可选 commit/push　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | Issue、task branch/worktree、PR、独立 Review、required CI、exact-head、readback、cleanup evidence、packet/hash/receipt 均非前置；协作工具自愿使用且不授予外部 mutation 权限　　　　　　　　　　　　　　　　　　　　 |
| 本地验证　　　　　　　　　　　　 | 本地必要检查是完成声明依据；纯文档只做适用检查，深业务变化运行对应领域套件　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 任一必要检查失败即不得声明完成；CI 仅作补充　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 普通仓库删除　　　　　　　　　　 | Git 跟踪的源码、测试、普通配置、工程流程、hook/rule/workflow、ADR 和过期文档可直接删除　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 同一变更关闭 active references；仅用 Git history 恢复，不建 backup/quarantine/rollback tag/packet/receipt　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 受控外部操作　　　　　　　　　　 | 生产 DB/正式数据不可逆 mutation、仓库外删除、远端 release/tag、历史重写、Runtime/live、真实通知和 GitHub rules 只接受范围明确的一次性执行意图　　　　　　　　　　　　　　　 | 请求标识类别与 scope，只用于紧随其后的一次匹配尝试；成功、失败、重试、scope 变化或跨会话都需新请求；dry-run 不授权 mutation　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 安全优先级　　　　　　　　　　　 | 业务正确性与安全约束优先于执行意图　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 意图不能绕过认证/输入校验、数据质量、DataGap、未来函数、密钥保护、default-off 或 no-order　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 迁移期 legacy compatibility 读取 | RQData/标准 Parquet → metadata/profile/lineage → 旧 consumers　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 仅保留旧消费者保护：`rqdata/local_parquet + primary + quality != failed`，严格研究 passed-only；不是 V2 active selector，不再扩展　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 历史与 live　　　　　　　　　　　| canonical historical 与 live observation 分层　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | live 不直接成为正式历史 active；EOD 以 provider-final RQData 校验后发布，失败保留最后有效 canonical　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 指标　　　　　　　　　　　　　　 | 复用公共指标内核、逐调用方迁移　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| Web/回测/实时不得长期各自实现一套算法　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 回测　　　　　　　　　　　　　　 | vn.py 引擎不改源码，策略/参数/数据/订单/trade/equity/lineage 可复算　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 可信度优先于收益；不覆盖旧报告　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| 信号与通知　　　　　　　　　　　 | `Strategy -> SignalEvent -> Notification Gate -> Channel`　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 研究观察、幂等、默认关闭真实发送、无订单　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| HTDY original　　　　　　　　　　| 精确 realtime first-seen observation-only exception　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 不用于正式历史回测、收益结论、自动通知或交易；见指标与信号 canonical　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| release/tag　　　　　　　　　　　| 用户对 selected remote、target branch/tag 与 local commit 的一次明确请求授权一次匹配发布尝试　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| mutation 前展示精确目标；branch 仅 fast-forward，tag 冲突即停止，不自动 force，不创建 rollback tag；release/tag 意图不授权 Runtime/live/通知　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| 数据核心 V2 active target　　　　| RQData 是唯一上游；Canonical 持久化 provider-direct `1m/1d/1w` 与 preaggregated `5m/15m/30m/60m`，再经 Catalog/Manifest/Gap/MainContractMap 由 `MarketDataService` 同频读取 | canonical Parquet 是受治理存储而非第二上游；缺少同频 dataset/partition 必须 DataGap，不做历史跨频 fallback　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| Canonical 数据准入　　　　　　　 | 只依赖自身 schema、coverage、Manifest digest、物理 checksum、Catalog、DataGap、MainContractMap 与代表性统一读取验证　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | legacy 与 Canonical 全历史逐条一致不是正式准入条件；legacy Shadow 仅为可选诊断或 frozen compatibility　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 数据身份　　　　　　　　　　　　 | `DatasetKey` 唯一定位；正式历史 allowlist 为 `1m/5m/15m/30m/60m/1d/1w`；`continuous` 与 `actual_dominant` 显式且不可互换　　　　　　　　　　　　　　　　　　　　　　　　　　| 新 active BarsResult 的 request/source/bars 必须同频且 `derived_frequency=null`；actual-dominant `1w` 使用该周最后交易日 rank=1 合约　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| 21 品种精确退役　　　　　　　　　| 活动品种池收口为 69 个；JR/PM/RI/WH/ZC/WR/BB/FB/PP_F/L_F/V_F/BC/CY/LG/AD/OP/RR/T/TF/TS/TL 进入一次性全链路退役　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 实际生产 DML、正式文件删除或 Runtime 变化前必须通过 exact product/blocker/transaction/integrity/default-off 检查，并取得标明精确对象范围的一次性执行意图；当前代码与计划不授权执行　　　　　　　　　　　　　　　　　|
| Task 07 Stage C　　　　　　　　　| 只验收 active config + Catalog + MainContractMap 生成的 JM 目标 Canonical；结果闭集为 `KEEP_CANONICAL/REDOWNLOAD_DIRECT/REBUILD_AGGREGATE/REGISTER_DATA_GAP`　　　　　　　　| 不扫描全量 legacy；Direct 只允许 `1m/1d/1w`，Aggregate 只允许从同 DatasetKey 身份和窗口 Canonical 1m 重建；仅生成未授权缺口计划，失败不覆盖旧有效 Canonical　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| Task 07/08 分工　　　　　　　　　| Task 07 不以 Profile/Binding retirement、Runtime legacy reference=0、legacy 文件数或旧派生数据删除为完成条件；Runtime promotion 属于 Task 08　　　　　　　　　　　　　　　　| 旧派生数据清理为后续独立可选任务；legacy-wide packet/inventory/retirement 数字仅作 superseded historical evidence　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| V2 迁移资产　　　　　　　　　　　| 只迁移 trusted historical bars 及最小 Catalog/Manifest/Gap/MainContractMap metadata　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 旧 indicator/cache、Backtest、Signal/Review、live/EOD/Sample、permanent derived period、重复 bar layer 与 Profile/Binding/legacy lineage 均为 rebuild-only 或 compatibility-only，不得提升为 active migration asset |
| Profile/Binding 迁移　　　　　　 | 既有 Profile/ActiveBinding/复杂 lineage 仅作 legacy compatibility，按消费者切换、rollback 与引用清除决定退出　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| GY-CORE-02 Facade 与 GY-CORE-03 CLI 壳可复用；旧 active selector 不再扩展；任何生产数据 deletion 另需精确 scope 的一次性意图　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| GY-CORE 路线替换　　　　　　　　 | 旧 GY-CORE-04～08 superseded/paused；04 已合入代码保留为 legacy compatibility　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 不按旧路线进入 Shadow、release、Runtime 或删除　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| 运行明细留存　　　　　　　　　　 | live/decision/event/notification/reconciliation/snapshot/fingerprint 目标为统一 30 天；人工复盘后仅提取精简 ResearchSample　　　　　　　　　　　　　　　　　　　　　　　　　| 目标未实现；repair/replay 永不补发通知；真实生产清理需精确 scope 的一次性意图　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| 历史工件处理　　　　　　　　　　 | 已发生的 evidence/report/receipt 保留事实含义或由 Git history 追溯　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 仓库内无 active reference 的过期工件可普通删除；生产 DB、正式数据或仓库外工件删除是受控外部操作　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| Task 04 legacy 保留　　　　　　　| 已下载旧行情只读保留；PR #90～#94 的 Shadow/identity/session 实现可作为可选诊断或 frozen compatibility　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| PR 编号只作历史事实；移除 referenced code 先迁移 caller，删除正式行情/DB/仓库外工件另需精确 scope 的一次性意图　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| S6-10 收口　　　　　　　　　　　 | 旧 schema-v4～v7 合同暂停并冻结为历史；恢复入口为 `GY-S6-10-R2`　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | 不生成新 C2/Approval D/daily child，不执行旧 mapping/deployment/Runtime/notification；旧名称不是新授权　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| JM Runtime 验收时长　　　　　　　| 一个完整 DCE 交易日 + 恢复证据　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 单日覆盖夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、幂等与零非法写入；失败整日重启，Ledger append-only；真实 Runtime 操作每次需独立 scope 意图　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| Ready 语义　　　　　　　　　　　 | `JM_RUNTIME_READY` 只能依据完整业务验收结果表达　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | `LONG_RUNNING_READY=false` 固定为 deprecated/not_applicable；任何 ready 结果都不授权交易、盈利推断或下一次外部 mutation　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| ObservationPlan 首轮合同　　　　 | 文件型 Registry 只允许一个 JM dominant-rank1 15m HTDY realtime first-seen active plan　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 | notification=false；disabled 不执行；非 JM/15m、第二 active plan 或合同漂移 fail-closed　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| StrategyAdapter 首轮边界　　　　 | 只包装既有 HTDY 纯 evaluator 并保留 observation identity　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　| 不含 Session/writer，不写 SignalEvent/notification，不实现苏冰，不改变 HTDY policy/公式　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |

## 重要取舍

- 数据质量、lineage 与可复算性优先于产品扩展和性能优化。
- 任一验证或真实执行只证明其精确范围；不得由数据、回测、release、Runtime、单次通知或 smoke 推导盈利、长稳、交易或生产 Ready。
- 协作门禁与可选工具边界以上表「个人开发」与 `AGENTS.md` 为准，本文不另列清单。
- 当前树保留 canonical、active business contracts、Runtime 仍消费的 frozen 文件和必要历史事实；已完成协作过程由文本或 Git history 追溯，不提供可复用授权。
- `docs/tasks/GY-DATA-CORE-V2.md` 是当前数据交互收口的 active 业务合同；`docs/tasks/GY-CORE-CONVERGENCE.md` 只作为 superseded/frozen historical 来源保留。
- Runtime 进程重启、RQData/网络短故障恢复和主机重启验证与单日自然运行分离；实际 Runtime/live/通知动作分别使用自己的精确 scope 意图，且默认保持关闭。

## 已取代的工作流 ADR

- ADR-WS-003 / ADR-WS-004 已被「个人开发」决策与 `AGENTS.md` 取代；旧文可由 Git history 追溯，其中的协作门禁描述不再是 active prerequisite。

未来涉及产品边界、数据/回测口径、live/通知或个人开发/发布模型的长期变化，先在此处或对应 deep canonical 固化；普通实现细节不新增 ADR。