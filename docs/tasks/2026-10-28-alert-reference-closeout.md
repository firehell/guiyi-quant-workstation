# Alert 状态与 HTDY 60m 参考记录收敛

Owner 已交办完整实现、验证、发布和闭市切换。基线 develop `72bf8f3`；现场 v1.16.30/gen36。
本任务不启用 SimNow、不改变公式/推送受众/30 秒时效，不补历史或补发。

## 验收与实施

1. Alert 合法暖机是未就绪而非计算失败；不制造成功水位。v2 coverage 兼容 v1，重启后的无新输入、
   真正滞后和未验证分别保留；未决失败不能被新日期或重启清除。
2. HTDY `htdy_first_seen_reverse_close_v1` / `latest_only_32_v1` 仅接受 operational 60 品种×60m。
   buy 开多、sell 开空，反向先平后开，同向不加仓；Bar close、零费用/滑点的页面参考，不是 Fill。
   每条输入绑定持久原件、32 根窗口和 hash；已有候选 15m 不自动扩 Scope。
3. 一次事务完成全部启用种子/activation/receipt，共同未来起点、空参考仓位。旧 Event 不补配交易，
   原件/动作/交易/checkpoint 通过原生事务和稳定关联验证；未知提交只读核对，不盲重试。
4. 定向及隔离 PostgreSQL/Redis 验证后独立 Review；再集成、向前发布、权威闭市窗口原生切换，
   保留 10 秒收尾预算与唯一发布树。自然无信号保持待验收，不人为构造信号或真实测试发送。

普通 transport 失败独立保留时间、错误类型和次数，不判定策略故障；计算、输入、持久化和未知提交仍报错。

## 实际验证

实施中，尚未发布或切换。Reference 非 PG 回归 1208 passed / 10 skipped（后者非验收通过）；
HTDY SQLite 与 PG 原子启用、信号/交易、提交未知定向通过，真实隔离 Redis Inbox 协议 12 passed。
Web type/build、离线 uv lock、12 项 OpenSpec、secret scan 0、定向 Ruff/Mypy 通过。
扩大验证中的历史 codec 测试改用真实 partial/resume 报告验证 pending 存储，保持既有同单元 advance/rebuild；
handover 旧 fixture 补齐已存在的 retry/health 状态，原件失败仍不 ACK，未修改生产处理逻辑。

真实 Canonical 60/60×32 根 60m 冻结完成，7 路跨物理合约。v30 与候选独立进程计算的指标、信号、动作、
交易、收益、transition 和 checkpoint 差异全部 0。私有对照 `output/alert-htdy-20261028/htdy-60m-offline-comparison-v2.json`，
SHA256 `e559b9a1ab19044d5e4708d2440af1c836db7f052103ab32eef82f21046fcd11`。
这是离线 Canonical 对照，`first_seen_proven=false`，不产生自然信号、参考交易或通知。

独立 Review 确认并修复启用时钟 TOCTOU：取锁后、逐路及最终 flush 后按单调时钟重新校验，起点保留 10 秒余量，
PG statement_timeout 5 秒；SQLite 11/PG 9 项通过，Review 已复核关闭。
Review 中的分钟连续暖机进度、未决覆盖写失败跨日恢复均已修复并独立复核关闭。
分钟暖机以带原件 ID 的连续 attempted cutoff 与同代际 ACK 证明，不使用成功水位；下一真实未处理端点仍可报滞后。
诊断持久化失败保留 pending，在后续处理/heartbeat 先写成功，不重试 Event 或 transport。
history 仅输出当前 warming 路由，整体最多 128 条；300 route 场景 journal 53,366 bytes，缺证明保持未验证。
最终 native handover/cohort 299 passed，真实 PG HTDY 13 passed，Web 定向 10 passed；真实 Redis 覆盖/游标/重启额外 1 passed。
候选版本入口已改为 1.16.31；远端 develop 前进到 abc181e12（独立研究文档），集成时保留。

一次性隔离依赖：`guiyi-alert-htdy-pg-20261028`（15486、tmpfs）、
`guiyi-alert-htdy-redis-20261028`（16389、tmpfs、无持久化）。不使用生产依赖进行破坏性测试。
