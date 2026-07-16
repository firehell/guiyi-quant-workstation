# WorkBuddy Command Protocol

WorkBuddy commands are a thin remote facade over existing controlled scripts.

| WorkBuddy command | Local script |
|---|---|
| `analyze` | `bootstrap_github_task.sh --dry-run` or `route_task.sh` |
| `bootstrap` | `bootstrap_github_task.sh` |
| `plan` | `dispatch_task.sh <target> plan --json` |
| `approve` | `approve_task.sh --task <TASK_ID>` and requires `--confirm-user-approval` |
| `dev` | `dispatch_task.sh <target> dev --json` |
| `test` | `dispatch_task.sh <target> test --json` |
| `review` | `dispatch_task.sh <target> review --json` |
| `result` | `dispatch_task.sh <target> result --json` |
| `delivery` | `make_delivery_summary.sh --task <TASK_ID>` |
| `status` | `dispatch_task.sh <target> status --json` |
| `cancel` | `dispatch_task.sh <target> cancel --json` |
| `sync-pr` | `update_pr_from_result.sh --confirm-issue-ops` and requires `--confirm-github-write` |
| `record-external-review` | `record_external_review.sh --task <TASK_ID> --pr <N>` |

No command may be chained automatically by WorkBuddy. The user decides each transition.
