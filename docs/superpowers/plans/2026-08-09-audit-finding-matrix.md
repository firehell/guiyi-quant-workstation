# Audit Finding Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the existing audit return a complete, categorized, per-product read-only finding matrix for the active universe.

**Architecture:** HistoricalDataManager.audit remains the sole audit service. It resolves each symbol independently, converts only an explicit allowlist of coverage metadata codes into findings, and re-raises unknown exceptions. The existing partition consistency probe returns a precise reason code so audit can distinguish missing partitions from physical corruption without changing update or refresh behavior.

**Tech Stack:** Python 3, dataclasses, pytest, SQLAlchemy fixture Catalog, existing guiyi CLI, OpenSpec Markdown.

## Global Constraints

- Do not add a CLI command, a second audit engine, a temporary operator script, or a checkpoint file.
- Audit remains zero RQData, zero PostgreSQL write, and zero Canonical Parquet write.
- Known metadata findings retain their exact code and use categories metadata_session, metadata_calendar, or metadata_window.
- Existing map, partition, and physical findings use categories main_contract_map, partition, and physical.
- Unknown exceptions remain fail-closed through the existing CLI error boundary.
- Nullable year/month are used only when a metadata failure prevents identifying a meaningful month.
- No repair, synchronization, update --apply, refresh --apply, Runtime, live, notification, or order action is in scope.

---

## File Structure

- Modify services/quant-api/app/market_data/maintenance.py: define finding category data, per-symbol audit isolation, metadata-code allowlist, and precise partition state.
- Modify services/quant-api/tests/data_foundation/test_maintenance.py: prove categorized continuation, physical reason preservation, and unknown-exception propagation.
- Modify docs/DATA_CENTER.md and the active OpenSpec historical-data-maintenance spec: document the structured read-only result contract.
- Create no production data assets or new service modules.

### Task 1: Add categorized per-symbol audit findings through red-green tests

**Files:**

- Modify: services/quant-api/tests/data_foundation/test_maintenance.py
- Modify: services/quant-api/app/market_data/maintenance.py:143-184 and 342-384

**Interfaces:**

- Consumes: AuditRequest(products: tuple[str, ...]).
- Produces: AuditFinding(code: str, category: str, dataset: tuple[str, str, str, str], year: int | None, month: int | None).
- Produces: MaintenanceResult.as_payload()["findings"] entries with code, category, dataset, year, and month.

- [ ] **Step 1: Write failing audit tests.**

Import `InfrastructureError` from `app.market_data.infrastructure`. Extend FakeCoverage with
`latest_errors: dict[str, Exception]` and `latest_calls: list[tuple[str, ...]]`; its
`latest_complete_day(products)` appends `products`, raises `latest_errors[products[0]]` when
present, and otherwise returns its current fixed date. Then add these tests:

~~~python
def test_audit_continues_after_known_session_metadata_failure(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["a"] = InfrastructureError("TRADING_SESSION_MISSING")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.audit(AuditRequest(("a", "jm")))

    assert result.status == "failed"
    assert result.findings[0].code == "TRADING_SESSION_MISSING"
    assert result.findings[0].category == "metadata_session"
    assert result.findings[0].dataset == ("metadata", "a", "session", "1d")
    assert result.findings[0].year is None
    assert result.findings[0].month is None
    assert coverage.latest_calls == [("a",), ("jm",)]


def test_audit_reports_calendar_metadata_failure(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["jm"] = InfrastructureError("TRADING_CALENDAR_MISSING")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    result = manager.audit(AuditRequest(("jm",)))

    assert [(item.code, item.category) for item in result.findings] == [
        ("TRADING_CALENDAR_MISSING", "metadata_calendar")
    ]


def test_audit_reraises_unknown_coverage_error(session, tmp_path) -> None:
    coverage = FakeCoverage({})
    coverage.latest_errors["jm"] = RuntimeError("database disconnected")
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))

    with pytest.raises(RuntimeError, match="database disconnected"):
        manager.audit(AuditRequest(("jm",)))
~~~

- [ ] **Step 2: Run only the new tests before implementation.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_maintenance.py -k 'metadata_failure or unknown_coverage'
~~~

Expected: the new tests fail because AuditFinding has no category and audit exits at the first InfrastructureError.

- [ ] **Step 3: Implement per-symbol metadata isolation.**

In maintenance.py, add an explicit code-to-category mapping:

~~~python
_AUDIT_METADATA_CATEGORIES = {
    "TRADING_SESSION_MISSING": ("metadata_session", "session"),
    "PREVIOUS_TRADING_DAY_MISSING": ("metadata_session", "session"),
    "TRADING_CALENDAR_MISSING": ("metadata_calendar", "calendar"),
    "COMPLETE_TRADING_DAY_MISSING": ("metadata_calendar", "calendar"),
    "PRODUCT_WINDOW_START_MISSING": ("metadata_window", "window"),
    "INSTRUMENT_EXCHANGE_MISSING": ("metadata_window", "exchange"),
}
~~~

