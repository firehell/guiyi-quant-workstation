"""Minimal simulation-only futures strategy for the local smoke gate."""

from rqalpha.api import buy_open

from app.backtest.strategy_params import load_strategy_params


def init(context) -> None:
    params = load_strategy_params()
    context.guiyi_order_book_id = params["order_book_id"]
    context.guiyi_quantity = params["quantity"]
    context.guiyi_order_submitted = False


def handle_bar(context, bar_dict) -> None:
    del bar_dict
    if context.guiyi_order_submitted:
        return
    buy_open(context.guiyi_order_book_id, context.guiyi_quantity)
    context.guiyi_order_submitted = True
