# 分钟牛哇 P0–P6 执行记录

计划：docs/superpowers/plans/2026-09-19-newow-intraday-roadmap.md

## 目标与边界

RB 首品种四周期趋势/震荡/双策略历史闭环，必要边界数据维护及读回、测试、容量、真实浏览器、独立 Review 后集成 develop。排除 P7 全量、release/Runtime/Live/通知/订单。

## 基线

develop b48ffe0e504ee3d0850a2e75c2820dca26f9aefe；用户计划修改已复制，用户 outputs 未动。独立 codex/newow-intraday-pilot worktree。正式根仍为 v1.10.38，不修改。

## 进度与裁定

- P0–P5c 已实现并进入最终回归；P2 最终 source/generation 读回通过。
- P6 代码/数据/容量/浏览器/独立 Review 已完成；最后 develop 集成读回进行中。
- Pre-flight：P1 周期集合影响默认枚举，须显式保持日周/60m 既有默认；P3 端点与 P5a 实际 warmup 决定 P2 最终结果；P5b 完整快照是 P5b-F 前提；P5c 后端修改等上述交接。
- Ruling：执行 inline，最终高风险 fresh-context Review；现有用户授权覆盖必要数据修复与 develop 集成，不重复审批。

- P0 source baseline: 202 contract/adapter/fusion tests passed in 7.24s. RB 9/24 MDS readonly current-day inputs: 345/23/12/7 bars in 1m/15m/30m/60m, all RB2701. Evidence outputs/p0-rb-current-inputs.json; no provider or mutation. This proves current day only, not historical prefix.
- P1 RED: new intraday identity/wire/open-gate tests 9 failed/4 passed (unsupported frequencies). Preserve legacy defaults via explicit frequency tuple.
- Ruling: the existing public v22 deferred list remains wire-stable; new recognized minute frequencies return a staged reason when explicitly audited, without implicitly expanding old capabilities.

- Baseline finding: consumer-only readiness test expects 7 sections/21 work; current baseline has 6 auxiliary + chart/reference = 8/24. Reproduced unchanged develop failure; correct test to assert exact actual supported section set, not remove cup_handle from production.

- P1 GREEN: 236 tests passed, including corrected pre-existing readiness assertion.
- P3 RED: Session-window selection 3 failed/1 passed. Reuse pure endpoint expansion shared with DatabaseCoverageSource; no separate resolver.
- Ruling: existing chart_before opaque cursor already encodes strict datetime bar_end and is snapshot-bound. Keep its public contract instead of introducing a parallel raw-datetime cursor; fix authoritative day viewport selection and verify same-day pagination.

- P2 initial full maintained RB window 2023-01-01..2026-09-24: all four MDS windows readable, counts 309345/20623/10764/6287. Physical prefix and warmup remain unproven at this point; source identity recorded in audit output. No provider or production mutation.
- P4: existing 30m scope reused; added explicit 1m-only scope and CLI. Prior test classifying 1m as unsupported updated after targeted RED proves new scope. 489 other data checks passed before updating obsolete expectation.
- P5a: two existing kernels pass eight minute batch/incremental/prefix invariants without formula changes. Three new coverage cases fail HOURLY-only guard; generalized explicit intraday membership without relaxing identity conflicts.

- P2 physical prefix audit: all RB four-period owners verified, no interruptions and no data gap requiring mutation. Complete input counts (including owner lifecycle prefixes): 60m 17695; 30m 30300; 15m 58055; 1m 870825. 1m read 82.589s. Evidence `outputs/newow-intraday-pilot-20260927/p2-rb-physical-prefix.json`.
- P5b in progress: build planner admits trend/oscillation four frequencies, main-rise not expanded. Input pinning only under explicit maintenance lease; exception exit discards snapshot. Compact intraday manifest binds full input hash/count and freshly verified Catalog-resolved immutable file content plus owner/calendar/session proof. No production mutation yet. Compact frozen inputs require rebuild on source/cutoff change; no unsafe append proof inferred from a hash.
- Capacity evidence: RB source proof 1m/15m/30m/60m took 0.196/0.151/0.195/0.177s, 140/280/280/280 partition dependencies respectively. This is validation cost, not full build/query performance acceptance.
- P5b-F core progress: 201/1000-trade tests pass; complete curve and summary independent of 200-record page; exit trading_day and stable reference revision added, source/model ordering unchanged. Persistence and UI integration still pending.
- P5b query fix: one scan of saved presentation facts aggregates availability by trading_day/owner/calculation identity, preserving WARMING and exact last status; allows initial holding prefix with saved snapshot's original window, rejects extending cutoff/through. Removes obsolete 10000 availability-point limit and repeated minute pagination; complete trade curve budget is explicit 100000, never truncated silently.
- Test environment ruling: shared .venv editable quant-core points at develop; ALL new verification must set `PYTHONPATH=packages/quant-core:services/quant-api` (add `.` for scripts). Earlier core results are preliminary; current fresh reruns use task core. A pre-existing daily V1 fixture was no longer a registered current stream; updated its identity AND calculation segment labels to accepted DAILY_V2, retaining pure-vs-persisted ID/Decimal checks. No legacy reader reopened.
- Verification: planner 25 passed; source/pin/persisted/fusion 21 passed; query/persisted 12 passed; expanded Newow/data targeted run ongoing. Ruff initial one E701 in new test fixed. Integration fixture with old daily V1 still needs current-policy update before final gate.

