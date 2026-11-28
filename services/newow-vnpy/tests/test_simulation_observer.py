from queue import Queue
from threading import Event

import pytest

from simulation_observer import build_gateway, claim_workdir
from app.simulation_center.readback import ReadbackError


def test_isolated_veighna_read_only_assembly(tmp_path):
    messages = Queue()
    workdir = tmp_path.resolve()
    workdir.chmod(0o700)
    with claim_workdir(workdir, "isolated-a"):
        engine, gateway = build_gateway(messages, Event())
        td = gateway.td_api
        try:
            td.brokerid = "9999"
            td.userid = "fixture-account"
            td.front_open = True
            td.reqid = 1
            settlement_calls = []
            td.reqSettlementInfoConfirm = lambda *args: settlement_calls.append(args)
            td.onRspUserLogin({"TradingDay": "20261130", "BrokerID": td.brokerid, "UserID": td.userid}, {}, 1, True)
            assert messages.get(timeout=2) == ("login", "20261130")
            assert settlement_calls == []
            assert not gateway.md_api.connect_status
            td.onRspQryOrder({}, {}, 2, True)
            assert messages.get(timeout=2)[:6] == ("reply", "orders", 2, {}, 0, True)
            td.onRtnTrade({"InvestorID": td.userid})
            assert messages.get(timeout=2) == ("changed",)
            with pytest.raises(ReadbackError, match="NATIVE_FENCE_CHANGED"):
                gateway.publish(None, ({},), 1)
            for method in (gateway.send_order, gateway.cancel_order, td.send_order, td.cancel_order):
                with pytest.raises(ReadbackError, match="OBSERVER_READ_ONLY"):
                    method(None)
        finally:
            engine.close()


def test_one_shot_authentication_ignores_duplicate_and_stale_callbacks(tmp_path):
    messages = Queue()
    workdir = tmp_path.resolve()
    workdir.chmod(0o700)
    with claim_workdir(workdir, "isolated-a"):
        engine, gateway = build_gateway(messages, Event(), single_connection=True)
        td = gateway.td_api
        try:
            commands = []
            td.auth_code = "fixture-auth"
            td.brokerid, td.userid, td.appid = "9999", "fixture-account", "fixture-app"
            td.authenticate = lambda: commands.append("auth")
            td.login = lambda: commands.append("login")
            td.reqid = 1
            response = {"BrokerID": td.brokerid, "UserID": td.userid, "AppID": td.appid}
            td.onFrontConnected()
            td.onRspAuthenticate(response, {}, 2, True)
            td.onRspAuthenticate(response, {}, 1, False)
            td.onRspAuthenticate(response, {}, 1, True)
            td.onRspAuthenticate(response, {}, 1, True)
            td.onFrontDisconnected(4097)
            td.onFrontConnected()
            td.onRspAuthenticate(response, {}, 1, True)
            assert commands == ["auth", "login"]
        finally:
            engine.close()


def test_account_process_owns_native_workdir(tmp_path):
    workdir = tmp_path.resolve()
    workdir.chmod(0o700)
    with claim_workdir(workdir, "isolated-a"):
        with pytest.raises(OSError):
            with claim_workdir(workdir, "isolated-a"):
                pytest.fail("duplicate runtime")
    with pytest.raises(ReadbackError, match="WORKDIR_ACCOUNT_CONFLICT"):
        with claim_workdir(workdir, "isolated-b"):
            pytest.fail("different account cannot reuse the directory")
