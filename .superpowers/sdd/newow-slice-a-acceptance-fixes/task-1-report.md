# Task 1 report: Freeze D marker codes and trend transition facts

## Scope

Implemented only Task 1 in the `fix/newow-slice-a-acceptance` worktree. No
Slice B, Web/API/Runtime/Alert/DB/Redis/Worker/SuBing/HTDY changes were made.

## TDD evidence

Tests were added before production changes.

RED command:

```text
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_models_profile.py::test_escape_marker_contract_codes_are_spec_stable services/quant-api/tests/newow/test_trend_band.py::test_transition_marker_facts_freeze_state_before_and_after
```

RED result:

```text
FF                                                                       [100%]
2 failed in 0.04s
```

The first failure observed `ESCAPE_D1` instead of `NEWOW_ESCAPE_D1`; the
second raised `KeyError: 'state_before'`.

GREEN focused command:

```text
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_models_profile.py::test_escape_marker_contract_codes_are_spec_stable services/quant-api/tests/newow/test_trend_band.py::test_transition_marker_facts_freeze_state_before_and_after
```

GREEN result: `2 passed in 0.04s`.

Full Newow command:

```text
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow
```

Full result: `58 passed in 0.11s`.

## Changes

- `packages/quant-core/guiyi_quant/newow/models.py`: D1/D2/D3 enum values now
  emit `NEWOW_ESCAPE_D1`, `NEWOW_ESCAPE_D2`, and `NEWOW_ESCAPE_D3`.
- `packages/quant-core/guiyi_quant/newow/trend_band.py`: BUILD and CLEAR
  trigger facts now include deterministic string snapshots of
  `state_before` and `state_after`, while preserving yellow/blue semantics,
  signal-close facts, and reference facts.
- `services/quant-api/tests/newow/test_models_profile.py`: exact D marker code
  contract test.
- `services/quant-api/tests/newow/test_trend_band.py`: BUILD/CLEAR transition
  state snapshot test.

## Commit

Implementation commit: `f8629a763704692c607b1ac15dd049f499349a69`
(`fix(newow): freeze slice a marker contracts`).

## Self-review

`git diff --check` passed. The diff is limited to the four intended source and
test files; no unrelated worktree changes were present. The private marker
helper receives the explicit post-transition state, and the pre-transition
state is taken from the validated prior state, so facts are immutable through
the existing frozen `trigger_facts` mapping. No formula, threshold, severity,
ordering, or scope behavior was changed.

## Acceptance

Task 1 code and tests are complete and verified. No external Gate, release,
Runtime promotion, or production operation was performed.
