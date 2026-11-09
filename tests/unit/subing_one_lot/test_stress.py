from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from copy import deepcopy
import json

import pytest

from scripts.research.subing_one_lot_stress import (
    session_eligibility,
    stressed,
    metrics,
    dump,
    build_context,
    open_calendar_days,
    oos_preflight,
)
from tests.unit.subing_one_lot.test_policy import setup, run


def test_oos_uses_all_session_times_not_trading_day_label():
    lock = datetime(2026, 11, 8, 13, tzinfo=timezone.utc)
    windows = {
        "2026-11-09": [
            (lock - timedelta(days=2), lock - timedelta(days=2) + timedelta(hours=2)),
            (lock + timedelta(hours=20), lock + timedelta(hours=22)),
        ],
        "2026-11-10": [
            (lock + timedelta(days=1), lock + timedelta(days=1, hours=2)),
            (lock + timedelta(days=2, hours=20), lock + timedelta(days=2, hours=22)),
        ],
    }
    rows = session_eligibility(lock, lock + timedelta(days=2), windows)
    assert not rows[0]["entire_day_after_lock"] and not rows[0]["temporally_eligible"]
    assert rows[1]["entire_day_after_lock"] and not rows[1]["completed"]
    assert session_eligibility(lock, lock + timedelta(days=3), windows)[1][
        "temporally_eligible"
    ]


def test_stress_scales_all_fee_fields_without_changing_market_facts():
    xs, _, _, _, _, _ = setup([100, 101, 102], {0: dict(near_zero_golden=True)})
    original = deepcopy(xs)
    changed = stressed(xs, 3)
    for before, after in zip(xs, changed, strict=True):
        assert (
            before.bar == after.bar and before.facts.tick_size == after.facts.tick_size
        )
        assert (
            after.facts.fees.open_per_contract
            == 3 * before.facts.fees.open_per_contract
        )
        assert (
            after.facts.fees.close_today_per_contract
            == 3 * before.facts.fees.close_today_per_contract
        )
        assert after.facts.fees.source_id.endswith(":research_fee_x3")
    assert xs == original and stressed(xs, 1) is xs
    with pytest.raises(ValueError):
        stressed(xs, True)


def test_independent_metrics_reconcile_cash_and_expose_one_lot_ordinary_exit():
    xs, obs, eng, _, _, _ = setup(
        [100, 101, 102, 101, 100],
        {0: dict(near_zero_golden=True), 2: dict(below_previous_low=True)},
    )
    result = run(xs, obs, eng)
    measured = metrics(xs, result)
    assert measured["accounting_verified"] and measured["max_lots"] == 1
    assert measured["exit_reasons"] == {"ONE_LOT_ORDINARY_EXIT": 1}
    assert D(measured["fees"]) == sum(D(f["fee"]) for f in result["fills"])
    broken = deepcopy(result)
    broken["fills"][0]["fee"] = "999"
    with pytest.raises(ValueError, match="ACCOUNTING_CONFLICT"):
        metrics(xs, broken)


def test_atomic_artifact_refuses_to_overwrite_existing_result(tmp_path):
    path = tmp_path / "result.json"
    dump(path, {"value": D("123.456")})
    before = path.read_bytes()
    assert json.loads(before) == {"value": "123.456"}
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        dump(path, {"value": 0})
    assert path.read_bytes() == before


def test_structure_context_never_uses_later_hourly_point():
    xs, _, _, _, _, _ = setup([100, 101, 102], {})
    end = xs[-1].bar.bar_end
    hourly = {
        xs[0].bar.bar_end: dict(direction="UP"),
        end + timedelta(minutes=1): dict(direction="DOWN"),
    }
    contexts = build_context([], xs, "JM2609", hourly)
    assert all(v["hourly"] == {"direction": "UP"} for v in contexts.values())


def test_mds_calendar_rows_keep_night_session_and_provider_columns():
    metadata = {
        "calendar": [
            ["2026-11-08", False, False, "provider", ""],
            ["2026-11-09", True, True, "provider", ""],
        ]
    }
    assert [str(d) for d in open_calendar_days(metadata)] == ["2026-11-09"]


def test_missing_future_calendar_stays_unknown_without_blocking_known_day_preflight():
    from app.market_data.market_data_service import MarketDataError
    from datetime import date
    from types import SimpleNamespace

    days = [(date(2026, 11, 9), True), (date(2026, 11, 10), True)]

    class Market:
        catalog = SimpleNamespace(calendar_days=lambda *args: days)

        def historical_metadata_evidence(self, *, symbol, since, through):
            if since != through:
                raise MarketDataError("HISTORICAL_METADATA_EVIDENCE_MISSING")
            return {"calendar": [[str(since), True, True, "provider", ""]]}

        def session_windows(self, *, symbol, trading_day):
            at = datetime.combine(trading_day, datetime.min.time(), tzinfo=timezone.utc)
            return [SimpleNamespace(start=at, end=at + timedelta(hours=7))]

    lock = datetime(2026, 11, 8, 13, tzinfo=timezone.utc)
    result = oos_preflight(Market(), lock, lock)
    assert not result["requested_window_complete"]
    assert "2026-11-16" in result["missing_calendar_days"]
    assert len(result["eligibility"]) == 2 and not any(
        r["temporally_eligible"] for r in result["eligibility"]
    )
    assert (
        result["execution_and_market_facts"]
        == "NOT_VALIDATED_IN_THIS_TEMPORAL_PREFLIGHT"
    )


def test_future_session_failure_is_unknown_not_closed_or_eligible():
    from app.market_data.market_data_service import MarketDataError
    from datetime import date
    from types import SimpleNamespace

    class Market:
        catalog = SimpleNamespace(
            calendar_days=lambda *args: [(date(2026, 11, 11), True)]
        )

        def historical_metadata_evidence(self, **kwargs):
            raise MarketDataError("HISTORICAL_METADATA_EVIDENCE_MISSING")

    lock = datetime(2026, 11, 8, 13, tzinfo=timezone.utc)
    result = oos_preflight(Market(), lock, lock)
    assert result["eligibility"] == []
    assert result["individual_day_failures"] == [
        {
            "trading_day": "2026-11-11",
            "status": "UNKNOWN",
            "error_code": "HISTORICAL_METADATA_EVIDENCE_MISSING",
        }
    ]


@pytest.mark.parametrize("change", ["net", "missing", "duplicate", "fill_link"])
def test_closed_rounds_cannot_escape_independent_metrics_validation(change):
    xs, obs, eng, _, _, _ = setup(
        [100, 101, 102, 101, 100],
        {0: dict(near_zero_golden=True), 2: dict(below_previous_low=True)},
    )
    result = run(xs, obs, eng)
    if change == "net":
        result["closed_rounds"][0]["net_pnl"] = "-999999"
    elif change == "missing":
        result["closed_rounds"] = []
    elif change == "duplicate":
        result["closed_rounds"].append(deepcopy(result["closed_rounds"][0]))
    else:
        result["closed_rounds"][0]["fills"] = []
    with pytest.raises(ValueError, match="CLOSED_ROUND_RECONCILIATION_FAILED"):
        metrics(xs, result)
