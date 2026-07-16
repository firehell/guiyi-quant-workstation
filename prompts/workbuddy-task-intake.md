# WorkBuddy Task Intake Prompt

Use this prompt when the user sends an idea, Issue, TASK_ID, or PR.

Read:

1. Issue / PR if provided.
2. `docs/tasks/<TASK_ID>.md` if provided.
3. `PROJECT_SOURCE.md`, `STATUS.md`, `DECISIONS.md`.

Output:

1. requirement conclusion
2. stage boundary
3. non-goals
4. data / strategy / safety impact
5. suggested Issue or linked Issue
6. recommended experts
7. recommended execution owner: `Codex`, `Copilot`, or `no-code`
8. WorkBuddy command sequence
9. tests and acceptance
10. merge-precheck

Do not create a second state. Do not ask the user to paste full `.ai/results` or secrets into chat.
