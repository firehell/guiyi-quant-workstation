# SI 工业硅四周期历史候选安全暂缓

状态：**PARTIAL / SAFE_DEFERRED_QUOTA_GUARD，0/12 页面候选闭环**。SI 是本轮 PS→Y→SI 交办中的补充品种，不计入原有 13/21 品种分母。本任务只允许集成已审 SI 单品种 v27 私有预览准入与安全暂缓记录；没有构建 SI 资产、运行 SI 页面预览或开放正式分钟、Runtime、Scope、通知和交易。PS/Y 既有闭环及 AO/CU 失败现场均未触碰。

原始证据位于 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/si-candidate-pilot/outputs/si-candidate-pilot-20261001/`，不入 Git；下文文件名均相对此目录。冻结代码 `76d23ab4c46239e48536d6c4ade09a9f53058c93` 仅增加 SI v27 singleton 资格与两端直接测试，未改变策略公式、正式 v28 范围、共享时钟或 Canonical schema。

## 权威范围与唯一维护

原生 provider 上市日 **2022-12-22**，页面历史起点为 `max(2023-01-01, provider/product_start)=2023-01-01`，终点 **2026-09-24**，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 仅是聚合源；候选目标为 5m/15m/30m/60m × trend/oscillation/dual。当前 MainContractMap 有 **30 个有序 rank1 区段、27 个不同物理合约**；SI2401、SI2506、SI2507 各有两次非连续 rank1 区段。候选消费保留全部 30 个区段及 29 个区段边界；数据维护按同一物理合约的最大映射截止日去重成 **27 合约 × 四频 = 108 个唯一原生单元**，不将重复区段当作重复下载。12 个私有候选组合的旧 stream 均为 0。见 `baseline.json`、`probe-segments.json`、`maintenance-dry-run.json`。

旧七频前像含 **196 个 dataset / 1,257 个 active 文件**。108 份原生 dry plan 全为 `planned`，去重保守上限为 **221 个 1m 源月、894 个派生月**，源 Bar 估算 938,025 根。冻结父计划 `campaign-plan-v3.json` SHA `1f13bc8ca6147ef755994bc2140c72b7b9d3ebcc1b9afbac1774c35f417835d1`，唯一 runner SHA `37eceeb86c03e5ec98a732a3abc5345338b9b5087ccd9b4b475161854fe5acbd`。独立 fresh preapply 已核 30→27 Map 分组、108 份当前原生计划、旧文件前像、同卷 scratch、锁和额度，见 `independent-root-preapply-review.json`。执行前账户额度余量 **1,033,068,360 bytes**，全批源请求保守估算 **960,537,600 bytes**，最大单元 **51,379,200 bytes**；`completion_guaranteed=false`，每个单元仍须锁外和锁内 fresh 全量估算 Gate。

唯一 `--apply` 在首个 `SI2308/5m` 单元的**原生发布成功之后**因 `QUOTA_ESTIMATE_EXCEEDED_OR_OTHER_CONSUMER` 停止，未执行后续单元。原生结果 `status=passed`：仅 **1 个真实 RQData 源请求**、**2 个已发布目标**，即 `SI2308/2022-12` 的 1m **1,575 Bar**及 5m **315 Bar**；这段 2022 年数据是该合约的权威物理生命周期预热，不是页面窗口缩短。其后账户额度 `bytes_used` 从 **40,673,464** 增至 **43,249,873**，增量 **2,576,409 bytes**，超过首单元冻结估算 **1,612,800 bytes**。额度是账户级且包含其他行为，无法将全部增量归因于 SI；锁内 quota guard 执行了，但其原值没有单独持久化，不能冒称拥有锁内额度时间序列。见 `campaign/SI2308-5m-result.json`、`campaign/SI2308-5m-quota-before.json`、`campaign/SI2308-5m-quota-after.json`、`campaign-stopped.json`。

因此 108 单元严格分类为 **0 完成、1 发布成功后额度 Gate 停止的部分单元、107 未尝试**。campaign 与该单元 attempt 均保留 `PENDING / retry_allowed=false`；没有调整冻结的 1024 bytes/源 Bar 估算、重置额度、改变 plan/hash/窗口、取整/置零、改 schema 或重试。此次不是原生 `ATOMIC_PUBLISH_FAILED`，也不是零提交。见 `independent-root-failure-terminal-review.json`。

## 部分发布、安全边界和证据限制

七频 active 文件 **1,257→1,259**：仅上述 1m/5m 两个新增，**0 扩展、0 删除**；1,257 个旧 immutable 文件及当前行/哈希保持，636 个 D1/W1 文件和 Catalog 旧行保持，1,259 当前文件的 SHA/行数/排序独立核验。见 `seven-frequency-after.json`、`partial-difference-readonly.json`、`independent-root-partial-preservation-review.json`。只对已发布的 `SI2308/2022-12` 做了 fresh native 和独立数值读回：1m **1,575 Bar**经 Session 端点、质量与 SHA 验证；5m **315 Bar**由同物理 1m 按 Session `(start,end]` 经独立 Decimal 逐字段、逐端点复算，21 个 Session，均通过。见 `partial-native-readback.json`、`independent-root-partial-data-review.json`。这不证明 SI 四频完整历史，也不证明任何候选页面 READY。

停止后的 12 个私有组合仍为 **0 stream**，精确维护锁 granted/waiting 均为 0；8012/5178 无监听，未启动 SI asset build、API、Web 或 Chrome。见 `independent-root-partial-resource-review.json`；根独立安全终审证据另见 `independent-root-final-safe-defer-review.json`。首次探索性只读 probe 沿用单一合约断言，在发现 SI 三个回切合约时以 `OWNER_IDENTITY_INVALID` 停止，未保存业务 probe、未执行 provider 或生产写入；随后独立的 `probe-segments.json` 正确保留 30/27 身份。根独立 preapply 首次在默认沙箱因 `OperationalError` 退出，未创建维护 attempt、未写数据；宿主正常批准的同一只读审查通过，失败记录保留。两者均不是这次原生维护的重试或质量通过证据。

worker 定向 API **70 passed / 69 deselected**、Web **26 passed**、Web build 通过；独立 Spec 全 API **139 passed**、Web 三组 **122 passed**，Standards/Spec 均无 Confirmed Issue。候选准入代码 `76d23ab4` 与后续文档 commit 分开；当前没有页面收益、因果研究、OOS、模拟成交、真实交易或 Runtime 证据。

恢复 SI 前须先查明并按权威额度合同处理首单元账户级增量超过冻结估算的原因，重新核对当前 Canonical/Catalog、额度、Map、精确剩余目标与失败 attempt 的不可复用边界。不能靠再次批准盲重试、降低 1024 估算、缩窗或修改源值绕过 Gate。本轮 PS→Y→SI 到此如实结束，不启动其他品种。
