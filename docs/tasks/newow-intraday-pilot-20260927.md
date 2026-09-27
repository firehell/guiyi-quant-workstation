# 分钟牛哇 P0–P6 执行记录

计划：docs/superpowers/plans/2026-09-19-newow-intraday-roadmap.md

## 目标与边界

RB 首品种四周期趋势/震荡/双策略历史闭环，必要边界数据维护及读回、测试、容量、真实浏览器、独立 Review 后集成 develop。排除 P7 全量、release/Runtime/Live/通知/订单。

## 基线

develop b48ffe0e504ee3d0850a2e75c2820dca26f9aefe；用户计划修改已复制，用户 outputs 未动。独立 codex/newow-intraday-pilot worktree。正式根仍为 v1.10.38，不修改。

## 进度与裁定

- P0–P5c 已实现并进入最终回归；P2 最终 source/generation 读回通过。
- P6 仍进行中：1m 最终页面及队列/取消验收、冻结独立复审和 develop 集成尚未完成。
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
