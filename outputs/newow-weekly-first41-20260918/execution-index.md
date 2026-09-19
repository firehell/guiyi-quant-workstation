# 首批 41 品种周线闭环执行索引

原执行树：`codex/newow-first-41-weekly-continuation@fe422d296`（由
`v1.10.14@d63feb058` 正常合并 `develop@0c269265c` 与
`b107f323c` 后继续）。
本索引只记录本任务的新证据；历史报告仅作定位，不替代本次验证。

2026-09-18 基线接续：原 `33a2` worktree 在完整 dirty 快照保存后从本机消失；
快照位于本索引同级 `baseline-preservation.tar.gz`，含旧分支已提交差异、
tracked binary patch、两个 untracked 文件及 SHA-256 manifest。现于
`codex/newow-first41-baseline-converged@fbee36b776` 接续，原树未被本任务清理。
逐文件对照后，MDS、reader、identity、ReferenceTrade 与主要回归文件均已在 develop；
develop 的 `weekly_quality.py` 保留更完整的输入校验，未复制旧版。
候选范围移植为 41 品种 W1，正式 v3 stage 继续仅开放 D1 且 wire envelope 不变；
AU、PD/PT、AP 隔离预览保留原边界。候选 v4 独有 `weekly_products` 字段。
本次复验：后端 candidate/API/weekly-quality 85 passed，共享 MDS/reader/adapter/reference
326 passed；前端 capability/types/详情页 52 passed，production Web build 与 TypeScript
检查通过；Ruff、OpenSpec 9/9、secret scan 0、diff check 通过。
以下表格与紧接的“本轮新证据”记录基线收敛当时的历史快照；后续步骤以本文件末尾追加的
步骤 2–5 证据为准，不能用表格旧状态判断当前进度。
当时未执行真实数据读写或页面矩阵。

| 任务 | 状态 | 已完成的安全动作 | 外部 Gate |
| --- | --- | --- | --- |
| 0 | 基线收敛完成，现场盘点待续 | 已保全旧树完整差异并从 `develop@fbee36b776` 建立接续树；逐文件去重。D1/AU 现场只读 smoke 与 41 逐品种依赖读回待后续执行。 | 无 |
| 1 | 进行中 | 已实现并测试 41×W1 的产品范围 API 合同；前端现按当前 product 消费 `weekly_products`，未开放品种不再显示 1w。尚待 completed-week snapshot 身份字段。 | Runtime 发布未授权 |
| 2 | 已完成（隔离代码） | W1 以完整、互斥的 D1 端点证明正常 Bar 或缺价中断；MDS physical/actual-dominant → reader → calculation segment → ReferenceTrade 均已接通。D1 Trade ID 保持既有版本，W1 使用独立质量版本。 | 任何数据差量写入未授权 |
| 3–6 | 未开始 | 无。 | Runtime/维护扩围未授权 |
| 7 | 待现场只读核查 | 尚未生成差量 prepare；不得 apply。 | RQData/Canonical/Catalog 写入未授权 |
| 8–9 | 未开始 | 无。 | main/tag/release/Runtime/自然周均未授权或未发生 |

当前品种分母固定为 41；本索引尚未给任何品种标记 READY 或页面验收通过。

本轮新证据：前端 capabilities/详情页定向测试 10 passed；周线计算区段
定向测试 6 passed；周线 ReferenceTrade 中断定向测试 4 passed；MDS/reader
相关 fixture 回归 327 passed。以上均为隔离
代码测试，不是 41/123 现场、页面、发布或 Runtime 证据。

