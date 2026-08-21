"""市场数据子系统组装入口（数据核心 V2 依赖注入）。

本模块将 Catalog、Parquet Store、RQData 适配器与维护管道拼成可运行对象：
- ``build_market_data_service``：只读查询路径（API/CLI 使用）；
- ``build_historical_data_manager``：历史回填与分区发布路径（含元数据同步与 coverage 校验）。

canonical 根目录由环境变量 ``GUIYI_CANONICAL_DATA_ROOT`` 或仓库默认路径解析，
与八表 Catalog 中的相对 URI 保持一致。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.models import Contract
from app.market_data.catalog import MarketCatalog
from app.market_data.candidate_validation_policy import (
    load_candidate_manifest,
    load_candidate_validation_protocol,
)
from app.market_data.live_market import (
    RQDataLiveProvider,
    LiveMarketService,
    RedisClient,
    RedisLiveStore,
)
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.market_read_service import MarketReadService
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.operational_universe import load_operational_products
from app.market_data.market_data_service import MarketDataService
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2Error,
    MainForceMirrorV2Service,
)
from app.market_data.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchService,
)
from app.market_data.member_rank_snapshot import (
    MemberRankSnapshotError,
    MemberRankSnapshotRepository,
)
from app.market_data.market_radar import MarketRadarService
from app.market_data.market_research_service import MarketResearchService
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentLoader,
)
from app.market_data.jdj_candidate_validation_calendar import (
    assert_jdj_prospective_calendar,
)
from app.market_data.jdj_candidate_validation_policy import (
    load_jdj_candidate_manifest,
    load_jdj_candidate_validation_protocol,
)
from app.market_data.jdj_candidate_validation_service import (
    JdjCandidateValidationService,
)
from app.market_data.jdj_policy import load_jdj_policy
from app.market_data.jdj_research_service import JdjResearchService
from app.market_data.n_structure_policy import load_n_structure_policy
from app.market_data.n_structure_research_service import NStructureResearchService
from app.market_data.multi_candidate_robustness_policy import (
    load_multi_candidate_robustness_protocol,
)
from app.market_data.multi_candidate_robustness_service import (
    MultiCandidateRobustnessService,
)
from app.market_data.n_candidate_validation_policy import (
    load_n_candidate_manifest,
    load_n_candidate_validation_protocol,
)
from app.market_data.n_candidate_validation_service import (
    NStructureCandidateValidationService,
)
from app.market_data.subing_calibration import load_accepted_subing_calibration
from app.market_data.subing_calibration_service import SubingCalibrationResearchService
from app.market_data.subing_candidate_validation_service import (
    SubingCandidateValidationService,
)
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicyError,
    load_subing_lifecycle_policy,
)
from app.market_data.subing_lifecycle_research_service import (
    SubingLifecycleResearchService,
)
from app.market_data.subing_read_service import SubingReadService
from app.market_data.operational_universe import load_active_products
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_data.storage import CanonicalMonthlyStore
from app.redis_connections import get_redis_connection


_PRODUCT_STARTS = PROJECT_ROOT / "data/universe/product_window_starts.csv"
_HISTORY_FLOOR = PROJECT_ROOT / "data/universe/active_history_floor.txt"
_SUBING_CALIBRATION = (
    PROJECT_ROOT / "data/research_policies/subing_calibration_intraday_v1.json"
)
_SUBING_LIFECYCLE_POLICY = (
    PROJECT_ROOT / "data/research_policies/subing_lifecycle_v2_research_v1.json"
)
_CANDIDATE_MANIFEST = (
    PROJECT_ROOT / "data/research_candidates/subing_lifecycle_v2_candidate_v1.json"
)
_CANDIDATE_VALIDATION_PROTOCOL = (
    PROJECT_ROOT / "data/research_protocols/candidate_validation_v1.json"
)
_N_CANDIDATE_MANIFEST = (
    PROJECT_ROOT / "data/research_candidates/n_structure_5m_candidate_v1.json"
)
_N_CANDIDATE_VALIDATION_PROTOCOL = (
    PROJECT_ROOT / "data/research_protocols/n_structure_validation_v1.json"
)


def canonical_root() -> Path:
    """解析 canonical Parquet 根目录（环境变量优先，否则仓库内默认路径）。"""
    configured = os.getenv("GUIYI_CANONICAL_DATA_ROOT")
    root = Path(configured) if configured else PROJECT_ROOT / "data/parquet/canonical"
    return root.resolve()


def research_data_root() -> Path:
    """Resolve the explicit Git-external research-data root without creating it."""
    configured = os.getenv("GUIYI_RESEARCH_DATA_ROOT")
    if configured is None or not configured.strip():
        from app.market_data.member_rank_snapshot_builder import (
            MemberRankSnapshotBuildError,
        )

        raise MemberRankSnapshotBuildError("MEMBER_SNAPSHOT_ROOT_UNCONFIGURED")
    return Path(configured).resolve()


class _CatalogMemberRankPlanningSource:
    """Expose existing Catalog rank-1 and trading-calendar facts to the builder."""

    def __init__(self, catalog: MarketCatalog) -> None:
        self._catalog = catalog

    def rank1_map(self, symbol: str, since, through):
        return self._catalog.main_map(symbol, since, through)

    def trading_days(self, symbol: str, since, through):
        return self._catalog.trading_days(symbol, since, through)


class _CatalogMemberRankVerifiers:
    """Read-only Calendar/Contract facts required by the pinned Task 1 reader."""

    def __init__(self, session: Session, catalog: MarketCatalog) -> None:
        self._session = session
        self._catalog = catalog

    def is_trading_day(self, symbol: str, trade_date) -> bool:
        return self._catalog.trading_days(symbol, trade_date, trade_date) == (trade_date,)

    def is_contract_valid(self, physical_contract: str, trade_date) -> bool:
        return self._session.scalar(
            select(Contract.contract_code).where(
                Contract.contract_code == physical_contract,
                Contract.listed_date.is_not(None),
                Contract.listed_date <= trade_date,
                Contract.expired_date.is_not(None),
                Contract.expired_date > trade_date,
            )
        ) is not None


def build_member_rank_snapshot_builder(session: Session):
    """Compose a snapshot builder with lazy RQData construction only on apply."""
    from app.market_data.member_rank_snapshot_builder import MemberRankSnapshotBuilder
    from app.market_data.rqdata_adapter import RQDataClient, RQDataMemberRankProvider

    catalog = MarketCatalog(session, canonical_root())
    verifiers = _CatalogMemberRankVerifiers(session, catalog)

    def provider_factory() -> RQDataMemberRankProvider:
        client = RQDataClient()
        return RQDataMemberRankProvider(client, client_version=client.client_version)

    return MemberRankSnapshotBuilder(
        research_data_root(),
        rank1_source=_CatalogMemberRankPlanningSource(catalog),
        trading_calendar=verifiers,
        contract_validity=verifiers,
        provider_factory=provider_factory,
    )


def build_historical_data_manager(session: Session) -> HistoricalDataManager:
    """构造历史数据维护管理器：含 RQData provider、元数据同步与 session 边界校验 store。"""
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.rqdata_adapter import RQDataMarketAdapter

    root = canonical_root()
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
        metadata=build_metadata_synchronizer(session, adapter=adapter, catalog=catalog),
        provider=adapter,
    )


def build_metadata_synchronizer(
    session: Session,
    *,
    adapter=None,
    catalog: MarketCatalog | None = None,
):
    """构造唯一 metadata 同步边界，供受限单日同步与历史维护共用。

    不会在构造时初始化 RQData；实际 provider 连接只在同步方法被显式调用时发生。
    可选依赖仅供已有 composition 重用，避免建立第二个 metadata engine。
    """
    from app.market_data.rqdata_adapter import RQDataMarketAdapter
    from app.market_data.metadata import MetadataSynchronizer

    active_catalog = catalog or MarketCatalog(session, canonical_root())
    active_adapter = adapter or RQDataMarketAdapter(session=session)
    return MetadataSynchronizer(active_adapter, active_catalog)


def build_market_data_service(session: Session) -> MarketDataService:
    """构造只读 ``MarketDataService``（查询路径不注入 RQData 与维护依赖）。"""
    root = canonical_root()
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))


def member_rank_repository_from_env(
    session: Session | None,
) -> MemberRankSnapshotRepository | None:
    """Resolve only an exact configured member snapshot; never discover latest."""
    root_value = os.getenv("GUIYI_RESEARCH_DATA_ROOT")
    dataset_id = os.getenv("GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID")
    if root_value is None and dataset_id is None:
        return None
    if (
        root_value is None
        or dataset_id is None
        or not root_value.strip()
        or not dataset_id.strip()
    ):
        raise MainForceMirrorV2Error(
            "MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT"
        )
    try:
        if session is None:
            return MemberRankSnapshotRepository(Path(root_value), dataset_id)
        catalog = MarketCatalog(session, canonical_root())
        verifiers = _CatalogMemberRankVerifiers(session, catalog)
        return MemberRankSnapshotRepository(
            Path(root_value),
            dataset_id,
            trading_calendar=verifiers,
            contract_validity=verifiers,
        )
    except MemberRankSnapshotError:
        raise MainForceMirrorV2Error("MFM_V2_MEMBER_DATASET_INVALID") from None


def build_main_force_mirror_v2_service(
    session: Session,
) -> MainForceMirrorV2Service:
    """Compose the historical-only V2 page service without write dependencies."""
    from app.market_data.coverage_source import DatabaseCoverageSource

    market_data = build_market_data_service(session)
    return MainForceMirrorV2Service(
        market_data=market_data,
        segment_loader=ActualDominantResearchSegmentLoader(market_data),
        coverage=DatabaseCoverageSource(
            session,
            _PRODUCT_STARTS,
            history_floor_path=_HISTORY_FLOOR,
        ),
        member_repository=member_rank_repository_from_env(session),
    )


def build_market_research_service(session: Session) -> MarketResearchService:
    """构造 Product Workspace 的只读研究服务。"""
    return MarketResearchService(build_market_data_service(session))


def build_main_force_mirror_v2_research_service(
    session: Session,
) -> MainForceMirrorV2ResearchService:
    """Compose retrospective V2 around the exact API service identities."""
    mirror_service = build_main_force_mirror_v2_service(session)
    return MainForceMirrorV2ResearchService(
        market_data=mirror_service.market_data,
        mirror_service=mirror_service,
    )


def build_market_radar_service(session: Session) -> MarketRadarService:
    """构造完整 active 60 的只读 Radar，不注入 provider、Redis 或写入能力。"""
    from app.market_data.coverage_source import DatabaseCoverageSource

    coverage = DatabaseCoverageSource(
        session,
        _PRODUCT_STARTS,
        history_floor_path=_HISTORY_FLOOR,
    )
    return MarketRadarService(
        build_market_data_service(session),
        products=load_active_products(),
        taxonomy=load_product_taxonomy(),
        latest_complete_day=coverage.latest_complete_day,
    )


def build_market_read_service(session: Session) -> MarketReadService:
    """构造 Market Web 只读模型；Redis 仅作为可降级的 transient Live 边界。"""
    return MarketReadService(
        market_data=build_market_data_service(session),
        phase_resolver=MarketPhaseResolver(session),
        operational_products=load_operational_products(),
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
    )


def build_subing_read_service(session: Session) -> SubingReadService:
    """构造注入 accepted Calibration 与 exact research Policy 的只读模型。"""
    from app.market_data.coverage_source import DatabaseCoverageSource

    calibration = load_accepted_subing_calibration(_SUBING_CALIBRATION)
    try:
        lifecycle_policy = load_subing_lifecycle_policy(_SUBING_LIFECYCLE_POLICY)
    except SubingLifecyclePolicyError:
        lifecycle_policy = None
    return SubingReadService(
        market_data=build_market_data_service(session),
        market_read=build_market_read_service(session),
        calibration=calibration,
        lifecycle_policy=lifecycle_policy,
        lifecycle_coverage=DatabaseCoverageSource(
            session,
            _PRODUCT_STARTS,
            history_floor_path=_HISTORY_FLOOR,
        ),
    )


def build_subing_calibration_research_service(
    session: Session,
) -> SubingCalibrationResearchService:
    """Construct historical-only SuBing Calibration over MarketDataService."""
    return SubingCalibrationResearchService(
        market_data=build_market_data_service(session),
        products=load_active_products(),
    )


def build_subing_lifecycle_research_service(
    session: Session,
) -> SubingLifecycleResearchService:
    """Construct historical-only lifecycle research over MarketDataService."""
    return SubingLifecycleResearchService(
        build_market_data_service(session),
        products=load_active_products(),
        calibration=load_accepted_subing_calibration(_SUBING_CALIBRATION),
        policy=load_subing_lifecycle_policy(_SUBING_LIFECYCLE_POLICY),
    )


def build_n_structure_research_service(
    session: Session,
) -> NStructureResearchService:
    """Compose read-only N research over the shared segment loader."""
    return NStructureResearchService(
        ActualDominantResearchSegmentLoader(build_market_data_service(session)),
        products=load_active_products(),
        policy=load_n_structure_policy(),
    )


def build_jdj_research_service(session: Session) -> JdjResearchService:
    """Compose exact read-only JDJ research over one shared MDS."""
    market_data = build_market_data_service(session)
    return JdjResearchService(
        ActualDominantResearchSegmentLoader(market_data),
        products=load_active_products(),
        jdj_policy=load_jdj_policy(),
        n_policy=load_n_structure_policy(),
    )


def build_jdj_candidate_validation_service(
    session: Session,
    candidate_id: str,
) -> JdjCandidateValidationService:
    """Compose exact JDJ validation only after the frozen calendar gate."""
    assert_jdj_prospective_calendar(session)
    return JdjCandidateValidationService(
        build_jdj_research_service(session),
        manifest=load_jdj_candidate_manifest(candidate_id),
        protocol=load_jdj_candidate_validation_protocol(),
    )


def build_subing_candidate_validation_service(
    session: Session,
) -> SubingCandidateValidationService:
    """Compose Candidate validation around the single Lifecycle research path."""
    return SubingCandidateValidationService(
        build_subing_lifecycle_research_service(session),
        manifest=load_candidate_manifest(_CANDIDATE_MANIFEST),
        protocol=load_candidate_validation_protocol(_CANDIDATE_VALIDATION_PROTOCOL),
    )


def build_n_candidate_validation_service(
    session: Session,
) -> NStructureCandidateValidationService:
    """Compose N Candidate validation over the MDS-only N research path."""
    return NStructureCandidateValidationService(
        build_n_structure_research_service(session),
        manifest=load_n_candidate_manifest(_N_CANDIDATE_MANIFEST),
        protocol=load_n_candidate_validation_protocol(_N_CANDIDATE_VALIDATION_PROTOCOL),
    )


def build_multi_candidate_robustness_service(
    session: Session,
) -> MultiCandidateRobustnessService:
    """Compose the exact read-only robustness dossier over one shared MDS."""
    protocol = load_multi_candidate_robustness_protocol()
    active_products = load_active_products()
    if active_products != protocol.cross_symbol_products:
        from app.market_data.multi_candidate_robustness_service import (
            MultiCandidateActiveUniverseDriftError,
        )

        raise MultiCandidateActiveUniverseDriftError()
    market_data = build_market_data_service(session)
    subing = SubingLifecycleResearchService(
        market_data,
        products=protocol.cross_symbol_products,
        calibration=load_accepted_subing_calibration(_SUBING_CALIBRATION),
        policy=load_subing_lifecycle_policy(_SUBING_LIFECYCLE_POLICY),
    )
    n_structure = NStructureResearchService(
        ActualDominantResearchSegmentLoader(market_data),
        products=protocol.cross_symbol_products,
        policy=load_n_structure_policy(),
    )
    return MultiCandidateRobustnessService(
        protocol,
        subing_research=subing,
        n_research=n_structure,
        subing_validation=SubingCandidateValidationService(
            subing,
            manifest=load_candidate_manifest(_CANDIDATE_MANIFEST),
            protocol=load_candidate_validation_protocol(_CANDIDATE_VALIDATION_PROTOCOL),
        ),
        n_validation=NStructureCandidateValidationService(
            n_structure,
            manifest=load_n_candidate_manifest(_N_CANDIDATE_MANIFEST),
            protocol=load_n_candidate_validation_protocol(
                _N_CANDIDATE_VALIDATION_PROTOCOL
            ),
        ),
        current_active_products=active_products,
    )


def build_live_market_service(session: Session) -> LiveMarketService:
    """构造前台 Live 观察服务，不启动循环也不写入 historical Canonical。"""
    from app.market_data.rqdata_adapter import RQDataClient

    rqdata = RQDataClient()
    return LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(rqdata.live_market_client()),
        dominant_source=rqdata,
        phase_resolver=MarketPhaseResolver(session),
        store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        operational_products=load_operational_products(),
    )
