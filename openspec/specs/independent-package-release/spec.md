# Independent Package Release

## Purpose

This specification defines the independent release identities and artifacts for the Compute and Chart packages. It describes how applications select and verify the exact dependencies they consume.

## Requirements

### Requirement: PR01 Quant Core and Quant Chart have independent package versions

The Python package `guiyi-quant-core` and TypeScript package `@guiyi/quant-chart` SHALL have independent Semantic Versioning, build artifacts, package tests and release records while remaining in the same Monorepo. Quant Core SHALL produce wheel/sdist; Quant Chart SHALL produce an installable package tarball. Neither package release SHALL automatically change API/Web application versions or consumer dependencies.

#### Scenario: Quant Core publishes a new version

- **WHEN** a Quant Core release artifact is built and published
- **THEN** only the Quant Core package version/artifact advances
- **AND** API, Web, Market Core, Compute Runtime and simulation consumers remain on their locked versions until explicitly upgraded.

#### Scenario: Quant Chart publishes a new version

- **WHEN** a Quant Chart release artifact is built and published
- **THEN** only the Chart package version/artifact advances
- **AND** the Web application does not consume it until its dependency lock is deliberately updated and rebuilt.

### Requirement: PR02 Package, formula, state and result identities are independent

Package version MUST be distinct from formula_version, state_schema_version, result_schema_version, chart_catalog_schema_version and renderer/display_version. A package performance refactor that preserves formula semantics need not change formula_version; a formula change MUST create a new formula identity; an incompatible checkpoint or result schema MUST be rejected or rebuilt explicitly.

#### Scenario: A package is upgraded without formula change

- **GIVEN** a new package version changes internal implementation/performance only
- **WHEN** a consumer loads a saved result with compatible formula and result schema identities
- **THEN** the result remains interpretable under its recorded identities
- **AND** the package upgrade does not silently relabel historical results.

#### Scenario: A formula or schema is incompatible

- **WHEN** a consumer encounters an unsupported formula, state or result schema
- **THEN** it fails closed or rebuilds from verified input according to the declared migration
- **AND** it does not reinterpret old state/result bytes as the new schema.

### Requirement: PR03 Consumers lock exact package artifacts

Development MAY use local path/workspace dependencies. Release/runtime environments SHALL install exact package versions and verify artifact hashes; they MUST NOT depend on mutable editable paths, unpinned latest versions or implicit transitive upgrades. The API application version and existing Web application build identity remain separate from package versions.

#### Scenario: A clean environment installs a release artifact

- **WHEN** CI installs the exact Quant Core wheel or Quant Chart tarball into a clean environment
- **THEN** package tests and consumer contract checks run against that artifact
- **AND** the result does not depend on the Monorepo source path being importable.

#### Scenario: A consumer requests an incompatible package contract

- **WHEN** API/Web or a worker starts with an unsupported package/schema combination
- **THEN** compatibility validation fails explicitly
- **AND** the consumer does not silently fall back to an older package or renderer.

### Requirement: PR04 Package publication is separate from application deployment

Package Release SHALL produce an immutable versioned artifact and release record. Updating a running API/Web/worker requires an explicit consumer dependency update, lockfile change, rebuild and deployment/restart under the existing application/runtime process. Package publication MUST NOT hot-swap running consumers or authorize Runtime promotion.

#### Scenario: A package is released while consumers remain unchanged

- **WHEN** a new package artifact is published but no consumer lock is updated
- **THEN** running and newly built consumers continue to use their previously pinned package version
- **AND** no Runtime changes occur.

#### Scenario: A consumer is upgraded

- **WHEN** an application explicitly updates its package dependency
- **THEN** the application is rebuilt and its package/version identity is observable
- **AND** the upgrade is validated without changing unrelated package consumers.
