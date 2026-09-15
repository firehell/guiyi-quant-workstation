# 牛哇日线数据完善设计与 Implementation Plan 审查

## 原始 PR #367 同会话自审（历史记录）

本节记录原始提交 `6a769ec`，其中 hash、环境限制与集成结论仅对应当时版本；
本次补充设计与计划的验证和独立审查另记于文末，不以新结果覆盖历史。

日期：2026-09-15。仓库基线：`d653a8c864f5f09d98309357f64ab16dde87eb2d`。
被审文档为原始提交中的 design.md（当前修订见 [design.md](design.md)）。原始 UTF-8 bytes SHA-256：
`ca7b9c8106c9fa87aa7073acb38f6d97c2e2796f685bae5630cca29637c19935`。

## 审查范围与类型

本轮为同一会话的设计自审：先对照仓库代码与 active canonical 阅读，再对草案执行边界、
异常、验收及范围进行复核并修订。没有独立 reviewer/独立模型会话，不冒充独立 Review。
这不是生产故障根因报告，也不是实现代码 Review 或真实数据验收。

已核对来源包括 STATUS、AGENTS、DEVELOPMENT、PROJECT_SOURCE、DECISIONS、DATA_CENTER、
historical-data-maintenance OpenSpec，以及原生 manager、Newow reader/readiness/product_release、
周线恢复子执行器和 campaign。精确入口列在设计第 2 节，不以聊天总结替代源码。

## Confirmed Issue：设计风险已修订

以下项目是对方案的审查发现；已有程序中的 W1 限定属于当前有意边界，不直接判为生产 Bug。

| 编号 | 证据与触发条件 | 影响 | 设计修订与验收 |
|---|---|---|---|
| D1-01 / 高 | manager 的显式 `1d` 仅含 D1，但未传频率是七周期；daily mode 是盘后增量语义 | 误将“日线”当“每日更新”，可能扩大下载/写入范围 | 第 2、4 节明确只调用显式 D1 warm-up；跨频 target 在 provider 前拒绝 |
| D1-02 / 高 | recovery 的 `_validated_unit`、`_zero_commit_readback` 及 campaign 报告合同均固定 W1 | 只换参数会失败，或错误复用读回/隔离结论 | 第 3、4 节采用封闭 D1 profile 与新包 schema，完整贯穿 prepare/apply/readback；保留旧 W1 语义 |
| D1-03 / 高 | readiness 的 public matrix 仍建立九组合并将 D1 标 UNOPENED | 用矩阵全绿验收会诱发提前开放或伪造 Ready | 第 6、7 节分离盘点完整、数据输入可用、计算验收与产品开放；D1 报告允许 frequency_scope=1d 且 release_stage=weekly |
| D1-04 / 高 | W1 包包含 D1/W1；来源响应、单次意图及 zero/partial-commit receipt 是不同证明 | 把已知坏合约名单当成功名单，或用旧批准续跑 | 第 5 节要求 D1 精确重绑定；旧 receipt/plan hash 不跨 profile 授权，部分提交继续停批 |
| D1-05 / 中 | 旧任务的 exact commit/执行摘要可能在文档提交后不再匹配 develop HEAD | 方案提交本身可能干扰正在准备的周线操作 | 第 4.1 节保留旧精确执行根；新 D1 包从周线写入结束后的真实状态重审，不覆盖或清理旧 evidence |
| D1-06 / 中 | 来源请求组已有先校验再发布；整合约预取需要改变资源与部分提交路径 | 为尚未测量的瓶颈追加新 staging/publisher，延误普通补数 | 第 3 节将整合约预取后置，首版不新增来源导入管线或通用任务平台 |
| D1-07 / 中 | dependency 枚举未单列 comparator，且每次审计有确定窗口 | 主图就绪被扩大成全部面板/任意历史窗口就绪 | 第 1、7 节限定承诺窗口；比较器覆盖必须另由真实 service/reader 证明，不满足则明确待验 |

