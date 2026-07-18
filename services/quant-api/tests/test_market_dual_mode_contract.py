from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataProfile, DataQualityReport, MarketDataFile, ProfileActiveBinding
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def test_browser_profile_keeps_warning_visible_but_research_blocks_it(tmp_path: Path) -> None:
    client, session_factory = _client_with_binding(tmp_path, quality_status="warning")

    with client:
        browser = client.get("/api/v1/market/bars", params=_bars_params(access_mode="browser"))
        research = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))

    assert browser.status_code == 200
    assert browser.json()["quality"]["status"] == "warning"
    assert browser.json()["strict_research_ready"] is False
    assert browser.json()["lineage"]["quality_status"] == "warning"
    assert browser.json()["lineage"]["market_data_file_id"] is not None
    assert research.status_code == 422
    assert research.json()["detail"]["code"] == "MARKET_PROFILE_QUALITY_BLOCKED"

    with session_factory() as session:
        assert session.query(MarketDataFile).count() == 1


def test_research_bars_and_ema_share_immutable_lineage_and_warmup_asset(tmp_path: Path) -> None:
    client, _ = _client_with_binding(tmp_path, quality_status="passed")

    with client:
        bars = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))
        assert bars.status_code == 200
        bars_payload = bars.json()
        lineage = bars_payload["lineage"]
        indicators = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "access_mode": "research",
                "indicator_codes": "ema21",
                "display_start": bars_payload["bars"][-20]["time"],
                "display_end": bars_payload["bars"][-1]["time"],
                "display_bar_count": 20,
                "expected_market_data_file_id": lineage["market_data_file_id"],
                "expected_lineage_token": lineage["lineage_token"],
            },
        )
        macd = client.get(
            "/api/v1/market/indicators/macd",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "access_mode": "research",
                "start": "2026-07-01",
                "end": "2026-07-01",
                "expected_market_data_file_id": lineage["market_data_file_id"],
                "expected_lineage_token": lineage["lineage_token"],
            },
        )

    assert indicators.status_code == 200
    indicator_payload = indicators.json()
    assert bars_payload["strict_research_ready"] is True
    assert indicator_payload["strict_research_ready"] is True
    assert indicator_payload["lineage"] == lineage
    assert lineage["source_interval"] == "1m"
    assert lineage["source_interval_basis"] == "parquet_column"
    assert lineage["binding_snapshot"]["source_interval"] == "1m"
    assert indicator_payload["warmup"]["source_bar_count"] == 80
    assert indicator_payload["warmup"]["display_bar_count"] == 20
    assert macd.status_code == 200
    assert macd.json()["lineage"] == lineage


def test_research_blocks_unresolved_source_interval_but_browser_exposes_it(tmp_path: Path) -> None:
    client, session_factory = _client_with_binding(tmp_path, quality_status="passed")
    with session_factory() as session:
        market_file = session.query(MarketDataFile).one()
        frame = pd.read_parquet(market_file.file_path).drop(columns=["source_interval"])
        frame.to_parquet(market_file.file_path, index=False)

    with client:
        browser = client.get("/api/v1/market/bars", params=_bars_params(access_mode="browser"))
        research = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))

    assert browser.status_code == 200
    assert browser.json()["lineage"]["source_interval"] is None
    assert research.status_code == 422
    assert research.json()["detail"]["code"] == "MARKET_PROFILE_LINEAGE_INCOMPLETE"


def test_research_requires_profile_and_returns_stable_error_code(tmp_path: Path) -> None:
    client, _ = _client_with_binding(tmp_path, quality_status="passed")

    with client:
        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "access_mode": "research",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MARKET_RESEARCH_PROFILE_REQUIRED"
    assert "file_path" not in response.text


def test_research_missing_binding_and_uncovered_range_fail_closed(tmp_path: Path) -> None:
    client, session_factory = _client_with_binding(tmp_path, quality_status="passed")

    with client:
        uncovered = client.get(
            "/api/v1/market/bars",
            params={**_bars_params(access_mode="research"), "start": "2026-06-30T09:00:00"},
        )
        with session_factory() as session:
            binding = session.query(ProfileActiveBinding).filter_by(binding_status="active").one()
            binding.binding_status = "superseded"
            binding.superseded_at = datetime.now(UTC)
            session.commit()
        missing = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))

    assert uncovered.status_code == 422
    assert uncovered.json()["detail"]["code"] == "MARKET_PROFILE_RANGE_NOT_COVERED"
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "MARKET_PROFILE_BINDING_MISSING"


