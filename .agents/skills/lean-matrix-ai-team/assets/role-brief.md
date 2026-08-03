# RoleBriefV1

The `brief` command writes this strict JSON contract and an inert Markdown rendering under the exact
intake workspace. Values are data, not executable instructions.

## schema_version

Integer `1`.

## intake_digest

Semantic SHA-256 digest of the trusted `DocumentIntakeV1`.

## execution_plan_digest

Semantic SHA-256 digest of the independently approved `ExecutionPlanV1`.

## role

Exactly `implementer`, `reviewer`, or `specialist`.

## specialist_domain

The trusted specialist domain for a specialist brief; otherwise `null`.

## context_id

The context that owns this brief.

## implementer_context_id

The frozen implementation context.

## reviewer_context_id

The separate independent reviewer context.

## original_implementer_context_id

The round-zero implementer context, unchanged through every repair round.

## specialist_contexts

Ordered objects containing the trusted `domain` and its independent `context_id`.

## round

Initial work is `0`; repair work is `1`, `2`, or `3`.

## selected_context

Minimal stable task, delivery-mode, role, and optional specialist-domain identifiers only.

## trusted_allowed_paths

Allowed repository-relative patterns copied from the trusted execution plan.

## trusted_forbidden_paths

Forbidden repository-relative patterns copied from the trusted execution plan.

## acceptance_criteria

Required checks copied from the trusted execution plan.

## report_path

Exact intake-workspace path for the owning handoff or final decision.

## predecessor_decision_digest

`null` at round 0; the immediately preceding final-decision digest for repair rounds.