复核结果：上述问题已落实到设计及第 9 节验收用例；本次未为修订设计改变任何生产代码或 active canonical。

## Risk / Needs Verification

1. **真实数据余额与来源异常：未验证。** 未连接本地 Catalog/Parquet/evidence root，无法给出当前日线
   合约数、缺口数、批次数或耗时。只能在日线工程获批并就绪后，通过新完整 D1 原生只读审计冻结。
2. **D1 执行 profile 的实现安全性：尚待实现验证。** 需覆盖所有 W1 硬编码点、旧 schema 兼容、来源
   journal、零提交证明、partial/unknown、projection invalidation 及最终 replan。不能把本设计自审当成代码通过。
3. **真实消费者与共享 W1 影响：未验证。** 数据 ready 的作用域限冻结 consumer/window；若发现已有事实
   冲突或 W1 一致性问题，应阻塞相关结论并按专用合同处理，不能由 D1 包自动跨频纠错。
4. **独立审查与完整仓库验证：本轮未完成。** 当前会话没有独立 reviewer；本地无法取得完整仓库 checkout，
   不具备运行全仓工程测试和 OpenSpec CLI 的环境。不得声明 TEST_COMPLETE 或独立 REVIEW_COMPLETE。

## Optional Improvement

只有真实 D1 执行证明来源异常经常在较晚月份出现且恢复成本明显时，才单独评估有界全合约来源预校验。
保留原生 writer、单分区提交与失败恢复合同；不把该优化、60m 或后台调度作为本轮收口条件。

## 本轮验证记录

验证对象仅为本次两份 Markdown 文件，不是完整仓库或生产数据。

- 逐条对照设计第 2 节已读取源码/合同；检查引用路径、UTF-8、标题结构、尾随空白和占位项。
- 在隔离的文档暂存 Git 目录执行 staged diff 空白检查；目录不是用户工作站 worktree，也不冒充完整 checkout。
- 对两份文档运行仓库原版 secret_scan 的显式文件扫描。扫描器 Git blob SHA
  `bcf6747b1f3bca5c8ed6ec18348d48a0551c16ec` 与 GitHub 读取值匹配；扫描对象不含生产配置。
- 文档级检查通过；secret scan 为 0 findings。引用检查限本次链接及已经读取的仓库路径，不是全仓链接审计。
- 未运行后端/Web 测试、生产 smoke、真实补数或全仓 OpenSpec/工程检查；未获取独立 reviewer 结论。

提交后应通过 GitHub diff 和文件读回核对只新增本目录两份文档，设计 blob 与上面的内容 hash 匹配。
这一步的 commit/PR 身份记录在 GitHub，不写入本文件形成自引用 hash 循环。

## 结论与下一 Gate

**设计自审：无剩余已确认的设计阻断，可提交方案供 owner 确认。**

**develop 集成结论：阻塞，需在完整仓库环境补齐适用文档验证，并按任务风险完成必要复核后再集成。**
提交设计 PR 不等于合并，不关闭现有数据/发布/Runtime Gate。
本次不批准或执行代码实施、真实来源请求、数据写入、日线开放、main/tag 或 Runtime promotion。

## 2026-09-15 补充设计与 Implementation Plan 独立 Review

### 本轮范围与身份

Owner 明确要求补充上述四项、设计 Implementation Plan、Review 后直接在 develop commit/push。
核对基线为 `c9ed8ec503bda9287f4b77967854a3d696c8014b`；远端 develop 与本地一致，
PR #367 仍为 Draft，head 为 `6a769ec5fbe934f9d0d04b2213fc242f689f893b`。
本轮将 PR 原文带入 develop 工作区并修订，新增同目录 implementation-plan.md；
不通过合并旧 PR 替换当前 develop，不改生产代码、active canonical、配置、STATUS 或其他任务证据。

被审对象的 UTF-8 SHA-256：

