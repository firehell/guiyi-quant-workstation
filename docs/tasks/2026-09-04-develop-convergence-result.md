# `develop` 收敛实施结果

日期：2026-09-04
状态：`IN_PROGRESS`
实施 baseline：`18a62382685b6deb92010968d4a5a920952fa206`
任务分支：`chore/develop-convergence`
设计：`docs/tasks/2026-09-04-develop-convergence-design.md`
计划：`docs/tasks/2026-09-04-develop-convergence-implementation-plan.md`

## Owner 分发决定

`NEWOW_SCREENSHOT_POLICY=RETAIN`
`DISTRIBUTION_STATUS=DISTRIBUTION_APPROVED_BY_OWNER`

该状态只覆盖 `docs/research/newow-v3.2.82/screenshots/**`，不覆盖原始页面响应、逐 Bar 股票数据或 RQData/Canonical 原文。

## Baseline inventory

- Git status：clean
- Baseline SHA：`18a62382685b6deb92010968d4a5a920952fa206`
- Branch topology：见本任务 PR 的 Task A evidence
- Open PR / Issue：见本任务 PR 的 Task A evidence
- Worktree：见本任务 PR 的 Task A evidence

## 初始 blocker

- 尚待 Task B–G 验证。

## 变更记录

- 删除 tracked `.playwright-cli/**`；Git 历史未重写。
- `.gitignore` 已加入 `.playwright-cli/`。
- Newow screenshot 保留，状态为 `DISTRIBUTION_APPROVED_BY_OWNER`。
- 未恢复或分发原始页面响应、逐 Bar 输入或 RQData/Canonical 原文。
- 删除三个 `docs/superpowers/*` 非 canonical 文件；replacement 与无 active inbound reference 已核验。
- Issue `#286`、`#259` 已关闭为 `NOT_PLANNED`，仅表示 superseded，不冒充旧计划完成。
- Issue `#307` 已更新为 `subing_ths_15m_v3` 当前合同并保持 open。
- PR `#333` metadata 已对齐 current head `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`，旧 SHA Review 标记为 `RELEASE_REVIEW_STALE`。
- `STATUS.md` 仅同步 PR current-head/stale Review 事实；`TESTING.md` 仅增加 repository-hygiene 命令与非授权边界。
- Task C fix round 1 将 Newow futures current task contract 从 blanket pending 同步为 `IMPLEMENTED / EVIDENCE_PARTIAL`：9/9 真实 series 已验证，18 个 D1/60m OOS 单元 passed，9 个 W1 单元因 execution facts 不足 blocked，完整冻结包独立复算仍待补齐。
- Task D 完成 retired surface、single authority 与 Newow research boundary 审计；未发现普通合并回归，未修改 source/test。

## 验证

- Task C guard RED：删除前定向 guard 以 `1 failed` 指出三个 tracked `docs/superpowers/**` 文件。
- Task C guard GREEN：删除后 `tests/engineering/test_repository_hygiene.py` 为 `3 passed`。
- Task C authority scan：首轮扫描没有识别 Newow futures current task contract 与 dossier 的证据状态漂移；fix round 1 已将该 task contract 同步到 dossier 已有事实，保留完整冻结包与 W1 的 pending Gate。旧 Newow V1 文档保留独立版本身份，UI 冲突优先级由 current Market Detail design 明确。
- Task D canonical/retirement：`19 passed, 1 skipped`，exit 0。
- Task D owner readback：CLI domain 仅 `data, runtime`；Alert Rule 仅 `htdy_original_15m, subing_ths_alert_15m_v1`；SuBing formula 为 `subing_ths_15m_v3`。FastAPI `0.138.0` 下计划脚本直接遍历 `app.routes` 得到空 Market 列表，因 `include_router()` 以无 `path` 的 `_IncludedRouter` 懒节点表示；同一 app 的 OpenAPI 读回确认 6 条 active `/api/v1/market/*` route：`/bars/page`、`/dominants`、`/newow/trend-detail`、`/research/home-overview`、`/research/product`、`/state`。
- Task D authority scan：6 个 hit 全部人工分类通过。其中 5 个是 Web 显式 series label/choice/type/preference，无 resolver 或 fallback；1 个是 session-anchor repair 在已解析 Canonical root 内对 D1/W1 做不变性 hash 的维护完整性 guard，不是 Historical consumer。旧 SuBing/Trend Focus/Main Force Mirror/market radar active hit 为 0。
- Task D research boundary scan：59 个 hit，均属显式边界元数据、fail-closed 能力校验、页面参考字段或独立 causal research 版本。Newow 照妖镜固定 `repainting=true` 且 `formal_signal_eligible=false`，causal executor 拒绝其 formula；`reference_change_pct` 明确标记为非真实成交、未计成本/限价/换月的页面参考变化；causal research 只在纯 research 模块中使用 completed actual-dominant、next-open、物理合约段隔离和显式 execution facts，无 Alert/Runtime/账户 consumer。HTDY repainting 属另一已冻结 observation-only first-seen 合同，不是 Newow formal signal。
- Task D Newow 全量 regression：`553 passed`，exit 0，191.49s。
- Task D 提交前验证：canonical/retirement 复跑 `19 passed, 1 skipped`，OpenSpec strict `8 passed, 0 failed`，secret scan `finding_count=0`，全部 exit 0。
- Task D 四项结论：`retired surface = PASS`；`single authority = PASS`；`research boundary = PASS`；`merge regression = NONE`。`LANE3_BLOCKER = NONE`。
- 全量完成矩阵仍待后续 Task。

## Branch 清理

- 尚未执行。

## Review 与集成

- 尚未执行。
