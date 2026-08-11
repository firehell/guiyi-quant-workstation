## Purpose

Defines how historical `data update` discovers exact missing windows, refreshes metadata before final planning, treats `--since` as a missing lower bound, and proves idempotent NOOP at a fixed watermark.

## ADDED Requirements

### Requirement: Exact missing window materialization
The system MUST convert each planned Direct or Derived identity window into zero or more exact `DataTarget` ranges equal to Catalog uncovered sub-windows. The system MUST NOT schedule or publish a full requested identity window when only a sub-range is missing. Catalog uniqueness and conflict rules MUST remain unchanged for routine catch-up.

#### Scenario: Sub-range hole becomes exact target
- **WHEN** Catalog coverage ends at day T0 and the requested window extends to day T1 with a hole only in `(T0, T1]`
- **THEN** the planner emits exactly one target covering that hole and does not emit the original full-window target

#### Scenario: No hole means no publish target
- **WHEN** Catalog effective coverage already covers the requested identity window for a dataset
- **THEN** the planner emits zero publish targets for that dataset identity

### Requirement: Explicit since is missing detection lower bound
When `--since` is provided, the system MUST use it only as the inclusive lower bound for missing detection through the update watermark. If every expected identity in that range is covered, the update MUST be a NOOP for those identities. The system MUST NOT force-refresh, rebuild, or republish already covered partitions because `--since` was set.

#### Scenario: Covered window with explicit since is NOOP
- **WHEN** an operator runs update with explicit `--since` and `--through` and all expected Direct and Derived identities in that range are fully covered
- **THEN** the plan schedules zero Direct and zero Derived publish targets

#### Scenario: Since does not authorize replacement
- **WHEN** an operator needs to rebuild already published partitions
- **THEN** that rebuild MUST use a separate expert repair/replacement command path, not `--since`

### Requirement: Metadata bootstrap precedes final plan on apply
On apply, the system MUST refresh Calendar and Session metadata for selected products before computing the latest completed trading day watermark, MUST refresh MainContractMap to that watermark, and MUST run the final exact plan only after those refreshes. Metadata freshness on apply MUST NOT depend on a prior non-empty data plan or non-empty publish target list.

#### Scenario: Apply refreshes metadata before final planning
- **WHEN** apply runs for selected products whose continuous bars currently look complete
- **THEN** the system still bootstraps Calendar and Session, recomputes the watermark, refreshes MainContractMap, and only then computes the final exact plan

#### Scenario: Dry-run never contacts RQData for metadata freshness
- **WHEN** dry-run update is invoked
- **THEN** the system performs zero RQData calls, zero DB writes, and zero Canonical writes, and MAY report that metadata refresh would be required without performing it

### Requirement: Actual dominant completeness from MainContractMap expectations
Actual-dominant completeness MUST be derived from MainContractMap `rank=1` expected contract windows after map refresh, not from the set of already registered actual-dominant Catalog datasets. A brand-new rank1 contract with no Catalog dataset MUST be discovered as missing for all required frequencies.

#### Scenario: Missing whole new dominant dataset is discovered
- **WHEN** MainContractMap assigns a new rank1 contract for a date range and no actual-dominant Catalog dataset exists for that contract
- **THEN** final planning includes exact Direct and Derived targets for that expected contract window

#### Scenario: Catch-up frontier includes actual-dominant-only holes
- **WHEN** continuous Direct and Derived coverage is complete but an expected actual-dominant derived frequency has a hole
- **THEN** product catch-up without `--since` MUST discover that hole and MUST NOT treat the product as NOOP solely because continuous coverage is complete

### Requirement: Same-watermark idempotent NOOP
After a successful apply through watermark W, a second dry-run update with the same `--through W` MUST schedule zero Direct targets, zero Derived targets, and zero changed publications, with no RQData, DB, or Canonical writes.

#### Scenario: Second dry-run at fixed through is NOOP
- **WHEN** G5-style apply completed through watermark W and a later dry-run repeats the same universe with `--through W`
- **THEN** direct_target_count, aggregate_target_count, and changed_count are all zero
