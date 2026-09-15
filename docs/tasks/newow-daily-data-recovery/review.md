# 牛哇日线数据完善设计审查

日期：2026-09-15。仓库基线：`d653a8c864f5f09d98309357f64ab16dde87eb2d`。
被审文档：[design.md](design.md)。其 UTF-8 bytes SHA-256：
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
