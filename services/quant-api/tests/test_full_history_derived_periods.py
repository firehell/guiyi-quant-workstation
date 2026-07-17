from __future__ import annotations

from datetime import UTC, date, datetime
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.data_center import Contract, MarketDataFile, ProfileActiveBinding, TradingCalendar, TradingSession
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars
from app.services.rqdata_ingest.full_history_derived_periods import (
    DERIVED_PERIOD_TARGETS_VERIFIED,
    EVIDENCE_ONLY,
    DerivedPeriodVerificationConfig,
    RepairApprovalError,
    apply_derived_period_repair_plan,
    apply_jm_session_repair_plan,
    build_consumer_targets,
    build_derived_period_repair_plan,
    build_jm_session_repair_plan,
    run_derived_period_verification,
    write_derived_period_reports,
    _compare_content,
    _datetime_series_equal,
    _load_processed_lineage,
    _validate_data_environment,
    _with_effective_target_end,
)
from app.services.rqdata_ingest.full_history_contract import resolve_first_completed_week
from app.services.trading_session_clock import SessionWindow
from app.services.rqdata_ingest.parquet import sha256_file


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts/rqdata_full_history_derived_periods.py"


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source_frame(start: str = "2023-06-28 09:01:00", rows: int = 10) -> pd.DataFrame:
    stamps = pd.date_range(start, periods=rows, freq="min")
    return pd.DataFrame(
        {
            "symbol": ["jm"] * rows,
            "contract": ["jm.MAIN"] * rows,
            "exchange": ["DCE"] * rows,
            "vt_symbol": ["jm.MAIN.DCE"] * rows,
            "datetime": stamps,
            "trading_day": [date(2023, 6, 28)] * rows,
            "interval": ["1m"] * rows,
            "period": ["1m"] * rows,
            "open": [100.0 + value for value in range(rows)],
            "high": [101.0 + value for value in range(rows)],
            "low": [99.0 + value for value in range(rows)],
            "close": [100.5 + value for value in range(rows)],
            "volume": [10.0] * rows,
            "turnover": [1000.0] * rows,
            "open_interest": [500.0] * rows,
            "source": ["rqdata"] * rows,
            "provider": ["rqdata"] * rows,
            "data_role": ["primary"] * rows,
            "quality_status": ["passed"] * rows,
            "data_version": ["source-v1"] * rows,
            "created_at": [datetime(2026, 7, 10, tzinfo=UTC)] * rows,
        }
    )


def _market_file(
    *,
    path: Path,
    period: str,
    version: str,
    role: str = "primary",
    quality: str = "passed",
) -> MarketDataFile:
    frame = pd.read_parquet(path)
    stamps = pd.to_datetime(frame["datetime"])
    return MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period=period,
        start_time=stamps.min().to_pydatetime().replace(tzinfo=UTC),
        end_time=stamps.max().to_pydatetime().replace(tzinfo=UTC),
        file_path=str(path),
        row_count=len(frame),
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version=version,
        data_role=role,
        quality_status=quality,
    )


def _seed_jm_session_repair_reference(session: Session) -> None:
    session.add(
        Contract(
            contract_code="JM2609",
            instrument_symbol="jm",
            exchange_code="DCE",
            product="jm",
            trading_hours="21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00",
            status="active",
            provider="rqdata",
        )
    )
    session.add(
        TradingSession(
            exchange_code="CNFE",
            instrument_symbol="jm",
            session_name="regular",
            start_time=datetime(2023, 1, 3, 9, 0).time(),
            end_time=datetime(2023, 1, 3, 15, 0).time(),
            crosses_midnight=False,
            is_active=True,
            provider="rqdata",
        )
    )
    for trading_day in (date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 6), date(2023, 1, 9)):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=trading_day,
                is_trading_day=True,
                has_night_session=False,
                provider="rqdata",
            )
        )
    session.commit()


