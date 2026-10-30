"""Settlement proof uses the current matching Gateway response, never date inference."""

from types import SimpleNamespace as NS

import pytest

from guiyi_quant.simnow_execution.settlement import SettlementConfirmation


def gateway(*, date="20261030", rows=None, failure=None, drift=None):
    calls = []
    native = NS(
        front="first", failed=False,
        native_session=dict(front_id=1, session_id=2, max_order_ref=10),
        result=dict(account_fingerprint="a" * 64, trading_day="20261102"),
        query_diagnostics=[],
    )

    def query(kind):
        calls.append(kind)
        if kind == "confirm" and failure:
            raise failure
        if kind == "confirm" and drift:
            drift(native)
        native.query_diagnostics.append(dict(kind=kind, request_id=len(calls)))
        return rows if rows is not None else [dict(ConfirmDate=date, ConfirmTime="20:59:13")]

    native.query = query
    return native, calls


def test_civil_date_confirmation_is_bound_to_current_session_and_never_repeated():
    native, calls = gateway()
    proof = SettlementConfirmation(native, "a" * 64, "20261102")
    assert not proof.read_confirmed()
    proof.confirm()
    source = proof.source_id
    proof.confirm()
    assert proof.read_confirmed() and proof.source_id == source
    assert source.startswith("native-settlement:v2:")
    assert calls == ["settlement", "confirm"]
    assert proof.diagnostic["confirm_date"] == "20261030"
    assert proof.diagnostic["request_id"] == 2


def test_same_trading_day_query_does_not_write_confirmation():
    native, calls = gateway(date="20261102")
    proof = SettlementConfirmation(native, "a" * 64, "20261102")
    assert proof.read_confirmed()
    proof.confirm()
    assert calls == ["settlement"]


@pytest.mark.parametrize("rows", [[], [{"ConfirmDate": "20261030"}] * 2])
def test_confirmation_missing_or_ambiguous_stops_without_retry(rows):
    native, calls = gateway(rows=rows)
    proof = SettlementConfirmation(native, "a" * 64, "20261102")
    if len(rows) > 1:
        with pytest.raises(ValueError):
            proof.read_confirmed()
    else:
        assert not proof.read_confirmed()
        with pytest.raises(ValueError):
            proof.confirm()
    with pytest.raises(ValueError):
        proof.confirm()
    assert proof.source_id is None
    assert calls.count("confirm") <= 1


def test_unknown_confirmation_result_never_gets_a_second_attempt():
    native, calls = gateway(failure=RuntimeError("private-diagnostic"))
    proof = SettlementConfirmation(native, "a" * 64, "20261102")
    assert not proof.read_confirmed()
    with pytest.raises(RuntimeError):
        proof.confirm()
    with pytest.raises(ValueError):
        proof.confirm()
    assert proof.source_id is None and calls == ["settlement", "confirm"]
    assert "private-diagnostic" not in str(proof.diagnostic)
    assert "request_id" not in proof.diagnostic
    assert "confirm_date" not in proof.diagnostic


@pytest.mark.parametrize("field", ["account", "day", "session", "front", "failed"])
def test_connection_or_account_drift_during_confirmation_cannot_produce_proof(field):
    def drift(native):
        if field == "account":
            native.result["account_fingerprint"] = "b" * 64
        elif field == "day":
            native.result["trading_day"] = "20261103"
        elif field == "session":
            native.native_session["session_id"] = 3
        elif field == "front":
            native.front = "another"
        else:
            native.failed = True

    native, calls = gateway(drift=drift)
    proof = SettlementConfirmation(native, "a" * 64, "20261102")
    assert not proof.read_confirmed()
    with pytest.raises(ValueError, match="NATIVE_SETTLEMENT_IDENTITY_MISMATCH"):
        proof.confirm()
    assert proof.source_id is None and calls == ["settlement", "confirm"]


def test_preexisting_identity_mismatch_does_not_send_any_request():
    native, calls = gateway()
    with pytest.raises(ValueError, match="NATIVE_SETTLEMENT_IDENTITY_MISMATCH"):
        SettlementConfirmation(native, "b" * 64, "20261102")
    assert calls == []