2026-09-18 任务 2 补证（基线 `717c0b206`）：完整周端点正常/缺价/未知缺口互斥；
已存 W1 Bar 与缺价周冲突、混合 `NO_TRADE` D1 与不一致 W1 冲突均阻断。
W1 `NO_TRADE` 不产生中断，也不推进策略观察；缺价周在原完成端点中断，
三策略的 prefix、逐周增量与纯函数重建结果一致。reader 重建后保留同一
Bar 与中断身份；W1 跨合约 CLEAR 不关闭旧参考交易。D1 固定参考交易 ID、
入/出价格、收益及持有 Bar 数新增回归哨兵。独立 Standards/Spec Review
均无 Confirmed Issue；review 指出的时间中点与空真断言已修正。
最终定向组 476 passed；Ruff 与 `git diff --check` 通过。
此处为隔离代码证据；真实完整周 MDS→reader、进程重启及混合零价真实样本
仍随现场/集成验收核对，不记作 41/123 READY。

2026-09-18 任务 3 已形成隔离代码与测试；任务 4 在只读候选预览进行六品种
真实默认首载。授权推送的 `6be43683f` 已在 GitHub 远端核对；本轮新增代码与
证据尚未推送。六品种 18 组合逐项证据见
[`../newow-weekly-first41-step4-20260918/acceptance.md`](../newow-weekly-first41-step4-20260918/acceptance.md)：
12 组合主要页面可读，PD 三策略 MACD 合法预热，PT 三策略被
`PT2612 / 2025-12-19` 同合约 W1 端点缺口阻断。18/18 已实际观察，
不得记作 18/18 READY；41/123 矩阵、数据修复、release 和 Runtime 均未完成。

PT 缺口的只读精确修复计划与写入前分区身份见
[`../newow-weekly-first41-step4-20260918/pt2612-repair-approval.md`](../newow-weekly-first41-step4-20260918/pt2612-repair-approval.md)。
范围为 `PT2612 / 2025-12-15～19 / D1+W1`，计划哈希已固定；
provider 与 Canonical/Catalog 写入待本批次明确授权，尚未 apply。

2026-09-18 PT 首个精确批次已单独获批并一次完成：
`PT2612 / 2025-12-15～19 / D1+W1`，计划哈希
`b73956d81b95f4a43f3186e5ece968e92438ab4d04adf73896141fa5cc76f11b`，
`applied=2`、`failed=blocked=0`、provider 请求 2；写入后 D1 内容未变、
2025-12-19 W1/MDS 通过。PT 三策略页面转为报 2025-12-26 内部缺口，
仍未 READY。新只读计划限定 PT2612 剩余完整前缀 20 个 D1/W1 月目标、
最多 20 个 provider 请求，见
[`../newow-weekly-first41-step4-20260918/pt2612-remaining-repair-approval.md`](../newow-weekly-first41-step4-20260918/pt2612-remaining-repair-approval.md)。
该新批次尚未授权或执行；不得复用已消费的首批授权。

2026-09-18 PT2612 第二个精确批次获一次性授权并执行，20 个 D1/W1
分区提交，20 次 RQData 来源请求、零失败；10 个月 D1 文件 SHA 未变，
W1 合计 39 根，剩余直接目标为 0。PT 三策略默认周快照与浏览器主图、
参考交易可读；MACD 合法预热，震荡比较器区段不足，不计全策略 READY。
六品种 18/18 主图及参考交易现均可读，其中 6/18 的 MACD 合法预热；详见
[`../newow-weekly-first41-step4-20260918/acceptance.md`](../newow-weekly-first41-step4-20260918/acceptance.md)。