- Expanded task-core regression: 2487 passed, 1 skipped, 9 failed in 328.60s. Failures were schema rejection of additive fusion fields and a legacy weekly acceptance helper enumerating the newly enlarged enum. Fixed wire schema with optional excluded legacy fields and explicit legacy frequency scope; fresh focused rerun 156 passed in 5.30s. This run was before the latest presentation-facts implementation; that implementation separately passed 12 tests.
- Real RB 60m two base streams built in isolated PostgreSQL schema `newow_intraday_pilot_20260927`: full input 17706 events/stream (17695 Bars plus boundaries); plan 7.654s, build 18.923s, peak RSS 276480000 bytes; both completed. Independent query 200-record page 0.151s trend / 2.172s oscillation; summary 0.013s/0.015s, one-year CLOSED counts 147/52. Evidence `60m-build-capacity.json` and exact `60m-build-plan.json`; no production Reference revision or Runtime changed. Re-running build without reading its current state is prohibited; existing stream revisions are preserved in task isolation.
- Remaining before P6: other three actual builds and full query/curve capacity, persistence of independent fusion derived from the two saved source streams, minute candidate API/UI, boundary actual readback, fresh independent Review and develop integration. No P6 completion claim yet.

- Actual base matrix complete: 30m 30311 events/stream, build28.649s/RSS339214336; 15m58066, build51.926s/RSS470204416; 1m870836, build844.004s/RSS3232792576. All eight revisions published only in isolated schema; exact identities in frequency build reports. No data gaps or provider writes required.
- Boundary day readback: RB/AP/AU/SC/PD × four periods20 PASS; shared Session endpoints and derived OHLCV independently equal Canonical1m aggregation. Listing/owner/quality additional acceptance pending.
- Independent fusion builds complete60m/30m/15m. 60m actual readback complete559 CLOSED curve equals exact Decimal database sum266.1265757433902576238424598900; one-year152records,3.334s read. Readback initially failed due audit script default Decimal precision28; rerun at project60precision proves exact equality; no production calculation changed.
- 1m fusion planning hit explicit presentation100000point budget before mutation; use existing allowed200000 bounded source scan, retain full prefix and fail closed if still insufficient. No duplicate candidate created.
- P5c in progress: default-off RB-only candidate capabilityv23, four minutes plus D1/W1 background; publicv22 unchanged. API independent fusion cursor/cache identity, complete curve and one-year UI paging wired; tests40candidate+71reference/service pass. Browser/type/fullcapacity still pending.

- P6 ongoing, not accepted: fresh module regression `PYTHONPATH=.:packages/quant-core:services/quant-api ... pytest -q services/quant-api/tests/newow services/quant-api/tests/reference_trading`: 2467 passed / 46 skipped, 380.41s (before latest Review fixes). SQLite real Canonical/Catalog/MDS historical integration now 1 passed / 1 dedicated PostgreSQL env skip, 10.39s; old fixture upgraded to current D1 DAILY_V2 without injecting it into W1.
- Independent Review found shared snapshot proof missing in lightweight reads, compact source quality validation gap, mixed generation risk, incorrect minute label/night record date. Repairs add common freshly verified full-maintained Canonical proof at cutoff to persisted minute sections, avoid falsely claiming decoded counts, verify quality digest and partition dataset/month scope, compare source summary exact revision/seq, authoritative trading_day labels, and close minute main-rise candidate scope. Review requires final frozen re-review.
- Direct latest regression: 105 passed (persisted Newow/fusion/product service/storage), 5.40s. Earlier proof/service/storage 127 passed, 5.67s. Web 713 passed / 1 skipped, typecheck passed; focused current decision/product contract 56 passed, 0.71s. Production build and bundle topology passed (nonblocking existing dynamic import warning).
- Actual additional boundary readback: RB 2024-01-02 (year boundary/day-only after holiday), 2024-02-19 (Spring Festival return/day-only), 2026-09-21 (Friday night maps to Monday) × four periods = 12 PASS, endpoints and OHLCV exactly Canonical 1m aggregation. Existing RB/AP/AU/SC/PD 20 PASS retained. Newly listed sample and final P2 matrix remain pending.
- Actual default full 1m product capacity: chart 21.374s, reference 39.464s PASS (not browser acceptance). Entire maintained history retained; saved presentation has explicit existing 200000-item budget. Default Web 30s timeout was below actual cold reference cost, now scoped minute reference gets 60s cancellable timeout. Must verify browser under that bound.
- Actual Chrome candidate main chart root cause: chartMarkerTime handled only60m; new minutes collapsed to BusinessDay. RED reproduced, all4 UTC intraday mapping GREEN (23tests). Main chart/actions now visible; minute state and D1/W1 background identity explicitly separate. Candidate only localhost5175/8011 and isolated schema; formal Runtime unaffected. Browser 12-mode/pagination and P6 full exit still pending.

