# FinalDecisionV1

The independent reviewer writes this strict JSON as `final-decision.json` at the reviewer brief's
derived path. It records evidence; it does not execute integration.

## schema_version

Integer `1`.

## review_package_digest

Semantic digest of the exact `ReviewPackageV1`.

## exact_head_sha

Exact package HEAD.

## implementer_context_id

Implementer context copied from the package.

## reviewer_context_id

Different reviewer context copied from the package.

## round

Package round `0` through `3`.

## spec_verdict

Exactly `PASS` or `FAIL`.

## quality_verdict

Exactly `APPROVED` or `CHANGES_REQUIRED`.

## findings

Objects with `severity` and `summary`; severity is `Critical`, `Important`, or `Minor`.

## decision

Derived value: `允许集成 develop`, `要求修正后再集成`, or `阻塞`.
