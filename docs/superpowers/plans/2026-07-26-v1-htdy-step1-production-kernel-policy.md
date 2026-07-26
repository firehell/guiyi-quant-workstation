# V1 HTDY Step 1 Production Kernel and Realtime Policy Plan

**Goal:** Promote the user-selected HTDY original XMA realtime observation subset into `quant-core`, freeze one exact JM actual-contract 15m first-seen repainting policy, and prove Python/Web parity without enabling Runtime, database, notification, backtest, or trading capabilities.

**Workspace:** `/Volumes/扩展盘/GuiyiWorktrees/guiyi-v1-htdy-realtime-closure`

**Branch/Base:** `codex/v1-htdy-realtime-closure` at `d4f51314`

## Global Constraints

- Work only in the existing isolated integration worktree.
- Follow strict TDD: tests must fail for the intended missing/wrong behavior before production edits.
- Do not cherry-pick the source branch wholesale.
- Do not modify Runtime services, database models/migrations, notification code, strict strategy parameters, Stage 5 conclusions, report 14, or report 15.
- Keep `huotian_dayou_original_v0` Registry status `observation_only` with backtest/live/alert capabilities false.
- Do not modify or weaken `require_formal_strategy_indicator_policy()`.
- Preserve `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` and the Stage 5 rejection.
- XMA(25) uses the oracle-supported symmetric `[-12,+12]` single window and `[-24,+24]` double dependency.
- XMA(6) normalizes to 7 and uses the user-selected symmetric `[-3,+3]` rule; this does not claim the external XMA(6) oracle is closed.
- Exact future dependency horizon is 24 bars. Configured repaint scan zone is the conservative `24 + max REF depth 3 = 27`.
- Source hash is SHA-256 of the production module bytes. Policy hash is SHA-256 of canonical sorted compact JSON.
- Create one Step 1 checkpoint only after all required verification succeeds. Do not push, merge, deploy, or enable anything.

## Task 1: Implement and verify the Step 1 atomic checkpoint

### Tests first

- Add Python tests for symmetric XMA(25), double dependency boundary, XMA(6) normalization, tail repaint appearance/disappearance, buy/sell third-consecutive semantics, conflict, lengths/NaN, 27-bar coverage, stable source/policy hashes, exact policy allow/reject behavior, Registry invariants, and formal-policy rejection.
- Run the new Python tests before implementation and record the expected failures.
- Add Web tests for the corrected centered XMA, 6-to-7 normalization, 27-bar metadata, and tracked Python/Web golden fixture.
- Run the new Web tests before Web implementation and record the expected failures.

### Production implementation

- Add `packages/quant-core/guiyi_quant/indicators/htdy_original.py` with the minimal realtime result: `zk1`, `zd1`, `zd2`, yellow/white candle flags, buy/sell observations, conflict, indicator metadata, and repaint/future-dependency metadata.
- Add `packages/quant-core/guiyi_quant/indicators/realtime_observation_policy.py` with immutable exact policy data, canonical policy hashing, and `require_realtime_repainting_observation_policy()`.
- Export the new interfaces from `guiyi_quant.indicators`.
- Point the original Registry entry at the production module and version `original-v0` while preserving all ordinary capability denials.
- Keep formal policy modules behaviorally unchanged.

### Web and golden

- Correct `tdxXma()` to the same symmetric clipped window and retain the even-to-next-odd rule.
- Add a tracked canonical golden fixture with input bars and normalized Python outputs. Normalize finite numbers to 12 decimal places, non-finite values to null, and require exact time/boolean/null/hash parity in Python and Web.
- Set Web HTDY unstable/repaint tail metadata to 27 without enabling live Web mode or alert capability.

### Documentation and verification

- Update `docs/INDICATOR_KERNEL.md`, `STATUS.md`, and a Step 1 task record. Do not rewrite historical D4-00 evidence.
- Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests -k "htdy or indicator_policy or indicator_registry"

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build

uv run --project services/quant-api ruff check \
  packages/quant-core/guiyi_quant \
  services/quant-api/tests

bash scripts/engineering/check-secrets.sh
git diff --check
```

- Review the final diff for forbidden paths and capability drift.
- Commit one independent Step 1 checkpoint.
- Final code-state markers:

```text
HTDY_ORIGINAL_PRODUCTION_KERNEL_READY
HTDY_REALTIME_REPAINTING_POLICY_READY
FORMAL_BACKTEST_POLICY_UNCHANGED
```

These markers do not imply Runtime, DB, SignalEvent, WeCom, historical equivalence, profitability, or trading readiness.