- P2 final actual readback PASS: four fresh source proof hashes unchanged; all twelve saved streams independently resolve exact generations; scoped data gap list empty, provider calls/Canonical writes/Catalog writes zero. Evidence `p2-final-pilot-readback.json`. Explicit pilot denominators 4 inputs/8 base/4 fusion/12 modes; no full expansion claim.
- Listing boundary actual readback PD first maintained product day2025-11-27×four periods4PASS (225/15/8/5), total real aggregate boundary36PASS. Physical PD2612 listing is a different date; not substituted for product listing.
- Final module regression before capacity-index/cache repairs:2472PASS/46SKIP,387.71s; Web718PASS/1SKIP,7.608s; build/type/topologyPASS. Subsequent focused query/cache/candidate137PASS; source-quality27PASS; card scientific/sparse/full-focus43PASS plus targeted panel20PASS/typecheckPASS.
- Independent Review found UI curve selection outside near-year pages and scientific Decimal card display; repaired. Focused card uses original full reference facts under theory-mode; one-year pagination remains unchanged. Reviewer 2000 seeded old/new Hint matching differential cases all equivalent.
- Real 1m UI capacity failures required repair: full Hint×trade scan40–44s→indexed interval lookup26.751s; separate bounded persisted minute admission avoids background starvation. Whole reference wire graph measured80537441bytes, above old32MiB cache entry budget; default-off RB candidate cache capped256MiB/entry and512MiB total. Fusion reuses exact base saved generation and fresh source proof, no public schema widening. Final browser acceptance remains pending, not inferred from repairs.
- Actual running cancellation PASS: presentation scan cancels after8batches/0.207s; readonly rollback and saved generation unchanged (`running-cancel-readback.json`). Pre-read cancellation0.000064s. No official service/Scope/Runtime changed.

## 最终冻结验证与 P6 出口

实现冻结6264c24df1063514acce150ccb4468134e82ee7d；候选fixture修正635bbea4a；合并最新develop@afde169a4后的代码候选10d40faa05badc04c86cefb65c53525a11dba4fb。独立Astra Review两次给出“无未解决Confirmed Issue，允许集成develop”，补审确认6264到10d未改变分钟业务源码。发布版本仍1.10.38，正式开关日周未变，RB四分钟候选默认关闭。最终证据提交只更新文档/验收输出，不改业务源码。

### 实际测试（重叠组不相加）

- `PYTHONPATH=.:packages/quant-core:services/quant-api services/quant-api/.venv/bin/pytest -q services/quant-api/tests/newow services/quant-api/tests/reference_trading`：2478PASS/46SKIP，365.89s（728冻结；6264补丁针对16PASS，独立Review在6264定向481PASS、历史/checkpoint/storage124PASS/1SKIP）。
- 合并候选 `PYTHONPATH=.:packages/quant-core:services/quant-api services/quant-api/.venv/bin/pytest -q services/quant-api/tests/reference_trading/test_newow_fusion_historical.py services/quant-api/tests/newow/test_product_snapshot_cache.py services/quant-api/tests/newow/test_market_newow_product_api.py tests/engineering/test_canonical_consistency.py`：98PASS，3.90s。
- 合并候选 `cd apps/quant-web && pnpm test`：719PASS/1SKIP，7318ms；`pnpm build`含vue-tsc/topology通过，562ms构建。现有无效dynamic-import警告单列。
- `PLAYWRIGHT_CANDIDATE_PREVIEW=1 pnpm test:e2e e2e/candidate-preview.spec.mjs`：3PASS，3.9s；已退役banner断言改为当前App身份gate，仍验证错身份不请求、固定截点、无live订阅和管理路径拒绝。
- `pnpm test:e2e e2e/newow-product.spec.mjs --grep 'late old chart response|shared-bar conflict|429 is bounded|auxiliary cache, applicability|curve window changes|tokenless chart|deferred explanation stays'`：候选7FAIL；相同命令在未修改develop@afde169a4逐项同样7FAIL（CDV2请求、记录窗口、旧截图与OPEN记录断言漂移），不声明此旧套件通过，下一轮测试维护处理。
- 实际SQLite Canonical/Catalog/MDS历史集成1PASS/1专用PostgreSQL环境SKIP；真实PostgreSQL12资产构建与独立读回另外有证据。缺隔离migration环境的46项skip没有连接生产绕过。
- 变更Python Ruff、tracked和全部候选outputs secret scan均通过，0secret finding；diff check通过。本轮Newow OpenSpec有效；全spec9PASS/1FAIL，reference-trading两个Requirement在Requirements段外，已在未修改develop复现，未改该spec。

