from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_ru_reprotection_transfer import compatible_visible_rebuild
from lms405_sh_reprotection_replay import shape_range_admits

START = datetime(2026, 10, 27, 13, tzinfo=UTC)
ONE = timedelta(minutes=1)


def test_shape_touch_allows_confirmation_above_the_band_but_not_an_unrelated_shape():
    band = (Decimal(19360), Decimal(19405))
    touching = SimpleNamespace(low=Decimal(19400), high=Decimal(19425))
    detached = SimpleNamespace(low=Decimal(19410), high=Decimal(19430))
    assert shape_range_admits(touching, Decimal(19435), band)
    assert not shape_range_admits(detached, Decimal(19435), band)
    assert not shape_range_admits(touching, Decimal(19405), band)


def test_retained_old_long_is_not_scored_as_a_rebuilt_leg():
    seed = {"long": Decimal(20), "short": Decimal(20)}
    observed = {"long": {"quantity": 20, "opening_average": "19674.8"}}
    result = compatible_visible_rebuild([], seed, [START + ONE], observed, [], Decimal(5))
    assert result["visible_quantity_cutoffs"] == [START + ONE]
    assert result["modeled_new_leg_cutoffs"] == []
    assert result["opening_average_checks"] == []