Make AuditFinding year and month nullable and add category. Audit each symbol in its own try block. For an exception whose code exists in the mapping, append a metadata finding and continue. For every other exception, raise it. Use each successful symbol's latest complete day for expected coverage and set MaintenanceResult.through to the minimum successful value, or None if all symbols have metadata findings.

- [ ] **Step 4: Run the focused maintenance test file.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_maintenance.py
~~~

Expected: all maintenance tests pass.

### Task 2: Preserve physical reasons and publish the matrix contract

**Files:**

- Modify: services/quant-api/tests/data_foundation/test_maintenance.py
- Modify: services/quant-api/app/market_data/maintenance.py:776-811
- Modify: docs/DATA_CENTER.md
- Modify: openspec/changes/converge-canonical-data-foundation/specs/historical-data-maintenance/spec.md

**Interfaces:**

- Consumes: _existing_partition(key, year, month).
- Produces: (bars, reason_code) where reason_code is None for a readable consistent partition.
- Produces: physical AuditFinding entries with the exact reason code.

- [ ] **Step 1: Write the failing physical-finding test.**

Add this test:

~~~python
def test_audit_preserves_unreadable_partition_reason(session, tmp_path) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    bars = (_daily(2, 100),)
    coverage = FakeCoverage({key.as_tuple(): tuple(bar.bar_end for bar in bars)})
    manager = _manager(session, tmp_path, coverage, FakeProvider({}))
    _publish_existing(manager, key, bars)
    manager.catalog.all_partitions(key)[0].file_path.write_bytes(b"invalid")

    result = manager.audit(AuditRequest(("jm",)))

    assert [(item.code, item.category) for item in result.findings] == [
        ("PARTITION_UNREADABLE", "physical")
    ]
~~~

- [ ] **Step 2: Run the physical test before implementation.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_maintenance.py \
  -k unreadable_partition_reason
~~~

Expected: it fails because audit currently reports EXPECTED_PARTITION_MISSING.

- [ ] **Step 3: Return precise partition reasons without altering write semantics.**

Change _existing_partition to return tuple[tuple[CanonicalBar, ...], str | None]. Return None only for an absent or readable consistent partition. Return PARTITION_CATALOG_MISMATCH for duplicate Catalog rows, a wrong URI, or a missing file; return the caught StorageError.code for unreadable Parquet; return PARTITION_EMPTY, PARTITION_ROW_COUNT_MISMATCH, or PARTITION_COVERAGE_MISMATCH for those checks. In _iter_targets, treat every non-None reason as the existing whole-month rebuild condition. In audit, emit category physical for a non-None reason and category partition only when an expected month has no registered partition.

- [ ] **Step 4: Serialize category and document the contract.**

Add category to MaintenanceResult.as_payload findings. In docs/DATA_CENTER.md and the active OpenSpec requirement, state that audit returns read-only categorized findings and that recognized metadata gaps do not abort the remaining requested symbols.

- [ ] **Step 5: Run complete local verification.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation
openspec validate converge-canonical-data-foundation --strict --no-interactive
uv run --project services/quant-api ruff check \
  services/quant-api/app/market_data \
  services/quant-api/tests/data_foundation/test_maintenance.py
git -c core.fsmonitor=false diff --check
~~~

Expected: all commands exit zero.

- [ ] **Step 6: Commit the implementation and documentation.**

~~~bash
git add services/quant-api/app/market_data/maintenance.py \
  services/quant-api/tests/data_foundation/test_maintenance.py \
  docs/DATA_CENTER.md \
  openspec/changes/converge-canonical-data-foundation/specs/historical-data-maintenance/spec.md
git commit -m "feat(data): classify audit findings"
~~~

### Task 3: Run the 58-product active-universe read-only matrix

**Files:**

- Create: none.
- Modify: none.
- Test: production read-only audit output only.

**Interfaces:**

- Consumes: guiyi data audit --universe active.
- Produces: a terminal-only matrix grouped by category, code, exchange, and symbol.

- [ ] **Step 1: Run the active-universe audit with the existing secure environment.**

~~~bash
uv run --project services/quant-api guiyi data audit --universe active
~~~

Expected: a failed audit result with findings, not a top-level TRADING_SESSION_MISSING error. Do not pass --apply.

- [ ] **Step 2: Group only returned fields.**

Group findings by category and code. Resolve exchange and symbol only from the finding dataset tuple and existing Catalog metadata. Do not emit credentials, database URLs, full raw bars, or filesystem contents.

- [ ] **Step 3: Re-run the read-only inventory baseline.**

Confirm production revision, active count, J/JM partition counts, and all candidate partition counts match the previous preflight. Report any mismatch as READ_ONLY_AUDIT_STATE_CHANGED and stop without repair.