def test_research_missing_physical_file_fails_closed(tmp_path: Path) -> None:
    client, session_factory = _client_with_binding(tmp_path, quality_status="passed")
    with session_factory() as session:
        market_file = session.query(MarketDataFile).one()
        Path(market_file.file_path).unlink()

    with client:
        response = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MARKET_PROFILE_FILE_MISSING"
    assert "file_path" not in response.text


def test_indicator_rejects_binding_change_after_bars_snapshot(tmp_path: Path) -> None:
    client, session_factory = _client_with_binding(tmp_path, quality_status="passed")

    with client:
        bars = client.get("/api/v1/market/bars", params=_bars_params(access_mode="research"))
        assert bars.status_code == 200
        lineage = bars.json()["lineage"]

        with session_factory() as session:
            old_binding = session.query(ProfileActiveBinding).filter_by(binding_status="active").one()
            old_binding.binding_status = "superseded"
            old_binding.superseded_at = datetime.now(UTC)
            second = _add_market_file(tmp_path, session, suffix="v2", quality_status="passed", close_offset=100.0)
            session.add(
                ProfileActiveBinding(
                    profile_id="intraday_research_v1",
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    contract_role="actual_contract",
                    period="15m",
                    data_version=second.data_version,
                    market_data_file_id=second.id,
                    binding_status="active",
                )
            )
            session.commit()

        response = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "access_mode": "research",
                "indicator_codes": "ema21",
                "display_bar_count": 20,
                "expected_market_data_file_id": lineage["market_data_file_id"],
                "expected_lineage_token": lineage["lineage_token"],
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MARKET_LINEAGE_CHANGED"


def _bars_params(*, access_mode: str) -> dict[str, object]:
    return {
        "symbol": "jm",
        "contract": "JM2609",
        "period": "15m",
        "profile_id": "intraday_research_v1",
        "access_mode": access_mode,
        "start": "2026-07-01T09:00:00",
        "end": "2026-07-02T04:45:00",
        "tail": False,
    }


def _client_with_binding(tmp_path: Path, *, quality_status: str):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with session_factory() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research",
                description="test",
                contract_roles=["actual_contract"],
                periods=["15m"],
                quality_policy="passed_only",
                provider="rqdata",
                is_active=True,
            )
        )
        market_file = _add_market_file(tmp_path, session, suffix="v1", quality_status=quality_status)
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="JM2609",
                contract_role="actual_contract",
                period="15m",
                data_version=market_file.data_version,
                market_data_file_id=market_file.id,
                binding_status="active",
            )
        )
        session.commit()

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    original_exit = client.__exit__

    def exit_with_cleanup(*args):
        try:
            return original_exit(*args)
        finally:
            app.dependency_overrides.clear()

    client.__exit__ = exit_with_cleanup  # type: ignore[method-assign]
    return client, session_factory


def _add_market_file(
    tmp_path: Path,
    session,
    *,
    suffix: str,
    quality_status: str,
    close_offset: float = 0.0,
) -> MarketDataFile:
    start = datetime(2026, 7, 1, 9, 0)
    path = tmp_path / "data" / "parquet" / "canonical" / "bars" / f"jm2609_15m_{suffix}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(80):
        timestamp = start + timedelta(minutes=15 * index)
        close = 1000.0 + close_offset + index
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": "15m",
                "provider": "rqdata",
                "data_version": f"dual-mode-{suffix}",
                "source_interval": "1m",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=start.replace(tzinfo=UTC),
        end_time=(start + timedelta(minutes=15 * 79)).replace(tzinfo=UTC),
        file_path=str(path),
        row_count=80,
        checksum=f"checksum-{suffix}",
        data_version=f"dual-mode-{suffix}",
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="15m",
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status=quality_status,
            missing_bars=1 if quality_status == "warning" else 0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
        )
    )
    session.flush()
    return market_file
