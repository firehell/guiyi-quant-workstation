# SuBing D1 Quality Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned D1 quality endpoint union, stable calculation segments, re-warmup, interrupted reference trades, and explicit Web presentation without changing strict readers or non-D1 SuBing behavior.

**Architecture:** The existing Canonical Parquet plus Catalog JSON quality field remains the sole Market Fact authority. A typed `NonpositiveCloseFact` extends the existing source-quality union; ordinary readers reject every quality fact, existing Newow readers accept only their existing `PriceUnavailableFact`, and a new SuBing D1 opt-in path accepts the approved union. SuBing D1 constructs stable calculation segments from the immutable owner start and preceding break identity, then projects the unchanged kernel with Reference v2 semantics.

**Tech Stack:** Python 3.12, dataclasses, SQLAlchemy/PostgreSQL Catalog, PyArrow Canonical storage, FastAPI/Pydantic, Vue 3/TypeScript, Node test runner, Playwright.

**Spec:** `docs/tasks/subing-d1-quality-segmentation/proposal.md`

## Global Constraints

- Fixed acceptance cutoff is `2026-09-18T18:30:00+08:00`.
- No provider request, Canonical/production DB/Redis mutation, migration, Runtime/Scope/notification change, release, tag, or main merge in this execution.
- Unknown endpoints, duplicate identities, Session/Map/owner conflicts, and unsupported classifications fail closed.
- `subing_ths_15m_v3`, Alert Rule/Event, 15m/30m/60m historical reference, formulas, and seeds remain unchanged.
- Bar states are `WARMING` for 1–33, `INDICATOR_READY_CROSS_UNEVALUABLE` for 34, and `CROSS_EVALUATED` for 35+.
- A quality interruption never creates OHLC, an exit, a return, or current floating PnL.
- Segment identity must remain unchanged when future owner mappings or bars are appended.

## Review Focus

- A future mapping append must not rename an existing owner/calculation segment; Task 2 adds a prefix-invariance test.
- Mixed valid and typed-break endpoints in OI/PF must prove exact union coverage; Task 1 adds storage/MDS tests.
- A break after an open trade must create `DATA_INTERRUPTED` with no synthetic exit/return/mark; Task 2 adds projector tests.
- A break at rollover must retain separate quality and rollover identities without closing a prior trade twice; Task 2 adds boundary tests.
- Non-D1 and strict consumers must continue rejecting quality-bearing partitions; Tasks 1 and 3 add regression tests.

---

### Task 1: Market Fact union, immutable publication, and opt-in MDS seam

**Files:**
- Modify: `services/quant-api/app/market_data/source_quality.py`
- Modify: `services/quant-api/app/market_data/storage.py`
- Modify: `services/quant-api/app/market_data/catalog.py`
- Modify: `services/quant-api/app/market_data/market_data_service.py`
- Test: `services/quant-api/tests/data_foundation/test_catalog_and_service.py`
- Test: `services/quant-api/tests/data_foundation/test_historical_data_manager.py`

**Interfaces:**
- Produces: `SourceQualityFact`, `NonpositiveCloseFact`, `source_quality_fact_from_record`, and `MarketDataService.query_contract_replay_quality_union(...)`.
- Preserves: `read_physical_daily_quality(...)` accepts only existing `PriceUnavailableFact` and rejects the new type.

- [ ] Write tests for exact classification, backward-compatible old records, mixed valid/break union coverage, unsupported strict consumer rejection, duplicate endpoints, and all-zero classification that is never `NO_TRADE`.
- [ ] Run the focused tests and observe failures caused by the missing new type/seam.
- [ ] Implement the minimum typed union and storage/Catalog serialization while preserving existing record hashes.
- [ ] Implement the explicit SuBing D1 MDS union seam and keep ordinary and Newow paths unchanged.
- [ ] Run focused and data-foundation regression tests.

### Task 2: Stable D1 calculation segments and Reference v2

**Files:**
- Modify: `packages/quant-core/guiyi_quant/subing_reference.py`
- Modify: `services/quant-api/app/market_data/subing_reference.py`
- Test: `services/quant-api/tests/test_subing_reference_projection.py`
- Test: `services/quant-api/tests/test_subing_reference_service.py`
- Test: `services/quant-api/tests/test_subing_ths_kernel.py`

