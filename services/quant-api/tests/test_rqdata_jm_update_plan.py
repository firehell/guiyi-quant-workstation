from datetime import date

import pandas as pd

from app.services.rqdata_ingest.jm_update_plan import build_jm_history_update_plan


class FakePlanClient:
    def trading_dates(self, start_date: date, end_date: date) -> list[date]:
        assert start_date == date(2026, 1, 1)
        assert end_date == date(2026, 1, 8)
        return [
            date(2026, 1, 2),
            date(2026, 1, 5),
            date(2026, 1, 6),
            date(2026, 1, 7),
            date(2026, 1, 8),
        ]

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        assert product == "JM"
        assert rank == 1
        assert start_date == date(2026, 1, 2)
        assert end_date == date(2026, 1, 8)
        return pd.DataFrame(
            [
                {"date": date(2026, 1, 2), "dominant": "JM2605"},
                {"date": date(2026, 1, 5), "dominant": "JM2605"},
                {"date": date(2026, 1, 6), "dominant": "JM2609"},
                {"date": date(2026, 1, 7), "dominant": "JM2609"},
                {"date": date(2026, 1, 8), "dominant": "JM2609"},
            ]
        )


def test_build_jm_history_update_plan_segments_dominant_contracts() -> None:
    plan = build_jm_history_update_plan(
        FakePlanClient(),
        current_end=date(2025, 12, 31),
        as_of=date(2026, 1, 8),
    )

    assert plan["status"] == "ready"
    assert plan["update_start_date"] == "2026-01-02"
    assert plan["latest_trading_date"] == "2026-01-08"
    assert plan["source_contracts"] == ["JM2605", "JM2609"]
    assert plan["main_contract_segments"] == [
        {"contract": "JM2605", "start_date": "2026-01-02", "end_date": "2026-01-05", "trading_days": 2},
        {"contract": "JM2609", "start_date": "2026-01-06", "end_date": "2026-01-08", "trading_days": 3},
    ]
    assert list(plan["periods"]) == ["1m", "5m", "15m", "30m", "60m", "1d"]
    assert plan["periods"]["1m"]["data_version"] == "rqdata_jm_standard_1m_20230103_20260108_v2"
    assert plan["periods"]["30m"] == {
        "data_version": "rqdata_jm_standard_30m_20230103_20260108_v2",
        "raw_required": True,
        "standard_required": True,
        "quality_required": "passed",
        "source_method": "rqdata_direct",
    }
    assert plan["periods"]["60m"]["source_method"] == "rqdata_direct"
    assert plan["periods"]["15m"]["quality_required"] == "passed"
    assert plan["safety"] == {
        "requires_checkpoint_before_apply": True,
        "writes_data": False,
        "writes_database": False,
        "dry_run_only": True,
        "do_not_use_continuous_contract_as_tradable_contract": True,
    }


def test_build_jm_history_update_plan_reports_up_to_date_when_no_trading_dates() -> None:
    class NoDatesClient:
        @staticmethod
        def trading_dates(start_date: date, end_date: date) -> list[date]:
            return []

    plan = build_jm_history_update_plan(
        NoDatesClient(),
        current_end=date(2025, 12, 31),
        as_of=date(2026, 1, 1),
    )

    assert plan["status"] == "up_to_date"
    assert plan["writes_data"] is False
    assert plan["writes_database"] is False
