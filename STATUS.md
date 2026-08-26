# 当前状态

更新时间：2026-08-26

## 正式 release 与 production Runtime

- 正式 release 为 `v1.8.4@f78db1b124744d8e2ebe1ee1b7a5ecdc365b40f6`（Release PR `#220`，annotated tag peeled commit 同一）；本机五个 launchd label 当前绑定 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.4` 的同一 commit。API 返回 `1.8.4`，Web、Live 与 Alert 均已从该根运行；旧 v1.8.2/v1.8.3 Runtime 与临时 release worktree 已在无 label/进程引用且 clean 的检查后移除。
- 2026-08-25 自然 after-market 曾于 18:05:02 开始、19:40:05 以 `passed` 终态完成，单次 attempts=1、覆盖 active60；该既有自然证据不因部署封装重复采集。v1.8.4 新 Runtime 根未导入旧根的运行状态文件，因此当前只读 health 将当日 after-market 表示为 `missed`；本次 promotion 未手工补跑、回填或写入该状态。
- production Alembic 已在 `20260825_0040 (head)`。HTDY production Scope 曾于 15:13 在独立明确授权下更新为 active 60 × 七周期 `60 symbols / 420 pairs`，随后于 20:43 按新的明确请求原子收敛为唯一 `jm × 15m`（`1 symbol / 1 pair`）；七周期图表能力与逐 `symbol × frequency` 开关能力不变，SuBing Scope 未变，未触发 Event、重放或通知。
- Alert transport 为 pushplus，provider accepted 不等于微信送达。19:40 的 processing failure 已被后续 `jm × 15m` 自然处理成功覆盖为 `processing_state=ok`；v1.8.4 已包含 W1 周内正常跳过与 Runtime observation schema v2 的精确失败 CAS acknowledgment 能力。当前 acknowledgment 仍为 `null`，没有执行 production acknowledgment、Event 重放、补发或真实通知；当前 Runtime 的 `degraded` 来自上述 after-market `missed` 与保留的 `notification_transport_failed`。Execution Review roll 仍为 `disabled`。

## Daily Watch V2 task branch 已验证、待合入

- Task branch `f17bf510a` 已将 Daily Watch D1/60m warm-up 改为截至来源交易日的最近 30 根 raw rank1 stitched actual-dominant Bar，并以唯一 source-day owner、同 contract 与 page segment 被完整 current segment 包含校验分页 identity；wrong owner、重叠 owner、越界 segment、future Bar 与 source-day 缺失继续 fail-closed。V1 bytes 未改，未增加 V1 fallback，Canonical、Catalog、DB 与 Runtime 均未改变。
- Task 1–4 相关后端验证为 `224 passed`，Ruff clean，focused Mypy `1 source file` 与仓库 canonical Mypy `171 source files` 均无问题。Web V2 contract 的既有本轮验证为 `300 passed / 1 skipped / 0 failed`、`vue-tsc` 与 production build 通过；本次 concern fix 只改后端 Builder 与后端测试，未改变 Web contract。
- 对 production Catalog/Canonical 的严格只读 smoke 使用 source trading day `2026-08-25`，active60 结果为 `universe=60 / long=16 / short=5 / excluded=39 / unavailable=0`；D1/H1 `warmup_bar_count` 均为 `30 × 60`，D1 segment-count 分布为 `1:4 / 2:47 / 3:9`，H1 为 `1:49 / 2:11`。该 smoke 直接调用 Builder、使用 read-only transaction 并 rollback；未调用 Generator/Store publish、RQData、HistoricalDataManager、Redis、notification 或 Runtime，也未生成或发布 V2 artifact。
- 上述仅构成 CODE_COMPLETE / TEST_COMPLETE 与 read-only data acceptance；尚未进入 develop、release 或 production Runtime，也不是自然盘后 V2 evidence。

## 已发布的 Architecture Convergence

Architecture Convergence Tasks 1–8 已完成实现、验证与独立 Review，并通过 Release PR `#220` 进入 v1.8.4 与当前 Runtime：SuBing homepage workbench 与详情 panel、四项 public overlay、Attention/Trend Focus、Main Force Mirror 与 Five-Candidate phase assets 的 active surface 退役均已完成。

保留的产品与研究事实：

- SuBing 仍有 Daily Context、Current Signal State、Formal Event 三类独立事实；production v1.8.4 的本次自然盘后已生成 target=2026-08-26 的 V1 segment-local Daily Watch，current=ready，计数为 universe=60、long=1、short=1、excluded=2、unavailable=56。该既有 V1 artifact 保持 immutable，不转换成 V2 artifact、V2 unavailable 事实或补取/回填授权。
- HTDY 七周期、frequency-aware Event 与 symbol × frequency Scope 已是 release/Runtime 事实；当前 production Scope 精确为 `jm × 15m`。此前 420-pair Scope 下自然形成的 6 条 D1 Event 保持 immutable，未删除、重放或补发；19:40 曾出现 W1 处理失败并记录 provider accepted 与一次 transport failure，后续 processing 已自然恢复，但这仍不证明微信送达，也不改变真实通知 Gate；自然 D1/W1 event identity/evidence 仍需按各自事实独立核验。
- Candidate Validation/Robustness 与 pending prospective OOS 保留；Generic Robustness relationship metrics 保留。已退役 phase-specific Dossier/Relationships 不再是 pending Gate。
- Alembic migration history、`futures_member_ranks` table identity 与仓库外既有 historical snapshots 保留；没有 active reader/builder/provider/CLI。
- RQAlpha local-only workbench 未加载、未进入 Runtime；真实 smoke 仍 pending。

## 待完成 Gate

- HTDY 的真实 PushPlus/微信送达与自然 D1/W1 `canonical_updated` evidence pending；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 的 develop integration、release、Runtime 与自然盘后 artifact 均 pending。上述既有 V1 自然 artifact 不作为 V2 evidence，不手工触发或回填。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 按各自 protocol 独立累积，均为 pending prospective OOS。
- Execution Review roll Gate 保持 `disabled / not activated`。
- Production notification acknowledgment 尚未执行；只有新的范围明确执行意图才能对当前精确失败做一次 CAS acknowledgment，且该操作仍不重放、不补发、不证明 provider accepted 或微信送达。

## 事实源边界

当前 release、Runtime、Scope、evidence 与 pending Gate 只看本文件。稳定产品边界见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，验证命令见 `TESTING.md`。
