from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Position
from lms405_staged_protection_permissions import allowed_first_stage, hypothetical, project_stage

AT = datetime(2026, 10, 22, 13, 1, tzinfo=UTC)
ONE = timedelta(minutes=1)
US = timedelta(microseconds=1)
SHORT = Position("FG2701", short=Decimal(20))


def test_early_action_does_not_authorize_the_remainder():
    result = hypothetical(SHORT, 7, source="fixture-plan", plan_at=AT - ONE, touch=AT,
                          confirm=AT + 11 * ONE, cutoff=AT + 30 * ONE)
    assert result["public_price_only"]["status"] == "INDETERMINATE"
    assert result["early_fixture"]["after"]["net"] == Decimal(-13)
    assert result["later_without_separate_approval"]["after"] == result["early_fixture"]["after"]
    assert result["later_fixture"]["after"]["net"] == Decimal(0)
    assert result["early_fixture"]["scope"] != result["later_fixture"]["scope"]


def test_stage_rejects_same_knowledge_time_and_requires_own_trigger():
    args = dict(stage="EARLY_PROTECTION", source="fixture-plan", plan_at=AT - ONE, price_at=AT,
                approved_at=AT + 4 * US, approved=True)
    unchanged_at_boundary, _ = project_stage(SHORT, Decimal(7), **args, trigger_at=AT + 2 * US,
                                            as_of=AT + 5 * US)
    unchanged_without_trigger, _ = project_stage(SHORT, Decimal(7), **args, as_of=AT + 6 * US)
    unchanged_at_price_knowledge, _ = project_stage(SHORT, Decimal(7), **args, trigger_at=AT + US,
                                                     as_of=AT + 6 * US)
    assert unchanged_at_boundary == unchanged_without_trigger == unchanged_at_price_knowledge == SHORT


def test_first_stage_lots_require_prices_after_touch():
    row = {"tick_bounds_before_touch_middle_after_confirmation": [(826, 826), (827, 827), (829, 829)]}
    assert allowed_first_stage(row, 20, range(16558, 16559)) == [11]
