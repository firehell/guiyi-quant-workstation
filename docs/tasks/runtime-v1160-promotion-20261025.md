# v1.16.0 Runtime promotion

Owner 要求切换至最新正式版本；目标固定为 annotated `v1.16.0` / `015a93ed0e63ba515d72c3764d174252da5345d9`。现役从 v1.15.18/gen23 切换到 v1.16.0/gen24。没有启用订单、改交易阶段、增 Scope/Rule/受众、补发通知或下载/修复行情。

## 准备与边界

原生 selective release plan 因 input/formula/reference/launcher 合同指纹不同，返回 MIXED_CONTRACT_INCOMPATIBLE；未执行该计划。经独立静态复核，active 策略版本与状态无迁移需求，变动包含离线研究及历史显示能力。采用全停后整体安装、整体 CAS 的独立精确冷切，禁止新旧 writer 混跑。

独立安装冻结依赖；exact 新版只读 Canonical/Catalog，在正式共享派生目录初始化首页。构建及独立 read/HTTP 回读均60/60 ready，无 failed/missing/stale。既有盘后成功刷新节点保留，不新增定时任务。

保护范围：权威60品种 CLOSED 窗口、原 PID/owner/loaded 身份、原 bindings/plist/launcher、维护锁和消费进度；pending Capture与可发送通知批次必须为0。Redis journal 原文、索引和游标完整摘要；Event/delivery/Rule/Policy和 forward 经济字段、状态及已有payload/pre/post-state哈希逐行摘要一致。业务摘要明确排除 seed_chunk_text/source_evidence/dependency_manifest 大载荷，不声称全部数据库载荷逐字扫描。没有通过修改旧结果制造新状态。

## 单次 attempt 与恢复

证据目录 `output/runtime-v1160-20261025/`（本地，不提交生成数据）。

1. `cold-attempt-001`：原生卸载 Feed 后立即检查标签，遇到 launchd 异步完成窗口，记录失败。四项 calendar 与 Feed 独立证明已退出；另五原 PID parked；未安装、未 CAS。
2. `cold-attempt-002`：新的封印续接计划仅停止剩五服务，卸载结果只等待、不重复发命令。10份新 plist、4个已有 activation marker 完成；盘后当前状态是 skipped 且无成功水位，原生 make_history 拒绝将其单独转换为历史，保留失败，未 CAS。
3. `cold-attempt-003`：基于全旧 PID 已退出/label absent、新 plist 字节精确相等的新计划。原生 read_history 校验旧有效历史（成功水位10/22、10/23失败），按原 retain_from_supervised 的 skipped 分支语义沿用，另保存当前 skipped 原记录。无重复 stop/install/marker。整体 CAS 后启动六常驻、注册四 calendar，完成全部摘要后验。

原 attempt 不重跑，未知结果先只读核对。最终计划 SHA `7d069b8b02862a39efb49cd7db42e92301a093c869265aeef54a1d0778ac4d8f`；completed UTC `2026-10-25T03:40:12.778498Z`。调用器各轮经独立复核，渲染、独占intent、原子写和摘要纯函数4项测试通过；这不等于完整故障注入测试。

## 独立结果

- `identity-after.json`：10项 exact v1.16.0/gen24；6常驻 active，4 calendar loaded且idle。
- PID：Feed96112、Live96082、Alert96087、Reference96093、API96100、Web96106；60秒连续采样不变，Reference至少一次 cycle ready，刷新/通知线程存活。瞬时scan ready波动不解释为整体业务READY。
- `/api/health` 1.16.0；5173 index与发布dist逐字一致；60品种首页及overview ready。
- 旧Event、delivery和经济状态摘要保持，pending Capture0；没有新增通知、伪造自然Bar或重放。
- 全局health仍degraded，旧原件缺口、部分暖机/滞后、盘后历史失败及自然验收分别保留。闭市切换不能证明下一Session采集、策略Event、推送或盘后成功，不宣称整体RUNTIME_READY。

旧v1.15.18发布树在新的binding/plist/loaded/进程引用归零后，按原生retention exact计划清理；8个.run原件逐字保存到本目录retired-v11518-run并记录SHA，tag/Release历史保留。其他仍被Codex使用的任务树未清理。
