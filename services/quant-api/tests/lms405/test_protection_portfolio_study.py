from datetime import datetime
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Position
from lms405_protection_portfolio_study import fixture_lock, source_episode, totals


POST = "2026-10-22T09:30:00+08:00"
AFTER = datetime.fromisoformat("2026-10-22T09:32:00+08:00")
PLAN = {"published_at": POST, "source_url": "https://example.test/plan"}


def test_research_diagnostics_do_not_become_protection_permission():
    episode = source_episode(
        "SH2701", "SHORT", "early-sh", PLAN, AFTER.isoformat(),
        {"price_touched": True, "geometric_confirmation": True}, no_chase=True,
    )
    assessment = episode["assessment"]
    assert assessment["decisions"]["RIGHT_PARTICIPATION"]["status"] == "NOT_PERMITTED"
    assert assessment["decisions"]["KEEP_HOLDING"]["status"] == "INDETERMINATE"
    assert assessment["decisions"]["LOCK_PROTECTION"]["status"] == "INDETERMINATE"
    assert assessment["decisions"]["LOCK_PROTECTION"]["checks"]["PROTECTION_SIGNAL"] is None
    assert assessment["action"] is None
    with pytest.raises(ValueError, match="SOURCE_EPISODE_BEFORE_POLICY_AVAILABLE"):
        source_episode("SH2701", "SHORT", "early-sh", PLAN, "2026-10-22T09:31:00+08:00", {}, no_chase=True)


def test_confirmation_changes_only_the_selected_contract_and_safety_remains_independent():
    sh = Position("SH2701", short=Decimal(20))
    iron = Position("I2701", short=Decimal(16))
    metrics_before = totals({"SH2701": sh, "I2701": iron})
    locked, result = fixture_lock(sh, AFTER, protection_confirmed=True, no_chase=True)
    unchanged, other = fixture_lock(iron, AFTER, protection_confirmed=False, no_chase=False)
    assert result["status"]["RIGHT_PARTICIPATION"] == "NOT_PERMITTED"
    assert result["status"]["LOCK_PROTECTION"] == "CONDITIONS_MET"
    assert result["fixture_action"] == "LOCK"
    assert locked == Position("SH2701", Decimal(20), Decimal(20))
    assert unchanged == iron and other["fixture_action"] is None
    assert metrics_before == {
        "short_contracts": 2, "equal_locked_contracts": 0, "gross_lots_subtotal": "36",
        "abs_net_lots_subtotal": "36",
    }
    assert totals({"SH2701": locked, "I2701": unchanged}) == {
        "short_contracts": 1, "equal_locked_contracts": 1, "gross_lots_subtotal": "56",
        "abs_net_lots_subtotal": "16",
    }