def test_jm_session_repair_plan_is_exact_and_apply_is_idempotent(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _seed_jm_session_repair_reference(session)
        plan = build_jm_session_repair_plan(
            session,
            batch_id="jm-session-reference-005-001",
            audit_start=date(2023, 1, 3),
            audit_end=date(2023, 1, 9),
            enforce_formal_counts=False,
        )

        assert plan["contract_evidence"]["rqdata_contract_count"] == 1
        assert plan["operation_counts"] == {
            "calendar_update": 2,
            "session_insert": 4,
            "session_retire": 1,
        }
        assert plan["calendar_evidence"]["night_enabled_count"] == 2
        assert plan["calendar_evidence"]["night_disabled_count"] == 2

        result = apply_jm_session_repair_plan(
            plan,
            approval_statement=plan["required_approval_statement"],
            session=session,
            require_postgresql=False,
        )
        second = apply_jm_session_repair_plan(
            plan,
            approval_statement=plan["required_approval_statement"],
            session=session,
            require_postgresql=False,
        )

        assert result["status"] == "APPLIED_VERIFIED"
        assert second["status"] == "ALREADY_APPLIED"
        active = session.query(TradingSession).filter_by(
            exchange_code="DCE",
            instrument_symbol="jm",
            is_active=True,
        ).all()
        assert [item.session_name for item in sorted(active, key=lambda item: item.start_time)] == [
            "day_am_1",
            "day_am_2",
            "day_pm",
            "night",
        ]


def test_jm_session_repair_rejects_approval_or_reference_drift(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _seed_jm_session_repair_reference(session)
        plan = build_jm_session_repair_plan(
            session,
            batch_id="jm-session-reference-005-001",
            audit_start=date(2023, 1, 3),
            audit_end=date(2023, 1, 9),
            enforce_formal_counts=False,
        )
        with pytest.raises(RepairApprovalError, match="SESSION_REPAIR_APPROVAL_STATEMENT_MISMATCH"):
            apply_jm_session_repair_plan(
                plan,
                approval_statement="wrong",
                session=session,
                require_postgresql=False,
            )
        session.query(TradingCalendar).filter_by(
            exchange_code="DCE",
            trade_date=date(2023, 1, 4),
        ).one().has_night_session = True
        session.commit()

        with pytest.raises(RepairApprovalError, match="SESSION_REPAIR_EVIDENCE_DRIFT"):
            apply_jm_session_repair_plan(
                plan,
                approval_statement=plan["required_approval_statement"],
                session=session,
                require_postgresql=False,
            )


def test_datetime_content_comparison_ignores_parquet_time_unit() -> None:
    expected = pd.Series(pd.to_datetime(["2023-06-28", "2023-06-29"]).astype("datetime64[ns]"))
    actual = pd.Series(pd.to_datetime(["2023-06-28", "2023-06-29"]).astype("datetime64[us]"))

    assert _datetime_series_equal(expected, actual) is True


def test_consumer_targets_keep_jm_hard_separate_from_profile_eligibility() -> None:
    rows = build_consumer_targets(("a", "al", "jm"), audit_end=date(2026, 7, 10))

    hard = [row for row in rows if row["requirement_level"] == "hard"]
    eligible = [row for row in rows if row["requirement_level"] == "profile_eligible"]
    assert {row["product"] for row in hard} == {"jm"}
    assert {row["period"] for row in hard} >= {"1m", "5m", "15m", "1d"}
    assert {row["product"] for row in eligible} == {"a", "al", "jm"}
    assert {row["period"] for row in eligible} == {"1m", "5m", "15m", "30m", "60m", "1d"}


def test_filtered_scope_can_never_emit_official_verified_marker(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        result = run_derived_period_verification(
            DerivedPeriodVerificationConfig(
                project_root=tmp_path,
                scan_mode="quick",
                products=("a",),
                require_postgresql=False,
            ),
            session,
        )

    assert result.summary["status"] == EVIDENCE_ONLY
    assert result.summary["formal_gate_eligible"] is False


def test_effective_target_end_uses_last_completed_trading_day(tmp_path: Path) -> None:
    source_path = tmp_path / "period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    source_path.parent.mkdir(parents=True)
    _source_frame().to_parquet(source_path, index=False)
    with _session(tmp_path) as session:
        source = _market_file(path=source_path, period="1m", version="v1")
        session.add_all(
            [
                source,
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2026, 6, 26),
                    is_trading_day=True,
                    has_night_session=False,
                    provider="fixture",
                ),
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2026, 6, 28),
                    is_trading_day=False,
                    has_night_session=False,
                    provider="fixture",
                ),
            ]
        )
        session.commit()
        target = _with_effective_target_end(
            {"target_end": "2026-06-28", "effective_target_end": "2026-06-28"},
            source=source,
            session=session,
        )

    assert target["effective_target_end"] == "2026-06-26"
    assert target["calendar_boundary_status"] == "verified"


