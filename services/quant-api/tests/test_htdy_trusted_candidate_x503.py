from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from app.backtest.htdy_trusted_candidate import (  # noqa: E402
    CandidateApplyError,
    RETIRED_GATE,
    apply_candidate_transaction,
    build_failure_packet,
    build_success_packet,
    load_x502_bundle,
    verify_packet_hash,
)
from app.backtest.service import BacktestService  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.backtest import (  # noqa: E402
    BacktestOrderModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding  # noqa: E402
from app.schemas.backtest import BacktestTaskConfig  # noqa: E402


X502_DIR = REPO_ROOT / "data/reports/htdy_trusted_report_x5_02"
SCRIPT_PATH = REPO_ROOT / "services/quant-api/scripts/htdy_trusted_candidate.py"


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_profile(session: Any, tmp_path: Path) -> tuple[MarketDataFile, ProfileActiveBinding]:
    source = tmp_path / "jm_MAIN_15m.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "datetime": datetime(2024, 1, 2, 9, 0),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 100,
                    "source_interval": "1m",
                }
            ]
        ),
        source,
    )
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday Research V1",
            description="X5-03 fixture",
            contract_roles=["dominant_main"],
            periods=["15m"],
            quality_policy="passed_only",
            provider="rqdata",
            config_path="configs/data_profiles/intraday_research_v1.json",
        )
    )
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="15m",
        start_time=datetime(2023, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 7, 11, tzinfo=UTC),
        file_path=str(source),
        row_count=1,
        checksum="x503-fixture",
        data_version="x503-fixture-v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    binding = ProfileActiveBinding(
        profile_id="intraday_research_v1",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        contract_role="dominant_main",
        period="15m",
        data_version=market_file.data_version,
        market_data_file_id=market_file.id,
        binding_status="active",
        activated_at=datetime.now(UTC),
    )
    session.add(binding)
    session.commit()
    return market_file, binding


def _trusted_result(*, invalid_timing: bool = False) -> dict[str, Any]:
    signal = "2024-01-02T09:15:00Z" if invalid_timing else "2024-01-02T09:00:00Z"
    return {
        "summary": {"initial_capital": 1_000_000},
        "trades": [
            {
                "tradeid": "HTDY-1",
                "symbol": "jm",
                "research_contract": "jm_MAIN",
                "contract": "JM2405",
                "entry_contract": "JM2405",
                "exit_contract": "JM2405",
                "exchange": "DCE",
                "timeframe": "15m",
                "direction": "long",
                "entry_signal_time": signal,
                "entry_signal_source": "strategy_execution_event",
                "entry_datetime": "2024-01-02T09:15:00Z",
                "exit_datetime": "2024-01-02T10:00:00Z",
                "entry_price": 100,
                "exit_price": 105,
                "volume": 1,
                "contract_multiplier": 60,
                "price_tick": 0.5,
                "gross_pnl": 300,
                "commission": 12,
                "slippage": 30,
                "net_pnl": 258,
                "margin_ratio": 0.12,
                "margin_required": 720,
                "holding_bars": 3,
                "entry_reason": "htdy_strict_long_observation",
                "exit_reason": "take_profit",
                "lineage_status": "mapped",
            }
        ],
        "orders": [
            {
                "orderid": "HTDY-1-OPEN",
                "trade_no": "HTDY-1",
                "leg": "entry",
                "symbol": "jm",
                "contract": "JM2405",
                "direction": "long",
                "offset": "open",
                "status": "all_traded",
                "price": 100,
                "volume": 1,
                "traded": 1,
                "datetime": "2024-01-02T09:15:00Z",
                "lineage_source": "strategy_execution_event",
                "mapping_status": "mapped",
            },
            {
                "orderid": "HTDY-1-CLOSE",
                "trade_no": "HTDY-1",
                "leg": "exit",
                "symbol": "jm",
                "contract": "JM2405",
                "direction": "short",
                "offset": "close",
                "status": "all_traded",
                "price": 105,
                "volume": 1,
                "traded": 1,
                "datetime": "2024-01-02T10:00:00Z",
                "lineage_source": "strategy_execution_event",
                "mapping_status": "mapped",
            },
        ],
        "strategy_execution_events": [
            {
                "action": "open_long",
                "signal_datetime": signal,
                "fill_datetime": "2024-01-02T09:15:00Z",
            }
        ],
        "warnings": [],
        "equity_curve": [
            {"sequence": 0, "equity": 1_000_000},
            {"sequence": 1, "equity": 1_000_258},
        ],
        "drawdown_curve": [],
    }


