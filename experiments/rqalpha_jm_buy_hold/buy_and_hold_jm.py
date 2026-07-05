"""
焦煤 JM 买入持有策略（RQAlpha Plus 官方 buy_and_hold 期货改写版）

回测逻辑：第一个交易日买入开仓 1 手 JM88（焦煤主力连续，不复权），持有至回测结束。
"""

from rqalpha.api import *


def init(context):
    # JM88 = 焦煤主力连续（量价简单拼接，不复权）
    # 文档：https://www.ricequant.com/doc/rqdata/python/futures-mod
    context.s1 = "JM88"
    subscribe(context.s1)
    context.fired = False
    logger.info("RunInfo: {}".format(context.run_info))


def before_trading(context):
    pass


def handle_bar(context, bar_dict):
    if not context.fired:
        # 期货：买入开仓 1 手（买入并持有，不做换月）
        order = buy_open(context.s1, 1)
        logger.info("buy_open: {}".format(order))
        context.fired = True


def after_trading(context):
    pass