def test_effective_target_end_does_not_shrink_on_stale_calendar(tmp_path: Path) -> None:
    source_path = tmp_path / "period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    source_path.parent.mkdir(parents=True)
    _source_frame().to_parquet(source_path, index=False)
    with _session(tmp_path) as session:
        source = _market_file(path=source_path, period="1m", version="v1")
        session.add_all(
            [
                source,
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2026, 6, 1),
                    is_trading_day=True,
                    has_night_session=False,
                    provider="fixture",
                ),
            ]
        )
        session.commit()
        target = _with_effective_target_end(
            {"target_end": "2026-06-28", "effective_target_end": "2026-06-28"},
            source=source,
            session=session,
        )

    assert target["effective_target_end"] == "2026-06-28"
    assert target["calendar_boundary_status"] == "unverified"


def test_production_data_root_must_be_a_mounted_external_volume(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ENV_BLOCKED_DATA_ROOT"):
        _validate_data_environment(tmp_path)


def test_quick_verification_requires_exact_lineage_not_source_interval_only(tmp_path: Path) -> None:
    root = tmp_path
    source_path = root / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    direct_daily_path = root / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=jm/contract=jm.MAIN/direct.parquet"
    source_path.parent.mkdir(parents=True)
    direct_daily_path.parent.mkdir(parents=True)
    source = _source_frame()
    source.to_parquet(source_path, index=False)
    daily = aggregate_standard_bars(source, "1d").drop(columns=["source_bar_count"])
    daily.to_parquet(direct_daily_path, index=False)

    with _session(tmp_path) as session:
        source_file = _market_file(path=source_path, period="1m", version="source-v1")
        daily_file = _market_file(path=direct_daily_path, period="1d", version="daily-direct-v1")
        session.add_all([source_file, daily_file])
        session.commit()
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1m",
                data_version="source-v1",
                market_data_file_id=source_file.id,
                binding_status="active",
            )
        )
        session.commit()

        result = run_derived_period_verification(
            DerivedPeriodVerificationConfig(
                project_root=root,
                scan_mode="quick",
                products=("jm",),
                require_postgresql=False,
            ),
            session,
        )

    daily_rows = [row for row in result.derived_period_inventory if row["period"] == "1d" and row["requirement_level"] == "hard"]
    assert daily_rows
    assert daily_rows[0]["lineage_status"] == "lineage_unverified"
    assert daily_rows[0]["source_bar_count_status"] == "column_missing"
    assert result.summary["status"] == "DERIVED_PERIOD_TARGETS_REPAIR_REQUIRED"


