# HandoffReportV1

The implementer or specialist writes this strict JSON directly at the brief's `report_path`.

## schema_version

Integer `1`.

## report_kind

Exactly `implementer` or `specialist`.

## specialist_domain

The trusted domain for a specialist handoff; otherwise `null`.

## intake_digest

Digest copied from the bound role brief.

## brief_digest

Semantic digest of the exact role brief.

## context_id

The brief-bound writer context.

## round

`0`, `1`, `2`, or `3`; specialists are round 0 only.

## report_path

Exact derived path copied from the role brief.

## exact_head_sha

Committed 40-character Git HEAD covered by the handoff.

## changed_paths

Sorted exact Git changed paths for an implementer; empty for a specialist.

## test_evidence

Repository-relative receipt paths covering every required check exactly once.

## advisory_evidence_digests

Ordered specialist handoff digests for an implementer; empty for a specialist.

## status

Exactly `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`.

## concerns

Explicit remaining concerns; empty only when none are known.

## predecessor_decision_digest

`null` at round 0; the immediately preceding final-decision digest for repair rounds.
