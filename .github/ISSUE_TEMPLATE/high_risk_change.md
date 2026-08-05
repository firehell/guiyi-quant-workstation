---
name: High-risk change
about: Optional backlog note for data, DB, strategy, Runtime, live, or real notification work. Not an authorization Gate.
title: "[High-risk]: "
labels: []
---

## Goal

## Scope and non-goals

## Impact

Data / DB / strategy / Runtime / live / notification / remote refs — what changes, what stays off.

## Validation

Local checks planned (domain tests, dry-run if any). Issue/PR/CI/packet/hash/receipt are not authorization.

## External mutation (if any)

Controlled external ops need a separate, scope-clear, one-shot user intent at execution time. This Issue does not authorize production writes, Runtime/live enable, real notifications, release/tag, or GitHub rules changes. Dry-run does not authorize mutation.

## Done when

## Risks

Do not paste secrets. `auto_order=false`; no order creation. Business correctness (quality, DataGap, default-off) overrides any intent.