### 数据身份与操作范围

Canonical根 `/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical`；private配置仅程序安全加载，config hash c9df3ef2a1a9f4b856b0fdc7a0839eaf9040fcad0eb56b6adc573b819c4ab746。冻结as_of=`2026-09-24T07:00:00.000001+00:00`，维护窗口2023-01-01..2026-09-24。四source proof、所有physical prefix以及12个stream/revision/seq精确身份见 `outputs/newow-intraday-pilot-20260927/p2-final-pilot-readback.json` 与构建plan；合并候选再次独立读回4/12PASS，gap=0。没有provider调用、Canonical或Market Catalog写入，不扩大60品种。保存资产仅使用隔离PostgreSQL schema `newow_intraday_pilot_20260927`；没有迁移或生产Reference指针切换。

### 实际验收与容量

Chrome12模式逐项主图、完整曲线、近一年记录PASS，观察SHA逐项保留于 `browser-12-mode-acceptance.json`，不会将6264现场证据改写成10d现场SHA。10d补验15m融合/60m趋势/60m震荡，独立Review确认分钟实现未变；10d的1m HTTP冷读/融合/第二页另外绑定最终SHA。页面年化展示仅用于验收口径，不是因果收益、模型账户收益或盈利结论。

| 周期 | 趋势 | 震荡 | 独立融合 |
|---|---|---|---|
|1m|106.6%|98.5%|129.7%|
|15m|54.1%|33.3%|59.2%|
|30m|43.8%|27.8%|49.1%|
|60m|36.3%|20.7%|41.6%|

48辅助HTTP读取PASS，分钟杯柄NOT_APPLICABLE；36实际Session/OHLCV独立聚合边界PASS（RB/AP/AU/SC/PD，年界/假日/周五夜盘/首维护日），PD上市8策略读回PASS，趋势首Bar按原合同ready、震荡真实warming且短30/60m不虚报ready。metadata缺失、缺分钟、短尾、owner重入、来源修订等反例由定向离线测试和独立Review覆盖，无人为改Canonical制造反例。

同日chart50×2=100无重，同snapshot/严格cursor；1m融合真实第二页继续到09-22、年化129.7%不受列表长度改变。分钟1m→15m→60m切换清除旧事实，最终显示60m；后台D1/W1独立角色显示，分钟不参与评分。冷/热API正常容量及表格读取完整历史，不缩prefix/统计。超队列实际429，显式重试恢复60m融合41.6%，未自动无限重试。

全1m构建844.004s/RSS3232792576B；融合构建324.37s/RSS约2.358GB。正常2请求并发9.635/4.455s，API采样RSS1043185664B；实测HTTP断开0.304s，后续保存读取47.111s。逐批presentation取消0.207s、generation不变；SQL/hydrate不保证即时取消，不能将这项证据表述为全链即时取消。明确保留60s客户端请求/50s等待与1running+2waiting预算，首品种可验收，不外推60品种容量。

### 第二轮与回滚

P7全品种精确盘点/维护/资产构建及240输入/480基础/240融合逐项验收；必要冷读与并发容量继续验证，完善旧fixture。P8发布/Runtime、P9启用观察、R1/R2因果执行/OOS另行交办。当前没有通知、订单、策略晋升或正式consumer切换。默认关闭候选可直接停用；源码回滚采用revert，不删除Canonical或修改正式指针；隔离schema保留审计，清理需精确对象与后续任务授权。

- 最终合并候选数据回归：`PYTHONPATH=.:packages/quant-core:services/quant-api services/quant-api/.venv/bin/pytest -q services/quant-api/tests/data_foundation/test_aggregation.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/data_foundation/test_session_anchor_repair.py services/quant-api/tests/data_foundation/test_historical_data_manager.py services/quant-api/tests/data_foundation/test_daily_maintenance.py services/quant-api/tests/data_foundation/test_newow_readiness_cli.py services/quant-api/tests/data_foundation/test_storage.py`：352PASS，25.23s。
- 10d最终1m HTTP：冷基础33.148s、融合20.745s、第二页17.540s，同一snapshot，完整基础曲线33169；没有把旧6264耗时改成10d结果。
