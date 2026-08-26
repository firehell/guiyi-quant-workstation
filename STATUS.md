# 当前状态

更新时间：2026-08-26

## 正式 release 与 production Runtime

- 正式 release 仍为 `v1.8.4@f78db1b124744d8e2ebe1ee1b7a5ecdc365b40f6`（Release PR `#220`，annotated tag peeled commit 同一）。2026-08-26 经用户单次明确批准，本机五个 launchd label 已从 v1.8.4 根协调切换到 clean/detached `/Volumes/扩展盘/guiyi-quant-runtime-c9633ef30@c9633ef302e536ba4f8c138c4334fffd54b3d232`；这是 develop 精确提交的本地开发 Runtime，不是新 release/tag。API `/api/health` 返回仓库包版本 `1.8.3`，Web、Live 与 Alert 均从该精确根运行；原 `/Volumes/扩展盘/guiyi-quant-runtime-v1.8.4` clean/detached 根保留为回滚点，未删除。
- 2026-08-25 自然 after-market 曾于 18:05:02 开始、19:40:05 以 `passed` 终态完成，单次 attempts=1、覆盖 active60；该既有自然证据不因部署封装重复采集。当前 c9633ef30 Runtime 根未导入旧根的运行状态文件，因此当前只读 health 将 after-market 表示为 `pending`；本次 switch 未手工补跑、回填或写入该状态。
- production Alembic 已在 `20260825_0040 (head)`。HTDY production Scope 曾于 15:13 在独立明确授权下更新为 active 60 × 七周期 `60 symbols / 420 pairs`，随后于 20:43 按新的明确请求原子收敛为唯一 `jm × 15m`（`1 symbol / 1 pair`）；七周期图表能力与逐 `symbol × frequency` 开关能力不变，SuBing Scope 未变，未触发 Event、重放或通知。
- Alert transport 为 pushplus，provider accepted 不等于微信送达。19:40 的 processing failure 已被后续 `jm × 15m` 自然处理成功覆盖为 `processing_state=ok`；v1.8.4 已包含 W1 周内正常跳过与 Runtime observation schema v2 的精确失败 CAS acknowledgment 能力。当前 acknowledgment 仍为 `null`，没有执行 production acknowledgment、Event 重放、补发或真实通知；当前 Runtime 的 `degraded` 来自上述 after-market `pending` 与保留的 `notification_transport_failed`。当前旧 Runtime 仍来自 `c9633ef30`，尚未切入 develop 的 RQAlpha / Execution Review 退役提交。

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
- develop 已退役 RQAlpha 与 Execution Review 的 active Web/API/domain/roll seam/tests/docs，Web 路由只保留 `/market` 与 `/market/chart`；SuBing Formal Event 与 Alert 主链保留。仓库 Alembic head 已延伸到 `20260826_0041`，但 production 仍为 `20260825_0040`，四张 `trade_*` 表只读盘点均为 0 行，尚未执行删表。
- Git 外安全配置未设置 `GUIYI_BACKTEST_RUNS_ROOT`，受限路径发现也未得到唯一 artifacts 目录，因此当前没有可验证的 RQAlpha runs 删除目标；未猜测路径，也未触及 Bundle 或 RQAlpha 安装。

## develop 中的 N Structure Historical range band

