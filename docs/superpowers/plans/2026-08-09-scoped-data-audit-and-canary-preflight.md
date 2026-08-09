# Scoped Data Audit and Canary Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a per-product read-only data audit selector and use it for a fixed-T0, four-exchange production read-only canary preflight.

**Architecture:** Keep HistoricalDataManager.audit(AuditRequest) unchanged. The parser and request builder use the same mutually exclusive selector pattern and _products() validation as data update, preserving one audit implementation and the retired-product guard. The preflight uses existing CLI read operations and one in-memory SQLAlchemy inventory query; it creates no operator file and makes no mutation.

**Tech Stack:** Python 3, argparse, pytest, SQLAlchemy ORM, existing guiyi CLI, OpenSpec Markdown.

## Global Constraints

- CLI syntax is exactly: guiyi data audit (--symbol X | --universe active).
- Audit is zero RQData, zero PostgreSQL write, and zero Canonical Parquet write.
- Reuse _products() and HistoricalDataManager.audit(); do not add an audit service, batch CLI, or task-specific operator file.
- The preflight uses fixed T0=2026-08-07.
- Candidates are one incomplete, non-J/JM active product each from CZCE, SHFE, INE, and GFEX, selected by alphabetical symbol order.
- Do not run --apply, RQData imports, migrations, Runtime actions, notifications, or orders.

---

## File Structure

- Modify services/quant-api/app/guiyi_cli/data_parser.py: define audit selector arguments.
- Modify services/quant-api/app/guiyi_cli/data_commands.py: build AuditRequest from selected products.
- Modify services/quant-api/tests/data_foundation/test_cli.py: cover public JSON CLI behavior.
- Modify docs/DATA_CENTER.md, TESTING.md, and openspec/changes/converge-canonical-data-foundation/specs/historical-data-maintenance/spec.md: publish one identical contract.
- Create no migrations, production data files, temporary scripts, or domain modules.

### Task 1: Deliver the scoped audit selector through a red-green CLI test cycle

**Files:**

- Modify: services/quant-api/tests/data_foundation/test_cli.py:100-110
- Modify: services/quant-api/app/guiyi_cli/data_parser.py:44-45
- Modify: services/quant-api/app/guiyi_cli/data_commands.py:41-42

**Interfaces:**

- Consumes: _products(symbol: str | None, universe: str | None) -> tuple[str, ...].
- Consumes: AuditRequest(products: tuple[str, ...]) and HistoricalDataManager.audit(request).
- Produces: data audit --symbol <active-symbol> with a one-product request.

- [ ] **Step 1: Write the failing behavior tests in test_cli.py.**

Replace test_audit_requires_active_universe with these tests:

~~~python
def test_audit_parses_single_active_symbol() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--symbol", "JM"], manager)

    assert code == 0 and payload["status"] == "passed"
    assert [action for action, _request in manager.calls] == ["audit"]
    assert manager.calls[0][1].products == ("jm",)


def test_audit_keeps_active_universe_selector() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--universe", "active"], manager)

    assert code == 0 and payload["status"] == "passed"
    assert len(manager.calls[0][1].products) == 60


@pytest.mark.parametrize(
    "arguments",
    ((), ("--symbol", "jm", "--universe", "active")),
)
def test_audit_requires_exactly_one_selector(arguments: tuple[str, ...]) -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", *arguments], manager)

    assert code == 2
    assert payload["status"] == "error"
    assert manager.calls == []


def test_audit_rejects_retired_symbol_before_manager_call() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--symbol", "ic"], manager)

    assert code == 1
    assert payload["error"]["code"] == "PRODUCT_RETIRED"
    assert manager.calls == []
~~~

- [ ] **Step 2: Run the new audit tests before production changes.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_cli.py -k audit
~~~

Expected: test_audit_parses_single_active_symbol fails because audit does not accept --symbol; the active-universe test remains green.

- [ ] **Step 3: Add the minimal parser and request-builder behavior.**

Replace the parser audit declaration with:

~~~python
audit = commands.add_parser("audit")
selector = audit.add_mutually_exclusive_group(required=True)
selector.add_argument("--symbol")
selector.add_argument("--universe", choices=("active",))
~~~

Replace the audit request construction with:

~~~python
if args.data_command == "audit":
    return AuditRequest(_products(args.symbol, args.universe))
~~~

