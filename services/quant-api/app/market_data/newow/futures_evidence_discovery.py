"""Guards shared by the owner-gated Newow futures coverage discovery runner."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.sql.base import Executable

from guiyi_quant.newow import WalkForwardFold

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    DatasetKey,
    DatasetKind,
)
from app.market_data.newow.futures_evidence_plan import (
    FuturesEvidenceCandidate,
    build_natural_year_folds,
    select_futures_evidence_products,
)


FROZEN_FREQUENCIES = ("1d", "1w", "60m")
SHANGHAI = ZoneInfo("Asia/Shanghai")
REQUIRED_READ_TABLES = (
    "exchanges",
    "contracts",
    "instruments",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "market_datasets",
    "market_partitions",
)


class ReadOnlyDiscoveryError(RuntimeError):
    """Stable fail-closed error for the discovery runner boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    base_sha: str
    owner_approved_run_id: str
    frequencies: tuple[str, ...]
    minimum_rollovers: int
    output_dir: Path


@dataclass(frozen=True, slots=True)
class CanonicalFileDigest:
    relative_path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CoverageDiscoveryResult:
    candidates: tuple[FuturesEvidenceCandidate, ...]
    selected: tuple[FuturesEvidenceCandidate, ...]
    common_since: date
    common_through: date
    complete_years: tuple[int, ...]
    folds: tuple[WalkForwardFold, ...]


