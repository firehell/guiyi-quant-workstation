from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from guiyi_quant.lms405 import Bar
from lms405_portfolio_left_entry import LeftScope, assess_left_proposal, assumed_carry_comparison, left_signals
from lms405_right_side_study import FIVE, US, at


def test_left_shape_contact_and_outside_close_split_the_exact_5m_proposal():
    contract = "V2701"
    initial = at("2026-10-27T10:35")
    published = at("2026-10-26T17:44")
    scope = LeftScope(contract, {"source_url": "test plan"}, published, at("2026-10-26T21:00"),
                      at("2026-10-27T15:01"), Decimal(5045), Decimal(5074))
    candles = []
    for opening, high, low, close in ((5062, 5070, 5058, 5064), (5064, 5067, 5059, 5062),
                                     (5063, 5078, 5060, 5076)):
        candles.append(Bar(contract, initial + FIVE, *map(Decimal, (opening, high, low, close)), start=initial))
        initial += FIVE
    series = {1: [], 5: candles}
    known = candles[-1].end + US
    assert left_signals(series, scope, known) == []
    (event,) = events = left_signals(series, scope, known + US)
    assert event["shape_overlap"] and event["confirmation_overlaps"] and event["close_distance"] == 2
    proposal = dict(contract=contract, action="ENTER_LONG", signal_bar_end=event["shape_end"].isoformat(),
                    generated_at=known.isoformat())
    overlap = assess_left_proposal(scope, events, "shape-overlap", proposal, known + US)
    assert overlap["can_project_fixture"] is True and overlap["author_permission_supplied"] is False
    assert assess_left_proposal(scope, events, "confirmation-inside", proposal, known + US)[
        "can_project_fixture"
    ] is False
    for changed in (event | {"mode": "5m_to_1m"}, event | {"scope": "other plan"}):
        assert assess_left_proposal(scope, [changed], "shape-overlap", proposal, known + US)["event"] is None


def test_assumed_carry_strict_quotes_exclude_the_quote_minute_and_preserve_trading_day():
    days = date(2026, 10, 27), date(2026, 10, 28)
    event = dict(mode="5m_to_5m", signal_at=at("2026-10-27T10:50"),
                 signal_known_at=at("2026-10-27T10:50") + US)
    anchors = {"WRoAkcEppg": "11:30", "U03": "15:00", "WRoEvasxQR": "22:10"}
    quotes = [
        dict(source=source, side="long", status="CHECKED", assumed_trading_day=days[1 if i == 2 else 0],
             visible=dict(quantity=40, today_quantity=0 if i == 2 else 40, opening_average="5078.4"),
             by_variant={"variant": {at(f"2026-10-27T{minute}").isoformat(): {}}})
        for i, (source, minute) in enumerate(anchors.items())
    ]
    ordinary = SimpleNamespace(bar_end=at("2026-10-27T10:52"), low=Decimal(5070), high=Decimal(5077),
                               trading_day=days[0])
    quote_minute = SimpleNamespace(bar_end=at("2026-10-27T11:30"), low=Decimal(5078), high=Decimal(5079),
                                   trading_day=days[0])
    (report,) = assumed_carry_comparison([event], quotes, [ordinary, quote_minute], "variant")
    assert tuple(next(iter(v.values())) for v in report["strict_prices_exclude_quote_minute"].values()) == (
        False, True, True,
    )
    assert report["exits_simulated"] is False and report["author_continuity_verified"] is False
