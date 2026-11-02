"""Native session IDs retain signed identity; other quantity gates stay strict."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import pytest
from guiyi_quant.simnow_execution.model import (
    Session,
    FRONT,
    VERSION,
    integer,
    session_identifier,
)

T = datetime(2026, 11, 2, 15, tzinfo=UTC)


def session(value):
    return Session(
        "a" * 64,
        "SIMNOW_FIRST",
        FRONT,
        "20261103",
        1,
        value,
        0,
        "fixture-login",
        "fixture-settlement",
        T,
        T + timedelta(hours=1),
    )


@pytest.mark.parametrize("value", [-(2**31), -123456789, -1, 1, 2**31 - 1])
def test_signed_native_identity_is_retained_without_abs_or_wrapping(value):
    assert session(value).session_id == value
    assert VERSION == "simnow_ctp_controlled_v3"


@pytest.mark.parametrize(
    "value", [0, True, False, "-1", -1.0, None, -(2**31) - 1, 2**31]
)
def test_unproven_type_zero_or_out_of_native_width_still_rejects(value):
    with pytest.raises(ValueError, match="NATIVE_SESSION_ID_INVALID"):
        session(value)


@pytest.mark.parametrize(
    "field,value",
    [("front_id", -1), ("front_id", 0), ("max_order_ref", -1), ("max_order_ref", True)],
)
def test_other_integer_contracts_do_not_broaden(field, value):
    with pytest.raises(ValueError, match="NATIVE_INTEGER_INVALID"):
        replace(session(-1), **{field: value})


def test_old_positive_quantity_rule_rejects_legal_signed_identity():
    with pytest.raises(ValueError, match="NATIVE_INTEGER_INVALID"):
        integer(-1, 1)
    session_identifier(-1)
