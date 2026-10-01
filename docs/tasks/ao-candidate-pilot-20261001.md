# AO 氧化铝四周期历史候选安全暂缓

状态：**PARTIAL / DEFERRED_DATA_BLOCKED，0/12 页面候选闭环；允许集成 develop（仅安全暂缓记录）**。本任务只处理 AO，尚未启动 CU。页面窗口为权威上市日 **2023-06-19** 至 2026-09-24，`as_of=2026-09-24T07:00:00.000001+00:00`；Canonical 1m 仅作聚合源，目标仍为 5m/15m/30m/60m × trend/oscillation/dual。冻结候选代码 `93948b7489f1f900f9b190a987007ca59c3af751` 只增加 AO v27 单品种私有预览准入和直接测试；正式分钟、公式、Scope、Runtime、通知和交易均未变。

原始证据保存在 AO 独立任务工作区 `.worktrees/ao-candidate-pilot/outputs/ao-candidate-pilot-20261001/`，不入 Git；失败请求完整数值、失败 attempt、原生计划、先后七频快照和首次只读审计工具失败记录均保留。以下文件名均相对于该目录。

## 冻结计划与实际停止

当前 rank1 MainContractMap 有 **22 个物理 owner / 88 个 owner×四频维护单元**，原始私有 12 组合均为 0 stream。原生 dry-run 在既定完整物理合约前缀下有 74 个缺口单元、14 个无缺口单元；四频重复请求去重后为 **154 个 1m 源月、682 个派生月目标**。旧七频前像为 161 个 dataset、1,158 个 active 文件。冻结 `campaign-plan-v3.json` SHA `b36d4776b6a1529f587d8e347b17a1b1eba171831e96ebdef17f48ba0626b9b6`，runner SHA `97368331437e5fa7f82e1d9fd1d53c290c5de814de32afa843350dd261715f28`。独立 fresh preapply 逐项验证 88 份原生计划、Map、旧文件、同卷 scratch 相同 SHA、锁与额度后，唯一一次串行维护才启动；见 `independent-root-preapply-review.json`。

执行前额度余量 **1,055,743,280 bytes**，按既有 1m 每 Bar 1,024 bytes 的全批保守估算为 **1,387,192,320 bytes**，因此 `overall_theoretical_budget_pass=false`、不保证全批完成；最大单元保守预算为 101,621,760 bytes。已审原生机器合同在每个有缺口单元的锁外、锁内分别用 fresh 余额覆盖该单元预算，额度不足即停，不降低单元预算或缩窗。额度数字属于账户级采样，不把前后差额归因于 AO；见 `preflight.json`、`independent-root-quota-policy-review.json`。

唯一 maintenance session **exit 1**，`campaign-stopped.json` 为 `AO2403/5m` 的 `ATOMIC_PUBLISH_FAILED → ArrowInvalid`。88 单元严格分类：**9 READBACK_VERIFIED、7 NO_GAP、1 已知失败且有部分成功发布、71 未尝试**。前 16 个完成单元形成 54 个派生月；失败单元在错误前另成功发布 `AO2403/5m/2023-06` 一个派生月，不能称为零提交。失败请求是 `AO2403/1m/2023-07`，其 active 指针前后均为 0、物理目录为空，未生成该请求的 native result。失败单元 attempt 保持 `PENDING / retry_allowed=false`，不复用、不盲重试；未尝试单元无 attempt。唯一成功前缀后没有继续维护或构建资产。见 `independent-root-failure-terminal-review.json`。

失败 PublishRequest 的 **9,765 根原始 CanonicalBar**、全部预期端点、dataset/month、异常类链已排他以 0600 保存于 `campaign/AO2403-5m-failed-publish-payload.json`，SHA `8639c184928e6ea2c8a957ad27bff5c063acfebf5c44198da5ca069e0cc374b0`。无 provider、DB 或 Canonical 重写的离线 Arrow 实际复现，唯一无法表示的字段是第 3254 行 `turnover=1.4551915228366852E-11`，需要 scale 27，当前 Canonical 类型为 `decimal128(38,18)`；错误为 `Rescaling Decimal value would cause data loss`。这确认当前请求数值无法按现有 schema 无损发布，**不证明**其上游浮点噪声成因；该 Bar 的 volume=0 也不能据此把 turnover 改零。未对数值取整、置零、改 schema 或改计划 hash。见 `independent-root-failure-reproduction-review.json`。

## 已发布范围与安全边界

七频 active 文件 **1,158→1,204**：46 新增、9 扩展、0 删除，恰为 55 个已发生且包含失败单元前缀的冻结目标。1,158 个旧 immutable 文件字节保留；1,149 个未扩展旧分区保持，9 个扩展分区原有 **7,980 根 Bar** 全字段与端点保持；544 个 D1/W1 文件及 Catalog 行保持。任务方第一版 partial-difference 错将失败单元所有提交排除而断言失败；第二版只有未尝试单元元数据误以 22 owner 为分母；两份原报告保留，修正的 `seven-frequency-partial-difference-v3.json` 与独立 `independent-root-partial-preservation-review.json` 真实 PASS，不覆盖旧记录。

实际已发布 **55 个派生月 / 46,480 根 Bar**，其中 5m 31,092、15m 10,148、30m 5,240、60m 无新增。任务方原生 `aggregation-partial-native.json` 和独立 `independent-root-partial-data-review.json` 对这些月按相同物理合约 1m、权威 Session `(start,end]` 和 Decimal 200 逐端点、逐字段复算通过。该结论仅覆盖部分已发布前缀，**不证明** AO 22 owner 的四频完整生命周期或任何页面 READY。

失败源 `AO2403/1m/2023-07` 的 active=0、目录空；候选 12 组合仍 0 stream/0 revision，维护锁 granted=0/waiting=0，8012/5178 无监听，没有启动 AO API、Web、Chrome、12 资产构建或浏览器 19 场。失败后账户余量只读样本为 1,052,774,961 bytes；不把差额归为本任务消费。见 `failure-boundary-final.json`、`independent-root-final-native-readback.json`。

AO 单品种准入定向 API **50 passed**、Web **26 passed**，worker Web build 通过；独立 Spec 全 API **119 passed**、Web 三组 **122 passed**，Standards/Spec 均无 Confirmed Issue；见 `independent-root-eligibility-code-review.json`。root 只读审计器首次把 `campaign-stopped` 存在条件写反，退出 `STOPPED_TERMINAL`，已保留错误报告并修正后独立审计通过；此错误没有生产写入或维护重试。最终独立 `independent-root-final-safe-defer-review.json` 为 **REVIEW_COMPLETE_SAFE_DEFERRED_DATA_BLOCKED**，仅确认共享数据安全边界与暂缓记录，不代表 AO 候选闭环。

恢复 AO 必须先确定该原始 turnover 与无损 Canonical 表示的权威处理合同，并另行证明精确恢复对象、预算、旧 attempt 不复用和当前源前像；不能仅批准重跑、改变数值或缩短历史窗口。只有 AO 安全暂缓独立最终 Review 完成后，才按 owner 本轮顺序开始 **CU**；AO 仍为 0/12，页面收益、因果研究、OOS、模拟成交和 Runtime 均未产生。