def _seed_report14(session: Any) -> int:
    config = BacktestTaskConfig(
        symbol="jm.MAIN",
        exchange="DCE",
        interval="15m",
        start=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        end=datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
        strategy_class_path="tests.test_htdy_trusted_candidate_x503:FixtureStrategy",
        strategy_code="report14_trusted_fixture",
        strategy_version="test-v1",
        strategy_parameters={},
        rate=0.0001,
        slippage=1,
        size=60,
        pricetick=0.5,
        capital=1_000_000,
        data_source="local_parquet",
        data_version="report14-fixture-v1",
        quality_status="passed",
        research_only=True,
        request_payload={"fixture": "report14"},
    )
    service = BacktestService(session)
    task = service.create_task(config)
    service.persist_result(task, _trusted_result())
    session.commit()
    report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
    return int(report.id)


class FixtureStrategy:
    pass


def _bundle(market_file: MarketDataFile, binding: ProfileActiveBinding, *, invalid_timing: bool = False) -> dict[str, Any]:
    dry_run = _trusted_result(invalid_timing=invalid_timing)
    dry_run.update(
        {
            "strategy_code": "huotian_dayou_strict",
            "strategy_version": "v0.1.0-backtest-candidate",
            "candidate_policy": "strict_v1_15m_formal_candidate_v0",
            "protocol_hash": "p" * 64,
            "parameter_hash": "a" * 64,
            "execution_snapshot_hash": "s" * 64,
            "data": {
                "start": "2024-01-02T09:00:00",
                "end": "2024-02-02T15:00:00",
                "row_count": 100,
                "data_version": market_file.data_version,
                "market_data_file_id": market_file.id,
                "profile_active_binding_id": binding.id,
            },
        }
    )
    snapshot = {
        "profile_id": "intraday_research_v1",
        "profile_active_binding_id": binding.id,
        "market_data_file_id": market_file.id,
        "data_version": market_file.data_version,
        "file_sha256": "f" * 64,
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "quality_policy": "passed_only",
        "binding_status": "active",
        "snapshot_hash": "s" * 64,
    }
    return {
        "packet": {
            "packet_hash": "x" * 64,
            "protocol_hash": "p" * 64,
            "parameter_hash": "a" * 64,
            "execution_snapshot_hash": "s" * 64,
            "cost_timeline_hash": "c" * 64,
            "dry_run_hash": "d" * 64,
        },
        "execution_snapshot": snapshot,
        "dry_run": dry_run,
        "cost_timeline": {"timeline_hash": "c" * 64, "row_count": 1, "rows": []},
        "preapply_audit": {"audit_status": "passed"},
    }


def _counts(session: Any) -> dict[str, int]:
    return {
        "tasks": int(session.scalar(select(func.count(BacktestTask.id))) or 0),
        "reports": int(session.scalar(select(func.count(BacktestReportModel.id))) or 0),
        "trades": int(session.scalar(select(func.count(BacktestTradeModel.id))) or 0),
        "orders": int(session.scalar(select(func.count(BacktestOrderModel.id))) or 0),
    }


def test_load_x502_bundle_recomputes_all_artifact_hashes() -> None:
    bundle = load_x502_bundle(X502_DIR)

    assert bundle["packet"]["gate"] == "HTDY_TRUSTED_REPORT_APPLY_PACKET_READY"
    assert bundle["preapply_audit"]["audit_status"] == "passed"
    assert bundle["execution_snapshot"]["quality_status"] == "passed"
    assert len(bundle["dry_run"]["trades"]) == 1255
    assert len(bundle["dry_run"]["orders"]) == 2510


