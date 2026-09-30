# P7-16 C 玉米历史候选闭环恢复

状态：**COMPLETED / CANDIDATE_CLOSED，12/12 页面组合**。仅把既有 C 候选从浏览器暂缓恢复验收；固定 21 品种分母不变。冻结代码 `7e69c554e78bec68ae23c10e5c096b8dc75de316`，窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`。1m 只作为四分钟周期的聚合来源；正式分钟、Runtime、Scope、通知、账户、main/tag/release 均未变。

此前 [C 暂缓记录](c-candidate-pilot-20260930.md) 的维护和资产构建事实保持：21 个物理 owner/84 个周期依赖全部 DATA_READY（81 读回、3 NO_GAP），195 次行情请求、790 派生目标；507667 根四频物理 Bar 独立全前缀复核，1174 旧文件与 95887 旧 Bar 保持。4 输入、8 基础、4 融合对应 12 条候选资产；本轮没有重跑 RQData 维护、Canonical 发布或资产 build/rebuild。

本轮使用新隔离工作树和只读 preview。当前 SHA 的原生 source/asset 报告四频 21 owner 与 12 条 READY 资产全部通过，候选始终 `enabled=false`、`activation_generation=0`、`complete_window_proven=false`。独立读回逐条核对原 build plan、保存 manifest/digest、checkpoint、source token、当前 reader 的新鲜输入和 4 组融合依赖，12/12 PASS。采集前后两个 source/asset 报告的 84 个依赖、12 条流及 source evidence 逐项相同。本地 API/Web 实际 GET 的代码、时点与 singleton capability 身份门禁通过。

真实 Chrome 采集 19/19 场：四分钟周期 × 三模式的功能、完整曲线/交易、较早窗口；日周各三模式；取消恢复。原始完整响应经有序分块保存，索引核对 19 场及 49 张截图的大小与 SHA 通过。旧阻断的 5m 双策略较早窗口本次有成功读回和可见 Marker，208 块原始传输完整、该场 409/页面错误均为 0；旧 OOM/409 证据不覆盖、不删除。此次未复现旧 409，**旧间歇性原因仍未证实**，不能声称快照机制已修复。

离线工具审计为 `NUMERICAL_PASS_VISUAL_PENDING`；另用独立 Decimal 实现对 18 个交易曲线场景的 **24574 笔 CLOSED、24610 个 SVG 点**逐值复算，18/18 PASS。49 张原 PNG 已逐张查看并与索引哈希、尺寸核对，结论 `PASS_WITH_RETAINED_VISUAL_LIMITATIONS`，无 Confirmed Issue。保留 Risk / Needs Verification：分钟较早窗口的趋势转折副图仅覆盖局部历史（60m 尤明显）；密集 BUILD/CLEAR 和双模式标签局部遮挡；周线当前物理合约 44/120 Bar 原生预热；日周 hover 浮层局部遮图。页面收益仅为零成本参考收益，不是因果研究、OOS、Paper 或真实交易结果。

验证：`pytest tests/newow_candidate_tools -q -p no:cacheprovider --basetemp=/private/tmp/c-recovery-tool-tests-20260930`，**159 passed**；`prepare`、当前 SHA 资产 `preflight --execute-get`、`capture`、`index`、`audit`、独立 source/asset 与数值/视觉读回均通过。证据保存在主仓库忽略目录 `outputs/c-candidate-recovery-20260930/`、`outputs/c-candidate-prepared-recovery-20260930/`；旧失败证据保留于 `outputs/c-candidate-pilot-20260930/`、`outputs/c-candidate-prepared-20260930-isolated-browser/`。任务专属 Chrome/API/Web 已停，8012/5178 无监听。本次仅关闭 C 历史候选页面证据，不晋升任何正式策略或运行阶段。