def test_quick_verification_accepts_processed_summary_source_reference(tmp_path: Path) -> None:
    root = tmp_path
    source_path = root / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    derived_path = root / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=DCE/symbol=jm/contract=jm.MAIN/derived.parquet"
    old_primary_path = root / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=DCE/symbol=jm/contract=jm.MAIN/old-primary.parquet"
    source_path.parent.mkdir(parents=True)
    derived_path.parent.mkdir(parents=True)
    source = _source_frame()
    source.to_parquet(source_path, index=False)
    aggregate_standard_bars(source, "5m").to_parquet(derived_path, index=False)
    aggregate_standard_bars(source, "5m").to_parquet(old_primary_path, index=False)
    summary = root / "data/processed/v1b/jm/lineage.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps(
            {
                "periods": {
                    "5m": {
                        "data_version": "derived-v1",
                        "raw": {"path": str(source_path)},
                        "standard": {"path": str(derived_path), "checksum": sha256_file(derived_path)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with _session(tmp_path) as session:
        source_file = _market_file(path=source_path, period="1m", version="source-v1")
        derived_file = _market_file(path=derived_path, period="5m", version="derived-v1", role="candidate")
        old_primary = _market_file(path=old_primary_path, period="5m", version="old-primary-v1")
        session.add_all([source_file, derived_file, old_primary])
        session.commit()
        result = run_derived_period_verification(
            DerivedPeriodVerificationConfig(
                project_root=root,
                scan_mode="quick",
                products=("jm",),
                require_postgresql=False,
            ),
            session,
        )

    row = next(row for row in result.derived_period_inventory if row["period"] == "5m" and row["consumer"] == "backtest")
    source_row = next(
        row
        for row in result.derived_period_inventory
        if row["period"] == "1m" and row["consumer"] == "live_observation"
    )
    assert row["lineage_status"] == "verified"
    assert row["derived_version"] == "derived-v1"
    assert row["source_1m_path"] == str(source_path)
    assert row["checksum_status"] == "matched"
    assert source_row["source_1m_file_id"] == source_file.id
    assert source_row["coverage_status"] == "partial"


def test_processed_lineage_preserves_conflicting_source_declarations(tmp_path: Path) -> None:
    processed = tmp_path / "data/processed/v1b/jm"
    processed.mkdir(parents=True)
    derived = tmp_path / "derived.parquet"
    for index, source in enumerate((tmp_path / "source-a.parquet", tmp_path / "source-b.parquet")):
        (processed / f"lineage-{index}.json").write_text(
            json.dumps(
                {
                    "periods": {
                        "5m": {
                            "raw": {"path": str(source)},
                            "standard": {"path": str(derived)},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    lineage = _load_processed_lineage(tmp_path)

    assert lineage[str(derived)] == (str(tmp_path / "source-a.parquet"), str(tmp_path / "source-b.parquet"))


def test_exact_lineage_requires_selected_source_physical_checksum(tmp_path: Path) -> None:
    source_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    derived_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=5m/exchange=DCE/symbol=jm/contract=jm.MAIN/derived.parquet"
    source_path.parent.mkdir(parents=True)
    derived_path.parent.mkdir(parents=True)
    source = _source_frame()
    source.to_parquet(source_path, index=False)
    aggregate_standard_bars(source, "5m").to_parquet(derived_path, index=False)
    processed = tmp_path / "data/processed/v1b/jm/lineage.json"
    processed.parent.mkdir(parents=True)
    processed.write_text(
        json.dumps(
            {
                "periods": {
                    "5m": {
                        "raw": {"path": str(source_path)},
                        "standard": {"path": str(derived_path)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with _session(tmp_path) as session:
        source_file = _market_file(path=source_path, period="1m", version="source-v1")
        derived_file = _market_file(path=derived_path, period="5m", version="derived-v1", role="candidate")
        session.add_all([source_file, derived_file])
        session.commit()
        drifted = pd.read_parquet(source_path)
        drifted.loc[0, "close"] += 1
        drifted.to_parquet(source_path, index=False)
        result = run_derived_period_verification(
            DerivedPeriodVerificationConfig(
                project_root=tmp_path,
                scan_mode="quick",
                products=("jm",),
                require_postgresql=False,
            ),
            session,
        )

    row = next(row for row in result.derived_period_inventory if row["period"] == "5m")
    assert row["source_checksum_status"] == "mismatch"
    assert row["lineage_status"] == "lineage_unverified"


def test_full_content_comparison_recomputes_and_detects_drift(tmp_path: Path) -> None:
    source = _source_frame()
    source_path = tmp_path / "source.parquet"
    derived_path = tmp_path / "derived.parquet"
    source.to_parquet(source_path, index=False)
    aggregate_standard_bars(source, "5m").to_parquet(derived_path, index=False)

    class Clock:
        def trading_days_between(self, start: date, end: date, *, exchange: str):
            assert exchange == "DCE"
            return [date(2023, 6, 28)], True

        def windows_for_trading_days(self, trading_days: list[date], *, product: str, exchange: str):
            assert product == "jm"
            assert exchange == "DCE"
            return [
                SessionWindow(
                    trading_days[0],
                    "day",
                    datetime(2023, 6, 28, 9, 0),
                    datetime(2023, 6, 28, 9, 10),
                )
            ]

    matched = _compare_content(
        source_path,
        derived_path,
        period="5m",
        product="jm",
        target_start=date(2023, 6, 28),
        target_end=date(2023, 6, 28),
        clock=Clock(),  # type: ignore[arg-type]
    )
    assert matched["content_comparison_status"] == "matched"
    drifted = pd.read_parquet(derived_path)
    drifted.loc[0, "close"] += 1
    drifted.to_parquet(derived_path, index=False)
    mismatch = _compare_content(
        source_path,
        derived_path,
        period="5m",
        product="jm",
        target_start=date(2023, 6, 28),
        target_end=date(2023, 6, 28),
        clock=Clock(),  # type: ignore[arg-type]
    )
    assert mismatch["content_comparison_status"] == "mismatch"
    trading_day_drift = aggregate_standard_bars(source, "5m")
    trading_day_drift["trading_day"] = date(2023, 6, 29)
    trading_day_drift.to_parquet(derived_path, index=False)
    mismatch = _compare_content(
        source_path,
        derived_path,
        period="5m",
        product="jm",
        target_start=date(2023, 6, 28),
        target_end=date(2023, 6, 29),
        clock=Clock(),  # type: ignore[arg-type]
    )
    assert mismatch["content_comparison_status"] == "mismatch"


def test_completed_week_requires_provider_bar_on_closed_week_end() -> None:
    trading_days = [date(2012, 5, 10), date(2012, 5, 11)]

    assert resolve_first_completed_week(
        listed_semantic_start=date(2012, 5, 10),
        provider_first_weekly_bar=date(2012, 5, 11),
        trading_days=trading_days,
        closed_through=date(2012, 5, 11),
        provider_authoritative=True,
        calendar_complete=True,
    ) == date(2012, 5, 11)
    assert resolve_first_completed_week(
        listed_semantic_start=date(2012, 5, 10),
        provider_first_weekly_bar=date(2012, 5, 11),
        trading_days=trading_days,
        closed_through=date(2012, 5, 10),
        provider_authoritative=True,
        calendar_complete=True,
    ) is None


def test_repair_plan_contains_only_hard_residuals() -> None:
    residuals = [
        {
            "target_id": "hard-jm-1d",
            "requirement_level": "hard",
            "product": "jm",
            "period": "1d",
            "source_1m_file_id": 1,
            "source_1m_path": "/tmp/source.parquet",
            "source_1m_version": "v1",
            "source_1m_checksum": "abc",
        },
        {"target_id": "eligible-a-1d", "requirement_level": "profile_eligible", "product": "a", "period": "1d"},
    ]

    plan = build_derived_period_repair_plan(residuals, batch_id="derived-period-hard-001")

    assert [row["target_id"] for row in plan["operations"]] == ["hard-jm-1d"]
    assert plan["required_approval_statement"].startswith(
        "APPROVE FULL-HISTORY-DERIVED-PERIODS-005 derived-period-hard-001 "
    )
    assert len(plan["ledger_sha256"]) == 64


def test_repair_plan_deduplicates_consumers_into_one_product_period_operation() -> None:
    residuals = [
        {
            "target_id": "backtest-jm-5m",
            "requirement_level": "hard",
            "consumer": "backtest",
            "product": "jm",
            "period": "5m",
            "target_start": "2023-06-28",
            "target_end": "2026-06-28",
            "source_1m_file_id": 10,
            "source_1m_path": "/tmp/source.parquet",
            "source_1m_version": "v1",
            "source_1m_checksum": "abc",
        },
        {
            "target_id": "signal-jm-5m",
            "requirement_level": "hard",
            "consumer": "signal",
            "product": "jm",
            "period": "5m",
            "target_start": "2023-01-03",
            "target_end": "2026-07-10",
            "source_1m_file_id": 10,
            "source_1m_path": "/tmp/source.parquet",
            "source_1m_version": "v1",
            "source_1m_checksum": "abc",
        },
    ]

    plan = build_derived_period_repair_plan(residuals, batch_id="derived-period-hard-001")

    assert len(plan["operations"]) == 1
    assert plan["operations"][0]["target_start"] == "2023-01-03"
    assert plan["operations"][0]["target_end"] == "2026-07-10"
    assert plan["operations"][0]["consumers"] == ["backtest", "signal"]


def test_repair_plan_blocks_rebuild_when_session_reference_is_unresolved() -> None:
    residuals = [
        {
            "target_id": "hard:signal:jm:5m",
            "requirement_level": "hard",
            "product": "jm",
            "period": "5m",
            "session_boundary_status": "unmatched_source_rows",
        },
        {
            "target_id": "hard:backtest:jm:1d",
            "requirement_level": "hard",
            "product": "jm",
            "period": "1d",
            "session_boundary_status": "passed",
            "source_1m_file_id": 1,
            "source_1m_path": "/tmp/source.parquet",
            "source_1m_version": "v1",
            "source_1m_checksum": "abc",
        },
    ]

    plan = build_derived_period_repair_plan(residuals, batch_id="derived-period-hard-002")

    assert [row["period"] for row in plan["operations"]] == ["1d"]
    assert [row["period"] for row in plan["blocked_residuals"]] == ["5m"]


def test_repair_plan_rejects_conflicting_consumer_source_identity() -> None:
    residuals = [
        {
            "target_id": f"hard-{source_id}",
            "requirement_level": "hard",
            "consumer": consumer,
            "product": "jm",
            "period": "5m",
            "session_boundary_status": "passed",
            "source_1m_file_id": source_id,
            "source_1m_path": f"/tmp/source-{source_id}.parquet",
            "source_1m_version": f"v{source_id}",
            "source_1m_checksum": f"checksum-{source_id}",
        }
        for source_id, consumer in ((1, "backtest"), (2, "signal"))
    ]

    plan = build_derived_period_repair_plan(residuals, batch_id="derived-period-hard-003")

    assert plan["operations"] == []
    assert len(plan["blocked_residuals"]) == 2


def test_repair_batch_id_must_be_safe_slug() -> None:
    with pytest.raises(RepairApprovalError, match="REPAIR_BATCH_ID_INVALID"):
        build_derived_period_repair_plan([], batch_id="../unsafe")


def test_apply_repair_requires_exact_approval_and_writes_new_candidate(tmp_path: Path) -> None:
    root = tmp_path
    source_path = root / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/source.parquet"
    source_path.parent.mkdir(parents=True)
    _source_frame().to_parquet(source_path, index=False)

    with _session(tmp_path) as session:
        source_file = _market_file(path=source_path, period="1m", version="source-v1")
        session.add_all(
            [
                source_file,
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2023, 6, 28),
                    is_trading_day=True,
                    has_night_session=False,
                    provider="fixture",
                ),
                TradingSession(
                    exchange_code="DCE",
                    instrument_symbol="jm",
                    session_name="day",
                    start_time=datetime(2023, 6, 28, 9, 0).time(),
                    end_time=datetime(2023, 6, 28, 9, 10).time(),
                    crosses_midnight=False,
                    is_active=True,
                    provider="fixture",
                ),
            ]
        )
        session.commit()
        plan = build_derived_period_repair_plan(
            [
                {
                    "target_id": "hard-jm-1d",
                    "requirement_level": "hard",
                    "consumer": "backtest",
                    "profile_id": "intraday_research_v1",
                    "product": "jm",
                    "contract_role": "dominant_main",
                    "period": "1d",
                    "target_start": "2023-06-28",
                    "target_end": "2023-06-28",
                    "source_1m_file_id": source_file.id,
                    "source_1m_path": str(source_path),
                    "source_1m_version": "source-v1",
                    "source_1m_checksum": source_file.checksum,
                    "source_1m_quality": "passed",
                }
            ],
            batch_id="derived-period-hard-001",
        )

        with pytest.raises(RepairApprovalError):
            apply_derived_period_repair_plan(
                plan,
                approval_statement="wrong",
                project_root=root,
                session=session,
                require_postgresql=False,
            )

        result = apply_derived_period_repair_plan(
            plan,
            approval_statement=plan["required_approval_statement"],
            project_root=root,
            session=session,
            require_postgresql=False,
        )

        candidate = session.get(MarketDataFile, result["market_data_file_ids"][0])
        assert candidate is not None
        assert candidate.data_role == "candidate"
        assert candidate.quality_status == "passed"
        assert Path(candidate.file_path).is_file()
        frame = pd.read_parquet(candidate.file_path)
        assert frame["source_interval"].unique().tolist() == ["1m"]
        assert frame["source_bar_count"].tolist() == [10]
        assert frame["source_market_data_file_id"].unique().tolist() == [source_file.id]
        assert frame["source_path"].unique().tolist() == [str(source_path.resolve())]
        assert frame["source_data_version"].unique().tolist() == ["source-v1"]
        assert frame["source_checksum"].unique().tolist() == [source_file.checksum]
        assert frame["source_profile_id"].unique().tolist() == ["intraday_research_v1"]
        summary = json.loads(
            (root / "data/processed/v1b/jm/jm_derived-period-hard-001_derived_periods_005.json").read_text()
        )
        lineage = summary["periods"]["1d"]["lineage"]
        assert lineage["source_market_data_file_id"] == source_file.id
        assert lineage["source_checksum"] == source_file.checksum
        assert result["profile_binding_changed"] is False
        assert result["calls_rqdata"] is False


def test_report_writer_refuses_existing_directory(tmp_path: Path) -> None:
    result = type(
        "Result",
        (),
        {
            "consumer_target_matrix": [],
            "derived_period_inventory": [],
            "lineage_residuals": [],
            "materialization_estimate": {},
            "summary": {"status": DERIVED_PERIOD_TARGETS_VERIFIED},
        },
    )()
    output = tmp_path / "reports"
    output.mkdir()

    with pytest.raises(FileExistsError):
        write_derived_period_reports(result, output)


def test_direct_postgresql_is_required_by_default(tmp_path: Path) -> None:
    with _session(tmp_path) as session, pytest.raises(RuntimeError, match="ENV_BLOCKED_DB"):
        run_derived_period_verification(
            DerivedPeriodVerificationConfig(project_root=tmp_path, products=("jm",)),
            session,
        )


def test_cli_plan_repair_freezes_only_hard_residuals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    verification = tmp_path / "verification"
    verification.mkdir()
    pd.DataFrame(
        [
                {
                    "target_id": "hard-jm-1d",
                    "requirement_level": "hard",
                    "product": "jm",
                    "period": "1d",
                    "source_1m_file_id": 1,
                    "source_1m_path": "/tmp/source.parquet",
                    "source_1m_version": "v1",
                    "source_1m_checksum": "abc",
                },
            {"target_id": "eligible-a-1d", "requirement_level": "profile_eligible", "product": "a", "period": "1d"},
        ]
    ).to_csv(verification / "lineage_residuals.csv", index=False)
    module = _load_script()

    exit_code = module.main(
        [
            "plan-repair",
            "--project-root",
            str(tmp_path),
            "--verification-dir",
            str(verification),
            "--batch-id",
            "derived-period-hard-001",
            "--output-dir",
            str(tmp_path / "plan"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    plan = json.loads((tmp_path / "plan/repair_plan.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "DRY_RUN_APPROVAL_REQUIRED"
    assert len(plan["operations"]) == 1
    assert plan["operations"][0]["product"] == "jm"
    assert payload["writes_database"] is False
    assert payload["calls_rqdata"] is False


def test_cli_exposes_separate_session_plan_and_apply_commands() -> None:
    module = _load_script()

    planned = module.build_parser().parse_args(
        ["plan-session-repair", "--output-dir", "/tmp/session-plan"]
    )
    applied = module.build_parser().parse_args(
        [
            "apply-session-repair",
            "--plan-dir",
            "/tmp/session-plan",
            "--approval-statement",
            "approved",
        ]
    )

    assert planned.command == "plan-session-repair"
    assert planned.batch_id == "jm-session-reference-005-001"
    assert applied.command == "apply-session-repair"


def _load_script():
    spec = importlib.util.spec_from_file_location("rqdata_full_history_derived_periods", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
