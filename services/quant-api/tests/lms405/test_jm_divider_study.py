from decimal import Decimal, localcontext

from lms405_jm_divider_study import minimum_early_quantity


def limits(low, high):
    return Decimal(low), Decimal(high)


def test_price_envelope_requires_lots_before_touch_and_completed_close():
    average = Decimal("1385.25")
    all_early = limits("1362", "1400")
    day_early = limits("1365.5", "1391.5")
    assert minimum_early_quantity(average, 20, all_early, limits("1388", "1396")) == 3
    assert minimum_early_quantity(average, 20, day_early, limits("1388", "1396")) == 3
    assert minimum_early_quantity(average, 20, all_early, limits("1392.5", "1395")) == 5
    assert minimum_early_quantity(average, 20, day_early, limits("1392.5", "1395")) == 6


def test_price_envelope_quantity_bound_handles_both_directions_and_missing_prices():
    assert minimum_early_quantity(Decimal("97.5"), 20, limits("88", "100"), limits("94", "96")) == 8
    assert minimum_early_quantity(Decimal("96"), 20, limits("88", "100"), limits("94", "96")) == 0
    assert minimum_early_quantity(Decimal("95"), 20, limits("96", "100"), limits("98", "99")) is None
    assert minimum_early_quantity(Decimal("95"), 20, None, limits("92", "96")) is None


def test_quantity_ceiling_is_exact_even_under_reduced_decimal_precision():
    with localcontext(prec=3):
        assert minimum_early_quantity(Decimal("100.49995"), 20, limits("99.5", "100"), limits("101.5", "102")) == 11