- design.md：`cedffe75e8f951ecc038f99f17bf8bab7eb92455eb4f362ae334e11c51bb3bd3`
- implementation-plan.md：`f45f00b83df178c0d63d514c071e3157b15fc660b8c1dc8c9be71450385fde61`

两个独立子审查者分别核对 Standards 和 Spec/可落地性；均直接读取当前文档及相关源码，
没有编辑被审文件或访问生产数据。此 Review 覆盖设计与实施计划，不是尚不存在的恢复代码审查。

### Confirmed Issue：本轮已修订

| 编号 | 证据、影响及修订 | 复核 |
|---|---|---|
| PLAN-01 / P2 | 初稿 Task 1 要求完整 digest 覆盖 Task 4 才新增的模块，并把成功冻结当 Task 1 出口；Task 4 又依赖前序包，形成顺序循环。现改为 Task 1–3 使用显式 fixture 身份的离线包，Task 4.6 才验收完整摘要及干净临时代码根冻结；禁止空壳文件满足摘要。 | 独立 Reviewer 再次读取修订后文档，确认关闭 |

四项原补充均已落地：D1 隔离合同同步（Task 2）、拒绝 W1 partial 输入（Task 3）、
最终审计失败不抹去执行事实（Task 4）、比较器默认与自定义窗口分别证明（Task 4）。
同时补明确 verify 退出 0 须执行结算明确、普通恢复完成且输入完整可用，未知执行不能被审计成功覆盖。

### Risk / Needs Verification

1. **实现未开始。** 独立只读进程、provider/写入能力隔离、父子进程保存失败、digest 和真实代码根的冻结
   仍须在 Task 1–4 实现测试中证明；本次文档 Review 不能替代这些测试。
2. **生产数据未验收。** 未读取 Catalog/Parquet 或调用 RQData，当前缺口、异常、批次数和耗时未测量。
   W1 旧证据只能按合同重新核对；没有授予新下载、写入或失败重试权限。
3. **基线工程检查仍有两项失败。** 本轮重新运行完整适用检查，结果为 20 passed、2 failed：
   `test_noncanonical_superpowers_documents_are_not_tracked` 检出既有
   docs/superpowers/plans/2026-09-14-market-web-pre-release.md；
   `test_project_codex_permission_mode_is_preserved` 仍读取已经移除的固定 model_reasoning_effort=high。
   前者属于其他任务的既有文档，后者与 AGENTS 当前用户级模型配置约定存在未收敛断言；
   本轮不改配置、不删除无关文档、不降低测试。两项均在未加入本次文档的原基线复现，
   其相关文件未被本任务修改，不能声称全仓工程 TEST_COMPLETE。

### Optional Improvement

无必须新增的抽象。完整合约预取、跨 W1 自动来源导入、后台 worker 和 60m 保持后置，
不为追求流程完整将其提升为 D1 普通恢复前置。

### 实际验证与提交结论

- 按 TESTING 中工程一致性命令运行 repository_hygiene/canonical_consistency：20 passed、2 项上述基线失败。
- OpenSpec strict 全部 9/9；本任务目录 secret scan 为 0 findings。
- 当前三份文档的相对链接、UTF-8、尾随空白和占位项检查通过；设计/计划 hash 如上。
- 未运行后端/Web 功能测试或生产 smoke：没有修改这些实现，不将文档检查冒充功能验证。
- 提交前仅暂存本目录三份文档并检查 staged diff；保留未跟踪的上轮本地报告，不全量 add。

**独立设计/计划 Review：已确认问题关闭，无剩余设计阻断。**

**允许集成 develop：仅限 owner 本轮明确要求的三份文档 commit/push。**
该结论不表示两项既有工程失败已修复，不批准本计划代码实施、完整工程候选、数据恢复、Release 或 Runtime。
文档交付完成后的唯一下一步：owner 审阅并批准计划中的 Task 1–4 代码实施范围。