2026-09-19 步骤 5 固定 41 品种／123 组合的只读候选验收已执行，逐品种结论及原始证据见
[`../newow-weekly-first41-step5-20260918/acceptance.md`](../newow-weekly-first41-step5-20260918/acceptance.md)。
17＋18 两批 105 个默认页面均有首载终态；连同首批 18 个，共 111 组合主图和参考可读，
AL、SC、SS、ZN 的 12 组合真实来源阻断。可读品种中 6 个有合法辅助预热。
W1 原生只读审计覆盖固定 41 品种、1670 条来源依赖，1660 READY、8 UNAVAILABLE、
2 个短 owner NOT_APPLICABLE；报告 complete 表示审计完成，正式 W1 123 个策略仍为 UNOPENED。
D1 候选 chart 60×3 为 179 ready、RS 震荡 1 warming；初次全域原生审计预算耗尽后，
四个有界只读批次补齐原 84 个未检，最初合并为 176 READY、RS 震荡
1 WARMING、AL 三策略 3 DATA_UNAVAILABLE。随后同截止时间对 AL、ZN 六案例重新只读核查均 READY；
按各品种最新证据为 179 READY、1 WARMING、0 未检。审计跨多个时刻，未冻结共同数据修订；
AL、ZN 的最新 W1 快照阻塞为 2611 合约 REPLAY_ENDPOINTS_MISSING，早期 D1 前缀错误单独保留。
余下 19 品种的 W1 和 60m 候选请求
38/38 被拒绝。未执行 provider、Canonical、Catalog 写入或 Runtime 变更。
步骤 5 状态仍为 PARTIAL：12 个 W1 组合有来源阻断；
原始浏览器首次故障与独立后续首载分别保留，不将后者覆盖前者。

2026-09-19 owner 授权对 AL2611、SC2611、SS2611、ZN2611 做精确 W1
前缀恢复。四份原生只读计划在现有全品种 audit 自然释放维护锁后再次生成，
哈希与步骤 5 readiness 完全一致。随后串行执行 88 个 D1/W1 目标，RQData
请求 88 次，`applied=88`、`blocked=failed=0`；写入前后 44 个 D1 活动文件
SHA-256 全部不变，44 个 W1 月分区完成发布，缺价质量事实为 0。
补数后 358 个 W1 依赖为 356 DATA_READY、2 合法 NOT_APPLICABLE；12 个默认
周快照、12 组主图/参考交易同快照读回及 12 个独立 Chrome 单次导航全部通过。
固定 41 品种当前合并为 123/123 页面可读；其余 19 品种 W1/60m 的关闭范围未改。
完整回执见
[`../newow-weekly-first41-step5-recovery-20260919/recovery-closeout.md`](../newow-weekly-first41-step5-recovery-20260919/recovery-closeout.md)。

2026-09-19 步骤 6 已完成候选代码与当前数据只读验收。盘后主任务释放维护锁后，
独立记录 `consumer_checks.newow_d1` 与 `consumer_checks.newow_w1`；W1 固定 41 品种，
输入修订同时绑定 D1/W1。消费者优先验证三策略主图、参考交易和 5 个辅助区段；
只有阻断失败品种才调用原生 `ContractWarmupPlanner` 生成精确只读提案，消费者阶段
没有 provider、Canonical/Catalog 写入、retry 或通知能力。重复行情窗口可跨区段及策略复用，
D1/W1 各有 600 秒、总计 1200 秒的有界预算。

当前 Catalog 的完整只读事务用时 1103.196 秒：D1 180/180、W1 123/123 均为
`audited`，两个范围均 `budget_exhausted=false`，未检项、阻断失败和预热提案均为 0。
D1 为 179 个主图 READY、180 个参考 READY，剩余显式状态合法；W1 主图与参考均
123/123 READY。当前结论为 `no mutation needed`，不制造新数据批次。该证据没有写入
正式 after-market 状态，也不证明新版本已发布、Runtime 已切换或下一自然完整周已发生；
完整周发布后的自然消费与重启同结果仍是部署后的 Gate。
定向盘后/readiness/health 回归 174 passed；完整 Newow、盘后与 Runtime health 回归
2025 passed、1 skipped，其中两项 socket 用例因沙箱禁止绑定回环端口后在允许本机端口的
环境 2/2 通过。完整周/周快照/重启不变量补充组 57 passed；Ruff、OpenSpec 9/9、
secret scan 0 findings 与 `git diff --check` 通过。
