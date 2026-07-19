from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from app.backtest.htdy_trusted_report import (  # noqa: E402
    CanonicalCostDay,
    FrozenProfileSelection,
    assert_profile_selection_unchanged,
    build_candidate_bars,
    build_apply_packet,
    build_canonical_cost_timeline,
    build_preapply_audit,
    cost_timeline_payload,
    evaluate_full_window,
    freeze_profile_selection,
    packet_hash,
    verify_packet_hash,
    write_artifact_bundle,
)
from app.db.base import Base  # noqa: E402
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding  # noqa: E402
from guiyi_quant.strategies.huotian_dayou_strict import validate_params  # noqa: E402
from guiyi_quant.strategies.huotian_dayou_strict.vnpy_strategy import (  # noqa: E402
    CandidateCostRule,
    TradeParams,
    build_strict_snapshot_series,
    commission_for_trade,
    strict_signal_snapshot,
)


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_profile(session: Session, tmp_path: Path) -> tuple[ProfileActiveBinding, MarketDataFile]:
    source = tmp_path / "jm_15m.parquet"
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
            label="intraday",
            description="x502",
            contract_roles=["dominant_main"],
            periods=["15m"],
            provider="rqdata",
            quality_policy="passed_only",
            is_active=True,
            config_path="configs/data_profiles/intraday_research_v1.json",
        )
    )
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="15m",
        start_time=datetime(2023, 1, 3, tzinfo=UTC),
        end_time=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
        row_count=100,
        file_path=str(source),
        checksum="x502",
        data_version="x502-data-v1",
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
        activated_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    session.add(binding)
    session.commit()
    return binding, market_file


