# 当前状态

更新时间：2026-08-25

## 正式 release 与 production Runtime

- 正式 release 为 `v1.8.4@f78db1b124744d8e2ebe1ee1b7a5ecdc365b40f6`（Release PR `#220`，annotated tag peeled commit 同一）；本机五个 launchd label 当前绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.4` 的同一 commit。API 返回 `1.8.4`，Web、Live 与 Alert 均已从该根运行；旧 v1.8.2/v1.8.3 Runtime 与临时 release worktree 已在无 label/进程引用且 clean 的检查后移除。
- 2026-08-25 自然 after-market 曾于 18:05:02 开始、19:40:05 以 `passed` 终态完成，单次 attempts=1、覆盖 active60；该既有自然证据不因部署封装重复采集。v1.8.4 新 Runtime 根未导入旧根的运行状态文件，因此当前只读 health 将当日 after-market 表示为 `missed`；本次 promotion 未手工补跑、回填或写入该状态。
- production Alembic 已在 `20260825_0040 (head)`。HTDY production Scope 曾于 15:13 在独立明确授权下更新为 active 60 × 七周期 `60 symbols / 420 pairs`，随后于 20:43 按新的明确请求原子收敛为唯一 `jm × 15m`（`1 symbol / 1 pair`）；七周期图表能力与逐 `symbol × frequency` 开关能力不变，SuBing Scope 未变，未触发 Event、重放或通知。
- Alert transport 为 pushplus，provider accepted 不等于微信送达。19:40 的 processing failure 已被后续 `jm × 15m` 自然处理成功覆盖为 `processing_state=ok`；v1.8.4 已包含 W1 周内正常跳过与 Runtime observation schema v2 的精确失败 CAS acknowledgment 能力。当前 acknowledgment 仍为 `null`，没有执行 production acknowledgment、Event 重放、补发或真实通知；当前 Runtime 的 `degraded` 来自上述 after-market `missed` 与保留的 `notification_transport_failed`。Execution Review roll 仍为 `disabled`。

## 已发布的 Architecture Convergence

Architecture Convergence Tasks 1–8 已完成实现、验证与独立 Review，并通过 Release PR `#220` 进入 v1.8.4 与当前 Runtime：SuBing homepage workbench 与详情 panel、四项 public overlay、Attention/Trend Focus、Main Force Mirror 与 Five-Candidate phase assets 的 active surface 退役均已完成。

保留的产品与研究事实：

- SuBing 仍有 Daily Context、Current Signal State、Formal Event 三类独立事实；本次自然盘后已生成 target=2026-08-26 的 Daily Watch，current=ready，计数为 universe=60、long=1、short=1、excluded=2、unavailable=56。unavailable 仍是显式数据充分性结果，不构成补取或回填授权。
- HTDY 七周期、frequency-aware Event 与 symbol × frequency Scope 已是 release/Runtime 事实；当前 production Scope 精确为 `jm × 15m`。此前 420-pair Scope 下自然形成的 6 条 D1 Event 保持 immutable，未删除、重放或补发；19:40 曾出现 W1 处理失败并记录 provider accepted 与一次 transport failure，后续 processing 已自然恢复，但这仍不证明微信送达，也不改变真实通知 Gate；自然 D1/W1 event identity/evidence 仍需按各自事实独立核验。
- Candidate Validation/Robustness 与 pending prospective OOS 保留；Generic Robustness relationship metrics 保留。已退役 phase-specific Dossier/Relationships 不再是 pending Gate。
- Alembic migration history、`futures_member_ranks` table identity 与仓库外既有 historical snapshots 保留；没有 active reader/builder/provider/CLI。
- RQAlpha local-only workbench 未加载、未进入 Runtime；真实 smoke 仍 pending。

## 待完成 Gate

- HTDY 的真实 PushPlus/微信送达与自然 D1/W1 `canonical_updated` evidence pending；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch 的自然盘后 artifact 已于上述单次自然运行产生，不手工触发或回填。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 按各自 protocol 独立累积，均为 pending prospective OOS。
- Execution Review roll Gate 保持 `disabled / not activated`。
- Production notification acknowledgment 尚未执行；只有新的范围明确执行意图才能对当前精确失败做一次 CAS acknowledgment，且该操作仍不重放、不补发、不证明 provider accepted 或微信送达。

## 事实源边界

当前 release、Runtime、Scope、evidence 与 pending Gate 只看本文件。稳定产品边界见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，验证命令见 `TESTING.md`。
