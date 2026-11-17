import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import subing_portfolio as api
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, portfolio_policy


def test_cursor_keeps_equity_and_fills_at_same_observation(tmp_path, monkeypatch):
    first = "2026-11-17T01:01:00+00:00"
    second = "2026-11-17T01:02:00+00:00"
    day = "2026-11-17"
    mark = dict(contract="I2701", quantity=0, pending=None, layers=[], decision={},
                stop=None, target=None)
    timeline = [
        dict(at=at, day=day, accounts={"I2701": mark},
             pending_exit_contracts=[], valuation_unproven=[],
             daily=dict(equity=equity, day_start="1000000", margin="0"))
        for at, equity in ((first, "1000000"), (second, "999999"))
    ]
    result = dict(equity="999999", cash="999999", policy=portfolio_policy(EXPANDED_PORTFOLIO_PRODUCTS),
                  accounts={"I2701": {"fills": [{"fill_at": second}], "decisions_with_actions": []}})
    data = json.dumps(dict(result=result, timeline=timeline, charts={}, requested=[day, day], coverage=[])).encode()
    path = tmp_path / "history.json"
    path.write_bytes(data)
    monkeypatch.setattr(api, "read_registration", lambda _: dict(path=str(path), sha256=hashlib.sha256(data).hexdigest()))
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        before = client.get("/api/v1/subing-portfolio/history?index=0").json()
        after = client.get("/api/v1/subing-portfolio/history?index=1").json()
        assert client.get("/api/v1/subing-portfolio/history?index=2").status_code == 404
    assert before["account"]["equity"] == "1000000"
    assert before["products"][-1]["accounts"][0]["fills"] == []
    assert after["day_net"] == "-1"
    assert after["products"][-1]["accounts"][0]["fills"] == [{"fill_at": second}]