def test_freeze_profile_selection_includes_exact_binding_and_file_hash(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        binding, market_file = _seed_profile(session, tmp_path)
        frozen = freeze_profile_selection(session, project_root=tmp_path)

    assert isinstance(frozen, FrozenProfileSelection)
    assert frozen.profile_active_binding_id == binding.id
    assert frozen.market_data_file_id == market_file.id
    assert frozen.profile_id == "intraday_research_v1"
    assert frozen.data_role == "primary"
    assert frozen.quality_status == "passed"
    assert frozen.file_sha256
    assert frozen.snapshot_hash == packet_hash(frozen.payload_without_hash())
    assert not frozen.relative_path.startswith("/")


def test_freeze_profile_selection_rejects_superseded_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _, market_file = _seed_profile(session, tmp_path)
        market_file.data_role = "superseded"
        session.commit()
        with pytest.raises(ValueError, match="primary"):
            freeze_profile_selection(session, project_root=tmp_path)


def test_profile_revalidation_rejects_binding_drift() -> None:
    before = _frozen_selection()
    after = FrozenProfileSelection(
        **{**before.__dict__, "profile_active_binding_id": before.profile_active_binding_id + 1}
    )

    with pytest.raises(ValueError, match="changed during X5-02"):
        assert_profile_selection_unchanged(before, after)


def test_canonical_cost_timeline_is_complete_and_keeps_close_today(monkeypatch: pytest.MonkeyPatch) -> None:
    days = [date(2026, 7, 8), date(2026, 7, 9)]

    def fake_resolve(session: object, *, trading_day: date):
        return SimpleNamespace(
            trading_day=trading_day,
            actual_contract="JM2609",
            exchange="DCE",
            contract_multiplier=60,
            price_tick=0.5,
            margin_ratio=0.12,
            commission_rule=SimpleNamespace(
                fee_type="rate",
                open_fee=0.0001,
                close_fee=0.0001,
                close_today_fee=0.0003,
            ),
            parameter_source="futures_trading_parameters",
            main_contract_source=SimpleNamespace(
                map_id=10,
                provider="rqdata",
                data_version="map-v1",
                rule="volume_open_interest",
                rank=1,
            ),
        )

    monkeypatch.setattr("app.backtest.htdy_trusted_report.resolve_jm_contract", fake_resolve)
    timeline = build_canonical_cost_timeline(object(), days)

    assert list(timeline) == days
    assert timeline[days[0]].close_today_fee == 0.0003
    assert timeline[days[0]].parameter_source == "futures_trading_parameters"
    assert timeline[days[0]].main_contract_map_id == 10


def test_commission_uses_close_today_only_for_same_trading_day() -> None:
    rule = CandidateCostRule(
        fee_type="rate",
        open_fee=0.0001,
        close_fee=0.0001,
        close_today_fee=0.0003,
        parameter_source="futures_trading_parameters",
        main_contract_map_id=10,
        main_contract_data_version="map-v1",
    )
    entry = TradeParams(
        price_tick=0.5,
        contract_multiplier=60,
        commission_rate=None,
        commission_per_contract=None,
        margin_rate=0.12,
        symbol="jm",
        exchange="DCE",
        contract="JM2609",
        trading_day="2026-07-08",
        cost_rule=rule,
    )
    same_day = TradeParams(**{**entry.__dict__, "trading_day": "2026-07-08"})
    next_day = TradeParams(**{**entry.__dict__, "trading_day": "2026-07-09"})

    intraday = commission_for_trade(1000, 1010, 1, entry, same_day)
    overnight = commission_for_trade(1000, 1010, 1, entry, next_day)

    assert intraday == pytest.approx(1000 * 60 * 0.0001 + 1010 * 60 * 0.0003)
    assert overnight == pytest.approx(1000 * 60 * 0.0001 + 1010 * 60 * 0.0001)


def test_precomputed_strict_snapshots_equal_causal_prefixes() -> None:
    bars = []
    start = datetime(2026, 1, 2, 9, 0)
    for index in range(80):
        base = 100 + index * 0.1
        bars.append(
            SimpleNamespace(
                datetime=start + timedelta(minutes=15 * index),
                open=base,
                high=base + 1.5,
                low=base - 1.0,
                close=base + (0.4 if index % 3 else -0.2),
            )
        )
    params = validate_params()
    snapshots = build_strict_snapshot_series(bars, params)

    assert len(snapshots) == len(bars)
    for index in (0, 24, 49, 79):
        assert snapshots[index] == strict_signal_snapshot(bars[: index + 1], params)


def test_apply_packet_hash_is_canonical_and_tamper_evident() -> None:
    packet = build_apply_packet(
        source_commit="abc123",
        protocol_hash="protocol",
        parameter_hash="params",
        execution_snapshot_hash="execution",
        cost_timeline_hash="costs",
        dry_run_hash="dry-run",
        preapply_audit_hash="audit",
    )
    encoded = json.loads(json.dumps(packet))

    assert packet["gate"] == "HTDY_TRUSTED_REPORT_APPLY_PACKET_READY"
    assert packet["packet_status"] == "READY_FOR_USER_APPROVAL"
    assert verify_packet_hash(encoded) is True
    encoded["source_commit"] = "tampered"
    assert verify_packet_hash(encoded) is False
    assert packet["expected_writes"]["would_write_db"] is False


def _frozen_selection() -> FrozenProfileSelection:
    base = FrozenProfileSelection(
        profile_id="intraday_research_v1",
        profile_active_binding_id=4945,
        market_data_file_id=71338,
        data_version="active-v2",
        relative_path="data/parquet/canonical/jm.parquet",
        file_sha256="source-sha",
        start="2023-01-03T00:00:00+00:00",
        end="2026-07-10T15:00:00+00:00",
        row_count=80,
        source_interval="1m",
        provider="rqdata",
        data_role="primary",
        quality_status="passed",
        quality_policy="passed_only",
        binding_status="active",
    )
    return FrozenProfileSelection(**{**base.__dict__, "snapshot_hash": packet_hash(base.payload_without_hash())})


def _cost_day(day: date) -> CanonicalCostDay:
    return CanonicalCostDay(
        trading_day=day,
        actual_contract="JM2609",
        exchange="DCE",
        contract_multiplier=60,
        price_tick=0.5,
        margin_rate=0.12,
        fee_type="rate",
        open_fee=0.0001,
        close_fee=0.0001,
        close_today_fee=0.0003,
        parameter_source="futures_trading_parameters",
        main_contract_map_id=10,
        main_contract_provider="rqdata",
        main_contract_data_version="map-v1",
        main_contract_rule="volume_open_interest",
        main_contract_rank=1,
    )


def test_full_window_evaluation_is_report_shaped_and_preapply_auditable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = date(2026, 7, 8)
    rows = []
    start = datetime(2026, 7, 8, 9, 0)
    for index in range(80):
        base = 1000 + index * 0.5
        rows.append(
            {
                "datetime": start + timedelta(minutes=15 * index),
                "trading_day": day,
                "open": base,
                "high": base + 5,
                "low": base - 5,
                "close": base + 1,
                "volume": 100,
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "data_version": "active-v2",
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
            }
        )
    timeline = {day: _cost_day(day)}
    bars = build_candidate_bars(rows, timeline, data_version="active-v2")

    import app.backtest.htdy_trusted_report as module

    original = module.build_strict_snapshot_series
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "build_strict_snapshot_series", counted)
    dry_run = evaluate_full_window(
        bars,
        execution_snapshot=_frozen_selection(),
        protocol_hash="protocol",
        parameter_hash="params",
    )
    cost_payload = cost_timeline_payload(timeline)
    audit = build_preapply_audit(
        dry_run,
        execution_snapshot=_frozen_selection(),
        cost_payload=cost_payload,
        expected_trading_days={day},
    )

    assert calls == 1
    assert dry_run["status"] == "htdy_trusted_report_full_window_dry_run"
    assert dry_run["summary"]["trade_count"] == len(dry_run["trades"])
    assert dry_run["equity_curve"]
    assert dry_run["drawdown_curve"]
    assert dry_run["boundaries"]["would_write_db"] is False
    assert audit["audit_status"] == "passed"


