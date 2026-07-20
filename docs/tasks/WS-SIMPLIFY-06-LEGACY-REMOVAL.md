# WS-SIMPLIFY-06-LEGACY-REMOVAL

| Field | Value |
|---|---|
| Status | `DELIVERY_READY` |
| Date | 2026-07-20 |

## Result

- Removed WorkBuddy facade, dispatcher, model router, writer lock, TASK schema runtime force, `tests/workstation/**`, orchestrator skills.
- Makefile / CI point to `scripts/engineering` + `tests/engineering`.
- Retained redaction, resource_lock, env bootstrap, engineering Gates. See `docs/archive/workstation/STEP6_RETENTION.md`.
- Legacy Issue/PR cleanup suggestions only: `docs/archive/workstation/GITHUB_LEGACY_ISSUE_PR_CLEANUP.md`.
