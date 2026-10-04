# CU 铜四周期历史候选安全暂缓

状态：**PARTIAL / DEFERRED_DATA_BLOCKED，0/12 页面候选闭环**。本任务只处理 LC→FG→AO→CU 顺序中的最后一项 CU；允许集成 develop 的范围仅为已审 CU 单品种候选准入与安全暂缓记录。没有启动后续品种，也没有开放正式分钟、构建 CU 候选资产或启用 Runtime、Scope、通知、交易。

原始证据全部留在 CU 独立工作区 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/cu-candidate-pilot/outputs/cu-candidate-pilot-20261001/`，不入 Git。下文证据文件名均相对此目录。冻结代码 `e81693c7e5413ec712407429c64c587d7bb40184` 只增加 CU v27 singleton 私有预览准入与直接测试；公式、正式 v28 频率、共享时钟未改。

## 冻结计划与唯一维护结果

权威 provider 上市日为 1999-01-04，按任务窗口下限确定页面起点 **2023-01-01**，终点 2026-09-24，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅作聚合源；候选目标为 5m/15m/30m/60m × trend/oscillation/dual。rank1 MainContractMap 有 **45 个物理 owner / 180 个 owner×四频单元**，原有 12 私有组合均为 0 stream。旧七频前像为 **329 个 dataset / 1,952 个 active 文件**。原生 dry-run 为 174 个缺口、6 个 NO_GAP 单元；四频去重后保守计划含 **473 个 1m 源月 / 1,914 个派生月**。

冻结父计划 `campaign-plan-v3.json` SHA `81e030c35dc826b46a439dfb60b7a70b4dc471a57dc652715b8ae7b502688524`，runner SHA `89593aca6d362b83681ee298a6010213958f7054166b199f161cfbe78b181af6`。独立 fresh preapply 对 180 个当前原生计划、Map、七频前像、同卷 scratch、锁和额度逐项核验通过，见 `independent-root-preapply-review.json`。执行前账户级额度余量 1,052,774,961 bytes；全批保守估算 4,287,943,680 bytes，`overall_theoretical_budget_pass=false`，不能保证整批完成；最大单元 102,097,920 bytes。已审合同要求每单元锁外、锁内均用 fresh 余额覆盖完整单元预算，额度不足即停，不缩窗或调低估算，见 `independent-root-quota-policy-review.json`。

唯一 maintenance 执行在**首个单元 `CU2302/5m`**因 `ATOMIC_PUBLISH_FAILED → ArrowInvalid` 退出，`campaign-stopped.json` 已封存；没有继续其余单元。180 单元严格分类为 **0 完成、1 已知失败且部分成功发布、179 未尝试**。失败单元记录 7 个已启动源请求，不能当作 7 个成功发布；实际仅 **6 个 1m 源月与 6 个 5m 派生月**成功发布，均为 `CU2302` 2022-02 至 2022-07。失败请求 `CU2302/1m/2022-08` 的 active=0、物理目录为空，失败 attempt 保持 `PENDING / retry_allowed=false`；这次维护是**部分提交，不是零提交**。见 `independent-root-failure-terminal-review.json`。

失败 PublishRequest 的 **10,695 根原始 CanonicalBar**及预期端点以权限 0600 保存于 `campaign/CU2302-5m-failed-publish-payload.json`，SHA `937bca9ae52e767177689bda78af9e4cd9dfeaf0c9d65db3b37baf2a3f90f7e3`。离线 Arrow 逐字段复现确认唯一无法无损表达的是 **`row_index=5355`（从 0 计数）** 的 `turnover=7.450580596923828E-9`，需要 scale 24，而当前 Canonical 为 `decimal128(38,18)`；报错 `Rescaling Decimal value would cause data loss`。这确认本次原值与既有 schema 不兼容，**没有证明**上游 provider 浮点噪声成因。未取整、置零、改 schema、缩窗、改计划 hash 或重试失败 attempt。见 `independent-root-failure-reproduction-review.json`。

## 部分发布读回与边界

七频 active 文件 **1,952→1,964**：12 新增、0 扩展、0 删除，全部位于首个冻结单元的已成功源/派生目标。1,952 个旧 immutable 文件及 active 行保持，**1,173 个 D1/W1 文件与 Catalog 行保持**；当前 1,964 个文件 SHA/行数均独立核验，见 `seven-frequency-after.json`、`seven-frequency-partial-difference.json`、`independent-root-partial-preservation-review.json`。仅此部分已发布范围，**51,360 根 1m 源 Bar**经 fresh Session 端点、质量与 SHA 核对；**10,272 根 5m 派生 Bar**按相同物理合约 1m 和 Session `(start,end]` 经独立 Decimal 200 逐字段、逐端点复算通过；见 `aggregation-partial-native.json`、`independent-root-partial-data-review.json`。这不证明 CU 四频完整历史、任何候选资产或页面 READY。

失败后只读现场：12 组合仍 **0 stream**，全局维护锁 granted/waiting 均为 0，8012/5178 无监听，未启动 CU asset build、API、Web 或 Chrome；`failure-boundary-final.json` 与 `independent-root-final-native-readback.json` 保留实测。失败后账户级额度采样不能归因于本任务消费。root 首次只读元数据探针误用 `rows` 键而 `aggregation-partial-native.json` 实际为 `source_rows`/`derived_rows`，其 `KeyError` 已保存在 `independent-root-readonly-probe-error.json`；修正后的独立数学审计通过，未导致生产写入或维护重试。

worker CU 准入定向 API **55 passed / 69 deselected**、Web **26 passed**、Web build 通过；独立 Spec 全 API **124 passed**、Web 三组 **122 passed**，Standards 与 Spec 均无 Confirmed Issue，见 `independent-root-eligibility-code-review.json`。最终 `independent-root-final-safe-defer-review.json` 已独立封存 **REVIEW_COMPLETE_SAFE_DEFERRED_DATA_BLOCKED**，只证明已发生部分发布及共享资源的安全边界，**不是 CU CLOSED**。

恢复 CU 前须先确定该原始 turnover 与无损 Canonical 表示的权威处理合同，并独立证明精确恢复对象、当前前像、预算及失败 attempt 不复用。不能靠再次批准盲重试、取整/置零、改 schema 或缩短窗口。此轮四品种队列至 CU 暂缓结束，不启动其他品种；页面收益、因果研究、OOS、模拟成交与 Runtime 均未产生。