- Market `图表设置` 已增加独立持久化的 `N字区间` 开关，默认关闭，仅在 `actual_dominant + 5m` 可用；四项 public Overlay 保持不变，N 区间可与任一 Overlay 组合显示。
- 只读 `GET /api/v1/market/research/n-structure/bands` 复用既有 causal N reducer 与真实 rank1 segment warm-up，只投影严格 Completed N：形成区为 `N1 pivot -> completed_at`，完成后沿精确 N1-N2 price span 继续扩张，记录既有 first range-band re-entry，并终止于首个严格 N2-origin break 或当前 segment/Canonical 边界；窗口相交的更早 Completed N 也会返回。不跨 segment，不复制算法，不读取 Live。
- Web 使用一个 candlestick series primitive 在 K 线下层绘制双阶段区间：形成区 6% 实线、完成后观察区 2.5% 虚线，完成点为实心圆、首次回区间为空心圆、N2 破坏为叉号；支持左侧裁剪、分页生命周期合并、最新重叠命中和 factual Historical hover。屏幕内同方向、至少三条的 `>=60%` 可见矩形重叠簇会自动降噪：从未失效且最新完成的优先锚点最多沿三跳纳入邻近成员，第四跳及更远不合并；主 N 保留完整呈现，其余成员只保留低透明上下轨。稳定公共可见锚点上的可访问徽标显示组数，可悬停查看并点击/键盘轮换；离开、缩放或 resize 后重置，方向彼此独立。旧/畸形生命周期响应 fail-closed，只降级该图层，不遮挡 K 线。
- 2026-08-26 后端 N Swing/Pattern/State/API/composition 回归 `250 passed`，Web 单元测试 `323 passed / 1 skipped`，ruff、Vue 类型检查、生产 build/bundle topology 与完整 Web E2E `110 passed / 1 skipped` 均通过；E2E 覆盖完成点在已加载窗口左侧、但扩张观察段仍与窗口相交的分页场景，以及不同起点的三条同向高重叠区间的主成员/淡轨、悬停、点击轮换与离开复位。隔离本地开发栈真实读取 AU `actual_dominant + 5m` 的 Canonical 页面：请求窗口得到 32 条相交生命周期事实（26 条已有首次回区间、11 条已有 N2 失效），其中 15 条与当前视口/价格范围相交并形成有效 geometry，同时包含 up/down；当前 300-bar 视口实际形成 1 个同向重叠组（`N↑ ×4`）并压低 3 条成员。
- 2026-08-26 上述精确 develop commit 已按一次明确授权切入本机五标签 Runtime：所有 plist/loaded environment 均读回同一根与 `c9633ef3`，checkout clean/detached，API/Web 为 200；AU `actual_dominant + 5m` 截至已完成 Canonical `2026-08-25` 的 bands API 返回 200 与正确 Policy lineage，包含 `2026-08-26` 尚未满足源合同的窗口继续显式返回 `N_STRUCTURE_SOURCE_UNAVAILABLE` 409。正式 5173 页面实际加载 32 条 N facts、当前视口渲染 13 条、同时包含 up/down，并形成 `N↑ ×4` / 3 条 suppressed；验收后开关恢复默认关闭。本次未执行 DB、Canonical、Scope、手工盘后、手工 Event/通知、release 或 tag，也不构成 N 独立产品、第五个 Overlay、候选晋升或交易语义。

## 待完成 Gate

- HTDY 的真实 PushPlus/微信送达与自然 D1/W1 `canonical_updated` evidence pending；不以测试、synthetic event、replay 或手工发送补证。
- SuBing 自然 Live seam evidence pending；Daily Watch V2 的 develop integration、release、Runtime 与自然盘后 artifact 均 pending。上述既有 V1 自然 artifact 不作为 V2 evidence，不手工触发或回填。
- SuBing、N 与 JDJ Candidate 的 prospective OOS 按各自 protocol 独立累积，均为 pending prospective OOS。
- RQAlpha / Execution Review 退役的生产收口 pending：必须先取得一次明确 Runtime switch 授权，将不再读取四表的新精确提交切入并读回健康状态；随后才可执行已批准的 production `upgrade 20260826_0041`。外部 runs artifacts 仅在发现并验证唯一 `GUIYI_BACKTEST_RUNS_ROOT` 时删除。
- Production notification acknowledgment 尚未执行；只有新的范围明确执行意图才能对当前精确失败做一次 CAS acknowledgment，且该操作仍不重放、不补发、不证明 provider accepted 或微信送达。

## 事实源边界

当前 release、Runtime、Scope、evidence 与 pending Gate 只看本文件。稳定产品边界见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，验证命令见 `TESTING.md`。
