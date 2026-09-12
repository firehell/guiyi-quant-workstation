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

## Fix round 1 — independent review findings

- Fix implementation commit: `9951be5ae9f495a5e9475ab5a98cf4852c974803` (`fix(runtime): harden stopped-terminal authority recovery`).
- Status: all six review findings addressed in code/tests/contracts; fresh affected verification passed. Independent re-review and controller integration remain pending.
- No push, develop integration, provider/data write, service load/unload, release, Runtime switch/promotion, notification, or Package B/C/D operation was performed.

### Finding evidence and resolution

1. **Trusted HOME:** confirmed. `run-local-service.sh` now pins the caller HOME before sourcing runtime configuration and restores it in the preflight process. The Python authority independently resolves the account home from the uid via `pwd`, passes it through installed-plist and `RuntimeDataBinding` validation, and no longer uses environment-sensitive `Path.home()` inside process identity checks. Tests cover retained installed plist + stopped writer with an overridden `HOME`, including a real binding.
2. **Independent stopped-terminal SHA:** confirmed. The stopped resolver now requires a caller/receipt-provided 64-hex expected SHA and compares it with the exact current bytes before constructing the binding. Deployment preflight receives `GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256` from outside the sourced runtime environment; missing, malformed, mismatched, or pre-binding replacement all fail closed. No field-specific one-off SHA is embedded in generic code.
3. **Genuine first install:** confirmed. First-install authority now requires both no installed plist and no candidate status path. Promotion does not read status in this mode. Residual passed and interrupted files both block authority resolution, and the public promotion characterization proves no candidate status read occurs.
4. **Partial-install recovery/state ownership:** confirmed. Before market mutation, the installer captures a bounded preimage of the shared launcher, log rotator, after-market/Live plists, and exact loaded/absent states. After reverse candidate cleanup it restores and byte/state-verifies that preimage, never copies or rewrites status, and remains blocked pending a fresh preflight/install intent. A stateful fake launchd test injects the first Live failure, verifies the old stopped-writer/loaded-Live ownership is restored, then proves a second preflight/install is reachable.
5. **launchctl error classification:** confirmed. Installer state checks require a readable user domain plus exact not-found output; permission/domain/other command failures are unknown. Exact not-found is accepted independently of its nonzero exit code. Cleanup unknown retains the activation marker and reports blocked instead of stopped; restoration unknown does the same.
6. **Real binding through public E/F:** confirmed. New tests construct a real schema-v5 `RuntimeDataBinding` with exact SHA, installed five-plist/config identity, four running services, explicitly absent writer, fresh Live/Alert heartbeats, and identity rechecks. Public `run_daily_recovery` and `run_current_day_metadata_recovery` accept the stopped terminal; writer reappearance and launchd read errors fail before the fake provider/manager result for both entry points.

### RED → GREEN evidence

The behavior regressions were encoded before implementation:

- The selected authority tests initially reported `5 failed`: environment HOME displaced retained ownership; missing expected SHA was accepted; replacement before binding was accepted; and both first-install residue cases were accepted.
- The cleanup error test initially reported `1 failed` because a nonzero permission result was treated as absence and the marker was removed.
- The stateful second-preflight test initially reported `1 failed` because candidate plists/launcher replaced the old authority and no recovery path remained.
- The real-binding/public E/F addition closes a review coverage gap rather than asserting a separate pre-existing production failure; its first focused run after the shared authority fix was `7 passed, 99 deselected`.

After the fixes, the focused authority/promotion/real-binding/launchd group reported:

```text
203 passed in 28.77s
```

### Fresh final verification

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
# 428 passed in 74.45s

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
# 21 passed, 1 deselected in 0.93s

openspec validate --specs --strict --no-interactive
# 9 passed, 0 failed

python3 scripts/engineering/secret_scan.py --json
# finding_count=0, status=passed

bash -n scripts/ops/macos/install-local-services.sh \
  scripts/ops/macos/run-local-service.sh
git diff --check
# both exit 0
```

The same brief-authorized frontend evidence remains reusable because frontend source/config/lock remain unchanged from `24ab72601ea8a7da4c92bd4379c885060485c8f8`.

### Fix-round self-review and residual risks

- Normal closeout remains the strict five-loaded-service path; stopped authority is confined to the terminal recovery/maintenance/preflight seam.
- Promotion still has only the four existing predicates; stopped-terminal validity alone cannot pass it.
- Compatible proof remains `recovery_ready=false` with published-tag, immutable-root, and separate execution-intent blockers.
- The installer recovery preimage is deliberately bounded to the four changed files and two market label states; status is never copied or restored. Any cleanup/restore uncertainty retains the marker and requires inspection rather than claiming recovery.
- All evidence is fixture/repository verification. Field precheck, Packages B/C, release, installation, Runtime promotion, and natural-run acceptance remain separate external Gates.

Fix-round conclusion remains `允许进入独立 Review`; integration and every external Gate remain unauthorized here.
