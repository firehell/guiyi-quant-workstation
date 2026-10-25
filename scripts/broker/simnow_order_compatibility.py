"""No-network Mac CTP request ABI smoke with explicitly synthetic account facts.

No native API instance is created, no credential is read and no front is registered.
Uses installed isolated openctp-ctp 6.7.7.1; output is NOT broker E2E evidence.
"""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from importlib.metadata import version
from pathlib import Path
import hashlib
import json
import platform
import sys
import tempfile


def main():
    if (
        platform.system() != "Darwin"
        or platform.machine() != "arm64"
        or version("openctp-ctp") != "6.7.7.1"
    ):
        raise ValueError("VERIFIED_MAC_SDK_REQUIRED")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages" / "quant-core"))
    from openctp_ctp import tdapi
    from guiyi_quant import (
        htdy_execution as h,
        htdy_account_execution as a,
        simnow_execution as b,
    )

    class Capture:
        def __init__(self):
            self.calls = []

        def ReqOrderInsert(self, req, rid):
            assert isinstance(req, tdapi.CThostFtdcInputOrderField)
            assert req.VolumeTotalOriginal == 1 and req.CombOffsetFlag == "0"
            self.calls.append(("insert", req, rid))
            return 0

        def ReqOrderAction(self, req, rid):
            assert isinstance(req, tdapi.CThostFtdcInputOrderActionField)
            assert req.OrderRef == self.calls[0][1].OrderRef and req.ActionFlag == "0"
            self.calls.append(("cancel", req, rid))
            return 0

    user = "123456"  # Explicit fake, never a credential.
    account = hashlib.sha256(
        json.dumps(["SIMNOW_FIRST", "9999", user], separators=(",", ":")).encode()
    ).hexdigest()
    t = datetime(2026, 10, 27, 1, tzinfo=UTC)
    rb = a.Readback(
        h.AccountSnapshot(account, t, D("100000"), D("100000")),
        D(0),
        D(0),
        D(0),
        (),
        (),
        "synthetic-funds",
        t + timedelta(hours=3),
        True,
    )
    state = a.start(account, ("RB",), t, rb)
    state = a.apply(state, "owner", h.Owner("RB", "RB2701", t, "synthetic-owner")).state
    with tempfile.TemporaryDirectory(prefix="simnow-no-network-") as temp:
        store = a.LocalStore(Path(temp) / "account.db", state)
        journal = b.Journal(Path(temp) / "dispatch.db", account)
        now = t + timedelta(minutes=61)
        facts = a.ExecutionInput(
            a.Instrument(
                "RB",
                "RB2701",
                t,
                t + timedelta(hours=3),
                "synthetic-instrument",
                D(1),
                D(10),
                D(".1"),
                D(".1"),
                D(3),
            ),
            a.Session(
                "RB2701",
                t,
                t + timedelta(hours=3),
                "synthetic-session",
                t + timedelta(hours=6),
                True,
                True,
            ),
            a.Quote(
                "RB2701",
                now,
                now + timedelta(seconds=5),
                "synthetic-quote",
                D(999),
                D(1000),
                1,
                1,
                D(900),
                D(1100),
            ),
        )
        store.execute(
            "signal",
            h.Signal(
                "synthetic-signal",
                "RB",
                "RB2701",
                t + timedelta(hours=1),
                t + timedelta(hours=1, seconds=2),
                None,
                ("buy",),
                "a" * 64,
            ),
        )
        effect = store.execute("tick", a.Tick(now, (facts,))).effects[0]
        session = b.Session(
            account,
            "SIMNOW_FIRST",
            "tcp://182.254.243.31:30001",
            "20261027",
            1,
            2,
            0,
            "synthetic-login",
            "synthetic-settlement",
            t,
            t + timedelta(hours=3),
        )
        binding = b.Contract(
            "RB2701", "rb2701", "SHFE", "synthetic-binding", t, t + timedelta(hours=3)
        )
        api = Capture()
        adapter = b.Adapter(store, journal, tdapi, api, user, session)
        permit = b.Permit(
            "synthetic-intent",
            account,
            "20261027",
            b.action_hash(store.current(), effect, session, binding, None, facts),
            now,
            now + timedelta(seconds=3),
        )
        assert (
            adapter.dispatch(effect, binding, None, facts, permit, now)
            == "REQUEST_ACCEPTED_AWAIT_NATIVE"
        )

        class Spi(b.Callbacks, tdapi.CThostFtdcTraderSpi):
            pass

        spi = Spi()
        spi.execution_adapter = adapter
        row = tdapi.CThostFtdcOrderField()
        for key, value in dict(
            BrokerID="9999",
            InvestorID=user,
            TradingDay="20261027",
            OrderRef="1",
            FrontID=1,
            SessionID=2,
            InstrumentID="rb2701",
            ExchangeID="SHFE",
            Direction="0",
            CombOffsetFlag="0",
            CombHedgeFlag="1",
            LimitPrice=1000.0,
            VolumeTotalOriginal=1,
            VolumeTraded=0,
            VolumeTotal=1,
            OrderStatus="3",
            OrderSubmitStatus="3",
            OrderSysID="1",
            InsertDate="20261027",
            InsertTime="10:01:00",
        ).items():
            setattr(row, key, value)
        adapter.order_callback(row, now + timedelta(seconds=1))
        adapter.drain()
        later = now + timedelta(seconds=182)
        cancel = store.execute("deadline", a.Tick(later, (facts,))).effects[0]
        permit = b.Permit(
            "synthetic-cancel",
            account,
            "20261027",
            b.action_hash(store.current(), cancel, session, binding, None, facts),
            later,
            later + timedelta(seconds=3),
        )
        assert (
            adapter.dispatch(cancel, binding, None, facts, permit, later)
            == "REQUEST_ACCEPTED_AWAIT_NATIVE"
        )
        assert len(api.calls) == 2
        store.close()
        journal.close()
    print(
        json.dumps(
            dict(
                status="SDK_STRUCT_COMPATIBILITY_PASSED",
                sdk=version("openctp-ctp"),
                network_requests=0,
                native_api_created=False,
                credentials_read=False,
                broker_e2e_passed=False,
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"status":"SDK_COMPATIBILITY_FAILED","broker_e2e_passed":false}')
        raise SystemExit(1) from None
