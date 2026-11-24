import csv
import json

import pytest

from lms405_exposure_audit import ARCHIVE, BOOK, FIELDS, audit, displayed_contract


@pytest.fixture
def source_inputs():
    with ARCHIVE.open(newline="", encoding="utf-8") as stream:
        sources = {row["source_id"]: row for row in csv.DictReader(stream)}
    return json.loads(BOOK.read_text()), json.loads(FIELDS.read_text()), sources


def test_october_audit_preserves_table_scope_and_opening_average(source_inputs):
    report = audit(*source_inputs, ARCHIVE.parent)
    assert len(report["tables"]) == 9
    assert report["pair_counts_by_binding"] == {
        "SYSTEM_COVER": {"equal": 10, "unequal": 0},
        "SYSTEM_POST_MIXED_ROWS": {"equal": 1, "unequal": 0},
        "MIXED_POST_TABLE_BINDING_UNKNOWN": {"equal": 4, "unequal": 0},
    }
    assert report["comparison_counts"] == {
        "SAME_QUANTITY_AND_OPENING_AVERAGE": 35, "QUANTITY_OR_OPENING_AVERAGE_CHANGED": 20,
    }
    assert report["only_today_quantity_changed"] == 4
    assert {table["source"] for table in report["excluded_5_0_tables"]} == {"WRo2LIbP3s", "WRoEvFgWlh"}
    assert report["account_continuity"] is report["action_at"] is report["author_action_matches"] is None

    tables = {t["source"]: t for t in report["tables"]}
    assert "long" not in tables["U03"]["contracts"]["SH2701"]["legs"]
    assert tables["U03"]["contracts"]["SH2701"]["pair"] is None
    assert tables["U03"]["contracts"]["I2701"]["pair"]["older_side_by_today_field"] is None
    assert tables["WRoEvasxQR"]["contracts"]["OI2701"]["pair"]["older_side_by_today_field"] == "short"
    fg = next(c for c in report["comparisons"] if c["contract"] == "FG2701" and c["later"]["source"] == "WRnY5bznUE")
    assert (fg["earlier"]["opening_average"], fg["later"]["opening_average"]) == ("850", "856")
    assert fg["quantity_equal"] is True and fg["opening_average_equal"] is False
    sh = next(
        c for c in report["comparisons"]
        if c["contract"] == "SH2701" and c["side"] == "long" and c["later"]["source"] == "WRoEvasxQR"
    )
    assert sh["intervening_tables_without_leg"] == 1
    assert sh["earlier"]["source"] == "WRoAkcEppg"
    assert sh["result"] == "QUANTITY_OR_OPENING_AVERAGE_CHANGED" and sh["today_quantity_equal"] is None

    jm = next(
        c for c in report["comparisons"]
        if c["contract"] == "JM2701" and c["side"] == "long" and c["later"]["source"] == "WRoEvasxQR"
    )
    assert jm["result"] == "SAME_QUANTITY_AND_OPENING_AVERAGE" and jm["today_quantity_equal"] is False


def test_one_known_leg_or_one_unknown_quantity_cannot_establish_a_pair():
    assert displayed_contract({"short": 20}, {"short": ["1720", 0]})["pair"] is None
    assert displayed_contract(
        {"long": None, "short": 20}, {"long": ["1490.1", None], "short": ["1720", 0]},
    )["pair"] is None


def test_visible_partial_cover_and_today_quantities():
    legs = displayed_contract({"long": 20, "short": 10}, {"long": ["825", 0], "short": ["830", 10]})
    assert legs["pair"] == {
        "equal": False,
        "smaller_larger_lots": ["10", "20"],
        "displayed_net_lots": "10",
        "displayed_gross_lots": "30",
        "older_side_by_today_field": "long",
    }
    with pytest.raises(ValueError, match="INVALID_TODAY_QUANTITY"):
        displayed_contract({"long": 20}, {"long": ["830", 21]})


def test_baseline_rows_and_image_identity_cannot_be_overridden(source_inputs):
    book, fields, sources = source_inputs
    first = fields["tables"][0]
    first["additional_quantities"] = {}
    with pytest.raises(ValueError, match="BASELINE_OVERRIDE"):
        audit(book, fields, sources, ARCHIVE.parent)
    del first["additional_quantities"]
    first["image"] = "RoEvasxQR-position-screen.png"
    with pytest.raises(ValueError, match="IMAGE_IDENTITY_MISMATCH"):
        audit(book, fields, sources, ARCHIVE.parent)