def test_apply_candidate_is_retired_before_any_database_access(tmp_path: Path) -> None:
    calls = 0

    def forbidden_session_factory():
        nonlocal calls
        calls += 1
        pytest.fail("retired X5-03 path accessed the database")

    with pytest.raises(CandidateApplyError, match=RETIRED_GATE) as caught:
        apply_candidate_transaction(
            forbidden_session_factory,
            repo_root=tmp_path,
            bundle={},
            source_commit="1" * 40,
        )

    assert calls == 0
    assert caught.value.failure["gate"] == RETIRED_GATE
    assert caught.value.failure["transaction"] == {"status": "not_started"}
    assert caught.value.failure["database_accessed"] is False
    assert caught.value.failure["historical_evidence_mutated"] is False


def test_retired_apply_preserves_existing_report_and_creates_no_rows(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        market_file, binding = _seed_profile(session, tmp_path)
        report14_id = _seed_report14(session)
        before = _counts(session)

    with pytest.raises(CandidateApplyError, match=RETIRED_GATE) as caught:
        apply_candidate_transaction(
            SessionLocal,
            repo_root=tmp_path,
            bundle=_bundle(market_file, binding, invalid_timing=True),
            source_commit="2" * 40,
            report14_id=report14_id,
        )

    assert caught.value.failure["transaction"]["status"] == "not_started"
    with SessionLocal() as session:
        assert _counts(session) == before
        assert session.get(BacktestReportModel, report14_id) is not None


def test_repeated_retired_apply_is_stably_rejected_without_rows(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        market_file, binding = _seed_profile(session, tmp_path)
        report14_id = _seed_report14(session)
    bundle = _bundle(market_file, binding)
    with SessionLocal() as session:
        before = _counts(session)

    for _ in range(2):
        with pytest.raises(CandidateApplyError, match=RETIRED_GATE):
            apply_candidate_transaction(
                SessionLocal,
                repo_root=tmp_path,
                bundle=bundle,
                source_commit="5" * 40,
                report14_id=report14_id,
            )

    with SessionLocal() as session:
        assert _counts(session) == before


def test_success_packet_is_hash_valid_and_preserves_storage_semantics() -> None:
    result = {
        "transaction": {"status": "committed"},
        "candidate_identity": {"task": {"id": 23, "task_no": "BTV-X503"}, "report": {"id": 15, "report_no": "RPT-X503"}},
        "execution_snapshot": {"snapshot_hash": "s" * 64},
        "row_counts": {"delta": {"tasks": 1, "reports": 1, "trades": 1, "orders": 2}},
        "audits": {"candidate": {"audit_status": "passed"}, "report14": {"audit_status": "passed"}},
        "facts_hash": "f" * 64,
    }
    packet = build_success_packet(
        result,
        source_commit="3" * 40,
        x502_packet_hash="x" * 64,
        protocol_hash="p" * 64,
        parameter_hash="a" * 64,
        cost_timeline_hash="c" * 64,
        dry_run_hash="d" * 64,
        artifact_hashes={"candidate_audit": "q" * 64, "report14_audit": "r" * 64},
    )

    assert packet["gate"] == "HTDY_TRUSTED_BACKTEST_CANDIDATE"
    assert packet["storage_semantics"]["dedicated_equity_table"] is False
    assert packet["storage_semantics"]["metrics_location"] == "backtest_reports.summary"
    assert verify_packet_hash(packet)


def test_failure_packet_redacts_paths_and_secrets() -> None:
    packet = build_failure_packet(
        source_commit="4" * 40,
        reason="password leaked at /Users/example/project and /Volumes/private/data",
        failure={"transaction": {"status": "rolled_back"}, "row_counts": {"delta": {"tasks": 0}}},
    )
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True)

    assert packet["gate"] == "HTDY_TRUST_AUDIT_FAILED_REVIEW_REQUIRED"
    assert verify_packet_hash(packet)
    assert "password" not in encoded.lower()
    assert "/Users/" not in encoded
    assert "/Volumes/" not in encoded


def test_cli_is_fixed_scope_and_rejects_arbitrary_output_path(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("htdy_trusted_candidate_cli", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser = module.build_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--apply" not in option_strings
    assert "--report-id" not in option_strings
    assert "--strategy-parameters" not in option_strings
    assert "--x502-dir" not in option_strings
    with pytest.raises(ValueError, match="data/reports"):
        module._validated_output_dir(tmp_path / "outside")
