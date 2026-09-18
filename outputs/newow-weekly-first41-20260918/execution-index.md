# 首批 41 品种周线闭环执行索引

原执行树：`codex/newow-first-41-weekly-continuation@fe422d296`（由
`v1.10.14@d63feb058` 正常合并 `develop@0c269265c` 与
`b107f323c` 后继续）。
本索引只记录本任务的新证据；历史报告仅作定位，不替代本次验证。

2026-09-18 基线接续：原 `33a2` worktree 在完整 dirty 快照保存后从本机消失；
快照位于 `/private/tmp/newow-first41-baseline-20260918/`，含旧分支已提交差异、
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
