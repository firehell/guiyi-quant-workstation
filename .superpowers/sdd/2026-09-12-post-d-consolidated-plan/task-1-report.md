# Task 1 report — unified engineering closeout (Package A)

## Result

- Status: `CODE_COMPLETE`, `TEST_COMPLETE`, self-review complete; controller independent review and integration remain pending.
- Implementation commit: `c0e41f0ef7de64784107aa3f7a65c8f3cef26893` (`fix(runtime): authorize exact stopped-terminal state`).
- Approved plan SHA-256 rechecked: `e0ff45a0c2e308cd60efa3e01ae2044a0eca6f240a26c991f724b51241b3187b`.
- No push, develop integration, release, Runtime promotion, provider access, production data/status mutation, service load/unload, notification, or Package B/C/D operation was performed.

## Design and files changed

The change adds `runtime_status_authority.py` as the single Python owner resolver for loaded, exact stopped-terminal, and genuine first-install states. `RuntimeDataBinding` remains the shared E/F and compatible-recovery identity gate. Promotion preflight now obtains its default status path only through that authority; shell and sourced runtime environment cannot inject a competing status owner.

- Runtime authority and identity: `runtime_status_authority.py`, `closeout_binding.py`, `captured_recovery_runtime.py`, `after_market_closeout.py`.
- Promotion and launchd entry points: `runtime_promotion.py`, `run-local-service.sh`, `install-local-services.sh`.
- Tests: closeout binding, promotion, authority, captured Runtime, Market/Alert launchd engineering tests.
- Contracts: `historical-data-maintenance` OpenSpec, `docs/DATA_CENTER.md`, `deploy/README.md`, and `TESTING.md`.

Normal closeout still calls the strict five-service identity verifier. Only a schema-v5 interrupted terminal creates the stopped branch. That branch requires the installed after-market plist, exact immutable release, explicit label absence, exact other-four-service identities, pinned sources/processes/status, and fresh Live/Alert recovery-guard heartbeats. Every relevant use rechecks the pinned identity; launchd errors are never interpreted as absence.

Market installation now establishes the new idle after-market writer before starting Live. A partial failure stops attempted candidate labels in reverse order and restores the candidate activation marker before-image, then explicitly reports the install as blocked. Shared launcher, installed plists, and status remain documented as non-transactional; no automatic retry or old-writer restoration is claimed.

## RED evidence

The tests were added or changed before the corresponding implementation:

- Stopped binding fixture initially failed because unconditional after-market process parsing received an absent label.
- Promotion authority tests initially failed because `run_market_runtime_promotion_preflight` had no authority seam/recheck.
- Shell delegation initially failed because shell still called `launchctl` and selected the status path itself.
- Install-order test showed `com.guiyi.quant-live` before `com.guiyi.quant-after-market`.
- Partial-install injection initially lacked the required explicit blocked/recovery message.
- The first combined plan suite exposed one stale engineering test that still injected failure into after-market as the second label; it was corrected to fail Live and assert reverse cleanup `live -> after-market`.

Baseline before implementation:

```text
focused Package A baseline: 402 passed in 76.79s
```

## Final GREEN verification

All commands ran from the task worktree with no production endpoints or mutation.