- [ ] **Step 4: Run the targeted CLI test file after implementation.**

Run:

~~~bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_cli.py
~~~

Expected: all tests in test_cli.py pass.

- [ ] **Step 5: Commit the tested feature files.**

~~~bash
git add services/quant-api/app/guiyi_cli/data_parser.py \
  services/quant-api/app/guiyi_cli/data_commands.py \
  services/quant-api/tests/data_foundation/test_cli.py
git commit -m "feat(data): support scoped audit"
~~~

### Task 2: Align the public contract and verify the repository change

**Files:**

- Modify: docs/DATA_CENTER.md:94-99
- Modify: TESTING.md:42-46
- Modify: openspec/changes/converge-canonical-data-foundation/specs/historical-data-maintenance/spec.md:7-10

**Interfaces:**

- Consumes: the selector contract delivered by Task 1.
- Produces: one audit syntax and read-only meaning in active documentation.

- [ ] **Step 1: Update each active command reference.**

Use this exact syntax in docs/DATA_CENTER.md and TESTING.md:

~~~text
guiyi data audit (--symbol X | --universe active)
~~~

Add this no-write smoke command in TESTING.md:

~~~bash
uv run --project services/quant-api guiyi data audit --symbol jm
~~~

In the OpenSpec maintenance requirement, state that audit accepts the same mutually exclusive selector and remains read-only.

- [ ] **Step 2: Run contract and code-quality verification.**

Run:

~~~bash
openspec validate converge-canonical-data-foundation --strict --no-interactive
uv run --project services/quant-api ruff check \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests/data_foundation/test_cli.py
git -c core.fsmonitor=false diff --check
~~~

Expected: all commands exit zero.

- [ ] **Step 3: Commit the contract update.**

~~~bash
git add docs/DATA_CENTER.md TESTING.md \
  openspec/changes/converge-canonical-data-foundation/specs/historical-data-maintenance/spec.md
git commit -m "docs(data): document scoped audit"
~~~

### Task 3: Execute the fixed-T0 four-exchange read-only canary preflight

**Files:**

- Create: none.
- Modify: none.
- Test: production read-only command output only.

**Interfaces:**

- Consumes: scoped data audit, production eight-table Catalog, and active_products.txt.
- Produces: a terminal-only baseline with revision, Canonical root, J/JM partition counts, four deterministic candidates, and audit/dry-run outcomes.

- [ ] **Step 1: Select candidates with one in-memory read-only inventory query.**

Load active symbols from active_products.txt; select Instrument.exchange_code, Instrument.symbol, and count(MarketPartition.id) with outer joins through MarketDataset; group and order by exchange and symbol. Print no environment variables, database URLs, raw SQL, credentials, or data rows. Use this selection core:

~~~python
target_exchanges = ("CZCE", "SHFE", "INE", "GFEX")
candidates: dict[str, str] = {}
for exchange, symbol, partition_count in rows:
    if (
        exchange in target_exchanges
        and symbol not in {"j", "jm"}
        and partition_count == 0
    ):
        candidates.setdefault(exchange, symbol)
assert tuple(candidates) == target_exchanges
~~~

Also print only Alembic revision, Canonical root, active count, and J/JM partition counts. If an exchange lacks a candidate, report CANARY_CANDIDATE_UNAVAILABLE and stop; do not substitute another exchange.

- [ ] **Step 2: Capture the universe audit first blocker.**

Run:

~~~bash
uv run --project services/quant-api guiyi data audit --universe active
~~~

Expected: nonzero until all 60 products are complete. Record the first returned finding code and scope; do not treat this expected result as an implementation failure.

- [ ] **Step 3: Run scoped audit and fixed-T0 dry-run for every selected symbol.**

For each candidate, run:

~~~bash
uv run --project services/quant-api guiyi data audit --symbol <symbol>
uv run --project services/quant-api guiyi data update --symbol <symbol> --through 2026-08-07
~~~

Expected: neither command has --apply; neither command requests a provider or writes data. A metadata or session failure is a canary blocker only.

- [ ] **Step 4: Repeat inventory and compare read-only state.**

Compare Alembic revision, active count, J/JM partition counts, and selected candidate partition counts with Step 1. Any difference is READ_ONLY_PREFLIGHT_STATE_CHANGED; stop without repair. Otherwise report the results as a read-only baseline only.
