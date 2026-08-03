# ReviewPackageV1

`review-package` emits this strict read-only JSON from trusted contracts, receipts, and fixed local Git.
Store exact stdout as `review-package.json` beside the reviewer decision; never hand-edit it.

## schema_version

Integer `1`.

## execution_plan_digest

Digest of the approved execution plan.

## intake_digest

Digest of the trusted document intake.

## task_brief_digest

Digest of the bound implementer role brief.

## exact_base_sha

Frozen `origin/develop` SHA from the intake.

## exact_head_sha

Current committed task HEAD.

## round

Review round `0` through `3`.

## implementer_context_id

Frozen implementation context.

## reviewer_context_id

Separate reviewer context.

## changed_paths

Sorted complete Git diff paths, including both rename/copy endpoints.

## diff_digest

SHA-256 digest of the fixed binary/full-index Git diff.

## test_receipts

Current successful exact-HEAD receipt path/digest objects.

## implementer_handoff_digest

Digest of the brief-bound implementer handoff.

## specialist_evidence_digests

Ordered digests for every trusted specialist handoff.
