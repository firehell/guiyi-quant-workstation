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
未执行真实数据读写或页面矩阵。

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