```bash
UV_CACHE_DIR=/private/tmp/guiyi-package-a-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_closeout_binding.py \
  services/quant-api/tests/data_foundation/test_after_market_closeout.py \
  services/quant-api/tests/data_foundation/test_current_day_metadata_recovery.py \
  services/quant-api/tests/data_foundation/test_daily_recovery_cli.py \
  services/quant-api/tests/data_foundation/test_daily_maintenance.py \
  services/quant-api/tests/data_foundation/test_runtime_promotion.py \
  services/quant-api/tests/data_foundation/test_runtime_status_authority.py \
  services/quant-api/tests/test_captured_recovery_runtime.py \
  tests/engineering/test_market_runtime_launchd.py \
  tests/engineering/test_alert_runtime_launchd.py
# 413 passed in 66.18s

UV_CACHE_DIR=/private/tmp/guiyi-package-a-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases \
  --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
# Success: no issues found in 159 source files

UV_CACHE_DIR=/private/tmp/guiyi-package-a-uv-cache \
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests \
  packages/quant-core/guiyi_quant tests/engineering
# All checks passed!

UV_CACHE_DIR=/private/tmp/guiyi-package-a-uv-cache \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py \
  -k 'not alert_rule_codes_have_one_production_registry_per_language'
# 21 passed, 1 deselected in 0.86s

openspec validate --specs --strict --no-interactive
# 9 passed, 0 failed

python3 scripts/engineering/secret_scan.py --json
# finding_count=0, status=passed

git diff --check
# exit 0
```

The one deselected canonical-consistency test shells out to frontend `pnpm` and failed only because this isolated worktree has no frontend dependency installation. `git diff --quiet 24ab72601ea8a7da4c92bd4379c885060485c8f8 -- apps/quant-web pnpm-lock.yaml package.json` returned zero (`FRONTEND_UNCHANGED`), so the brief-authorized existing frontend evidence is reused: 543 passed / 1 skipped and build exit 0.

## Required-contract evidence

1. One Python path: recovery/maintenance continue through `RuntimeDataBinding`; deployment status lookup uses `resolve_market_runtime_status_authority`; shell no longer parses terminal JSON or selects a supervised root.
2. Exact stopped branch: schema v5 interrupted terminal, status hash/bytes, installed five plists/config, release markers/tag/root/commit, explicit writer absence, other four processes, and both heartbeats are checked.
3. Fail closed: exact not-found parsing is separate from domain/permission/error; writer reappearance and status/source/process/config/heartbeat drift have negative tests.
4. Normal closeout: `verify_closeout_identity` remains strict for all five services, with after-market loaded and idle.
5. Promotion: the four independent pass reasons remain unchanged; v5 interruption alone still blocks after session start.
6. Compatible proof: identity and heartbeats are checked before and after candidate inspection; `recovery_ready=false` and published-tag/immutable-root/execution-intent blockers remain unchanged.
7. Ownership/install: loaded, stopped-terminal, and genuine first-install ownership have direct tests. Install order is after-market then Live. Partial failure is injected and leaves candidate labels stopped/marker restored with explicit blocked recovery semantics; transactional rollback is not claimed.
8. Audit identity: the old plan/D receipt and terminal remain untouched. The consolidated plan hash and controller ledger remain the authority for remaining work.
9. Contracts/tests: OpenSpec, Data Center, deployment guide, test guide, implementation, and regression tests were updated together.

## Self-review

Fixed point `24ab72601ea8a7da4c92bd4379c885060485c8f8` was reviewed on two axes. Standards review found no repository-rule, secret, unrelated-scope, or code-smell blocker. Spec review found no missing Package A requirement in the implemented path. The explicit partial-install result is deliberately `blocked`, which is one of the approved outcomes; therefore this report does not claim the deployment package can autonomously recover after a partial install. Independent controller review is still required before integration.

## Remaining risks and Gates

- This is fixture/test evidence only. The exact field terminal SHA, four live services, heartbeat freshness, maintenance lock, and operational 60 still require a fresh read-only field precheck by the controller before any Package B/C or deployment action.
- A stopped terminal does not satisfy promotion. Snapshot/session/after-market/non-trading predicates remain independent.
- A partial real install requires a separately approved compatible-root recovery attempt after read-only inspection; the installer does not retry or transactionally restore shared launcher/plist/status.
- Exact release/tag, immutable recovery root, independent review, develop integration, release, and Runtime promotion remain separate Gates.
- Old v1.10.5 writer must remain stopped and must never be restored.

## Handoff conclusion

`允许进入独立 Review`。独立 Review 通过后，controller may integrate the implementation and report commits into develop; no external operation is authorized by this report.
