"""Migration-only Gate A candidate operator helpers.

FROZEN pending Gate C removal. New Gate A MUST use
``build_candidate_historical_data_manager`` + RQData-only ``update`` against an
isolated Candidate DB/root. This exact-scope/legacy flow MUST NOT gain features.
Not wired into the daily ``guiyi data`` CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.env import PROJECT_ROOT
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.composition import (
    build_candidate_bootstrap_manager,
    build_candidate_historical_data_manager,
    canonical_root,
)
from app.market_data.domain import ALL_FREQUENCIES, SeriesKind, SeriesQuery
from app.market_data.infrastructure import DatabaseCoverageSource
from app.market_data.legacy_bootstrap import plan_gate_a_scope, scan_legacy_coverages
from app.market_data.maintenance import (
    AuditRequest,
    BootstrapRequest,
    MaintenanceResult,
    UpdateRequest,
)
from app.market_data.service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.models import TradingSession
from app.models.data_core import DataGap, MarketDataset, MarketPartition

SHANGHAI = ZoneInfo("Asia/Shanghai")


WRAPPER_FIELDS = frozenset({"candidate_catalog", "dry_run_evidence", "report_sha256"})
EXPECTED_REVISION = "20260808_0036"


class GateAOperatorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CandidateRunConfig:
    """RQData-only Candidate run targeting an isolated DB + canonical root."""

    through: date
    candidate_root: Path
    candidate_catalog: str
    products: tuple[str, ...]


def default_candidate_root(through: date) -> Path:
    return (
        PROJECT_ROOT
        / "data/canonical-candidates/converge-canonical-data-foundation"
        / f"through={through.isoformat()}"
    ).resolve()


def reset_candidate_storage(candidate_root: Path) -> dict[str, int]:
    """Delete Parquet/Manifest under candidate root; does not touch evidence dirs."""
    root = candidate_root.resolve()
    if not root.is_dir():
        return {"deleted_paths": 0}
    deleted = 0
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and path.name in {"part.parquet", "manifest.json"}:
            path.unlink()
            deleted += 1
        elif path.is_dir() and path.name.startswith("kind="):
            try:
                path.rmdir()
                deleted += 1
            except OSError:
                pass
    return {"deleted_paths": deleted}


def run_rqdata_preflight(
    config: CandidateRunConfig,
    *,
    database_url: str,
    resume: bool = False,
) -> dict[str, Any]:
    assert_isolated_database(database_url, config.candidate_catalog)
    assert_candidate_root_isolated(config.candidate_root, canonical_root())
    assert_candidate_root_ready(config.candidate_root, resume=resume)
    session = open_candidate_session(database_url)
    try:
        revision = read_alembic_revision(session)
        if revision != EXPECTED_REVISION:
            raise GateAOperatorError("GATE_A_DATABASE_REVISION_MISMATCH")
        counts = read_catalog_counts(session)
        if not resume and (
            counts["market_datasets"] != 0 or counts["market_partitions"] != 0
        ):
            raise GateAOperatorError("GATE_A_CATALOG_NOT_EMPTY")
        coverage = DatabaseCoverageSource(
            session,
            PROJECT_ROOT / "data/universe/product_window_starts.csv",
        )
        starts = {symbol: coverage.product_start(symbol) for symbol in config.products}
        return {
            "action": "candidate_rqdata_preflight",
            "status": "passed",
            "through": config.through.isoformat(),
            "candidate_root": config.candidate_root.as_posix(),
            "candidate_catalog": config.candidate_catalog,
            "database_revision": revision,
            "catalog_counts": counts,
            "resume": resume,
            "products": list(config.products),
            "effective_starts": {k: v.isoformat() for k, v in starts.items()},
            "history_floor": coverage.history_floor.isoformat(),
        }
    finally:
        session.close()


def run_rqdata_update(
    config: CandidateRunConfig,
    *,
    session: Session,
    apply: bool,
    require_intent_token: bool = True,
    intent_confirmed: bool = False,
) -> dict[str, Any]:
    if apply and require_intent_token and not intent_confirmed:
        raise GateAOperatorError("GATE_A_APPLY_INTENT_REQUIRED")
    assert_candidate_root_isolated(config.candidate_root, canonical_root())
    if apply:
        config.candidate_root.mkdir(parents=True, exist_ok=True)
    manager = build_candidate_historical_data_manager(session, config.candidate_root)
    result = manager.update(
        UpdateRequest(
            products=config.products,
            since=None,
            through=config.through,
            apply=apply,
        )
    )
    payload = result.as_payload() if isinstance(result, MaintenanceResult) else dict(result)
    return {
        "action": "candidate_rqdata_update",
        "apply": apply,
        "through": config.through.isoformat(),
        "candidate_root": config.candidate_root.as_posix(),
        "products": list(config.products),
        "update": payload,
        **{
            key: payload[key]
            for key in ("status", "planned", "applied", "failed", "blocked", "provider_requests")
            if key in payload
        },
    }


def run_rqdata_audit(
    config: CandidateRunConfig,
    *,
    session: Session,
) -> dict[str, Any]:
    assert_candidate_root_isolated(config.candidate_root, canonical_root())
    manager = build_candidate_historical_data_manager(session, config.candidate_root)
    audit = manager.audit(AuditRequest(config.products))
    payload = audit.as_payload()
    return {
        "action": "candidate_rqdata_audit",
        "status": "passed" if audit.status == "passed" else "failed",
        "through": config.through.isoformat(),
        "candidate_root": config.candidate_root.as_posix(),
        "catalog_counts": read_catalog_counts(session),
        "audit": payload,
        "finding_count": payload.get("finding_count", len(audit.findings)),
    }


def run_rqdata_verify(
    config: CandidateRunConfig,
    *,
    session: Session,
) -> dict[str, Any]:
    assert_candidate_root_isolated(config.candidate_root, canonical_root())
    manager = build_candidate_historical_data_manager(session, config.candidate_root)
    audit = manager.audit(AuditRequest(config.products))
    catalog_counts = read_catalog_counts(session)
    service = MarketDataService(
        manager.catalog,
        CanonicalMonthlyStore(config.candidate_root),
    )
    start, end = _probe_window(config.through)
    probes: list[dict[str, Any]] = []
    for symbol in config.products[:3]:
        for frequency in sorted(ALL_FREQUENCIES, key=lambda item: item.value):
            for series_kind in (SeriesKind.CONTINUOUS, SeriesKind.ACTUAL_DOMINANT):
                item: dict[str, Any] = {
                    "symbol": symbol,
                    "frequency": frequency.value,
                    "series_kind": series_kind.value,
                }
                try:
                    result = service.query(
                        SeriesQuery(
                            series_kind=series_kind,
                            symbol=symbol,
                            frequency=frequency,
                            start=start,
                            end=end,
                        )
                    )
                    item["status"] = "ok"
                    item["bars"] = len(result.bars)
                except MarketDataError as exc:
                    item["status"] = "failed"
                    item["error"] = exc.code
                except Exception as exc:  # noqa: BLE001 - probe summary only
                    item["status"] = "failed"
                    item["error"] = type(exc).__name__
                probes.append(item)
    noop = manager.update(
        UpdateRequest(
            products=config.products,
            since=None,
            through=config.through,
            apply=False,
        )
    )
    status = "passed"
    if audit.status != "passed" or catalog_counts["data_gaps"] != 0:
        status = "failed"
    if any(item.get("status") != "ok" for item in probes):
        status = "failed"
    if noop.planned != 0 or noop.provider_requests != 0:
        status = "failed"
    return {
        "action": "candidate_rqdata_verify",
        "status": status,
        "through": config.through.isoformat(),
        "candidate_root": config.candidate_root.as_posix(),
        "catalog_counts": catalog_counts,
        "audit": audit.as_payload(),
        "noop_update": noop.as_payload(),
        "mds_probes": probes,
        "probe_failures": [item for item in probes if item.get("status") != "ok"],
    }


@dataclass(frozen=True, slots=True)
class LoadedExactScope:
    path: Path
    report_sha256: str
    scope_digest: str
    through: date
    candidate_root: Path
    active_canonical_root: Path
    candidate_catalog: str
    products: tuple[str, ...]
    legacy_roots: tuple[Path, ...]
    counts: Mapping[str, Any]
    exact_scope: Mapping[str, Any]
    raw_report: Mapping[str, Any]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_scope_digest(core_without_digest: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            core_without_digest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def core_scope_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in WRAPPER_FIELDS and key != "scope_digest"
    }


def database_name(url: str) -> str:
    parsed = make_url(normalize_database_url(url))
    name = parsed.database
    if not name:
        raise GateAOperatorError("GATE_A_DATABASE_NAME_MISSING")
    return name


def assert_isolated_database(url: str, expected_catalog: str) -> None:
    if database_name(url) != expected_catalog:
        raise GateAOperatorError("GATE_A_DATABASE_NAME_MISMATCH")


def assert_candidate_root_isolated(candidate_root: Path, active_root: Path) -> None:
    candidate = candidate_root.resolve()
    active = active_root.resolve()
    if candidate == active or candidate in active.parents or active in candidate.parents:
        raise GateAOperatorError("GATE_A_CANDIDATE_ROOT_OVERLAPS_ACTIVE")


def assert_candidate_root_ready(candidate_root: Path, *, resume: bool) -> None:
    root = candidate_root.resolve()
    if not root.exists():
        return
    if any(root.iterdir()) and not resume:
        raise GateAOperatorError("GATE_A_CANDIDATE_ROOT_NOT_EMPTY")


def load_exact_scope(
    path: Path,
    *,
    expected_scope_digest: str,
    expected_report_sha256: str,
) -> LoadedExactScope:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise GateAOperatorError("GATE_A_SCOPE_JSON_INVALID")
    report_sha = file_sha256(resolved)
    if report_sha != expected_report_sha256:
        raise GateAOperatorError("GATE_A_REPORT_SHA256_MISMATCH")
    try:
        report = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise GateAOperatorError("GATE_A_SCOPE_JSON_INVALID") from exc
    if not isinstance(report, dict):
        raise GateAOperatorError("GATE_A_SCOPE_JSON_INVALID")
    if report.get("mode") != "gate_a_exact_scope_dry_run":
        raise GateAOperatorError("GATE_A_SCOPE_MODE_INVALID")
    if report.get("schema_version") != 1:
        raise GateAOperatorError("GATE_A_SCOPE_SCHEMA_INVALID")
    core = core_scope_payload(report)
    digest = compute_scope_digest(core)
    stored = report.get("scope_digest")
    if not isinstance(stored, str) or stored != digest:
        raise GateAOperatorError("GATE_A_SCOPE_DIGEST_MISMATCH")
    if digest != expected_scope_digest:
        raise GateAOperatorError("GATE_A_SCOPE_DIGEST_MISMATCH")
    windows = core.get("rqdata_windows")
    legacy_targets = core.get("legacy_selected_month_targets")
    if not isinstance(windows, list) or not windows:
        raise GateAOperatorError("GATE_A_PROVIDER_SCOPE_INVALID")
    if not isinstance(legacy_targets, list):
        raise GateAOperatorError("GATE_A_LEGACY_SCOPE_INVALID")
    catalog = report.get("candidate_catalog")
    if not isinstance(catalog, str) or not catalog.strip():
        raise GateAOperatorError("GATE_A_CANDIDATE_CATALOG_MISSING")
    try:
        through = date.fromisoformat(str(core["through"]))
        candidate_root = Path(str(core["candidate_root"])).resolve()
        active_root = Path(str(core["active_canonical_root"])).resolve()
        products = tuple(str(item).strip().lower() for item in core["products"])
        legacy_roots = tuple(Path(str(item)).resolve() for item in core["legacy_roots"])
        counts = core["counts"]
    except (KeyError, TypeError, ValueError) as exc:
        raise GateAOperatorError("GATE_A_SCOPE_JSON_INVALID") from exc
    if not products or len(set(products)) != len(products):
        raise GateAOperatorError("GATE_A_UNIVERSE_INVALID")
    assert_candidate_root_isolated(candidate_root, active_root)
    if not isinstance(counts, dict):
        raise GateAOperatorError("GATE_A_SCOPE_JSON_INVALID")
    return LoadedExactScope(
        path=resolved,
        report_sha256=report_sha,
        scope_digest=digest,
        through=through,
        candidate_root=candidate_root,
        active_canonical_root=active_root,
        candidate_catalog=catalog.strip(),
        products=products,
        legacy_roots=legacy_roots,
        counts=counts,
        exact_scope=core,
        raw_report=report,
    )


def open_candidate_session(database_url: str) -> Session:
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def read_alembic_revision(session: Session) -> str | None:
    row = session.execute(text("SELECT version_num FROM alembic_version")).first()
    if row is None:
        return None
    return str(row[0])


def read_catalog_counts(session: Session) -> dict[str, int]:
    return {
        "market_datasets": int(session.scalar(select(func.count()).select_from(MarketDataset)) or 0),
        "market_partitions": int(
            session.scalar(select(func.count()).select_from(MarketPartition)) or 0
        ),
        "data_gaps": int(session.scalar(select(func.count()).select_from(DataGap)) or 0),
    }


def reset_candidate_bar_catalog(session: Session) -> dict[str, int]:
    """Clear candidate bar Catalog rows while preserving metadata tables."""
    from sqlalchemy import CursorResult, delete

    def _rowcount(result: object) -> int:
        if isinstance(result, CursorResult):
            return int(result.rowcount or 0)
        return int(getattr(result, "rowcount", 0) or 0)

    gaps = _rowcount(session.execute(delete(DataGap)))
    partitions = _rowcount(session.execute(delete(MarketPartition)))
    datasets = _rowcount(session.execute(delete(MarketDataset)))
    session.commit()
    return {
        "deleted_data_gaps": gaps,
        "deleted_market_partitions": partitions,
        "deleted_market_datasets": datasets,
    }


def _first_night_trading_day(symbol: str) -> date | None:
    root = (
        PROJECT_ROOT
        / "data/raw/rqdata/dominant_contract_bars"
        / f"product={symbol.strip().lower()}"
        / "frequency=1m"
    )
    if not root.is_dir():
        return None
    earliest: date | None = None
    for path in sorted(root.rglob("*.parquet")):
        try:
            table = pq.ParquetFile(path).read()
            names = set(table.column_names)
            if "datetime" not in names:
                continue
            datetimes = table.column("datetime").to_pylist()
            trading_dates = (
                table.column("trading_date").to_pylist()
                if "trading_date" in names
                else [None] * len(datetimes)
            )
        except Exception:  # noqa: BLE001 - skip unreadable legacy files
            continue
        for value, trading_date in zip(datetimes, trading_dates, strict=False):
            if value is None:
                continue
            local = value.astimezone(SHANGHAI) if getattr(value, "tzinfo", None) else value
            if not hasattr(local, "hour"):
                continue
            if local.hour < 20 and local.hour >= 3:
                continue
            if trading_date is not None:
                day = trading_date.date() if hasattr(trading_date, "date") else trading_date
            else:
                day = local.date()
            if earliest is None or day < earliest:
                earliest = day
    return earliest


def repair_night_session_effective_from(
    session: Session,
    products: tuple[str, ...],
) -> dict[str, Any]:
    """Align night-session effective_from with first observed legacy night bar.

    MetadataSynchronizer currently backfills current trading_hours to product
    listing day, which invents night sessions years before they existed.
    """
    updated = 0
    disabled = 0
    details: list[dict[str, Any]] = []
    for symbol in products:
        first_night = _first_night_trading_day(symbol)
        rows = session.scalars(
            select(TradingSession).where(
                TradingSession.instrument_symbol == symbol,
                TradingSession.is_active.is_(True),
            )
        ).all()
        night_rows = [
            row
            for row in rows
            if row.start_time >= time(20, 0) or bool(row.crosses_midnight)
        ]
        if not night_rows:
            continue
        if first_night is None:
            for row in night_rows:
                row.is_active = False
                disabled += 1
            details.append({"symbol": symbol, "action": "disabled_night", "first_night": None})
            continue
        for row in night_rows:
            if row.effective_from != first_night:
                row.effective_from = first_night
                updated += 1
        details.append(
            {
                "symbol": symbol,
                "action": "set_effective_from",
                "first_night": first_night.isoformat(),
                "night_sessions": len(night_rows),
            }
        )
    session.commit()
    return {
        "action": "gate_a_repair_sessions",
        "status": "passed",
        "updated_sessions": updated,
        "disabled_sessions": disabled,
        "products_touched": len(details),
        "details": details[:20],
        "detail_count": len(details),
    }


def build_gate_a_scope_report(
    *,
    session: Session,
    products: tuple[str, ...],
    through: date,
    candidate_root: Path,
    candidate_catalog: str,
) -> dict[str, Any]:
    coverage = DatabaseCoverageSource(
        session,
        PROJECT_ROOT / "data/universe/product_window_starts.csv",
    )
    active = canonical_root()
    catalog = MarketCatalog(session, candidate_root)
    starts = {symbol: coverage.product_start(symbol) for symbol in products}
    trading_days = {
        symbol: catalog.trading_days(symbol, starts[symbol], through) for symbol in products
    }
    main_map = tuple(
        fact
        for symbol in products
        for fact in catalog.main_map(symbol, starts[symbol], through)
    )
    contract_root = (PROJECT_ROOT / "data/raw/rqdata/actual_contract_bars").resolve()
    continuous_raw_root = (PROJECT_ROOT / "data/raw/rqdata/dominant_contract_bars").resolve()
    legacy_coverages, invalid = scan_legacy_coverages(
        contract_root=contract_root,
        continuous_raw_root=continuous_raw_root,
        previous_canonical_root=active,
        products=products,
    )
    payload = plan_gate_a_scope(
        products=products,
        starts=starts,
        through=through,
        candidate_root=candidate_root,
        active_canonical_root=active,
        trading_days=trading_days,
        main_map=main_map,
        legacy_coverages=legacy_coverages,
        legacy_roots=(contract_root, continuous_raw_root, active),
    )
    payload["candidate_catalog"] = candidate_catalog
    payload["dry_run_evidence"] = {
        "canonical_written": False,
        "direct_bar_downloaded": False,
        "legacy_invalid_candidate_count": len(invalid),
        "legacy_invalid_candidates": list(invalid[:20]),
        "main_map_rows_read": len(main_map),
        "metadata_complete": coverage.metadata_complete(products, through),
        "rqdata_intraday_history_start": "2010-01-04",
    }
    return payload


def run_preflight(
    loaded: LoadedExactScope,
    *,
    database_url: str,
    resume: bool = False,
) -> dict[str, Any]:
    assert_isolated_database(database_url, loaded.candidate_catalog)
    active = canonical_root()
    if active != loaded.active_canonical_root:
        # Allow report active root to differ from env only when paths resolve equal after env override.
        # Fail closed if the live active root overlaps the candidate.
        assert_candidate_root_isolated(loaded.candidate_root, active)
    assert_candidate_root_ready(loaded.candidate_root, resume=resume)
    session = open_candidate_session(database_url)
    try:
        revision = read_alembic_revision(session)
        if revision != EXPECTED_REVISION:
            raise GateAOperatorError("GATE_A_DATABASE_REVISION_MISMATCH")
        counts = read_catalog_counts(session)
        if not resume and (
            counts["market_datasets"] != 0 or counts["market_partitions"] != 0
        ):
            raise GateAOperatorError("GATE_A_CATALOG_NOT_EMPTY")
        return {
            "action": "gate_a_preflight",
            "status": "passed",
            "scope_digest": loaded.scope_digest,
            "report_sha256": loaded.report_sha256,
            "through": loaded.through.isoformat(),
            "candidate_root": loaded.candidate_root.as_posix(),
            "candidate_catalog": loaded.candidate_catalog,
            "database_revision": revision,
            "catalog_counts": counts,
            "expected_counts": dict(loaded.counts),
            "resume": resume,
            "products": list(loaded.products),
        }
    finally:
        session.close()


def run_apply(
    loaded: LoadedExactScope,
    *,
    session: Session,
    resume: bool = False,
    require_intent_token: bool = True,
    intent_confirmed: bool = False,
) -> dict[str, Any]:
    if require_intent_token and not intent_confirmed:
        raise GateAOperatorError("GATE_A_APPLY_INTENT_REQUIRED")
    assert_candidate_root_isolated(loaded.candidate_root, canonical_root())
    assert_candidate_root_ready(loaded.candidate_root, resume=resume)
    loaded.candidate_root.mkdir(parents=True, exist_ok=True)
    manager = build_candidate_bootstrap_manager(
        session,
        loaded.candidate_root,
        exact_scope=loaded.exact_scope,
    )
    result = manager.bootstrap(
        BootstrapRequest(
            products=loaded.products,
            through=loaded.through,
            apply=True,
        )
    )
    provider = getattr(manager, "provider", None)
    provider_window_requests = int(getattr(provider, "request_count", 0) or 0)
    unused_windows = int(getattr(provider, "unused_window_count", 0) or 0)
    payload = result.as_payload() if isinstance(result, MaintenanceResult) else dict(result)
    return {
        "action": "gate_a_apply",
        "apply": True,
        "scope_digest": loaded.scope_digest,
        "through": loaded.through.isoformat(),
        "candidate_root": loaded.candidate_root.as_posix(),
        "provider_window_requests": provider_window_requests,
        "unused_exact_scope_windows": unused_windows,
        "bootstrap": payload,
        **{key: payload[key] for key in ("status", "planned", "applied", "failed", "blocked") if key in payload},
    }


def _probe_window(through: date) -> tuple[datetime, datetime]:
    end = datetime(through.year, through.month, through.day, 16, 0, tzinfo=UTC)
    start = end - timedelta(days=21)
    return start, end


def run_verify(
    loaded: LoadedExactScope,
    *,
    session: Session,
) -> dict[str, Any]:
    assert_candidate_root_isolated(loaded.candidate_root, canonical_root())
    manager = build_candidate_bootstrap_manager(
        session,
        loaded.candidate_root,
        exact_scope=loaded.exact_scope,
    )
    audit = manager.audit(AuditRequest(loaded.products))
    catalog_counts = read_catalog_counts(session)
    service = MarketDataService(
        manager.catalog,
        CanonicalMonthlyStore(loaded.candidate_root),
    )
    start, end = _probe_window(loaded.through)
    probes: list[dict[str, Any]] = []
    probe_symbols = loaded.products[:3]
    for symbol in probe_symbols:
        for frequency in sorted(ALL_FREQUENCIES, key=lambda item: item.value):
            for series_kind in (SeriesKind.CONTINUOUS, SeriesKind.ACTUAL_DOMINANT):
                item: dict[str, Any] = {
                    "symbol": symbol,
                    "frequency": frequency.value,
                    "series_kind": series_kind.value,
                }
                try:
                    result = service.query(
                        SeriesQuery(
                            series_kind=series_kind,
                            symbol=symbol,
                            frequency=frequency,
                            start=start,
                            end=end,
                        )
                    )
                    item["status"] = "ok"
                    item["bars"] = len(result.bars)
                except MarketDataError as exc:
                    item["status"] = "failed"
                    item["error"] = exc.code
                except Exception as exc:  # noqa: BLE001 - probe summary only
                    item["status"] = "failed"
                    item["error"] = type(exc).__name__
                probes.append(item)
    noop = manager.bootstrap(
        BootstrapRequest(
            products=loaded.products,
            through=loaded.through,
            apply=False,
        )
    )
    status = "passed"
    if audit.status != "passed" or catalog_counts["data_gaps"] != 0:
        status = "failed"
    if any(item.get("status") != "ok" for item in probes):
        status = "failed"
    if noop.planned != 0 or noop.provider_requests != 0:
        status = "failed"
    return {
        "action": "gate_a_verify",
        "status": status,
        "scope_digest": loaded.scope_digest,
        "through": loaded.through.isoformat(),
        "candidate_root": loaded.candidate_root.as_posix(),
        "catalog_counts": catalog_counts,
        "expected_counts": dict(loaded.counts),
        "audit": audit.as_payload(),
        "noop_bootstrap": noop.as_payload(),
        "mds_probes": probes,
        "probe_failures": [item for item in probes if item.get("status") != "ok"],
    }
