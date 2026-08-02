# Routing policy

Start with the four base roles in [roles.md](roles.md). Add a specialist only when the declared domain needs it; assign at most two specialists. When three or more domains are declared, require a split before routing: return `split_required` and create separate Task Charters.

## Domain mapping

| CLI domain | Specialist |
| --- | --- |
| `product-interaction` | product-interaction-specialist |
| `frontend` | frontend-specialist |
| `data-database` | data-database-specialist |
| `quant-research` | quant-research-specialist |
| `backtest-audit` | backtest-audit-specialist |
| `research-ai` | research-ai-specialist |
| `runtime-sre` | runtime-sre-specialist |
| `security` | security-specialist |

## Lane and model rules

| Lane | Model and effort | Start mode | Gate rule |
| --- | --- | --- | --- |
| Lane 1 | Terra, medium | direct-or-short-plan | No external Gate in the Charter. |
| Lane 2 | Terra, medium | plan-then-execute | No external Gate in the Charter. |
| Lane 3 | Sol, high | plan-only-start | Name the required human external Gate before any real action. |

Do not route a Lane 3 task as approved merely because its code, dry-run, isolated migration, disabled feature, test, CI, or review passes. Model selection is a routing hint, not a permission change.

## State flow and escalation

`current canonical facts -> value check -> frozen Charter -> existing worktree/Issue workflow -> implementation -> validation -> independent review -> exact-head evidence -> human Gate when required -> release/Runtime only when separately approved`

Escalate to the user before a real data/DB write, strategy/backtest semantic change, notification, live operation, `main/release/tag`, Runtime action, deletion, candidate promotion, or GitHub-rules change. Keep code/test/CI/review evidence distinct from a real Gate, release, and Runtime state. Stop rather than infer approval from an Issue, test, receipt, or prior Gate.
