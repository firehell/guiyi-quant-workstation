# WorkBuddy Security Boundary

WorkBuddy must never:

- run arbitrary shell;
- call Codex directly;
- push, merge, deploy, close Issues, or mark PRs ready;
- write `.env`, credentials, tokens, cookies, webhook URLs, license text, or account data;
- write DB, Parquet, runtime data, live trading state, or production paths;
- create automatic trading, unattended order routing, or signal-to-order execution;
- turn WorkBuddy memory or chat into a task state source.

Codex remains the writer for core implementation and uses the `codex` writer lock. There is no `workbuddy` writer lock.
