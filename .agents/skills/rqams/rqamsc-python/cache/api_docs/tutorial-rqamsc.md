## 常见使用场景的教程

### **交易流水相关教程**

#### 录入流水的通用示例

当您要使用接下来介绍的方式导入流水时，您需要注意

- 您需要将您在其他系统获得的流水转化为 rqamsc 所要求的字典格式，具体数据结构可参考 [_交易流水对象_](api-rqamsc.md#交易流水对象)
- 在构建交易流水时一个关键的字段是 transaction_type(交易类型， 如 'buy', 'sell', 'cash_in' 等)，不同系统获得的流水该值差异可能巨大，您需要将其转化为
  rqams 规定的标准值，具体可参考[_交易类型_](api-rqamsc.md#交易类型)
- 所有流水会被标记为 openapi 来源的流水，该类流水的特性可以参考 [交易流水来源](api-rqamsc.md#交易流水来源)

以下是一个导入流水的完整过程的示例代码

```python
import datetime
import rqamsc
from rqamsc import TransactionType


def demo():
    rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
    rqamsc.choose_workspace('需要指定的工作空间')

    trades = [
        # 第一条流水
        {
            'transaction_type': 'buy',  # 交易类型，字段值可在文档【交易类型】中参考
            'account': '范例产品交易账号中文名',  # 交易账户名称，不提供则默认第一个产品账户
            'datetime': datetime.datetime(2024, 5, 7, 10, 4, 25),
            'order_book_id': '000001.XSHE',
            'symbol': '平安银行',
            'quantity': 1,  # 分红、付息等现金类交易则不需要提供
            'price': 10,  # 分红、付息等现金类交易则不需要提供
            'settlement_amount': 0,  # 买卖等类型可以不提供该字段，但分红、付息、出入金等(可参考文档【给产品导入交易流水】中介绍)必须设置该字段作为交易金额
            'commission': 0.1,  # 交易佣金, 不提供默认为0
            'tax': 0,  # 交易税, 不提供默认为0
            'other_fees': 0,  # 其他费用, 不提供默认为0
            'exchange_rate': 1,  # 汇率, 不提供默认为1
            'remarks': '这是当天第一笔交易',  # 备注, 可不提供
            'foreign_id': '可指定一个在交易系统范围内唯一的id',  # 外部id, 可不提供, 具体功能可参考文档【交易流水来源】中介绍
            'asset_unit_id': None  # 资产单元id, 如果是资产单元下的流水需要指定该字段，不指定则默认该流水是产品层流水
        },
        # 第二条流水
        {
            'transaction_type': 'sell',  # 交易类型
            'datetime': datetime.datetime(2024, 5, 7, 11, 4, 25),
            'order_book_id': '000001.XSHE',
            'symbol': '平安银行',
            'quantity': 1,
            'price': 100,
            'commission': 0.1
        },
        # 第三条流水
        {
            'transaction_type': 'cash_in',  # 入金
            'datetime': datetime.datetime(2024, 5, 7, 14, 4, 25),
            'order_book_id': 'CNY',
            'symbol': 'CNY',
            'settlement_amount': 1000000,  # 入金的金额
            'foreign_id': '123321954783203'
        },
        # 第四条流水
        {
            'transaction_type': 'dividend_payment',  # 现金分红
            'account': '一个不存在的账号',
            'datetime': datetime.datetime(2024, 5, 7, 8, 0, 0),
            'order_book_id': '000001.XSHE',
            'symbol': '平安银行',
            'settlement_amount': 1,  # 分红的金额
        },
        # 第五条流水
        {
            'transaction_type': 'interest_payment',  # 利息支出
            'datetime': datetime.datetime(2024, 5, 7, 16, 0, 0),
            'order_book_id': 'CNY',
            'symbol': 'CNY',
            'settlement_amount': 50,  # 利息支出金额
            'remarks': '银行借款利息支出'
        }

        # ... 可增加更多流水
    ]

    # 调用导入流水api，使用result变量接收返回结果并打印输出，可使用chunk_size参数指定每批上传的流水数量，默认1000
    result = rqamsc.insert_product_trades('一个范例产品', trades, chunk_size=500)
    print(result)


if __name__ == '__main__':
    demo()

# [ 
# 本批次流水的导入结果
# 第一条流水导入结果: modify表示覆盖了相同foreign_id的流水
# {'id': '66aca9b916822a16d8143b58', 'action': 'modify'},
# 第二条流水导入结果: insert表示增加成功
# {'id': '66acae1c6d4a6ec991079160', 'action': 'insert'},
# {'id': '66acae1c6d4a6ec991079161', 'action': 'insert'},
# 第四条流水导入失败
# {'err': '该产品中没有该交易账户名: 一个不存在的账号'}
# ... 该结果列表和上传流水的顺序一致，即 chunk_start + 列表下标 = 该流水在上传数据序列中的位置
# ]
```

#### 录入股票交易流水

更多交易类型（如两融业务）可以参考 [交易类型](api-rqamsc.md#交易类型) 字段的枚举值

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

trades = [
    # 第一条：最简单的股票买入，只提供必须字段
    {
        'transaction_type': TransactionType.buy,  # 买入
        'datetime': datetime.datetime(2024, 5, 7, 9, 30, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 1000,  # 买入1000股
        'price': 12.50  # 每股12.50元
    },
    # 第二条：或许你可以提供更详细的字段
    {
        'transaction_type': TransactionType.sell,  # 卖出
        'datetime': datetime.datetime(2024, 5, 8, 14, 30, 0),
        'account': '范例产品交易账号中文名',  # 交易账户名称，不提供则默认第一个产品账户
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 500,
        'price': 13.20,
        'commission': 6.60,  # 佣金
        'tax': 0,  # 交易税, 不提供默认为0
        'other_fees': 0.5,  # 其他费用
        'remarks': '部分止盈',  # 备注信息
        'foreign_id': 'SELL_001_20240508'  # 外部系统ID，可不提供, 用于去重
    },
    # 第三条：分红收入流水 - 股票分红
    {
        'transaction_type': TransactionType.dividend_payment,  # 红利入账
        'datetime': datetime.datetime(2024, 5, 15, 9, 0, 0),
        'order_book_id': '000001.XSHE',  # 股票分红
        'symbol': '平安银行',
        'settlement_amount': 12500,  # 分红金额12,500元
    },
    # 第四条：分红税支付流水
    {
        'transaction_type': TransactionType.dividend_tax_payment,  # 红利税支付
        'datetime': datetime.datetime(2024, 5, 15, 9, 1, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'settlement_amount': 1250,  # 红利税10%
    },
    # 第五条：送股流水
    {
        'transaction_type': TransactionType.bonus_share,  # 红股
        'datetime': datetime.datetime(2024, 5, 16, 9, 0, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 250,  # （十送五）
    },
]

result = rqamsc.insert_product_trades_v2('我的产品', trades)
print(result)
# id 字段的值表示导入后流水的id, insert表示流水是新增
# [
# {'id': '697b1c896d9670c3ac85592c', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592d', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592e', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592f', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac855930', 'action': 'insert'},
# ]
```

#### 录入期货交易流水

期货交易与股票类似，但需要注意合约代码的格式：

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

trades = [
    # 第一条：最简单的期货开仓，只提供必须字段
    {
        'transaction_type': TransactionType.buy_open,  # 开多仓
        'datetime': datetime.datetime(2024, 5, 7, 10, 15, 0),
        'order_book_id': 'IF2406',  # 沪深300期货主力合约
        'symbol': 'IF2406',
        'quantity': 2,  # 开仓2手
        'price': 3250.0  # 每点3250元
    },
    # 第二条：或许你可以提供更详细的字段
    {
        'transaction_type': 'sell_close',  # 平多仓
        'datetime': datetime.datetime(2024, 5, 8, 11, 30, 0),
        'account': '范例产品交易账号中文名',  # 交易账户名称，不提供则默认第一个产品账户
        'order_book_id': 'IF2406',
        'symbol': 'IF2406',
        'quantity': 1,  # 平仓1手
        'price': 3280.0,  # 盈利平仓
        'commission': 15.0,  # 期货手续费
        'remarks': '部分止盈平仓',
        'foreign_id': 'FUT_SELL_001'  # 外部系统ID
    }
]

result = rqamsc.insert_product_trades_v2('期货产品', trades)
print(result)

# [
# {'id': '697b1c896d9670c3ac85592c', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592d', 'action': 'insert'},
# ]
```

#### 录入现金类流水示例

这个示例展示如何导入现金类流水，包括入金、利息收入和利息支出等。

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

trades = [
    # 入金流水
    {
        'transaction_type': 'cash_in',  # 入金
        'datetime': datetime.datetime(2024, 5, 7, 9, 0, 0),
        'order_book_id': 'CNY',  # 人民币
        'symbol': 'CNY',
        'settlement_amount': 1000000  # 入金100万元
    },
    # 银行存款利息收入
    {
        'transaction_type': TransactionType.interest_income,  # 利息收入
        'datetime': datetime.datetime(2024, 5, 8, 16, 0, 0),
        'order_book_id': 'CNY',
        'symbol': 'CNY',
        'settlement_amount': 850,  # 利息收入850元
    },
    # 借款利息支出
    {
        'transaction_type': TransactionType.interest_payment,  # 利息支出
        'datetime': datetime.datetime(2024, 5, 10, 16, 0, 0),
        'order_book_id': 'CNY',
        'symbol': 'CNY',
        'settlement_amount': 2500,  # 利息支出2500元
    },
]

result = rqamsc.insert_product_trades_v2('我的产品', trades)
print(result)

# [
# {'id': '697b1c896d9670c3ac85592c', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592d', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592e', 'action': 'insert'},
# ]
```

#### 录入回购交易流水示例

这个示例展示如何导入回购相关流水，包括正回购、逆回购以及到期购回等操作。

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

trades = [
    # 逆回购操作 - 资金出借
    {
        'transaction_type': TransactionType.reverse_repo,  # 逆回购
        'datetime': datetime.datetime(2024, 5, 7, 10, 30, 0),
        'order_book_id': '131810.XSHE',  # 深市1天逆回购
        'symbol': 'R-001',
        'quantity': 10,  # 10手，即100万元
        'price': 2.5,  # 年化利率 2.5%
    },
    # 逆回购到期购回 - 资金收回
    {
        'transaction_type': TransactionType.reverse_repo_repurchase,  # 逆回购购回
        'datetime': datetime.datetime(2024, 5, 8, 16, 0, 0),
        'order_book_id': '131810.XSHE',
        'symbol': 'R-001',
        'quantity': 10,
        'price': 2.5,
        'settlement_amount': 1000068.49,  # 本金+利息
    },
    # 正回购操作 - 质押融资
    {
        'transaction_type': TransactionType.repo,  # 正回购
        'datetime': datetime.datetime(2024, 5, 10, 14, 0, 0),
        'order_book_id': '204001.XSHG',  # 沪市1天回购
        'symbol': 'GC001',
        'quantity': 5,  # 5手，即50万元
        'price': 3.2,  # 年化利率 3.2%
    },
    # 正回购到期购回 - 还款付息
    {
        'transaction_type': TransactionType.repo_repurchase,  # 正回购购回
        'datetime': datetime.datetime(2024, 5, 11, 16, 0, 0),
        'order_book_id': '204001.XSHG',
        'symbol': 'GC001',
        'quantity': 5,
        'price': 3.2,
        'settlement_amount': 500044.44,  # 本金+利息
    }
]

result = rqamsc.insert_product_trades_v2('我的产品', trades)
print(result)

# [
# {'id': '697b1c896d9670c3ac85592c', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592d', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592e', 'action': 'insert'},
# {'id': '697b1c896d9670c3ac85592f', 'action': 'insert'},
# ]
```

#### 录入带有foreign_id字段的流水

这个示例展示如何使用 `foreign_id` 字段来避免重复导入和实现流水覆盖更新功能。

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

# 第一次导入 - 初始流水
trades_initial = [
    {
        'transaction_type': TransactionType.buy,
        'datetime': datetime.datetime(2024, 5, 7, 9, 30, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 1000,
        'price': 12.50,
        'commission': 6.25,
        'remarks': '初始买入',
        'foreign_id': 'ORDER_001_20240507'  # 外部系统唯一ID
    }
]

print("=== 第一次导入 ===")
result1 = rqamsc.insert_product_trades('我的产品', trades_initial)
print(result1)
# [{'id': '697b1c896d9670c3ac85592c', 'action': 'insert'}]

# 第二次导入 - 使用相同foreign_id但修改了数据（比如更正佣金费率）
trades_corrected = [
    {
        'transaction_type': TransactionType.buy,
        'datetime': datetime.datetime(2024, 5, 7, 9, 30, 0),
        'order_book_id': '000001.XSHE',
        'symbol': '平安银行',
        'quantity': 1000,
        'price': 12.50,
        'commission': 12.50,  # 修正后的佣金
        'remarks': '已修正佣金费率',
        'foreign_id': 'ORDER_001_20240507'  # 相同的外部ID
    }
]

print("\n=== 第二次导入（覆盖） ===")
result2 = rqamsc.insert_product_trades_v2('我的产品', trades_corrected)
print(result2)

# action为'modify'，说明覆盖了原有记录
# [
#   {'id': 'xxx', 'action': 'modify'}
# ]
# 

# foreign_id的最佳实践：
# 1. 使用业务系统中的唯一标识符作为foreign_id
# 2. 重新导入相同foreign_id的流水会覆盖原流水
# 3. 不提供foreign_id的流水会始终新增，不会覆盖
```

#### 录入每日的结算流水文件单

使用下述方式导入流水时，您通常每日收盘后都会收到当日的流水结算文件，您需要注意

- 不同券商的交易文件格式非常不同，甚至同一券商不同时期的格式也可能发生较大变化，您需要确保RQAMS中该产品下交易账户的交易通道类型为您实际使用的券商类型。（若您所用券商我们还未支持，请联系我们）
- 使用此方式导入的流水称为日终结算流水，该流水类型特点可参考 [交易流水来源](api-rqamsc.md#交易流水来源)

```python
import datetime
import rqamsc
from rqamsc import TransactionType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

product_name = '一个产品'
product = rqamsc.get_product(product_name)
print(product)
# Product(
# ...
# accounts=[
# {'name': '一个产品的账号名称', 'is_custodian': False, 'account_number': 'xxx', 'broker': 'ricequant'}
# ]
# ...
# )
account_name = product.accounts[0]['name']

file_path = r'path/to/your/trades_file.xlsx'
print(rqamsc.upload_product_settlement_trade_file(product_name, account_name, file_path))

# effect_count 表示识别并成功导入的流水数量为 58 条
# err_msg 为报错信息，表示文件中第二行的合约没有正确被识别
# confirmation_id 表示凭证id
# {
# 'path/to/your/trades_file.xlsx': 
#   {
#       'effect_count': 58,
#       'err_msg': [{ "line_num": 2, "msg": "无法识别资产：资产分类信息获取失败" }], 
#       'confirmation_id': '697b3055c9087bc930ed8868'
#   }
# }

```

### **估值表相关教程**

#### 录入估值表文件

使用该方式时您需要确保您的产品会收到托管的估值表，通常市面上大部分估值表RQAMS已经可以适配识别。（若您收到的估值表格式无法识别，请联系我们）
以下代码展示了如何将本地的估值表文件导入产品

```python
import rqamsc

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

print(
    rqamsc.upload_valuation_reports(
        '一个有估值表的产品',
        [
            r'your/valuation_report/path/file1.xlsx',
            r'your/valuation_report/path/file2.xlsx',
        ],
    )
)

# 返回一个列表，列表中元素包含的关键信息如下：
# file: 文件地址
# err_msg: 导入失败时的错误信息
# effect_count：导入成功的数量, 0表示未导入，1表示成功
# valuation_report_id：导入成功后估值表的id
# confirmation_id： 凭证id
# [
#     {
#         'err_msg': [],
#         'confirmation_id': '69805115af070387af13290b',
#         'effect_count': 1,
#         'valuation_report_id': '69805115409221935ecbe4c4',
#         'date': '2020-11-02',
#         'is_modified': False,
#         'file': 'your/valuation_report/path/file1.xlsx',
#     },
#     {
#         'err_msg': ['该产品在2020-11-03已存在估值表'],
#         'file': 'your/valuation_report/path/file2.xlsx',
#     }
# ]

```

#### 录入自己构建的字典格式估值表

通过 dict、json 格式的估值表数据导入产品，该方式需要您对RQAMS的头寸需要的信息有相当程度的了解,
并将您在其他渠道获取的头寸转化为[RQAMS要求的估值表数据格式](api-rqamsc.md#估值表对象)。
在满足上述条件后，通常在以下情况更推荐您这种导入方式：

- 您的估值表格式在RQAMS中还未适配，因此无法导入，而您此时需要将估值表导入RQAMS
- 您的估值来源并不是传统估值表，您需要将组合的截面头寸导入RQAMS

以下代码展示了如何构建估值表中的关键信息及调用api导入

```python
import rqamsc

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

# 产品于2024-09-03日的估值信息
valuation_report = {
    'date': '2024-09-03',  # 持仓单日期
    'total_equity': 2004.00,  # 净资产
    'units': 2000,  # 份额
    'unit_net_value': 1.002,  # 单位累计净值
    'acc_unit_net_value': 1.002,  # 单位累计净值
    'positions': [
        # 第一条持仓
        {
            'order_book_id': 'CNY',
            'symbol': '活期存款',
            'asset_class': 'current_deposit',
            'direction': 'long',
            'market_value': 1000.00,
        },
        # 第二条持仓
        {
            'order_book_id': '000001.XSHE',
            'symbol': '平安银行',
            'asset_class': 'stock',
            'direction': 'long',
            'market_value': 1004.00,  # 持仓市值
            'quantity': 100.00,  # 持仓数量
            'cost_price': 10.00,  # 单位成本
            'cost': 1000.00,  # 成本
            'fair_value': 10.04,  # 公允价格
        },
        # 第三条持仓
        {
            'order_book_id': '600519.XSHG',
            'symbol': '贵州茅台',
            'asset_class': 'stock',
            'direction': 'short',  # 空头
            'market_value': -150000.00,  # 持仓市值
            'quantity': 100.00,  # 持仓数量
            'cost_price': 2000.00,  # 单位成本
            'cost': -200000.00,  # 成本
            'fair_value': 1500,  # 公允价格
        },
    ],
}

# 调用导入估值表api
result = rqamsc.insert_valuation_reports('要导入持仓单的产品id或名称', valuation_report)
print(result)

# 参考文件估值表的返回
# [
#     {
#         'err_msg': [],
#         'confirmation_id': '6980675cabe35ad7c92cf357',
#         'effect_count': 1,
#         'valuation_report_id': '698060c6409221935eef4de2',
#         'date': '2024-09-03',
#         'is_modified': True,
#         'file': '产品名称_2024-09-03_api导入数据.csv',
#     }
# ]
```

**Tips**:
您需要注意的是：如果您使用估值表驱动产品的估值，在发生了申购、赎回、分红等事件后，RQAMS无法仅通过估值表倒推出准确的托管事件，为获取当日准确的收益率数据，您需要导入对应发生的托管事件，具体导入方式可以参考[托管事件相关教程](#托管事件相关教程)

### **托管事件相关教程**

#### 给产品录入申购赎回托管事件

需要将从其他渠道获取到的申赎事件按照 [托管事件要求的格式](api-rqamsc.md#托管事件对象) 转换后再录入，示例如下

```python
import rqamsc
from rqamsc import CustodianEvent
from rqamsc.definition import CustodianEventType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

custodian_events = [
    # 使用 CustodianEvent 构建的申购
    CustodianEvent(
        custodian_event_type=CustodianEventType.subscription_fund_received,
        sr_open_date='2026-01-05',  # 申购开放日
        date='2026-01-06',  # 申购到账日
        unit_net_value=1.4,  # 按什么净值申购
        # unit_net_value=1,  # 如果是产品的初始资金取1即可
        # 也可以考虑直接取开放日当天单位净值
        # unit_net_value=rqamsc.get_balance('一个产品', dt=20260105)['unit_net_value'],
        amount=1000000,
    ),
    # 使用 CustodianEvent 构建的赎回
    CustodianEvent(
        custodian_event_type=CustodianEventType.redemption_paid,
        sr_open_date='2026-01-16',  # 赎回开放日
        date='2026-01-19',  # 赎回出账日
        unit_net_value=rqamsc.get_balance('一个产品', dt=20260116)['unit_net_value'],
        amount=1000000,
    ),
    # 使用字典构建的赎回
    {
        'custodian_event_type': CustodianEventType.redemption_paid,
        'sr_open_date': '2026-01-15',  # 赎回开放日
        'date': '2026-01-19',  # 赎回出账日
        'unit_net_value': rqamsc.get_balance('一个产品', dt=20260116)['unit_net_value'],
        'amount': 500000,
    },
]

print(rqamsc.insert_custodian_events('一个产品', custodian_events))
# 数量为3表示三条都录入成功
# {'effect_count': 3}
```

#### 录入产品分红托管事件

示例如下

```python
import datetime

import rqamsc
from rqamsc import CustodianEvent, CustodianEventType

rqamsc.init('username', 'password', uri="https://www.ricequant.com", ssl_verify=True)
rqamsc.choose_workspace('需要指定的工作空间')

custodian_events = [
    # 使用 CustodianEvent 对象构建
    CustodianEvent(
        date=datetime.date(2020, 1, 1),
        custodian_event_type=CustodianEventType.product_dividend_paid,
        amount=1000000
    ),
    # 使用字典构建
    {
        'date': '2021-01-05',
        'custodian_event_type': 'product_dividend_paid',
        'amount': 1000000
    }
]

print(rqamsc.insert_custodian_events('一个产品', custodian_events))

# {'effect_count': 2}
```

---
