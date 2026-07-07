## rqamsc 简介

### rqamsc 是什么

rqamsc 是一个由米筐科技开发的 Python SDK(Software Development Kit),
该软件开发工具包提供了大量管理 [RQAMS](https://www.ricequant.com/welcome/ams) Web平台上资源（交割单、组合、产品等）的 Python
接口，大幅提升了 RQAMS 的自动化程度。

```
tips: RQAMS 是集多资产管理、实时监控、绩效分析、风险分析等多种功能于一体的智能投资组合管理平台, 可点击上方 RQAMS文档链接 了解详情
```

### 什么情况下选择rqamsc

在您有一定编程能力的情况下，以下情景选择rqamsc可能对您的效率提升更有帮助

- 情景1：您可以通过代码获取到产品的数据如：交易流水、估值表、托管事件（申赎等）、自定义合约价格等。这些数据您可能需要**全量导入
  **及**增量维护**，这些流程如果比较固化，rqamsc是一个高效的选择。
- 情景2：在 RQAMS Web端 提供的标准化风控之外，您**对组合的风控管理有个性化需求**，可以通过rqamsc获取产品历史、实时的各项指标来构建您自己的风控系统。
- 情景3：您需要**定期向投资人汇报本期业绩**，您可以使用rqamsc定制您个性化的业绩指标。

---

## 安装与升级

### 环境准备

- Python3.7+ 的运行环境。
- 在本机可访问 [RQAMS](https://www.ricequant.com/welcome/ams) Web 平台（系统需要商业授权才能使用），可在浏览器打开平台链接测试是否可以访问。但是请注意：
  **私有化部署**用户通常需要指定特殊地址，该地址可询问您公司负责维护本系统的IT获得。

### 安装

首先在系统中打开一个命令行, 选择好需要安装的 Python 环境，我们强烈建议使用 Anaconda 并在其创建的虚拟环境再运行以下安装命令

```
pip install --extra-index-url https://rquser:ricequant99@py.ricequant.com/simple/ rqamsc
```

第一次安装成功后，命令行应该有类似如下的输出（显示已成功安装的包中有 rqamsc）

```
Successfully installed brotli-1.1.0 certifi-2024.7.4 charset-normalizer-3.3.2 colorama-0.4.6 et-xmlfile-1.1.0 idna-3.7 msgpack-1.0.8
 numpy-1.24.4 openpyxl-3.1.5 orjson-3.10.6 pandas-2.0.3 python-dateutil-2.9.0.post0 python-rapidjson-1.18 pytz-2024.1 pyyaml-6.0.1 r
equests-2.32.3 rqamsc-0.4.1 rqdatac-3.0.12.2+12.ga61fb64d rqdatac-fund-1.0.35 six-1.16.0 tqdm-4.66.4 tzdata-2024.1 urllib3-2.2.2 win-inet-pton-1.1.0 xlrd-1.2.0
```

### 升级

若您曾经安装过旧的rqamsc版本，可使用如下命令获取最新的 rqamsc 版本，升级前您可到 [更新履历](changelogs.md#更新履历) 查看对应版本特性

```
pip install --upgrade rqamsc --extra-index-url https://rquser:ricequant99@py.ricequant.com/simple/
```

对应版本成功升级后的输出结果如下

```
Installing collected packages: rqamsc
  Attempting uninstall: rqamsc
    Found existing installation: rqamsc 0.4.0
    Uninstalling rqamsc-0.4.0:
      Successfully uninstalled rqamsc-0.4.0
Successfully installed rqamsc-0.4.1
```

### 如何选择适合的rqamsc版本

由于rqamsc强烈依赖于 RQAMS 平台，您可到 [更新履历](changelogs.md#更新履历) 查看对应版本的介绍

---

## 基本概念

在使用rqamsc之前，请确保您的 [RQAMS](https://www.ricequant.com/welcome/ams) Web平台在本机可以访问。
除此之外建议您对 RQAMS 中的基本概念有一定的了解，您可在 [RQAMS 参考文档](https://www.ricequant.com/doc/rqams/) 中阅读了解相关概念。

### 产品

产品是AMS系统的核心对象，产品可以被简单理解为一个投资组合，其输入为流水、估值表等数据，并以此为基础进行估值生成该组合在每个时间的[头寸](#头寸)。
以下代码展示了如何在python代码中获取该对象

```python
# 在成功安装 rqamsc 包后就可以在程序中使用 rqamsc，首先导入 rqamsc
import rqamsc

# 接着登录 RQAMS 平台。
# username/password 是您登陆 RQAMS 的凭证
# uri 是要访问的 RQAMS 平台地址，默认是米筐官方 RQAMS 平台，私有化部署用户需要特殊指定自己网络环境下的地址
# ssl_verify 表示是否开启https认证，默认为开。标准化用户选择默认即可，私有化部署用户需根据网址信息，若为https协议则开启，否则需要指定为False来关闭
rqamsc.init(username="your_user_name", password="your_password", uri="https://www.ricequant.com", ssl_verify=True)
# 私有化部署用户初始化可能为下方代码
# rqamsc.init(username="your_user_name", password="your_password", uri="http://internal.rqams.com", ssl_verify=False)

# 现在尝试获取一下当前空间下的所有产品
print(rqamsc.list_products())
# [
#   Product(name='多策略1号', data_source='trade_and_valuation_report', start_date='2021-03-10', investment_category='equity', benchmark={'type': 'index', 'id': '000300.XSHG'}, calendar='exchange', auto_equity=True, unit_policy='auto_prev_unit_net_value', accounts=[{'account_number': '123', 'name': '测试托管帐号', 'broker': 'RQ通道', 'is_custodian': True}, {'account_number': '123', 'name': '测试交易帐号', 'broker': 'RQ通道', 'is_custodian': False}], fee_settings={'management_fee_rate': 0.0, 'custodian_fee_rate': 0.0, 'operation_fee_rate': 0.0, 'sales_and_service_fee_rate': 0.0}, user_id=321843, workspace_id=ObjectId('5e9a6b06ba363be9fce2a599'), product_state='normal', full_name='多策略1号', create_time='2021-08-02 11:37:43', fund_code='', manager='', invest_advisor='', invest_manager='', maturity_date='2999-12-31', closing_date=None, id='61076887224d591257c5ebb5')
# ]
```

在RQAMS中，产品需要存在于某一个工作空间下。
若您具有多个工作空间，在使用rqamsc登录后默认会使用第一个空间, 以下代码展示了如何在切换空间后尝试获取所有产品

```python
import rqamsc

rqamsc.init(username="your_user_name", password="your_password", uri="https://www.ricequant.com", ssl_verify=True)
print(rqamsc.get_workspaces())
# [
#   WorkSpace(id=5e9a6bd6ba363be9fce3082a, name=工作空间1, admin=123456, capacity=3, ctime=2020-04-18 00:00:00, description=工作空间1, users=[123456, 123457, 454301]), 
#   WorkSpace(id=5ee9d4cb9d2e1ef15589963a, name=工作空间2, admin=123456, capacity=3, ctime=2020-06-17 00:00:00, description=工作空间2, users=[123456, 123457, 405892])
# ]
print(rqamsc.current_workspace())
# WorkSpace(id=5e9a6bd6ba363be9fce3082a, name=工作空间1, admin=123456, capacity=3, ctime=2020-04-18 00:00:00, description=工作空间1, users=[123456, 123457, 454301])
# 切换至 工作空间2
rqamsc.choose_workspace('工作空间2')
# 获取 工作空间2 下的所有产品
print(rqamsc.list_products())
# []
```

关于工作空间的更多详情请参考[工作空间API](api-rqamsc.md#工作空间)

### 头寸

这里的头寸可以理解为该产品（投资组合）的状况（包含了各资产持仓明细、总市值、负债、净值等一系列信息）。
以下代码展示了如何获取指定产品的头寸信息

```python
import rqamsc


def demo():
    rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
    rqamsc.choose_workspace('需要指定的工作空间')

    balance = rqamsc.get_balance('一个范例产品', dt=20240802)
    # 产品组同理，只需要把产品名换成产品组的名称即可
    # balance = rqamsc.get_balance('一个产品组', dt=20240802)
    print(balance)


if __name__ == '__main__':
    demo()

# {
# 'date': '2024-08-02',
# 'total_equity': 1000089.8,
# 'daily_pnl': 0,
# 'daily_returns': 0.0,
# 'units': 1000000.0,
# 'unit_net_value': 1.0000898,
# 'acc_unit_net_value': 1.0000898,
# 'adjusted_net_value': 1,
# 'acc_unit_dividend': 0,
# 'positions': [
#   ...
# ]
# ...
# }
```

有关头寸返回的详细信息可参考 [获取产品或产品组单日头寸](api-rqamsc.md#获取产品或产品组单日头寸) 中返回结果的说明文档

### 交易流水

交易流水是 RQAMS 中驱动产品估值的一类重要数据
以下代码展示了如何给一个产品导入交易流水，再获取流水生效后的头寸信息

```python
import datetime

import rqamsc

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

trades = [
    {
        'transaction_type': 'cash_in',  # 入金
        'datetime': datetime.datetime(2026, 1, 6, 9, 0, 0),
        'order_book_id': 'CNY',  # 人民币
        'symbol': 'CNY',
        'settlement_amount': 1000000,  # 入金100万元
    },
    {
        'transaction_type': 'buy',  # 买入
        'datetime': datetime.datetime(2026, 1, 6, 10, 30, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 1000,  # 买入1000股
        'price': 12.50,  # 每股12.50元
    },
]

rqamsc.insert_product_trades('空产品', trades)

print(rqamsc.get_balance('空产品', dt=20260106))

# {
#     '_id': '6979cb0bf121facebba8809c',
#     'product_id': '68ca5b44f387689a539434db',
#     'date': '2026-01-06',
#     'market_value': 999170.0,
#     'total_assets': 999170.0,
#     'total_liabilities': 0,
#     'total_equity': 999170.0,
#     'daily_pnl': -830.0,
#     'daily_returns': -0.0008299999999999974,
#     'units': 1000000.0,
#     'unit_net_value': 0.99917,
#     'acc_unit_net_value': 0.99917,
#     'adjusted_net_value': 0.99917,
#     'acc_unit_dividend': 0,
#     'positions': [
#         {
#             'asset_category': 'cash_equivalent',
#             'product_accounting_major_subject': 'asset',
#             'open_date': '2026-01-06',
#             'daily_open_amount': 0.0,
#             'price_change': None,
#             'quantity': 987500.0,
#             'daily_payment_amount': 0,
#             'market_value': 987500.0,
#             'currency': 'CNY',
#             'avg_price': 0.0,
#             'order_book_id': 'CNY',
#             'floating_pnl': 0.0,
#             'exchange_rate': 1,
#             'asset_class': 'current_deposit',
#             'has_settlement': False,
#             'open_avg_price': 0.0,
#             'avg_price_include_fee': 0.0,
#             'avg_price_mtm': 0,
#             'acc_pnl': 0.0,
#             'direction': 'long',
#             'money_fund_remain_quantity': 0,
#             'clean_price': None,
#             'accrued_interest': 0,
#             'contribute_returns': None,
#             'bonus_share_receivable': 0,
#             'acc_pnl_rate': 0.0,
#             'price_limit': None,
#             'acc_dividend_received': None,
#             'daily_pnl_rate': 0.0,
#             'floating_pnl_percentage': 0.0,
#             'price_change_percentage': None,
#             'last_avg_price_include_fee': 0,
#             'cost': 0.0,
#             'fair_value': None,
#             'acc_interest_received': None,
#             'last_quantity': None,
#             'update_time': None,
#             'fair_value_setl_ccy': None,
#             'last_acc_pnl': 0,
#             'daily_pnl': 0.0,
#             'weight': 0.9883203058538587,
#             'trade_date_latest': '2026-01-06',
#             'market_value_setl_ccy': None,
#             'symbol': 'CNY',
#             'clean_price_market_value': None,
#             'industry': None,
#         },
#         {
#             'asset_category': 'equity',
#             'product_accounting_major_subject': 'asset',
#             'open_date': '2026-01-06',
#             'daily_open_amount': 12500.0,
#             'price_change': None,
#             'quantity': 1000.0,
#             'daily_payment_amount': 0,
#             'market_value': 11670.0,
#             'currency': 'CNY',
#             'avg_price': 12.5,
#             'order_book_id': '000001.XSHE',
#             'floating_pnl': -830.0000000000001,
#             'exchange_rate': 1,
#             'asset_class': 'stock',
#             'has_settlement': False,
#             'open_avg_price': 12.5,
#             'avg_price_include_fee': 12.5,
#             'avg_price_mtm': 0,
#             'acc_pnl': -830.0,
#             'direction': 'long',
#             'money_fund_remain_quantity': 0,
#             'clean_price': None,
#             'accrued_interest': 0,
#             'contribute_returns': -0.00083,
#             'bonus_share_receivable': 0,
#             'acc_pnl_rate': -0.0664,
#             'price_limit': None,
#             'acc_dividend_received': 0.0,
#             'daily_pnl_rate': -0.0664,
#             'floating_pnl_percentage': -0.06640000000000001,
#             'price_change_percentage': None,
#             'last_avg_price_include_fee': 0,
#             'cost': 12500.0,
#             'fair_value': 11.67,
#             'acc_interest_received': None,
#             'last_quantity': None,
#             'update_time': None,
#             'fair_value_setl_ccy': None,
#             'last_acc_pnl': 0,
#             'daily_pnl': -830.0,
#             'weight': 0.011679694146141298,
#             'trade_date_latest': '2026-01-06',
#             'market_value_setl_ccy': None,
#             'symbol': '平安银行',
#             'clean_price_market_value': None,
#             'industry': '银行',
#         },
#     ],
#     'year_init_unit_net_value': 1,
#     'year_init_acc_net_value': 1,
#     'year_init_adjusted_net_value': 1,
#     'returns_this_year': None,
#     'pnl_this_year': -830.0,
#     'returns_from_establish': None,
#     'daily_pnl_on_close': None,
#     'daily_returns_on_close': None,
#     'daily_equity_long_returns': None,
#     'daily_equity_short_returns': None,
#     'net_cash_in': 1000000,
#     'total_risk_market_value': 11670.0,
#     'net_risk_market_value': 11670.0,
#     'update_time': None,
#     'all_futures_options_has_settlement': None,
#     'asset_unit_id': None,
#     'long_market_value': 11670.0,
#     'short_market_value': 0.0,
#     'name': '空产品',
#     'risk_exposure': 0.011679694146141298,
#     'net_risk_exposure': 0.011679694146141298,
#     'long_leverage': 0.011679694146141298,
#     'long_net_risk_exposure': 1,
# }

```

### 分析指标

有了前面几个概念的介绍，我们知道在有了产品以及输入数据后我们可以得到某一天的头寸。而头寸存在于时间序列中，即每日都会有一个头寸快照展示了投资组合在当日结算后的状态。
据此我们可以通过这个头寸序列来看到某一段时间内产品的一系列指标，由这些指标我们就可以从多个维度了解产品的情况。
以下代码展示了如何获取产品的指标进行分析

```python
import rqamsc

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

# 获取产品2025全年的净值
print(rqamsc.get_indicators_series('一个待分析的产品', 20250101, 20251231, indicators=['unit_net_value']))

# {
#     'unit_net_value': {
#         '2025-01-02': 0.9498295238950554,
#         '2025-01-03': 0.925665182302806,
#         '2025-01-06': 0.9242404900792742,
#         '2025-01-07': 0.933437462119262,
#         '2025-01-08': 0.931381546792538,
#         '2025-01-09': 0.930775363430525,
#         '2025-01-10': 0.9142313019411734,
#         '2025-01-13': 0.9157990148386302,
#         ...
#     }
# }

# 获取RQAMS提供的通用指标
print(rqamsc.get_indicators('一个待分析的产品', 20250101, 20251231))
# 以下截取了返回结果中的周度指标作为展示
# {
#     ...
#     'weekly_risk': {
#         'alpha': 0.10226012645239169,
#         'beta': 1.3000156756032943,
#         'sharpe': 1.6248902031702137,
#         'excess_sharpe': 1.5503637566546766,
#         'max_drawdown': 0.08579999999999999,
#         'annual_downside_risk': 0.14030225404979446,
#         'information_ratio': 1.320426844212631,
#         'geometric_excess_annual_return': 0.12881696519852448,
#         'arithmetic_excess_annual_return': 0.134441521823079,
#         'annual_volatility': 0.17651968724859335,
#         'excess_annual_volatility': 0.08368082366916214,
#         'annual_tracking_error': 0.08368082366916214,
#         'geometric_excess_max_drawdown': 0.036218555354313064,
#         'total_returns': 0.3313,
#         'total_geometric_excess_return': 0.1314503960948068,
#         'total_arithmetic_excess_return': 0.15466865620006617,
#         'total_annual_returns': 0.34548464019706016,
#         'annual_simple_interest': 0.3408436213991769,
#         'calmar_ratio': 4.026627508124244,
#     },
#     ...
# }

```

关于RQAMS提供的通用指标中的更多详情可以查看 [获取产品或产品组指标](api-rqamsc.md#获取产品或产品组指标) 中返回结果的说明文档
