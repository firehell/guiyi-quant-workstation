# Routing policy

After the user starts delivery with approved documents, the AI delivery lead selects one implementer,
one independent reviewer, and only the specialists required by the trusted plan. Assign at most two specialists.
When three or more domains are declared, return `split_required`; do not enlarge the team.

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

| Lane | Model and effort | Start mode | V06 rule |
| --- | --- | --- | --- |
| Lane 1 | Terra, medium | direct-or-short-plan | Charter freezes automatically; use Fast Path. |
| Lane 2 | Terra, medium | plan-then-execute | Charter freezes automatically; use Team Path. |
| Lane 3 | Sol, high | plan-only-start | Stop at Owner Gate before implementation or real action. |

Product-direction change, active-canonical conflict, or scope expansion also returns to Owner Gate.
No other ordinary Charter approval is invented. Model choice never changes authority.

## Delivery flow

`approved design + approved implementation plan + trusted ExecutionPlanV1 -> intake -> minimum role briefs -> implementation/specialist handoffs -> exact-head package -> independent decision -> existing Codex/GitHub flow when permitted`

The existing flow, not V06, may perform configured PR, exact-head CI, and automatic merge commit into
`develop`. Real data/DB, strategy/backtest semantics, notification, live, `main/release/tag`, Runtime,
deletion, candidate promotion, and GitHub-rules operations keep their separate Gates.