def test_preapply_audit_blocks_tampered_trade_count() -> None:
    day = date(2026, 7, 8)
    dry_run = {
        "summary": {"trade_count": 1, "total_commission": 0.0, "total_slippage": 0.0},
        "trades": [],
        "orders": [],
        "equity_curve": [{"equity": 1_000_000.0}],
        "drawdown_curve": [{"equity": 1_000_000.0, "drawdown": 0.0, "drawdown_pct": 0.0}],
        "data": {"trading_days": [day.isoformat()]},
        "boundaries": {"would_write_db": False, "would_touch_report14": False},
    }
    audit = build_preapply_audit(
        dry_run,
        execution_snapshot=_frozen_selection(),
        cost_payload=cost_timeline_payload({day: _cost_day(day)}),
        expected_trading_days={day},
    )

    assert audit["audit_status"] == "failed"
    assert any("trade_count" in reason for reason in audit["blocked_reasons"])


def test_artifact_bundle_binds_hashes_without_absolute_paths(tmp_path: Path) -> None:
    day = date(2026, 7, 8)
    selection = _frozen_selection()
    cost_payload = cost_timeline_payload({day: _cost_day(day)})
    dry_run = {
        "status": "htdy_trusted_report_full_window_dry_run",
        "summary": {"trade_count": 0},
        "trades": [],
        "orders": [],
        "equity_curve": [{"equity": 1_000_000.0}],
        "drawdown_curve": [{"equity": 1_000_000.0, "drawdown": 0.0, "drawdown_pct": 0.0}],
        "data": {"trading_days": [day.isoformat()]},
        "boundaries": {"would_write_db": False, "would_touch_report14": False},
    }
    audit = {
        "audit_status": "passed",
        "blocked_reasons": [],
        "readonly": True,
        "would_write_db": False,
    }
    packet = write_artifact_bundle(
        tmp_path,
        source_commit="abc123",
        protocol_hash="protocol",
        parameter_hash="params",
        execution_snapshot=selection,
        cost_payload=cost_payload,
        dry_run=dry_run,
        preapply_audit=audit,
    )

    assert verify_packet_hash(packet)
    assert packet["artifacts"]["execution_snapshot"]["path"] == "execution_input_snapshot.json"
    assert all((tmp_path / item["path"]).is_file() for item in packet["artifacts"].values())
    encoded = json.dumps(packet, ensure_ascii=False)
    assert "/Users/" not in encoded
    assert "/Volumes/" not in encoded
    assert "/private/" not in encoded


def test_formal_cli_has_no_source_or_cost_override_arguments() -> None:
    script_path = REPO_ROOT / "services/quant-api/scripts/htdy_trusted_report_packet.py"
    spec = importlib.util.spec_from_file_location("htdy_x502_cli", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.build_parser()
    options = {flag for action in parser._actions for flag in action.option_strings}

    assert "--output-dir" in options
    assert "--source" not in options
    assert "--price-tick" not in options
    assert "--commission-rate" not in options
    assert "--margin-rate" not in options


def test_formal_cli_imports_quant_core_outside_pytest_path_bootstrap() -> None:
    script_path = REPO_ROOT / "services/quant-api/scripts/htdy_trusted_report_packet.py"
    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=REPO_ROOT / "services/quant-api",
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--output-dir" in completed.stdout
