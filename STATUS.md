# 当前状态

更新时间：2026-08-25

## 正式 release 与 production Runtime

- 正式 release 为 `v1.8.3@9ca18afc9b056d413ee8cac56a056b7d7df078b4`；本机五个 launchd label 当前绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.3` 的同一 commit。该 Runtime 身份不包含本次 develop 收敛代码。
- 本地 API、Web、Live 与 Alert 从该根运行；after-market 按日程尚未运行。旧 v1.8.2 Runtime worktree 保留为 rollback 资产，当前无 label 指向。
- production Alembic 已在 `20260825_0040 (head)`。HTDY production Scope 已在独立明确授权下更新为 active 60 × 七周期 `60 symbols / 420 pairs`；SuBing Scope 未变。本 Program 不重放 migration、不改真实 Scope。
- Alert transport 为 pushplus，provider accepted 不等于微信送达。Execution Review roll 仍为 `disabled`。

## 已集成 develop 的 Architecture Convergence

Architecture Convergence Tasks 1–6 已通过 merge `0cc2452048f2b03b521f351e1cbd443a359f2b7f` 集成到 develop：SuBing homepage workbench 与详情 panel、四项 public overlay、Attention/Trend Focus、Main Force Mirror 与 Five-Candidate phase assets 的 active surface 退役均已完成。它们尚未 release，也未 Runtime promotion。

保留的产品与研究事实：

- SuBing 仍有 Daily Context、Current Signal State、Formal Event 三类独立事实；Daily Watch 当前仍等待下一次自然盘后 artifact。
- HTDY 七周期、frequency-aware Event 与 symbol × frequency Scope 已是 release/Runtime 事实；真实通知与自然 D1/W1 evidence 仍未验证。
- Candidate Validation/Robustness 与 pending prospective OOS 保留；Generic Robustness relationship metrics 保留。已退役 phase-specific Dossier/Relationships 不再是 pending Gate。
- Alembic migration history、`futures_member_ranks` table identity 与仓库外既有 historical snapshots 保留；没有 active reader/builder/provider/CLI。
- RQAlpha local-only workbench 未加载、未进入 Runtime；真实 smoke 仍 pending。

## 待完成 Gate

- HTDY 的真实 PushPlus/微信送达与自然 D1/W1 `canonical_updated` evidence pending；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然盘后 Daily Watch artifact 和自然 Live seam evidence pending；不手工触发或回填。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 按各自 protocol 独立累积，均为 pending prospective OOS。
- Execution Review roll Gate 保持 `disabled / not activated`。
- Architecture Convergence Task 7/8 尚在 develop 实施与验证流程；在用户明确 release 批准前不得合 main/tag/release，在单独 Runtime 批准前不得 promotion。

## 事实源边界

当前 release、Runtime、Scope、evidence 与 pending Gate 只看本文件。稳定产品边界见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，验证命令见 `TESTING.md`。