**Interfaces:**
- Produces: D1 `ReferenceSegment` values with `owner_segment_id`, stable `calculation_segment_id`, quality interruption metadata, and Reference model `subing_reference_reverse_close_quality_segment_v2`.
- Segment identity inputs: formula frequency, symbol, physical contract, authoritative owner start, quality policy version, preceding break timestamp/classification/evidence hash; owner end and future global revisions are excluded.

- [ ] Write failing tests for 1–33/34/35 states, break reset, prefix/batch parity, future append invariance, interrupted open trade, break/rollover interaction, and unchanged 15m golden identities.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement D1-only segment construction and Reference v2 projection; retain v1 for other frequencies.
- [ ] Run projector, service, kernel, and reference API regressions.

### Task 3: API and Web partial/warming/break presentation

**Files:**
- Modify: `services/quant-api/app/schemas/subing_reference.py`
- Modify: `services/quant-api/app/api/market_subing_reference.py`
- Modify: `apps/quant-web/src/types/subingReference.ts`
- Modify: `apps/quant-web/src/utils/subingReference.ts`
- Modify: `apps/quant-web/src/components/market/detail/subing/SubingReferencePanel.vue`
- Modify: `apps/quant-web/src/components/market/detail/subing/SubingDetailWorkspace.vue`
- Test: `services/quant-api/tests/test_subing_reference_api.py`
- Test: `apps/quant-web/tests/subingReference.test.ts`
- Test: `apps/quant-web/e2e/subing-reference.spec.mjs`

**Interfaces:**
- Produces: D1 response fields `quality_policy_version`, `coverage_intervals`, `quality_interruptions`, `calculation_segment_id`, three-state `research_status`, and separated interruption counts.
- Preserves: v1 response shape/identity for 15m/30m/60m.

- [ ] Write API and Web tests for exact response validation, three-state copy, partial coverage, break display, DATA_INTERRUPTED details, and no fabricated return/current mark.
- [ ] Run tests and observe schema/normalizer/presentation failures.
- [ ] Implement version-aware API serialization and fail-closed Web normalization/presentation.
- [ ] Run Web unit tests, production build/typecheck, and fixture E2E.

### Task 4: Exact non-applying production plan and isolated fixed-cutoff acceptance

**Files:**
- Create: `services/quant-api/app/market_data/subing_d1_quality_plan.py`
- Create: `scripts/subing_d1_quality_plan.py`
- Create: `services/quant-api/tests/newow/test_subing_d1_quality_plan.py`
- Create: `outputs/subing-four-period-readiness-20260918/d1-quality-segmentation-production-plan.json`
- Create: `outputs/subing-four-period-readiness-20260918/d1-quality-segmentation-candidate-acceptance.json`

**Interfaces:**
- Produces: deterministic plan hash bound to target partition identities, old URI/content/quality hashes, source evidence hashes, policy/schema/reference versions, maintenance lock, atomic partition commit, idempotent readback, recovery rules, budget, and excluded targets.
- The script defaults to read-only prepare and has no provider client. Any future apply requires an exact plan hash plus production authorization and is not executed here.

- [ ] Write failing deterministic-plan tests including OI/PF mixed partitions, excluded 40 targets, stale pointer/hash rejection, zero provider budget, and idempotent already-applied readback.
- [ ] Implement pure plan generation and validation.
- [ ] Run it against read-only Catalog/evidence and an isolated candidate Canonical/Catalog copy.
- [ ] Re-run 17-product D1 and 240-combination data/API/page acceptance at the fixed cutoff; record production as unchanged and candidate results separately.

### Task 5: Canonical contract, verification, Review, and delivery

**Files:**
- Modify: `openspec/specs/subing-ths-alert/spec.md`
- Modify: `openspec/specs/market-series-query/spec.md`
- Modify: `docs/DATA_CENTER.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/tasks/subing-d1-quality-segmentation/proposal.md`
- Modify: `outputs/subing-four-period-readiness-20260918/README.md`
- Create: `docs/tasks/subing-d1-quality-segmentation/PRODUCTION_APPROVAL_PACKET.md`

- [ ] Freeze the accepted D1-only semantic/version contract and corrected stable segment identity.
- [ ] Run targeted tests, module tests, full backend tests, Web tests/build/typecheck, OpenSpec validation, secret scan, and diff check.
- [ ] Obtain independent Review for data timing, segment identity, publication atomicity/idempotency, API/Web semantics, and non-D1 regressions; fix every confirmed issue and re-run affected checks.
- [ ] Commit and push the candidate branch; create or update the draft PR without integrating develop unless every current Gate is satisfied.
- [ ] Produce one exact production approval packet; do not execute its controlled actions.
