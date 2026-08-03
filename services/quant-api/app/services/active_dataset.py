from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Literal, Mapping

from app.data_core.contracts import BAR_FREQUENCY_VALUES


DatasetContext = Literal["historical", "live"]
AccessMode = Literal["browser", "research"]
ContractSelector = Literal["explicit", "dominant_rank1"]

HISTORICAL_PERIODS = frozenset(BAR_FREQUENCY_VALUES)
LIVE_PERIOD_SOURCE_MODES = {
    "1m": "poll_get_price_1m",
    "15m": "live_1m_sequential_bucket",
}
DESCRIPTOR_SNAPSHOT_TOKEN_VERSION = "dataset-descriptor-snapshot-v1"
ACTIVE_DATASET_DOMAIN_ERROR_CODES = frozenset(
    {
        "DATASET_REQUEST_UNSUPPORTED",
        "DATASET_ASSET_MISSING",
        "DATASET_ASSET_AMBIGUOUS",
        "DATASET_LINEAGE_CHANGED",
        "DATASET_ACTUAL_CONTRACT_MISMATCH",
        "LIVE_ACTUAL_CONTRACT_REQUIRED",
        "LIVE_SOURCE_MODE_REQUIRED",
        "LIVE_SOURCE_MODE_MISMATCH",
        "LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED",
    }
)

_ACTUAL_JM_CONTRACT = re.compile(r"^JM\d{4}$")
_CONTINUOUS_JM_CONTRACT = "jm.MAIN"


class ActiveDatasetDomainError(ValueError):
    """Stable, internal active-dataset domain failure without request payloads."""

    def __init__(self, code: str) -> None:
        if code not in ACTIVE_DATASET_DOMAIN_ERROR_CODES:
            raise ValueError("unsupported active dataset error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DatasetRequest:
    data_context: DatasetContext
    symbol: str
    contract_selector: ContractSelector
    contract: str | None
    period: str
    access_mode: AccessMode
    profile_id: str | None = None
    provider: str | None = None
    data_role: str | None = None
    live_source_mode: str | None = None
    mapping_date: date | None = None
    expected_market_data_file_id: int | None = None
    expected_lineage_token: str | None = None
    quote_mode: bool = False
    allow_continuous: bool = False


@dataclass(frozen=True)
class DatasetAsset:
    market_data_file_id: int | None
    provider: str
    data_role: str | None
    quality_status: str
    data_version: str | None
    checksum: str | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    source_interval: str | None
    source_interval_basis: str | None


@dataclass(frozen=True)
class DatasetDescriptor:
    data_context: DatasetContext
    access_mode: AccessMode
    symbol: str
    contract_selector: ContractSelector
    requested_contract: str | None
    resolved_contract: str
    contract_role: str
    continuous_contract: str | None
    actual_contract: str | None
    period: str
    provider: str | None
    data_role: str | None
    live_source_mode: str | None
    quality_status: str
    strict_research_ready: bool
    profile_id: str | None
    quality_policy: str | None
    binding_snapshot: dict[str, Any] | None
    assets: tuple[DatasetAsset, ...]
    mapping_identity: dict[str, Any] | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    source_coverage_row_count: int
    source_max_bar: datetime | None
    source_revision_hash: str | None
    lineage_kind: Literal["historical_asset", "live_response_snapshot", "unavailable"]
    lineage_token: str | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "binding_snapshot",
            deepcopy(self.binding_snapshot),
        )
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(
            self,
            "mapping_identity",
            deepcopy(self.mapping_identity),
        )
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class BarsResult:
    descriptor: DatasetDescriptor
    bars: tuple[dict[str, Any], ...]
    response_bar_count: int
    quality: dict[str, Any]
    coverage: dict[str, Any] | None
    response_request: dict[str, Any]
    message: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", deepcopy(tuple(self.bars)))
        object.__setattr__(self, "quality", deepcopy(self.quality))
        object.__setattr__(self, "coverage", deepcopy(self.coverage))
        object.__setattr__(
            self,
            "response_request",
            deepcopy(self.response_request),
        )


def validate_dataset_request(request: DatasetRequest) -> DatasetRequest:
    """Validate the frozen facade boundary and return repository-style normalization."""
    if request.data_context not in {"historical", "live"}:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
    if request.access_mode not in {"browser", "research"}:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
    if request.contract_selector not in {"explicit", "dominant_rank1"}:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    symbol = _normalize_symbol(request.symbol)
    if symbol != "jm":
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    if request.data_context == "historical":
        return _validate_historical_request(request, symbol=symbol)
    return _validate_live_request(request, symbol=symbol)


def snapshot_token(snapshot: Mapping[str, Any]) -> str:
    """Return a deterministic versioned token for explicit snapshot inputs only."""
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{DESCRIPTOR_SNAPSHOT_TOKEN_VERSION}:{digest}"


def _validate_historical_request(request: DatasetRequest, *, symbol: str) -> DatasetRequest:
    if request.period not in HISTORICAL_PERIODS:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    contract = _normalize_jm_contract(request.contract)
    if request.contract_selector == "explicit":
        if contract is None:
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
    else:
        if not _is_exact_date(request.mapping_date):
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        if contract == _CONTINUOUS_JM_CONTRACT:
            raise ActiveDatasetDomainError("DATASET_ACTUAL_CONTRACT_MISMATCH")

    if request.contract is not None and contract is None:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    return replace(request, symbol=symbol, contract=contract)


def _validate_live_request(request: DatasetRequest, *, symbol: str) -> DatasetRequest:
    if request.contract_selector != "explicit":
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
    if request.period not in LIVE_PERIOD_SOURCE_MODES:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
    if request.provider != "rqdata":
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    contract = _normalize_jm_contract(request.contract)
    if contract is None or not _ACTUAL_JM_CONTRACT.fullmatch(contract):
        raise ActiveDatasetDomainError("LIVE_ACTUAL_CONTRACT_REQUIRED")
    if request.access_mode == "research":
        raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED")
    if request.live_source_mode is None:
        raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_REQUIRED")
    if request.live_source_mode != LIVE_PERIOD_SOURCE_MODES[request.period]:
        raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_MISMATCH")
    if request.mapping_date is not None:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    return replace(request, symbol=symbol, contract=contract)


def _normalize_symbol(value: str) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _normalize_jm_contract(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.lower() == _CONTINUOUS_JM_CONTRACT.lower():
        return _CONTINUOUS_JM_CONTRACT
    upper = normalized.upper()
    return upper if _ACTUAL_JM_CONTRACT.fullmatch(upper) else None


def _is_exact_date(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)
