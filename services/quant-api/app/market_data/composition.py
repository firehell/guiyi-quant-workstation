from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Literal, Mapping

from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from app.core.env import PROJECT_ROOT
from app.db.base import Base
from app.db.session import DATABASE_URL
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.maintenance import HistoricalDataManager
from app.market_data.service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore

_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"
_CANDIDATE_DATABASE_URL = "GUIYI_CANDIDATE_DATABASE_URL"
_CANDIDATE_TABLES = (
    "exchanges",
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "contract_specs",
    "market_datasets",
    "market_partitions",
    "data_gaps",
)
_SHA256 = re.compile(r"^[0-9a-f]{40,64}$")


class CandidateTargetError(ValueError):
    """A bounded Candidate precondition failure suitable for CLI output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HistoricalDataTarget:
    """One explicit historical-data target for the shared maintenance pipeline."""

    mode: Literal["active", "candidate"]
    root: Path
    candidate_mode: Literal["fresh", "extend"] | None = None
    candidate_database_url: str | None = None

    @classmethod
    def active(cls) -> HistoricalDataTarget:
        return cls(mode="active", root=canonical_root())

    @classmethod
    def candidate(
        cls,
        root: Path,
        *,
        mode: Literal["fresh", "extend"],
    ) -> HistoricalDataTarget:
        if mode not in {"fresh", "extend"}:
            raise CandidateTargetError("CANDIDATE_UNSUPPORTED_OPERATION")
        database_url = os.getenv(_CANDIDATE_DATABASE_URL, "").strip()
        if not database_url:
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        normalized = normalize_database_url(database_url)
        if normalized == DATABASE_URL:
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        try:
            make_url(normalized)
        except Exception as exc:  # noqa: BLE001 - never return URL details
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc
        return cls(
            mode="candidate",
            root=_candidate_root(root),
            candidate_mode=mode,
            candidate_database_url=normalized,
        )

    def open_session(self) -> Session:
        if self.mode != "candidate" or self.candidate_database_url is None:
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        try:
            engine = create_engine(self.candidate_database_url, pool_pre_ping=True)
            return sessionmaker(bind=engine, autoflush=False, autocommit=False)()
        except Exception as exc:  # noqa: BLE001 - bounded Candidate configuration boundary
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc

    def build_manager(self, session: Session) -> HistoricalDataManager:
        return _build_historical_data_manager(session, self.root)

    def validate_update(self, session: Session, requested_through: date) -> dict[str, str]:
        self._require_candidate()
        identity = self.identity()
        if self.candidate_mode == "fresh":
            _require_candidate_tables_empty(session)
            if self.root.exists() and (not self.root.is_dir() or any(self.root.iterdir())):
                raise CandidateTargetError("CANDIDATE_TARGET_NOT_EMPTY")
            if _candidate_metadata_path(self.root).exists():
                raise CandidateTargetError("CANDIDATE_TARGET_NOT_EMPTY")
            return identity

        metadata = self._read_metadata()
        _require_candidate_tables_exist(session)
        if metadata["identity"] != identity:
            raise CandidateTargetError("CANDIDATE_IDENTITY_MISMATCH")
        recorded_through = _metadata_through(metadata)
        if requested_through < recorded_through:
            raise CandidateTargetError("CANDIDATE_THROUGH_REGRESSION")
        return identity

    def validate_audit(self, session: Session) -> None:
        self._require_candidate()
        metadata = self._read_metadata()
        _require_candidate_tables_exist(session)
        if metadata["identity"] != self.identity():
            raise CandidateTargetError("CANDIDATE_IDENTITY_MISMATCH")

    def identity(self) -> dict[str, str]:
        self._require_candidate()
        assert self.candidate_database_url is not None
        return {
            "catalog_session_identity": _digest(_safe_database_identity(self.candidate_database_url)),
            "canonical_root_identity": _digest(str(self.root)),
            "universe_digest": _universe_digest(),
            "active_history_floor": _history_floor(),
            "source_policy": "RQData-only/legacy=None",
            "code_sha": _code_sha(),
        }

    def record_through(self, requested_through: date, identity: Mapping[str, str]) -> None:
        self._require_candidate()
        expected_identity = self.identity()
        if dict(identity) != expected_identity:
            raise CandidateTargetError("CANDIDATE_IDENTITY_MISMATCH")
        _candidate_root(self.root)
        metadata_path = _candidate_metadata_path(self.root)
        if self.candidate_mode == "extend":
            existing = self._read_metadata()
            if existing["identity"] != expected_identity:
                raise CandidateTargetError("CANDIDATE_IDENTITY_MISMATCH")
            recorded_through = max(requested_through, _metadata_through(existing))
        else:
            if metadata_path.exists():
                raise CandidateTargetError("CANDIDATE_TARGET_NOT_EMPTY")
            recorded_through = requested_through
        _atomic_write_candidate_metadata(
            metadata_path,
            {
                "identity": expected_identity,
                "recorded_through": recorded_through.isoformat(),
            },
        )

    def _read_metadata(self) -> dict[str, object]:
        metadata_path = _candidate_metadata_path(self.root)
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise CandidateTargetError("CANDIDATE_METADATA_MISSING")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc
        if not isinstance(payload, dict) or set(payload) != {"identity", "recorded_through"}:
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        identity = payload.get("identity")
        if not isinstance(identity, dict) or set(identity) != {
            "catalog_session_identity",
            "canonical_root_identity",
            "universe_digest",
            "active_history_floor",
            "source_policy",
            "code_sha",
        } or not all(isinstance(value, str) for value in identity.values()):
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        _metadata_through(payload)
        return payload

    def _require_candidate(self) -> None:
        if self.mode != "candidate" or self.candidate_mode is None:
            raise CandidateTargetError("CANDIDATE_UNSUPPORTED_OPERATION")


def _candidate_root(candidate_root: Path) -> Path:
    raw = candidate_root
    if not raw.is_absolute():
        raw = (PROJECT_ROOT / raw).absolute()
    normalized = raw.resolve(strict=False)
    candidate_parent = (PROJECT_ROOT / "data/canonical-candidates").resolve(strict=False)
    if _has_symlink_component(raw) or normalized == candidate_parent:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    try:
        normalized.relative_to(candidate_parent)
    except ValueError as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc
    active_root = canonical_root()
    if normalized == active_root or normalized in active_root.parents or active_root in normalized.parents:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    return normalized


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _candidate_metadata_path(root: Path) -> Path:
    return root / "candidate.json"


def _require_candidate_tables_exist(session: Session) -> None:
    try:
        inspector = inspect(session.get_bind())
        if not all(inspector.has_table(name) for name in _CANDIDATE_TABLES):
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    except CandidateTargetError:
        raise
    except Exception as exc:  # noqa: BLE001 - bounded external precondition boundary
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc


def _require_candidate_tables_empty(session: Session) -> None:
    _require_candidate_tables_exist(session)
    try:
        for name in _CANDIDATE_TABLES:
            table = Base.metadata.tables.get(name)
            if table is None or int(session.scalar(select(func.count()).select_from(table)) or 0):
                raise CandidateTargetError("CANDIDATE_TARGET_NOT_EMPTY")
    except CandidateTargetError:
        raise
    except Exception as exc:  # noqa: BLE001 - bounded external precondition boundary
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc


def _metadata_through(payload: Mapping[str, object]) -> date:
    value = payload.get("recorded_through")
    if not isinstance(value, str):
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc


def _safe_database_identity(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception as exc:  # noqa: BLE001 - never return URL details
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _universe_digest() -> str:
    path = PROJECT_ROOT / "data/universe/active_products.txt"
    try:
        products = tuple(
            line.strip().upper() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    except OSError as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc
    if not products or len(products) != len(set(products)):
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    return _digest("\n".join(products))


def _history_floor() -> str:
    try:
        value = (PROJECT_ROOT / "data/universe/active_history_floor.txt").read_text(
            encoding="utf-8"
        ).strip()
        return date.fromisoformat(value).isoformat()
    except (OSError, ValueError) as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc


def _code_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not _SHA256.fullmatch(value):
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
    return value


def _atomic_write_candidate_metadata(path: Path, payload: Mapping[str, object]) -> None:
    root = path.parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=root, prefix=".candidate-", delete=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except CandidateTargetError:
        raise
    except OSError as exc:
        raise CandidateTargetError("CANDIDATE_PRECONDITION_FAILED") from exc



def canonical_root() -> Path:
    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    return _build_historical_data_manager(session, canonical_root())


def _build_historical_data_manager(session: Session, root: Path) -> HistoricalDataManager:
    from app.market_data.infrastructure import (
        DatabaseCoverageSource,
        RQDataMarketAdapter,
    )
    from app.market_data.metadata import MetadataSynchronizer

    catalog = MarketCatalog(session, root)
    adapter = RQDataMarketAdapter(session=session)
    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    return HistoricalDataManager(
        catalog=catalog,
        store=CanonicalMonthlyStore(root, boundary_validator=coverage.valid_boundary),
        coverage=coverage,
        metadata=MetadataSynchronizer(adapter, catalog),
        provider=adapter,
        legacy=None,
    )


def build_candidate_historical_data_manager(
    session: Session,
    candidate_root: Path,
) -> HistoricalDataManager:
    """Compose an isolated RQData-only Candidate writer.

    Reuses the production HistoricalDataManager algorithm with legacy=None.
    Callers must supply an isolated Catalog session and candidate root.
    """
    return _build_historical_data_manager(session, _candidate_root(candidate_root))


def build_candidate_bootstrap_manager(
    session: Session,
    candidate_root: Path,
    *,
    exact_scope: Mapping[str, Any] | None = None,
) -> HistoricalDataManager:
    """Freeze: migration-only legacy Gate A composition.

    Pending removal after Gate C. New Gate A MUST use
    ``build_candidate_historical_data_manager`` instead.
    """
    from app.market_data.infrastructure import DatabaseCoverageSource, RQDataMarketAdapter
    from app.market_data.legacy_bootstrap import ExactScopeProvider, LegacyBootstrapAdapter
    from app.market_data.metadata import MetadataSynchronizer

    root = _candidate_root(candidate_root)
    previous = canonical_root()
    contract_root = (PROJECT_ROOT / "data/raw/rqdata/actual_contract_bars").resolve()
    continuous_raw_root = (PROJECT_ROOT / "data/raw/rqdata/dominant_contract_bars").resolve()
    catalog = MarketCatalog(session, root)
    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    adapter = RQDataMarketAdapter(session=session)
    provider = ExactScopeProvider(adapter, exact_scope) if exact_scope is not None else adapter
    return HistoricalDataManager(
        catalog=catalog,
        store=CanonicalMonthlyStore(root, boundary_validator=coverage.valid_boundary),
        coverage=coverage,
        metadata=MetadataSynchronizer(adapter, catalog),
        provider=provider,
        legacy=LegacyBootstrapAdapter(
            contract_root=contract_root,
            continuous_raw_root=continuous_raw_root,
            previous_canonical_root=previous,
            allowed_roots=(contract_root, continuous_raw_root, previous),
            exact_scope=exact_scope,
        ),
    )


def build_market_data_service(session: Session) -> MarketDataService:
    root = canonical_root()
    return MarketDataService(
        MarketCatalog(session, root),
        CanonicalMonthlyStore(root),
    )