class _CatalogForCoverage(Protocol):
    def main_map_before(self, symbol: str, before: datetime | None) -> Sequence[object]: ...

    def all_partitions(self, key: DatasetKey) -> Sequence[object]: ...

    def calendar_days(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> Sequence[tuple[date, bool]]: ...


class _ReadOnlySession(Protocol):
    @property
    def new(self) -> Collection[Any]: ...

    @property
    def dirty(self) -> Collection[Any]: ...

    @property
    def deleted(self) -> Collection[Any]: ...

    def execute(self, statement: Executable) -> Any: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


SessionT = TypeVar("SessionT", bound=_ReadOnlySession)


class _MarketDataForCoverage(Protocol):
    def actual_dominant_segments(
        self,
        symbol: str,
        since: date,
        through: date,
    ) -> Sequence[object]: ...

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> Any: ...


class _RecordingCanonicalStore:
    """Record exactly which Catalog-resolved partitions MarketDataService reads."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.read_paths: set[Path] = set()

    def read_catalog_partition(self, partition: object) -> Any:
        file_path = getattr(partition, "file_path", None)
        if not isinstance(file_path, Path):
            raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
        self.read_paths.add(file_path)
        return self._delegate.read_catalog_partition(partition)


def validate_discovery_request(
    request: DiscoveryRequest,
    *,
    expected_base_sha: str,
    report_root: Path,
    canonical_root: Path,
) -> DiscoveryRequest:
    """Validate immutable discovery inputs before a session can be created."""

    if request.base_sha != expected_base_sha:
        raise ReadOnlyDiscoveryError("BASE_SHA_DRIFT")
    if (
        request.frequencies != FROZEN_FREQUENCIES
        or request.minimum_rollovers != 2
        or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,127}", request.owner_approved_run_id)
    ):
        raise ReadOnlyDiscoveryError("DISCOVERY_PARAMETERS_INVALID")

    resolved_output = request.output_dir.resolve()
    resolved_report_root = report_root.resolve()
    resolved_canonical_root = canonical_root.resolve()
    if (
        not _is_relative_to(resolved_output, resolved_report_root)
        or resolved_output.parent != resolved_report_root
        or resolved_output.name != request.owner_approved_run_id
        or _is_relative_to(resolved_output, resolved_canonical_root)
    ):
        raise ReadOnlyDiscoveryError("EVIDENCE_OUTPUT_PATH_INVALID")
    return DiscoveryRequest(
        base_sha=request.base_sha,
        owner_approved_run_id=request.owner_approved_run_id,
        frequencies=request.frequencies,
        minimum_rollovers=request.minimum_rollovers,
        output_dir=resolved_output,
    )


@contextmanager
def read_only_session(factory: Callable[[], SessionT]) -> Iterator[SessionT]:
    """Open a database session guarded against mutation and always roll it back."""

    session = factory()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        state = session.execute(text("SHOW transaction_read_only"))
        if state.scalar_one() != "on" or not _session_is_clean(session):
            raise ReadOnlyDiscoveryError("READ_ONLY_SESSION_INVALID")
        yield session
        if not _session_is_clean(session):
            raise ReadOnlyDiscoveryError("READ_ONLY_SESSION_INVALID")
    finally:
        session.rollback()
        session.close()


def validate_select_only_privileges(
    table_privileges: Mapping[str, Sequence[str] | set[str] | frozenset[str]],
) -> None:
    """Require exactly the approved Catalog table set and SELECT-only access."""

    if set(table_privileges) != set(REQUIRED_READ_TABLES) or any(
        set(table_privileges[table]) != {"SELECT"}
        for table in REQUIRED_READ_TABLES
    ):
        raise ReadOnlyDiscoveryError("READ_ONLY_ROLE_INVALID")


def canonical_file_manifest(
    file_paths: Sequence[Path],
    *,
    canonical_root: Path,
) -> tuple[CanonicalFileDigest, ...]:
    """Hash only exact files previously resolved by the Catalog."""

    root = canonical_root.resolve()
    digests: list[CanonicalFileDigest] = []
    for file_path in file_paths:
        if file_path.is_symlink():
            raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
        resolved = file_path.resolve()
        if not _is_relative_to(resolved, root) or not resolved.is_file():
            raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
        stat = resolved.stat()
        digest = sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digests.append(
            CanonicalFileDigest(
                relative_path=resolved.relative_to(root).as_posix(),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=digest.hexdigest(),
            )
        )
    if len({item.relative_path for item in digests}) != len(digests):
        raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
    return tuple(digests)


def discover_coverage_candidates(
    catalog: _CatalogForCoverage,
    *,
    operational_products: Sequence[str],
    taxonomy: Mapping[str, object],
) -> tuple[FuturesEvidenceCandidate, ...]:
    """Derive fail-closed candidates from exact mapped contract partitions only.

    A candidate exists only for the longest contiguous rank-1 mapping run where
    every mapped physical contract is covered by every frozen frequency.  This
    function intentionally inspects Catalog metadata only; the runner validates
    the selected ranges through ``MarketDataService`` before writing artifacts.
    """

    candidates: list[FuturesEvidenceCandidate] = []
    for product in operational_products:
        rows = tuple(catalog.main_map_before(product, None))
        if not rows or product not in taxonomy:
            continue
        eligible_runs = _complete_coverage_runs(catalog, product=product, rows=rows)
        if not eligible_runs:
            continue
        eligible_rows = max(
            eligible_runs,
            key=lambda run: (
                (_row_trading_day(run[-1]) - _row_trading_day(run[0])).days,
                -_row_trading_day(run[0]).toordinal(),
            ),
        )
        if _rollover_count(eligible_rows) < 2:
            continue
        first = eligible_rows[0]
        last = eligible_rows[-1]
        sector = getattr(taxonomy[product], "sector", None)
        if not isinstance(sector, str) or not sector:
            continue
        candidates.append(
            FuturesEvidenceCandidate(
                product=product,
                sector=sector,
                common_since=_row_trading_day(first),
                common_through=_row_trading_day(last),
                rollover_count=_rollover_count(eligible_rows),
                operational=True,
                frequencies=FROZEN_FREQUENCIES,
            )
        )
    return tuple(candidates)


def validate_candidate_market_data(
    market_data: _MarketDataForCoverage,
    candidate: object,
) -> None:
    """Read each frozen actual-dominant frequency without evaluating a strategy."""

    product = getattr(candidate, "product", None)
    since = getattr(candidate, "common_since", None)
    through = getattr(candidate, "common_through", None)
    expected_rollovers = getattr(candidate, "rollover_count", None)
    if (
        not isinstance(product, str)
        or not isinstance(since, date)
        or not isinstance(through, date)
        or type(expected_rollovers) is not int
    ):
        raise ReadOnlyDiscoveryError("ACTUAL_DOMINANT_COVERAGE_INVALID")
    segments = market_data.actual_dominant_segments(product, since, through)
    if not segments or len(segments) - 1 != expected_rollovers:
        raise ReadOnlyDiscoveryError("ACTUAL_DOMINANT_COVERAGE_INVALID")
    for frequency_value in FROZEN_FREQUENCIES:
        result = market_data.query_actual_dominant_trading_days(
            ActualDominantTradingDayQuery(
                product,
                BarFrequency(frequency_value),
                since,
                through,
            )
        )
        bars = getattr(result, "bars", ())
        identity = getattr(result, "request_identity", None)
        if (
            not isinstance(identity, Mapping)
            or set(identity) != {
                "series_kind",
                "symbol",
                "contract",
                "frequency",
                "start",
                "end",
            }
            or identity["series_kind"] != "actual_dominant"
            or identity["symbol"] != product
            or identity["contract"] is not None
            or identity["frequency"] != frequency_value
            or not isinstance(identity["start"], str)
            or not isinstance(identity["end"], str)
            or not bars
            or getattr(result, "coverage", None)
            != (getattr(bars[0], "bar_end", None), getattr(bars[-1], "bar_end", None))
            or getattr(result, "requested_trading_day_window", None) != (since, through)
            or not _result_segments_match_authority(
                result_segments=tuple(getattr(result, "resolved_contract_segments", ())),
                authoritative_segments=tuple(segments),
                bars=tuple(bars),
                allow_frequency_subset=frequency_value == "1w",
            )
        ):
            raise ReadOnlyDiscoveryError("ACTUAL_DOMINANT_COVERAGE_INVALID")


def _result_segments_match_authority(
    *,
    result_segments: tuple[object, ...],
    authoritative_segments: tuple[object, ...],
    bars: tuple[object, ...],
    allow_frequency_subset: bool,
) -> bool:
    """Validate physical owners; only W1 may omit incomplete-week segments."""

    normalized_result = tuple(_segment_interval(segment) for segment in result_segments)
    normalized_authoritative = tuple(
        _segment_interval(segment) for segment in authoritative_segments
    )
    if (
        not normalized_result
        or not normalized_authoritative
        or any(item is None for item in (*normalized_result, *normalized_authoritative))
    ):
        return False
    result_intervals = tuple(item for item in normalized_result if item is not None)
    authoritative_intervals = tuple(
        item for item in normalized_authoritative if item is not None
    )
    if not allow_frequency_subset and result_intervals != authoritative_intervals:
        return False
    for contract, start, end in result_intervals:
        owners = tuple(
            interval
            for interval in authoritative_intervals
            if interval[0] == contract and interval[1] <= start and end <= interval[2]
        )
        if len(owners) != 1:
            return False
    for bar in bars:
        trading_day = getattr(bar, "trading_day", None)
        if type(trading_day) is not date:
            return False
        result_owners = tuple(
            interval
            for interval in result_intervals
            if interval[1] <= trading_day <= interval[2]
        )
        authoritative_owners = tuple(
            interval
            for interval in authoritative_intervals
            if interval[1] <= trading_day <= interval[2]
        )
        if (
            len(result_owners) != 1
            or len(authoritative_owners) != 1
            or result_owners[0][0] != authoritative_owners[0][0]
        ):
            return False
    return True


def _segment_interval(segment: object) -> tuple[str, date, date] | None:
    contract = getattr(segment, "contract", None)
    start = getattr(segment, "start_trading_day", None)
    end = getattr(segment, "end_trading_day", None)
    if not isinstance(contract, str) or type(start) is not date or type(end) is not date:
        return None
    if not contract or start > end:
        return None
    return contract, start, end


def build_discovery_result(
    catalog: _CatalogForCoverage,
    market_data: _MarketDataForCoverage,
    *,
    operational_products: Sequence[str],
    taxonomy: Mapping[str, object],
) -> CoverageDiscoveryResult:
    """Freeze deterministic candidates, then validate each selected read scope."""

    candidates = discover_coverage_candidates(
        catalog,
        operational_products=operational_products,
        taxonomy=taxonomy,
    )
    selected = _select_candidates(candidates)
    for candidate in selected:
        validate_candidate_market_data(market_data, candidate)
    return _freeze_discovery_result(catalog, candidates=candidates, selected=selected)


def _freeze_discovery_result(
    catalog: _CatalogForCoverage,
    *,
    candidates: tuple[FuturesEvidenceCandidate, ...],
    selected: tuple[FuturesEvidenceCandidate, ...],
) -> CoverageDiscoveryResult:
    common_since, common_through, products = _selected_common_coverage(selected)
    complete_years = _calendar_proven_complete_years(
        catalog,
        products,
        common_since=common_since,
        common_through=common_through,
    )
    try:
        folds = build_natural_year_folds(
            common_since,
            common_through,
            complete_years=complete_years,
        )
    except ValueError as exc:
        raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED") from exc
    return CoverageDiscoveryResult(
        candidates=candidates,
        selected=selected,
        common_since=common_since,
        common_through=common_through,
        complete_years=complete_years,
        folds=folds,
    )


def calendar_proven_natural_year_folds(
    catalog: _CatalogForCoverage,
    selected: Sequence[object],
) -> tuple[object, ...]:
    """Freeze folds only where every selected exchange has a complete calendar year.

    The candidate coverage interval is a market-data fact.  Calendar rows add
    the independent proof that an apparent Jan-1/Dec-31 window did not skip a
    holiday, an exchange-calendar partition, or an entire trading day.
    """

    common_since, common_through, products = _selected_common_coverage(selected)
    complete_years = _calendar_proven_complete_years(
        catalog,
        products,
        common_since=common_since,
        common_through=common_through,
    )
    try:
        return build_natural_year_folds(
            common_since,
            common_through,
            complete_years=complete_years,
        )
    except ValueError as exc:
        raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED") from exc


def _selected_common_coverage(
    selected: Sequence[object],
) -> tuple[date, date, tuple[str, ...]]:
    candidates = tuple(selected)
    if not candidates:
        raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED")
    products: list[str] = []
    since_values: list[date] = []
    through_values: list[date] = []
    for candidate in candidates:
        product = getattr(candidate, "product", None)
        since = getattr(candidate, "common_since", None)
        through = getattr(candidate, "common_through", None)
        if (
            not isinstance(product, str)
            or not product
            or type(since) is not date
            or type(through) is not date
            or since > through
        ):
            raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED")
        products.append(product)
        since_values.append(since)
        through_values.append(through)

    common_since = max(since_values)
    common_through = min(through_values)
    if common_since > common_through:
        raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED")
    return common_since, common_through, tuple(products)


def _calendar_proven_complete_years(
    catalog: _CatalogForCoverage,
    products: Sequence[str],
    *,
    common_since: date,
    common_through: date,
) -> tuple[int, ...]:
    complete_years: list[int] = []
    for year in range(common_since.year, common_through.year + 1):
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        if year_start < common_since or year_end > common_through:
            continue
        if all(
            _calendar_year_is_complete(catalog, product, year_start, year_end)
            for product in products
        ):
            complete_years.append(year)
    return tuple(complete_years)


def _calendar_year_is_complete(
    catalog: _CatalogForCoverage,
    product: str,
    start: date,
    end: date,
) -> bool:
    rows = tuple(catalog.calendar_days(product, start, end))
    expected_days = tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )
    if len(rows) != len(expected_days):
        return False
    return all(
        isinstance(row, tuple)
        and len(row) == 2
        and row[0] == expected
        and type(row[1]) is bool
        for row, expected in zip(rows, expected_days, strict=True)
    )


def run_discovery_with_dependencies(
    request: DiscoveryRequest,
    *,
    expected_base_sha: str,
    report_root: Path,
    canonical_root: Path,
    session_factory: Callable[[], SessionT],
    table_privileges: Mapping[str, Sequence[str] | set[str] | frozenset[str]],
    catalog_factory: Callable[[SessionT], _CatalogForCoverage],
    market_data_factory: Callable[[_CatalogForCoverage], _MarketDataForCoverage],
    operational_products: Sequence[str],
    taxonomy: Mapping[str, object],
) -> CoverageDiscoveryResult:
    """Execute discovery behind the complete read-only preflight boundary.

    This dependency-injected seam is intentionally free of environment and
    filesystem output behavior, so production reads and report writes remain
    independently reviewable.
    """

    validate_discovery_request(
        request,
        expected_base_sha=expected_base_sha,
        report_root=report_root,
        canonical_root=canonical_root,
    )
    with read_only_session(session_factory) as session:
        validate_select_only_privileges(table_privileges)
        catalog = catalog_factory(session)
        return build_discovery_result(
            catalog,
            market_data_factory(catalog),
            operational_products=operational_products,
            taxonomy=taxonomy,
        )


def write_discovery_artifacts(
    output_dir: Path,
    result: CoverageDiscoveryResult,
    *,
    canonical_manifest: Sequence[CanonicalFileDigest],
) -> None:
    """Write the bounded discovery artifacts to one previously approved directory."""

    if output_dir.exists():
        raise ReadOnlyDiscoveryError("EVIDENCE_OUTPUT_PATH_INVALID")
    output_dir.mkdir(parents=True)
    _write_json(
        output_dir / "selection.json",
        {
            "selected_products": [candidate.product for candidate in result.selected],
            "selected": [_candidate_record(candidate) for candidate in result.selected],
        },
    )
    _write_json(
        output_dir / "folds.json",
        {
            "common_since": result.common_since.isoformat(),
            "common_through": result.common_through.isoformat(),
            "complete_years": list(result.complete_years),
            "folds": [
                {
                    "name": fold.name,
                    "train_since": fold.train_since.isoformat(),
                    "train_through": fold.train_through.isoformat(),
                    "test_since": fold.test_since.isoformat(),
                    "test_through": fold.test_through.isoformat(),
                }
                for fold in result.folds
            ],
        },
    )
    with (output_dir / "coverage.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "product",
                "sector",
                "common_since",
                "common_through",
                "rollover_count",
                "frequencies",
            ),
        )
        writer.writeheader()
        for candidate in result.candidates:
            writer.writerow(
                {
                    **_candidate_record(candidate),
                    "frequencies": ",".join(candidate.frequencies),
                }
            )
    _write_json(
        output_dir / "input_hashes.json",
        {
            "canonical_files": [
                {
                    "relative_path": digest.relative_path,
                    "sha256": digest.sha256,
                    "size": digest.size,
                    "mtime_ns": digest.mtime_ns,
                }
                for digest in canonical_manifest
            ]
        },
    )
    _write_json(
        output_dir / "zero_write_proof.json",
        {
            "canonical_manifest_unchanged": True,
            "canonical_manifest_covers_actual_reads": True,
            "database_transaction": "READ ONLY",
            "orm_session_clean": True,
        },
    )


def validate_canonical_read_window(
    market_data: Any,
    candidates: Sequence[FuturesEvidenceCandidate],
    *,
    paths: Sequence[Path],
    canonical_root: Path,
) -> tuple[CanonicalFileDigest, ...]:
    """Hash every bounded read target both before and after success or failure."""

    before_manifest = canonical_file_manifest(paths, canonical_root=canonical_root)
    original_store = market_data.store
    recording_store = _RecordingCanonicalStore(original_store)
    read_error: BaseException | None = None
    market_data.store = recording_store
    try:
        for candidate in candidates:
            validate_candidate_market_data(market_data, candidate)
    except BaseException as exc:
        read_error = exc
    finally:
        market_data.store = original_store
        after_manifest = canonical_file_manifest(paths, canonical_root=canonical_root)
    if before_manifest != after_manifest:
        raise ReadOnlyDiscoveryError("CANONICAL_MANIFEST_DRIFT")
    assert_manifest_covers_actual_reads(paths, recording_store.read_paths)
    if read_error is not None:
        raise read_error
    return before_manifest


def _candidate_record(candidate: FuturesEvidenceCandidate) -> dict[str, str | int]:
    return {
        "product": candidate.product,
        "sector": candidate.sector,
        "common_since": candidate.common_since.isoformat(),
        "common_through": candidate.common_through.isoformat(),
        "rollover_count": candidate.rollover_count,
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def run_discovery(
    *,
    base_sha: str,
    owner_approved_run_id: str,
    frequencies: tuple[str, ...],
    minimum_rollovers: int,
    output_dir: str,
) -> int:
    """Run exactly one owner-gated coverage discovery with no market mutations."""

    from app.core.env import PROJECT_ROOT
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service, canonical_root
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.product_taxonomy import load_product_taxonomy

    project_root = PROJECT_ROOT.resolve()
    canonical = canonical_root()
    request = validate_discovery_request(
        DiscoveryRequest(
            base_sha=base_sha,
            owner_approved_run_id=owner_approved_run_id,
            frequencies=frequencies,
            minimum_rollovers=minimum_rollovers,
            output_dir=Path(output_dir),
        ),
        expected_base_sha=_git_stdout(project_root, "rev-parse", "origin/develop"),
        report_root=project_root / "data/reports/newow_page_v2_real_futures_evidence",
        canonical_root=canonical,
    )
    if _git_status(project_root):
        raise ReadOnlyDiscoveryError("GIT_WORKTREE_DIRTY")

    with read_only_session(SessionLocal) as session:
        validate_select_only_privileges(_read_table_privileges(session))
        market_data = build_market_data_service(session)
        candidates = discover_coverage_candidates(
            market_data.catalog,
            operational_products=load_operational_products(),
            taxonomy=load_product_taxonomy(),
        )
        selected = _select_candidates(candidates)
        paths = catalog_paths_for_candidates(market_data.catalog, selected)
        before_manifest = validate_canonical_read_window(
            market_data,
            selected,
            paths=paths,
            canonical_root=canonical,
        )
        result = _freeze_discovery_result(
            market_data.catalog,
            candidates=candidates,
            selected=selected,
        )

    if _git_status(project_root):
        raise ReadOnlyDiscoveryError("GIT_WORKTREE_DIRTY")
    write_discovery_artifacts(
        request.output_dir,
        result,
        canonical_manifest=before_manifest,
    )
    _assert_only_report_changed(project_root, request.output_dir)
    return 0


def _read_table_privileges(session: _ReadOnlySession) -> dict[str, set[str]]:
    rows = session.execute(
        text(
            "SELECT tables.table_name, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'SELECT') AS can_select, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'INSERT') AS can_insert, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'UPDATE') AS can_update, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'DELETE') AS can_delete, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'TRUNCATE') AS can_truncate, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'REFERENCES') AS can_references, "
            "has_table_privilege(current_user, format('%I.%I', tables.table_schema, tables.table_name), 'TRIGGER') AS can_trigger "
            "FROM information_schema.tables AS tables "
            "WHERE tables.table_schema = current_schema() "
            "AND tables.table_type = 'BASE TABLE' "
            "ORDER BY tables.table_name"
        )
    ).mappings()
    privileges: dict[str, set[str]] = {}
    for row in rows:
        table = str(row["table_name"])
        granted = {
            privilege
            for privilege, permitted in (
                ("SELECT", row["can_select"]),
                ("INSERT", row["can_insert"]),
                ("UPDATE", row["can_update"]),
                ("DELETE", row["can_delete"]),
                ("TRUNCATE", row["can_truncate"]),
                ("REFERENCES", row["can_references"]),
                ("TRIGGER", row["can_trigger"]),
            )
            if permitted
        }
        if granted:
            privileges[table] = granted
    return privileges


def catalog_paths_for_candidates(
    catalog: _CatalogForCoverage,
    candidates: Sequence[FuturesEvidenceCandidate],
) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for candidate in candidates:
        for row in catalog.main_map_before(candidate.product, None):
            trading_day = _row_trading_day(row)
            if not candidate.common_since <= trading_day <= candidate.common_through:
                continue
            contract = getattr(row, "contract", None)
            if not isinstance(contract, str) or not contract:
                raise ReadOnlyDiscoveryError("MAIN_CONTRACT_MAP_INVALID")
            for frequency_value in FROZEN_FREQUENCIES:
                key = DatasetKey(
                    kind=DatasetKind.CONTRACT,
                    symbol=candidate.product,
                    series_or_contract=contract,
                    frequency=BarFrequency(frequency_value),
                )
                for partition in catalog.all_partitions(key):
                    file_path = getattr(partition, "file_path", None)
                    if not isinstance(file_path, Path):
                        raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
                    paths.add(file_path)
    if not paths:
        raise ReadOnlyDiscoveryError("CANONICAL_PATH_INVALID")
    return tuple(sorted(paths))


def _select_candidates(
    candidates: tuple[FuturesEvidenceCandidate, ...],
) -> tuple[FuturesEvidenceCandidate, ...]:
    try:
        return select_futures_evidence_products(candidates)
    except ValueError as exc:
        raise ReadOnlyDiscoveryError("NEWOW_EVIDENCE_PRODUCT_SELECTION_BLOCKED") from exc


def _git_stdout(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ReadOnlyDiscoveryError("GIT_STATE_UNAVAILABLE")
    return completed.stdout.strip()


def _git_status(project_root: Path) -> tuple[str, ...]:
    output = _git_stdout(project_root, "status", "--porcelain")
    return tuple(line for line in output.splitlines() if line)


def _assert_only_report_changed(project_root: Path, output_dir: Path) -> None:
    relative_output = output_dir.resolve().relative_to(project_root.resolve()).as_posix()
    changed = _git_status(project_root)
    if not only_approved_report_paths(changed, relative_output):
        raise ReadOnlyDiscoveryError("GIT_WORKTREE_DIRTY")


def only_approved_report_paths(changed: Sequence[str], relative_output: str) -> bool:
    """Accept only untracked files below one exact approved report directory."""

    prefix = f"{relative_output.rstrip('/')}/"
    def is_approved(line: str) -> bool:
        if not line.startswith("?? "):
            return False
        path = line[3:].rstrip("/")
        return path == relative_output or path.startswith(prefix)

    return bool(changed) and all(is_approved(line) for line in changed)


def assert_manifest_covers_actual_reads(
    manifest_paths: Sequence[Path],
    actual_read_paths: Collection[Path],
) -> None:
    """Ensure the before/after manifest covers each partition read by the service."""

    if not set(actual_read_paths) <= set(manifest_paths):
        raise ReadOnlyDiscoveryError("CANONICAL_MANIFEST_SCOPE_INVALID")


def _row_has_frozen_coverage(
    catalog: _CatalogForCoverage,
    *,
    product: str,
    row: object,
) -> bool:
    contract = getattr(row, "contract", None)
    trading_day = _row_trading_day(row)
    if not isinstance(contract, str) or not contract:
        return False
    for frequency_value in FROZEN_FREQUENCIES:
        partitions = catalog.all_partitions(
            DatasetKey(
                kind=DatasetKind.CONTRACT,
                symbol=product,
                series_or_contract=contract,
                frequency=BarFrequency(frequency_value),
            )
        )
        if not any(_partition_covers_day(partition, trading_day) for partition in partitions):
            return False
    return True


def _complete_coverage_runs(
    catalog: _CatalogForCoverage,
    *,
    product: str,
    rows: Sequence[object],
) -> tuple[tuple[object, ...], ...]:
    """Return contiguous mapping runs whose owners all have frozen coverage."""

    runs: list[tuple[object, ...]] = []
    current: list[object] = []
    for row in rows:
        if _row_has_frozen_coverage(catalog, product=product, row=row):
            current.append(row)
            continue
        if current:
            runs.append(tuple(current))
            current = []
    if current:
        runs.append(tuple(current))
    return tuple(runs)


def _partition_covers_day(partition: object, trading_day: date) -> bool:
    start = getattr(partition, "coverage_start", None)
    end = getattr(partition, "coverage_end", None)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return False
    return start.astimezone(SHANGHAI).date() <= trading_day <= end.astimezone(SHANGHAI).date()


def _row_trading_day(row: object) -> date:
    trading_day = getattr(row, "trade_date", None)
    if not isinstance(trading_day, date):
        raise ReadOnlyDiscoveryError("MAIN_CONTRACT_MAP_INVALID")
    return trading_day


def _rollover_count(rows: Sequence[object]) -> int:
    contracts = tuple(getattr(row, "contract", None) for row in rows)
    if any(not isinstance(contract, str) or not contract for contract in contracts):
        raise ReadOnlyDiscoveryError("MAIN_CONTRACT_MAP_INVALID")
    return sum(
        current != previous
        for previous, current in zip(contracts, contracts[1:], strict=False)
    )


def _session_is_clean(session: _ReadOnlySession) -> bool:
    return not session.new and not session.dirty and not session.deleted


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
