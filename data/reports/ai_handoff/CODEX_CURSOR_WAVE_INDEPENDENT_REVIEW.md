# Codex Cursor Wave 独立复核

任务：`CURSOR-WAVE-INDEPENDENT-REVIEW-X001`

结论：`ACCEPT_CURSOR_WAVE_AFTER_CODEX_FIXES`

Gate：`CODEX_ACCEPTED_CURSOR_WAVE`

基线：`cursor/v1-indicator-strategy-prep@b76791bf4bfa3ed0aaef048627ccca0bade1774d`

## 独立结论

Codex 未采用 Cursor 自报作为验收依据，已独立读取全部 Cursor checkpoint、handoff、manifest、D4-00 产物及 `origin/main...b76791bf` diff，并复跑声明测试和完整受影响测试。

Cursor Wave 的业务边界总体成立，但原 checkpoint 不能原样接受：`git diff --check` 实际失败；Web production build 实际存在 TypeScript 错误；formal strategy snapshot 校验仅检查名称存在，未阻断 observation-only HTDY original 与 unconfirmed policy 的错配，也未绑定 HTDY strict 的版本、confirmed-only、next-bar timing 和 request context。

Codex 已在隔离分支收敛修正并重新验证，因此结论为“修正后接受”，不是阶段 4 Ready。

## 十五项验收

| # | 检查项 | 结论 | 独立证据 |
|---|---|---|---|
| 1 | D4-00 original/strict/XMA 边界未改写 | PASS | 三份产物与 `64420a30` 逐文件无差异，SHA-256 不变 |
| 2 | Registry 生命周期与 capability matrix | PASS AFTER FIX | Registry 状态矩阵成立；formal snapshot 另加 observation/repaint/confirmed fail-closed |
| 3 | original 保持 observation-only | PASS AFTER FIX | Registry 禁止 backtest/live/alert；formal snapshot 无论 strategy code 均拒绝 original/alias |
| 4 | strict 仅 strategy_candidate | PASS | `status=strategy_candidate`，仅 backtest candidate；live/alert/Web 均 false |
| 5 | unknown formal policy fail-closed | PASS AFTER FIX | unknown indicator/policy、unconfirmed policy、invalid read snapshot 均 fail-closed |
| 6 | report 14 算法、参数和 hash 不变 | PASS | JM v1b strategy 目录零 diff；frozen config SHA-256=`8f45991aae4c4db62dffd4f60e9fc3cf61abea0381b88b9cd44e938fda26f49a` |
| 7 | formal caller 最多一个且逐 bar 一致 | PASS | C4-03 为 no-op，正式数值调用方迁移数为 0；指标算法文件零 diff |
| 8 | strategy snapshot 不猜 legacy | PASS AFTER FIX | 无 snapshot 仍为 `legacy_policy_unavailable`；无效 snapshot 改为 `invalid_policy_snapshot` |
| 9 | future-tail / confirmed-only / next-bar fill | PASS AFTER FIX | HTDY strict 测试通过；snapshot 强制 confirmed-only、strict exact version、next-bar open |
| 10 | validation config 未用结果调参 | PASS | 参数 hash 固定；协议明确 dry-run/OOS 不回写配置及 hard-reject 不得调参掩盖 |
| 11 | Review/Runtime 不伪造真实数据 | PASS | 缺字段保持 unavailable/null；fixture report_id=null；degraded 不映射 healthy |
| 12 | 无越界写入或执行 | PASS | 无 migration/DB/Parquet/Profile/live/archive/SignalEvent/WeChat/order 变更或启动 |
| 13 | 复跑全部声明测试 | PASS | pytest 73 passed；report14 1 passed；Web 16 passed |
| 14 | 完整受影响测试 | PASS AFTER FIX | backend 229 passed / 2 skipped；Web 75 passed / 1 skipped；production build pass |
| 15 | `git diff --check` | PASS AFTER FIX | Cursor checkpoint 失败；清理新增文档行尾空格后通过 |

## Codex 修正

1. 修复 `MarketRuntimeObservationPanel` 对 string/number observation union 的 TypeScript 类型错误，使 production build 通过。
2. formal strategy snapshot 强制 `confirmed_only is True`，拒绝 observation-only、known repainting 和 unconfirmed policy。
3. HTDY strict snapshot 强制 exact strategy version、only strict_v1、`backtest_candidate` 与 `next_bar_open`。
4. explicit snapshot 必须与 formal request 的 strategy/profile/execution context 一致。
5. 报告读取仅把完整且可验证的 snapshot 标为 available；不完整或越界 snapshot 标为 invalid，不回退猜测 Registry。
6. 清理 Cursor 新增 Markdown 的 trailing whitespace。

## Cursor 声明与实际差异

| Cursor 声明 | 独立结果 |
|---|---|
| `git diff --check` pass | 原 checkpoint 有 20 处 trailing whitespace，实际 fail |
| 前端定向 node tests 16 pass | 属实，但未覆盖 production type-check/build；build 实际 fail |
| formal policy fail-closed | unknown 名称属实；observation-only 搭配其他已知 policy 可绕过，已修复 |
| D4-00、report14、禁止范围未改 | 独立复核属实 |

## 保留风险与下一步

- D4-00 最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。
- 本 Gate 不等于 `INDICATOR_REGISTRY_V1_READY`、阶段 4 Ready、HTDY formal report Ready、OOS Ready 或 live Ready。
- validation protocol 仍是 `protocol_prepared_not_final_frozen`，未运行正式回测/OOS。
- Review/Runtime 仍是 foundation；未绑定新的真实 candidate report，也未执行 T3/T4。

下一任务应仅进入“阶段 4 指标契约与 formal candidate Codex 正式验收”的 Plan/批准流程，不直接创建报告、写 DB 或进入 live。
