# Weekly Audit and Page Quality Fixes Implementation Plan

> **For Codex:** Execute this plan in the current isolated worktree. Follow TDD for each behavior change. Do not install/reload launchd, run the real weekly audit, call RQData, or mutate Canonical/Catalog/production state.

**Goal:** Fix page-local source-quality handling, add one-attempt-per-week scheduled audit catch-up, and expose an installation-aware `missed` health state.

**Architecture:** Keep strict range reads unchanged. Add page-only quality-aware endpoint selection. Add a scheduled wrapper around the existing weekly audit under the same status lock, with a stable Shanghai Saturday 09:00 schedule identity. Add a separate weekly activation marker and derive health from marker + schedule identity + validated status.

**Tech Stack:** Python 3, SQLAlchemy, pytest, launchd plist, Bash installer, FastAPI/Pydantic schemas, Vue/TypeScript/Vitest.

---

## Task 1: Reproduce and fix physical D1 page-local quality behavior

**Files:**
- Modify: `services/quant-api/tests/data_foundation/test_market_pagination.py`
- Modify: `services/quant-api/app/market_data/market_data_service.py`

1. Add failing tests for a physical D1 page where an old quality fact is:
   - in the same month but outside `limit`;
   - in an older month outside `limit`;
   - inside the current page after moving the cursor.
2. Run only the new tests and confirm the old implementation fails for the window-external cases.
3. Add a page-only partition decoder returning validated bars and quality facts without weakening `_partition_bars` or `_read_physical`.
4. Select from a descending combined endpoint stream. A quality endpoint inside the visible page raises `PRICE_UNAVAILABLE`; a page-external endpoint may prove `has_more_before` without blocking.
5. Run the new tests plus existing physical pagination tests.

## Task 2: Fix actual-dominant D1 quality ownership and page boundaries

**Files:**
- Modify: `services/quant-api/tests/data_foundation/test_market_pagination.py`
- Modify: `services/quant-api/app/market_data/market_data_service.py`

1. Add failing tests for:
   - old owner quality outside the latest page;
   - owner quality entering a later page;
   - non-owner contract quality on the same trading day;
   - correct `has_more_before` when the only older endpoint is a quality fact.
2. Confirm failures against the old whole-partition rejection.
3. Apply existing D1 owner resolution to both bars and quality facts before page-window selection.
4. Preserve W1 owner selection, calendar caching, duplicate identity checks and `_actual_page_result` validation.
5. Run all market pagination and Catalog/MarketDataService quality tests.

## Task 3: Define weekly schedule identity and one-attempt gate

**Files:**
- Modify: `services/quant-api/tests/data_foundation/test_weekly_audit.py`
- Modify: `services/quant-api/tests/data_foundation/test_weekly_audit_ownership.py`
- Modify: `services/quant-api/app/market_data/weekly_audit.py`

1. Add failing tests for Shanghai schedule identity before/at/after Saturday 09:00 and across a week boundary.
2. Add failing tests proving:
   - first due scheduled invocation audits once;
   - later same-week invocation does not call the manager or overwrite status;
   - `failed` and `skipped_busy` count as attempts;
   - manual invocation remains available;
   - concurrent ownership remains fail-closed.
3. Add `trigger` and `scheduled_for` to status schema while retaining bounded validation of schema v1 as historical evidence.
4. Implement the scheduled gate inside the status-writer lock and reuse `_run_owned_audit` for the one real attempt.
5. Run weekly audit unit and ownership tests.

## Task 4: Route launchd through the scheduled entrypoint

**Files:**
- Modify: `services/quant-api/tests/test_runtime_entry.py`
- Modify: `services/quant-api/app/runtime_entry.py`
- Modify: `scripts/ops/macos/run-local-service.sh`
- Modify: `deploy/launchd/com.guiyi.quant-weekly-audit.plist.template`
- Modify: `tests/engineering/test_market_runtime_launchd.py`

1. Add failing runtime-entry tests for `weekly-audit-scheduled`, including `not_due` and `already_attempted` successful no-op exits.
2. Add failing plist test requiring Saturday hourly triggers from 09:00 through 23:00, no `RunAtLoad/KeepAlive`, and the scheduled command.
3. Implement the internal scheduled command without exposing a new data-writing public CLI.
4. Update the launcher and plist.
5. Run runtime-entry and launchd packaging tests.

## Task 5: Add activation-aware `disabled/not_run/missed` health

**Files:**
- Modify: `services/quant-api/tests/data_foundation/test_weekly_audit.py`
- Modify: `services/quant-api/tests/data_foundation/test_weekly_audit_ownership.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`
- Modify: `services/quant-api/app/market_data/weekly_audit.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`

1. Add failing health tests for disabled, pre-due not_run, post-due missed, current-week attempt and prior-week status precedence.
2. Add a weekly activation-marker reader with the same fail-closed fixed-content rules as Market/Alert markers and an injectable test override.
3. Extend `weekly_audit_health` with configured-enabled and schedule identity inputs.
4. Ensure weekly state remains diagnostic-only and never changes top-level operational health.
5. Run weekly and runtime health tests.

## Task 6: Make weekly activation installation atomic

**Files:**
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `tests/engineering/test_market_runtime_launchd.py`

1. Add failing installer tests proving render-only does not write the marker, confirm-weekly writes it, and a failed load restores its prior state.
2. Add `weekly-audit-enabled` to the existing activation marker transaction rather than creating a second recovery path.
3. Preserve the rule that weekly install does not replace the shared launcher and does not kickstart other services.
4. Run launchd packaging tests.

## Task 7: Update public status presentation and contracts

**Files:**
- Modify: `apps/quant-web/src/api/runtime.ts`
- Modify: `apps/quant-web/src/utils/runtimePresentation.ts`
- Modify: `apps/quant-web/tests/runtimeStatus.test.ts`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: relevant shell/status tests found by `rg`

1. Add failing frontend tests for `disabled` and warning-tone `missed` labels.
2. Extend Python/TypeScript status unions and bounded shell whitelist.
3. Keep `not_run`, `running` and `skipped_busy` neutral; make `missed` warning.
4. Run Vitest status tests and relevant Python/shell tests.

## Task 8: Update operating documentation

**Files:**
- Modify: `deploy/README.md`
- Modify: `docs/DATA_CENTER.md` if it contains the active weekly schedule contract

1. Document Saturday bounded probes, application-level one-attempt semantics, marker states, and the external deployment/run Gate.
2. Explicitly state that `missed` does not trigger repair or notification.
3. Run reference searches and `git diff --check`.

## Task 9: Verification and review

1. Run focused suites:
   - market pagination and Catalog/MarketDataService tests;
   - weekly audit, ownership and PostgreSQL readonly tests;
   - runtime entry/health tests;
   - launchd engineering tests;
   - frontend runtime presentation tests.
2. Run the broader quant-api data-foundation slice selected from `TESTING.md` if focused suites pass.
3. Inspect `git diff --check`, changed-file diff, secret scan, and confirm no unrelated user files are present.
4. Perform a fresh self-review using the repository review categories because sub-agent delegation is disabled by system instruction.
5. Fix confirmed issues and rerun affected tests.
6. Commit implementation, push the task branch, and integrate to `develop` only if tests/review pass and the develop worktree can be updated without touching unrelated dirty changes. Otherwise report the exact integration blocker.
7. Do not publish main/tag/release, promote Runtime, reload LaunchAgent, or run the actual weekly audit.
