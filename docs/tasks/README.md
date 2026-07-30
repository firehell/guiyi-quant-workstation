# 受控任务合同

本目录只保存未关闭的高风险合同，及仍被运行时 Gate 以路径/哈希消费的受控证据。历史过程不再维护 archive；通过 Git 历史和 final receipt 追溯。

## 当前合同

- `JM-LIVE-STABILITY-S6-10.md`：HTDY 15m 收盘观察、完整日与长期晋级 Gate。
- `V1-DATA-REAUDIT-STATUS-001.md`：Audit V2 与全历史 residual triage 边界。
- `V1-FINAL-ACCEPTANCE-S6-11.md`：V1 最终只读验收合同。

## 受控证据例外

- `S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md`：S6-07 recovery/rebind Gate 读取并绑定其内容哈希。
- `JM-LIVE-SIGNAL-EVENT-S6-08.md`：S6-08 code-only deployment Gate 的测试合同。

除非同步完成相应业务 Gate 的重新设计、哈希迁移和专项验证，不得移动、删改上述受控证据。

普通开发不创建任务合同。策略公式、回测口径、migration、正式数据或 live 写入、Runtime 与真实企业微信发送等保护模式任务，只有在 Issue 无法表达、Gate 直接消费或合同需长期保留时才创建 `docs/tasks/<TASK_ID>.md`。

工程规则见 `AGENTS.md`；当前状态见 `STATUS.md`。
