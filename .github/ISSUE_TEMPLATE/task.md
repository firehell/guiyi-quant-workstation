---
name: Task
about: GitHub Native V3 task lifecycle entry. Link to TASK, branch, and Draft PR; do not paste the full TASK.
title: "TASK-ID: "
labels: ["type/task", "area/workstation", "status/draft"]
---

## Remote entry contract

> Issue is the lifecycle and remote entry point. The executable contract remains the linked TASK file.

| Field | Value |
|---|---|
| Task ID | `TASK-...` |
| Goal summary |  |
| Risk level | `R0` / `R1` / `R2` / `R3` |
| Work level | `L0` / `L1` / `L2` |
| Task branch | `task/...` |
| TASK file path | `docs/tasks/...` or `.ai/tasks/...` |
| Draft PR | `#` / pending |
| Current status | `DRAFT` |
| Key gates | Issue / Plan / Approval / Worktree / Scope / Runtime / Evidence |
| Non-goals |  |
| Related Epic |  |

## Handoff notes

- Static TASK contract:
- Local runtime overlay: `.ai/task-runtime/<TASK_ID>.json`
- Expected first local action: `scripts/ai/init_task_worktree.sh --task <TASK_ID>`

## Acceptance

- [ ] Issue links a stable `task_id`, branch, TASK path, and Draft PR.
- [ ] Issue does not duplicate the full TASK body.
- [ ] Lifecycle labels reflect current state.
- [ ] User approval remains required for Plan, production writes, merge, deploy, and real trading operations.
