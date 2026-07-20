# Step 6 retention notes

| Path | Why retained |
|---|---|
| `scripts/engineering/**` | Formal engineering entrypoints |
| `scripts/ai/redact_evidence.sh` + `lib/result_bundler.py` | Secret redaction capability |
| `scripts/ai/resource_lock.sh` + `lib/resource_lock.py` | Data-writer lock capability (fail-closed) |
| `scripts/env/bootstrap_worktree_env.sh` | Scoped env bootstrap + `--confirm-production` |
| `scripts/env/check_task_env.sh` | Thin deprecated shim → engineering preflight/secrets |
| `configs/ai/**` | Codex profile templates may still be used manually; not deleted without separate audit |
| `docs/tasks/**` historical TASK files | Historical contracts; not runtime-enforced |
| `docs/decisions/ADR-WS-001-*` | Historical ADR; may be superseded by DECISIONS simplify row |

## Deleted (grep + Pilot)

- WorkBuddy facade, dispatcher stage machine, model router, writer lock, TASK schema runtime force
- `tests/workstation/**` control-plane suite
- `.agents/skills/guiyi-workstation-orchestrator` / `guiyi-delivery-team`
- `.ai/schema/task.schema.json` runtime schema force
