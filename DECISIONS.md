# 架构决策记录

本文件只记录长期影响代码、数据口径或运行边界的有效决策；当前状态见 `STATUS.md`，过程资料由 Git 与 final receipt 追溯。

## 当前有效决策

| 主题 | 决策 | 边界 |
|---|---|---|
| 产品 | 本地单用户国内期货研究工作站 | 不做自动交易、SaaS、多用户或无人值守下单 |
| 数据主链路 | RQData/标准 Parquet → metadata/profile/lineage → consumers | active 仅 `rqdata/local_parquet + primary + quality != failed`；严格研究 passed-only |
| 历史与 live | canonical historical 与 live observation 分层 | live 不直接成为正式历史 active |
| 指标 | 复用公共指标内核、逐调用方迁移 | Web/回测/实时不得长期各自实现一套算法 |
| 回测 | vn.py 引擎不改源码，策略/参数/数据/订单/trade/equity/lineage 可复算 | 可信度优先于收益；不覆盖旧报告 |
| 信号与通知 | `Strategy -> SignalEvent -> Notification Gate -> Channel` | 研究观察、幂等、默认关闭真实发送、无订单 |
| HTDY original | 精确 realtime first-seen observation-only exception | 不授权历史回测、收益、自动通知或交易；见指标与信号 canonical |
| 真实写入 | 按业务域使用 hash-bound、scope-bound approval packet/Gate | Issue 或测试通过均不能替代专用 Gate |
| worktree | canonical、集成、task 与 detached Runtime 物理隔离 | `main` 为 canonical/release，`develop` 为长期集成主干；task 经手动 PR 合入 develop，只有 clean 且已合入才可清理 |
| release | `release-flow.sh` 以精确 SHA 受控发布 | 用户批准、main/develop clean 且同 SHA 才可 apply；不自动 merge、打 tag 或切换 Runtime |

## 重要取舍

- 数据质量、lineage 与可复算性优先于产品扩展和性能优化。
- 独立 Gate 只证明其精确范围；不得由数据、回测、单次通知或 smoke 推导盈利、Runtime、长稳或交易 Ready。
- GitHub Issue/PR 用于 backlog、跨模块审查和保护模式；普通立即执行任务不必增加协作仪式。
- 当前树保留 canonical、未关闭受控合同和业务证据；已完成协作过程由 Git 历史提供。
- ADR-WS-004 仅在显式启用前置已满足时，允许合规 Lane 1/2 受控入口自动完成验证、commit、push 与 draft PR；用户仍手动 merge，main、Runtime 与 Lane 3 不自动化。

## 现行 ADR

- `docs/decisions/ADR-WS-003-develop-release-worktree-lifecycle.md`：本地 worktree 生命周期。
- `docs/decisions/ADR-WS-004-five-layer-manual-pr.md`：受控 Lane 1/2 draft PR 边界；不改变手动 merge 与 Runtime/Gate 限制。

未来涉及产品边界、数据/回测口径、live/通知或 worktree/发布模型的长期变化，先在此处或对应 deep canonical 固化；普通实现细节不新增 ADR。
