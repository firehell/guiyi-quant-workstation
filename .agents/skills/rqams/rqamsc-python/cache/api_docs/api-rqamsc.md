## 打开网页版 RQAMS

```python
rqamsc.go()
```

---

## 登录

```python
rqamsc.init(username, password, uri="https://www.ricequant.com", ssl_verify=True)
```

- 参数

| **参数**     | **类型** | **说明**                                        |
|------------|--------|-----------------------------------------------|
| username   | str    | 用户名                                           |
| password   | str    | 密码                                            |
| uri        | str    | AMS 平台 URI，默认为米筐官方 RQAMS 平台 URI               |
| ssl_verify | bool   | 是否开启 https 认证（默认开启，若无 https 则可以指定为 False 来关闭） |

---

## 工作空间

工作空间是您创建产品，管理资产，和其他人协同工作的场所，您可以邀请他人进入您的工作空间和您协作，也可能被邀请进入其他人的工作空间。

对于大多数的用户，默认工作空间已经可以满足日常工作所需。您也可在 RQAMS 平台上创建新的工作空间，rqamsc
支持在不同的工作空间中切换使用。 (更多关于工作空间的介绍请前往[米筐官方网站](https://www.ricequant.com))

### **获取所有工作空间信息**

获取所有您拥有的或者参与的工作空间。

```python
rqamsc.get_workspaces()
```

- 返回

List[[Workspace](#工作空间对象)]

---

### **指定一个工作空间**

一般情况下您处于默认的工作空间中。choose_workspace 让您可以在工作空间之间切换。

```python
rqamsc.choose_workspace(workspace_name_or_id: str)
```

---

### **获取当前工作空间**

```python
rqamsc.current_workspace()
```

- 返回

[Workspace](#工作空间对象)

---

## 产品管理

### **获取全部产品信息**

```python
rqamsc.list_products() -> List[Product]
```

获取全部的产品信息

- 返回

_List[[Product](#产品对象)]_

- 示例

```python
>>> rqamsc.list_products()
[
  Product(
    name='多策略1号',
    data_source='trade_and_valuation_report',
    start_date=datetime.date(2021, 3, 10),
    investment_category='equity',
    benchmark={'type': 'index', 'id': '000300.XSHG'},
    calendar='exchange',
    auto_equity=True,
    unit_policy='auto_prev_unit_net_value',
    accounts=[
        {'account_number': '123', 'name': '测试托管帐号', 'broker': 'RQ通道', 'is_custodian': True},
        {'account_number': '123', 'name': '测试交易帐号', 'broker': 'RQ通道', 'is_custodian': False}
    ],
    fee_settings={
        'management_fee_rate': 0.0,
        'custodian_fee_rate': 0.0,
        'operation_fee_rate': 0.0,
        'sales_and_service_fee_rate': 0.0
    },
    user_id=321843,
    workspace_id='5e9a6b06ba363be9fce2a599',
    label='paper',
    product_state='normal',
    full_name='多策略1号',
    create_time=datetime.datetime(2021, 8, 2, 11, 37, 43),
    fund_code='',
    manager='',
    invest_advisor='',
    invest_manager='',
    maturity_date=datetime.date(2999, 12, 31),
    closing_date=None,
    id='61076887224d591257c5ebb5'
    )
]
```

---

### **获取单个产品信息**

```python
rqamsc.get_product(product_id_or_name: str) -> Product
```

- 参数

| **参数**             | **类型** | **是否必须** | **说明**      |
|--------------------|--------|----------|-------------|
| product_id_or_name | str    | 是        | 产品 id 或产品名称 |

- 返回

_[Product](#产品对象)_

- 示例

```python
>>> rqamsc.get_product("60b49659dd715e69dd8b1d8a")
Product(
    name='多策略1号',
    data_source='trade_and_valuation_report',
    start_date=datetime.date(2021, 3, 10),
    investment_category='equity',
    benchmark={'type': 'index', 'id': '000300.XSHG'},
    calendar='exchange',
    auto_equity=True,
    unit_policy='auto_prev_unit_net_value',
    accounts=[
        {'account_number': '123', 'name': '测试托管帐号', 'broker': 'RQ通道', 'is_custodian': True},
        {'account_number': '123', 'name': '测试交易帐号', 'broker': 'RQ通道', 'is_custodian': False}
    ],
    fee_settings={
        'management_fee_rate': 0.0,
        'custodian_fee_rate': 0.0,
        'operation_fee_rate': 0.0,
        'sales_and_service_fee_rate': 0.0
    },
    user_id=321843,
    workspace_id='5e9a6b06ba363be9fce2a599',
    label='paper',
    product_state='normal',
    full_name='多策略1号',
    create_time=datetime.datetime(2021, 8, 2, 11, 37, 43),
    fund_code='',
    manager='',
    invest_advisor='',
    invest_manager='',
    maturity_date=datetime.date(2999, 12, 31),
    closing_date=None,
    id='61076887224d591257c5ebb5'
)
```

---

### **修改单个产品信息**

```python
rqamsc.update_product(product_id_or_name: str, update_fields: Dict) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必须** | **说明**                               |
|--------------------|--------|----------|--------------------------------------|
| product_id_or_name | str    | 是        | 产品 id 或产品名称                          |
| update_fields      | dict   | 是        | 需要修改的产品信息(字段值可参考_[Product](#产品对象)_ ) |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**              |
|--------------|--------|----------|---------------------|
| effect_count | int    | 是        | 是否修改成功(1:成功， 0:未成功) |

- 示例

```python
>>> rqamsc.update_product('范例产品', update_fields={'name': '范例产品copy'})
{'effect_count': 1}
```

---

### **删除单个产品**

```python
rqamsc.delete_product(product_id_or_name: str) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必须** | **说明**      |
|--------------------|--------|----------|-------------|
| product_id_or_name | str    | 是        | 产品 id 或产品名称 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**              |
|--------------|--------|----------|---------------------|
| effect_count | int    | 是        | 是否删除成功(1:成功， 0:未成功) |

- 示例

```python
>>> rqamsc.delete_product('范例产品')
{'effect_count': 1}
```

---

## 产品组管理

### **获取全部产品组信息**

```python
rqamsc.list_product_groups() -> List[ProductGroup]
```

获取全部的产品组信息

- 返回

_List[[ProductGroup](#产品组对象)]_

- 示例

```python
>>> rqamsc.list_product_groups()
[ProductGroup(
    name='范例产品组-等权',
    products=[
        {'id': '635fa0dcf900a7b2fcfb44c0', 'name': '量化对冲_347418'},
        {'id': '635fa0e3f900a7b2fcfb4670', 'name': '商品期货_347418'},
        {'id': '635fa0e3f900a7b2fcfb4691', 'name': '300估值因子增强_347418'},
        {'id': '635fa0d6f900a7b2fcfb4485', 'name': '期权产品_347418'},
        {'id': '635fa0d9f900a7b2fcfb449f', 'name': '可转债产品_347418'}
    ],
    benchmark={'type': 'index', 'id': '000300.XSHG'},
    description='范例产品组',
    create_time=datetime.datetime(2021, 10, 14, 17, 15, 46),
    label='live',
    product_weights={
        '635fa0dcf900a7b2fcfb44c0': 0.2,
        '635fa0e3f900a7b2fcfb4670': 0.2,
        '635fa0e3f900a7b2fcfb4691': 0.2,
        '635fa0d6f900a7b2fcfb4485': 0.2,
        '635fa0d9f900a7b2fcfb449f': 0.2
    },
    id='6167f542ea2e8ac215581cde'
)]
```

---

### **获取单个产品组信息**

```python
rqamsc.get_product_group(group_id_or_name: str) -> ProductGroup
```

- 参数

| **参数**           | **类型** | **是否必须** | **说明**     |
|------------------|--------|----------|------------|
| group_id_or_name | str    | 是        | 产品组 id 或名称 |

- 返回

_[ProductGroup](#产品组对象)_

- 示例

```python
>>> rqamsc.get_product_group("范例产品组")
ProductGroup(
    name='范例产品组',
    products=[
        {'id': '635fa0dcf900a7b2fcfb44c0', 'name': '量化对冲_347418'},
        {'id': '635fa0e3f900a7b2fcfb4670', 'name': '商品期货_347418'},
        {'id': '635fa0e3f900a7b2fcfb4691', 'name': '300估值因子增强_347418'},
        {'id': '635fa0d6f900a7b2fcfb4485', 'name': '期权产品_347418'},
        {'id': '635fa0d9f900a7b2fcfb449f', 'name': '可转债产品_347418'}
    ],
    benchmark={'type': 'index', 'id': '000300.XSHG'},
    description='',
    create_time=datetime.datetime(2023, 5, 5, 17, 22, 44),
    label='live',
    product_weights=None,
    id='6454cae473ddf7712bcd3434'
)
```

---

### **修改单个产品组信息**

```python
rqamsc.update_product_group(group_id_or_name: str, update_fields: Dict) -> Dict
```

- 参数

| **参数**           | **类型** | **是否必须** | **说明**                                     |
|------------------|--------|----------|--------------------------------------------|
| group_id_or_name | str    | 是        | 产品组 id 或名称                                 |
| update_fields    | dict   | 是        | 需要修改的产品信息(字段值可参考_[ProductGroup](#产品组对象)_ ) |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**              |
|--------------|--------|----------|---------------------|
| effect_count | int    | 是        | 是否修改成功(1:成功， 0:未成功) |

- 示例

```python
# 以下为聚合型产品组字段构建
update_fields = {
    'name': '新的聚合型范例产品组名称',
    'benchmark': {'index': '000300.XSHG'},
    'products': [
        {'id': "6423efcab15e5e6bbd037292", 'name': "范例产品1"},  # 可省略name
        {'id': "641d74fe026c38928ac2ef55", 'name': "范例产品2"}
    ]
}

# 以下为权重产品组字段构建，也可以使聚合产品组变为权重产品组
update_fields = {
    'name': '新的权重产品组名称',
    'product_weights': {'6423efcab15e5e6bbd037292': 0.5, '641d74fe026c38928ac2ef55': 0.5}
}

# 若想将权重产品组改为聚合产品组，需要设置product_weights为空
update_fields = {
    'name': '新的聚合产品组名称',
    'products': [
        {'id': "6423efcab15e5e6bbd037292", 'name': "范例产品1"},
        {'id': "641d74fe026c38928ac2ef55", 'name': "范例产品2"}
    ],
    'product_weights': None
}
```

---

### **删除单个产品组**

```python
rqamsc.delete_product_group(group_id_or_name: str) -> Dict
```

- 参数

| **参数**           | **类型** | **是否必须** | **说明**     |
|------------------|--------|----------|------------|
| group_id_or_name | str    | 是        | 产品组 id 或名称 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**              |
|--------------|--------|----------|---------------------|
| effect_count | int    | 是        | 是否删除成功(1:成功， 0:未成功) |

---

## 重算

### 产品或产品组重算

```python
def recompute(
        product_like_ids_or_names: Union[str, List[str]], start_date: optional_datetime_like = None
) -> Dict[str, int]
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                                   |
|---------------------------|-----------------------|----------|------------------------------------------|
| product_like_ids_or_names | str, list[str]        | 是        | 产品或产品组 id 或名称                            |
| start_date                | int,str,datetime,date | 否        | 指定某一天至今每天的头寸全部重新计算，若不指定，默认从产品或产品组起始日开始重算 |

- 返回

| **字段**                 | **类型** | **是否必须** | **说明**            |
|------------------------|--------|----------|-------------------|
| submit_recompute_count | int    | 是        | 表示所选产品或产品组触发重算的数量 |

---

## 交易流水管理

### **给产品导入交易流水_v2**

`insert_product_trades_v2` 是 RQAMSC 的核心 API 之一，用于向 AMS 产品导入交易流水数据。导入的流水称为 openapi
来源流水，支持股票、期货、现金等多种资产类型的批量导入。

```python
rqamsc.insert_product_trades_v2(
    product_id_or_name: str,
trades_or_df: Union[List[Dict], DataFrame],
chunk_size: int = 1000
) -> List[Dict]
```

- 参数说明

| **参数名**            | **类型**                  | **必须** | **说明**                              |
|--------------------|-------------------------|--------|-------------------------------------|
| product_id_or_name | str                     | 是      | 产品 ID 或产品名称，用于指定要导入交易流水的目标产品        |
| trades_or_df       | List[Dict] or DataFrame | 是      | 交易流水数据，可以是字典列表或 pandas DataFrame 格式 |
| chunk_size         | int                     | 否      | 批次大小，默认 1000。API 会按此大小分批上传，最小值为 500 |

**交易流水字段：** 单条流水中的详细字段可参考 [_交易流水对象_](#交易流水对象)

返回一个结果列表， 和流水导入时的顺序一一对应：

| **字段** | **类型** | **是否必须** | **说明**                                                            |
|--------|--------|----------|-------------------------------------------------------------------|
| id     | str    | 否        | 导入成功的交易流水 id                                                      |
| action | str    | 否        | 导入行为：<br> • `insert`: 新增成功 <br> • `modify`: 覆盖已有记录（相同 foreign_id） |
| err    | str    | 否        | 错误信息（导入失败时返回）                                                     |

**返回示例：**

```python
[
    {'id': '507f1f77bcf86cd799439011', 'action': 'insert'},
    {'id': '507f1f77bcf86cd799439012', 'action': 'insert'},
    {'id': '507f1f77bcf86cd799439013', 'action': 'insert'},
    # ...
]
```

更多使用示例请参考 [录入流水的通用示例](tutorial-rqamsc.md#录入流水的通用示例)

### **给产品导入交易流水_v1**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 `insert_product_trades_v2` API。

```python
rqamsc.insert_product_trades(
    product_id_or_name: str,
trades_or_df: Union[List[Dict], DataFrame],
chunk_size: int = 1000
) -> List[Dict]
```

返回格式值为列表，列表中每个元素表示一批流水的导入结果，每一批的数据结构如下：

| **字段**      | **子字段** | **类型**     | **是否必须** | **说明**                                                            |
|-------------|---------|------------|----------|-------------------------------------------------------------------|
| chunk_start |         | int        | 是        | 分批导入时每一批的起始位置, 第一批从位置 0 开始                                        |
| result      |         | list[dict] | 是        | 每一批的导入结果                                                          |
|             | id      | str        | 否        | 导入成功的交易流水 id                                                      |
|             | action  | str        | 否        | 导入行为：<br> • `insert`: 新增成功 <br> • `modify`: 覆盖已有记录（相同 foreign_id） |
|             | err     | str        | 否        | 错误信息（导入失败时返回）                                                     |

返回结果示例

```python
[
    {
        'chunk_start': 0, 'result': [
        {'id': '507f1f77bcf86cd799439011', 'action': 'insert'},
        {'id': '507f1f77bcf86cd799439012', 'action': 'insert'},
        # ...
    ]
    }
]
```

---

### **给产品导入结算交易流水_v2**

使用此方式导入的流水称为日终结算流水，该流水类型特点可参考 [交易流水来源](#交易流水来源)

```python
rqamsc.upload_product_settlement_trade_file(
    product_id_or_name: str, account_name: str, file_or_dir_path: Union[str, List[str]],
asset_unit_id: Optional[Union[str, ObjectId]] = None
) -> Dict
```

- 参数

| **参数**             | **类型**           | **是否必须** | **说明**             |
|--------------------|------------------|----------|--------------------|
| product_id_or_name | str              | 是        | 需要导入流水的产品 id 或产品名称 |
| account_name       | str              | 是        | 需要导入流水的交易账号名称      |
| file_or_dir_path   | str or List[str] | 是        | 需要导入流水的文件或文件夹目录    |
| asset_unit_id      | str or ObjectId  | 否        | 需要导入的资产单元 id       |

- 返回：返回一个 Dict 字典，key 为文件路径， value 结构如下

| **文件导入状态** | **类型** | **参数**          | **说明**                              |
|------------|--------|-----------------|-------------------------------------|
| 成功或部分导入成功  | dict   | confirmation_id | 凭证 id, 可以通过此 id 查询凭证以获取详细的导入结果      |
|            |        | effect_count    | 解析出的流水数量                            |
|            |        | err_msg         | 是一个存储 dict 的列表，存储导入失败的流水信息(全部成功则为空) |
| 失败         | str    |                 | 失败原因的信息                             |

e.g.

```json
{
  "D:/kst20210618.csv": {
    "confirmation_id": "617bb94760108f5400628391",
    "effect_count": 6105,
    "err_msg": []
  },
  "D:/kst20210621.csv": {
    "confirmation_id": "617bb94560108f5400626bac",
    "effect_count": 3261,
    "err_msg": [
      {
        "line_num": 2,
        "msg": "无法识别资产：资产分类信息获取失败"
      }
    ]
  },
  "D:/日终结算.json": "流水文件格式错误"
}
```

---

### **给产品导入结算交易流水_v1**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 [`upload_product_settlement_trade_file`](#给产品导入结算交易流水_v2) API。

```python
rqamsc.insert_product_settlement_trade_file(
    product_id_or_name: str, account_name: str, file_or_dir_path: Union[str, List[str]],
asset_unit_id: Optional[Union[str, ObjectId]] = None
) -> Dict
```

参数和返回值与新接口 `upload_product_settlement_trade_file` 完全相同，请参考 [给产品导入结算交易流水_v2](#给产品导入结算交易流水_v2)。

---

### **获取产品的交易流水_v2**

```python
rqamsc.list_product_trades(
        product_id_or_name: str, start_date: optional_datetime_like = None, end_date: optional_datetime_like = None,
        sources: Union[str, Iterable] = None, order_book_id: str = None, symbol: str = None,
        asset_transaction_types: Union[str, Iterable] = None, account_names: Union[str, Iterable] = None,
        asset_unit_id_or_list: Optional[str, ObjectId, List[str, ObjectId]] = None,
        key_words: Union[str, Iterable] = None, group_by: str = None, remarks: str = None,
        is_query_assistant: bool = False
) -> Dict
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                         |
|-------------------------|-----------------------|----------|------------------------------------------------------------------------------------------------|
| product_id_or_name      | str                   | 是        | 产品 id 或产品名称                                                                                    |
| start_date              | int,str,datetime,date | 否        | 开始日期(如果不传则从今天向前取三个月)                                                                           |
| end_date                | int,str,datetime,date | 否        | 结束日期(如果不传则为今天)                                                                                 |
| _[sources](#交易流水来源)_    | str,Iterable          | 否        | 参考[_交易流水来源_](#交易流水来源)                                                                          |
| account_names           | str,Iterable          | 否        | 账户名称(可传字符串或字符串列表等)                                                                             |
| asset_unit_id_or_list   | str,ObjectId,Iterable | 否        | 资产单元 id(可传字符串或字符串列表等), 指定后查询资产单元下的流水                                                           |
| asset_transaction_types | str,Iterable          | 否        | _[资产类型](#资产类型)_ 与 _[交易类型](#交易类型)_ (可传字符串或字符串列表等) <br/> eg. asset_transaction_types='stock-buy' |
| key_words               | str,Iterable          | 否        | 关键字, 可检索'账号'、'代码'、'名称'、'变动类型'(传多个值时相互间为并集)                                                     |
| order_book_id           | str                   | 否        | 资产代码(根据所给值进行正则匹配, 不区分大小写)                                                                      |
| symbol                  | str                   | 否        | 资产名称(根据所给值进行正则匹配, 不区分大小写)                                                                      |
| group_by                | str                   | 否        | 分组聚合关键字:<br/> 1. asset(根据资产聚合) <br/> 2. trading_date(根据交易日期聚合)                                 |
| remarks                 | str                   | 否        | 备注(根据所给值进行正则匹配, 不区分大小写)                                                                        |

- 返回：交易流水数组，单个流水结构可参考[_交易流水对象_](#交易流水对象)

---

### **获取产品的交易流水_v1**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 [`list_product_trades`](#获取产品的交易流水_v2) API。

```python
rqamsc.get_product_trades(
        product_id_or_name: str, start_date=None, end_date=None,
        sources=None, order_book_id=None, symbol=None,
        asset_transaction_types=None, account_names=None,
        asset_unit_id_or_list=None, key_words=None, group_by=None, remarks=None,
        is_query_assistant=False
) -> Dict
```

参数和返回值与新接口 `list_product_trades` 完全相同，请参考 [获取产品的交易流水_v2](#获取产品的交易流水_v2)。

---

### **按检索条件删除流水**

```python
rqamsc.delete_product_trades_by_date(
    product_id_or_name: str,
    start_date: optional_datetime_like = None,
    end_date: optional_datetime_like = None,
    sources: Union[str, Iterable] = None,
    order_book_id: str = None,
    symbol: str = None,
    asset_transaction_types: Union[str, Iterable] = None,
    account_names: Union[str, Iterable] = None,
    asset_unit_id_or_list: Optional[Union[str, ObjectId, List[Union[str, ObjectId]]]] = None,
    key_words: Union[str, Iterable] = None,
    remarks: str = None,
    is_query_assistant: bool = False
) -> Dict
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                         |
|-------------------------|-----------------------|----------|------------------------------------------------------------------------------------------------|
| product_id_or_name      | str                   | 是        | 产品 id 或产品名称                                                                                    |
| start_date              | int,str,datetime,date | 否        | 开始日期(如果不传则为产品交易起始日)                                                                            |
| end_date                | int,str,datetime,date | 否        | 结束日期(如果不传则为今天)                                                                                 |
| _[sources](#交易流水来源)_    | str,Iterable          | 否        | 参考[_交易流水来源_](#交易流水来源)                                                                          |
| order_book_id           | str                   | 否        | 资产代码(根据所给值进行正则匹配, 不区分大小写)                                                                      |
| symbol                  | str                   | 否        | 资产名称(根据所给值进行正则匹配, 不区分大小写)                                                                      |
| asset_transaction_types | str,Iterable          | 否        | _[资产类型](#资产类型)_ 与 _[交易类型](#交易类型)_ (可传字符串或字符串列表等) <br/> eg. asset_transaction_types='stock-buy' |
| account_names           | str,Iterable          | 否        | 账户名称(可传字符串或字符串列表等)                                                                             |
| asset_unit_id_or_list   | str,ObjectId,Iterable | 否        | 资产单元 id(可传字符串或字符串列表等), 指定后查询资产单元下的流水                                                           |
| key_words               | str,Iterable          | 否        | 关键字, 可检索'账号'、'代码'、'名称'、'变动类型'(传多个值时相互间为并集)                                                     |
| remarks                 | str                   | 否        | 备注(根据所给值进行正则匹配, 不区分大小写)                                                                        |
| is_query_assistant      | bool                  | 否        | 是否删除副表流水，默认为 False                                                                             |

- 返回

| **字段**        | **类型** | **是否必须** | **说明**  |
|---------------|--------|----------|---------|
| deleted_count | int    | 是        | 删除流水的数量 |

**使用示例：**

```python
import rqamsc
from datetime import datetime

# 删除指定日期范围的交易流水
result = rqamsc.delete_product_trades_by_date(
    '产品名称',
    start_date='2023-01-01',
    end_date='2023-01-31',
)
print(f"删除结果: {result}")
```

---

### **删除产品的交易流水**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用功能更强大的 `delete_product_trades_by_date` API。

```python
rqamsc.delete_product_trades(product_id_or_name: str, trade_ids: List[Union[str, ObjectId]]) -> Dict
```

- 参数

| **参数**             | **类型**                | **是否必须** | **说明**                     |
|--------------------|-----------------------|----------|----------------------------|
| product_id_or_name | str                   | 是        | 产品 id 或产品名称                |
| trade_ids          | List[str or ObjectId] | 否        | 流水 id(可见流水查询结果中 '\_id' 字段) |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**  |
|--------------|--------|----------|---------|
| effect_count | int    | 是        | 删除流水的数量 |

---

### **交易流水文件自动化导入 AMS**

AMS 对于一些常见的流水文件模板也做了一定的适配（如：迅投 csv 格式流水、CTP 来源 txt 格式流水）

启动服务可以使用如下两种方式

方式一：在 python 代码中启动

```python
import rqamsc

rqamsc.init(username='AMS账号', password='AMS密码')  # 具体可参考rqamsc的初始化
rqamsc.choose_workspace('AMS工作空间名称或id')
rqamsc.run_import_trades_server()
```

or

方式二：命令行启动

```commandline
run_import_trades_server -u AMS账号 -p AMS密码 -w 工作空间名称或id
```

以下为该服务启动时所需的函数/命令参数

| **参数**             | **是否必须** | **说明**                                           |
|--------------------|----------|--------------------------------------------------|
| -u / --user_name   | 否        | AMS 账号，若像方式一中已初始化过则无需指定，方式二则必须指定                 |
| -p / --password    | 否        | AMS 密码，若像方式一中已初始化过则无需指定，方式二则必须指定                 |
| -w / --workspace   | 否        | 需要导入的流水所在产品的工作空间名称或 id，若像方式一中已初始化过则无需指定，方式二则必须指定 |
| -c / --config_file | 否        | 配置文件的绝对路径，默认为程序工作目录下的 config.yaml, 有关配置内容可见下方    |
| --ams_uri          | 否        | AMS 网页端地址，默认为线上，私有化部署用户可按实际情况指定                  |
| --ssl_verify       | 否        | 是否进行安全检测，线上默认为 True, 私有化部署若未使用 https 需置为 False   |

服务运行需要依赖 config.yaml 配置文件来明确要导入的流水文件与产品之间的关系，以及可以指定一些导入设置，其示例及参数如下

```yaml
# 每30s同步一次实时流水至AMS
- path: D:\迅投流水目录
  template: xuntou
  interval: 30 # 用以做实时增量导入，30即30s导入一次
  expire_time: "15:30" # 指定该项配置每天运行到15:30就不再执行
  filename_model: Deal # 所要导入的流水文件名称中共有的字符串，如源文件为 Deal(20230808).csv， 即可指定为 Deal 用以区分出流水文件
  product_account:
    - product: 产品1
      account_name: 产品1的迅投账号名称1
      account_number: "000111" # 注意这里给定字符串类型的账号
    - product: 产品1
      account_name: 产品1的迅投账号2
      account_number: "000222"

# 将 20230801~20230804 的历史流水导入AMS
- path: D:\迅投流水目录
  template: xuntou
  start: "20230801" # 指定导入哪些日期的流水，该字段为区间开始日期，不指定则只导入当天的流水
  end: "20230804" # 指定导入哪些日期的流水，该字段为区间结束日期，不指定则只导入当天的流水
  product_account:
    - product: 产品1
      account_name: 产品1的迅投账号名称1
      account_number: "000111" # 注意这里给定字符串类型的账号
    - product: 产品2
      account_name: 产品2的迅投账号名称
      account_number: "999999" # 注意这里给定字符串类型的账号

# 指定导入 20230726 的期货流水
- path: D:\期货流水目录
  template: ctp_txt
  interval: 0 # 不指定或为0时表示只执行一次
  filename_model: FuturesSettlement
  product_account:
    - product: 期货产品
      account_name: 期货账号名称
      account_number: "888888"
  start: "20230726"
  end: "20230726"
```

配置文件关键字介绍

| **字段名**         | **子字段**        | **数据类型**   | **是否必须** | **说明**                                                                                                                                   |
|-----------------|----------------|------------|----------|------------------------------------------------------------------------------------------------------------------------------------------|
| path            |                | str        | 是        | 流水文件所在的目录的地址                                                                                                                             |
| template        |                | str        | 是        | 模板类型，目前已支持的类型如下：<br> 1. xuntou: 迅投流水(要在迅投客户端的导出设置中选择全部字段的导出方式) <br> 2. ctp_txt: CTP 期货期权 txt 格式结算单 <br> 3. caitong_txt: 财通期货期权 txt 格式结算单 |
| filename_model  |                | str        | 是        | 流水文件共有的一段连续的名称(如 FuturesSettlement_20230801.txt 可指定为 FuturesSettlement)                                                                  |
| product_account |                | List[Dict] | 是        |                                                                                                                                          |
|                 | product        | str        | 是        | 产品名称, 指定需要导入哪个 AMS 产品                                                                                                                    |
|                 | account_name   | str        | 是        | 账号名称, 指定需要导入该产品的哪个账号                                                                                                                     |
|                 | account_number | str        | 是        | 数字账号, 指定该账号名称对应的数字账号(有些账号名称会变化)                                                                                                          |
| start           |                | str        | 否        | 指定导入哪些日期的流水(根据文件名中的日期，格式如'20230801')，该字段为区间开始日期，不指定则只导入当天的流水                                                                             |
| end             |                | str        | 否        | 指定导入哪些日期的流水(根据文件名中的日期，格式如'20230801')，该字段为区间结束日期，不指定则只导入当天的流水                                                                             |
| interval        |                | int        | 否        | 指定这个配置项每隔多少秒运行一次（一般用于实时导入），值为 0 或没有该字段则只会执行一次                                                                                            |
| expire_time     |                | str        | 否        | 指定在每天的几点（格式可以是 'xx:xx'）停止运行这个配置项（一般用于实时导入），值为'00:00'或没有该字段时默认全天运行                                                                        |

---

### **交易流水文件自定义导入 AMS**

解析迅投流水文件为 DataFrame 格式

```python
rqamsc.parse_xuntou_to_df(file_path: str) -> pd.DataFrame
```

解析 CTP 期货期权 txt 格式流水文件为 DataFrame 格式

```python
rqamsc.parse_ctp_txt_to_df(file_path: str) -> pd.DataFrame
```

解析财通期货期权 txt 格式流水文件为 DataFrame 格式

```python
rqamsc.parse_caitong_txt_to_df(file_path: str) -> pd.DataFrame
```

可将上述方法调用后的解析结果自定义处理后使用 insert_product_trades 导入 AMS, 如下示例

```python
import rqamsc

df = rqamsc.parse_caitong_txt_to_df('直接指定要解析的文件地址')
# 这里对df做一些自定义处理，如指定账号名称(account)及foreign_id等
df['account'] = '账号1'
# 最后指定产品导入AMS
rqamsc.insert_product_trades('产品名称', df)
```

---

### **RQAlpha 回测流水自动导入 AMS 使用说明**

用户可通过 rqalpha-mod-ams 模块自动将 RQAlpha 策略回测产生的交易流水上传至 RQAMS 资产管理平台，以便于对策略结果进行深度分析与模拟策略监控。

针对策略回测，用户仅需在 RQAMS 中新建对应产品，并将产品与所在工作空间名称配置在回测框架中即可，rqalpha-mod-ams
模块会自动生成产品的第一笔入金流水。

针对策略模拟交易，用户仅需运行 rqalpha 增量回测，即可实现策略每日流水增量导入 RQAMS 中的对应产品。

**安装**

```bash
pip install rqalpha-mod-ams>=1.1.1 --extra-index-url https://rquser:ricequant99@py.ricequant.com/simple/
```

修改配置让 rqalpha 支持 upload 上传交易流水的功能

```bash
rqalpha mod enable ams
```

查看 upload 的参数

```bash
rqalpha upload -h
```

**使用案例**

```bash
rqalpha upload --ams-product https://user:name@www.ricequant.com/workspace/product trades.csv
```

mod-ams 有如下配置:

当回测需要使用时，在 config 中的 mod 配置即可，如下

```python
from rqalpha_plus.apis import *
from rqalpha_plus import run_func


def handle_bar(context, bar_dict):
    # 股票
    order_book_id = "000001.XSHE"
    if get_position(order_book_id).quantity <= 300:
        order_shares(order_book_id, 100)
    elif get_position(order_book_id).quantity > 300:
        order_shares(order_book_id, -100)


config = {
    "base": {
        "start_date": "2023-07-10",
        "end_date": "2023-07-26",
        "frequency": "1d",
        "accounts": {
            "stock": 200000,
            "future": 100000
        }
    },
    "mod": {
        "sys_analyser": {
            "benchmark": "000300.XSHG"
        },
        "ams": {
            "enabled": True,
            "ams_product": "https://username:password@www.ricequant.com/workspace/product",
            # 上传的产品地址，需修改对应的用户名、密码、工作空间名称（或id）、产品名称（或id）
            "reset_trades": True,
            # 是否重置流水，重置表示删除start_date之后的流水再重新上传
        }
    }
}

if __name__ == '__main__':
    result = run_func(config=config, handle_bar=handle_bar)

    for key, value in result["sys_analyser"].items():
        print(key)
        print(value)


```

---

## 持仓单管理（DMA 场景） {#positions-statement-management}

### **给资产单元导入持仓单**

```python
rqamsc.upload_positions_statement_file(
        product_id_or_name: str, asset_unit_id: Union[str, ObjectId],
        file_path_or_bytes: Union[str, bytes, BufferedReader, BytesIO],
        broker: str = 'ricequant'
) -> Dict
```

- 参数

| **参数**             | **类型**                         | **是否必须** | **说明**                                                                                                                                  |
|--------------------|--------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------|
| product_id_or_name | str                            | 是        | 需要导入流水的产品 id 或产品名称                                                                                                                      |
| asset_unit_id      | str or ObjectId                | 是        | 需要导入的资产单元 id                                                                                                                            |
| file_path_or_bytes | str or bytes or BufferedReader | 是        | 需要导入流水的文件地址 或 字节码 或 文件句柄                                                                                                                |
| broker             | str                            | 否        | 需要导入的持仓单模板类型，目前支持模板如下(默认为 RQ 通道):<br/> 1. RQ 通道： ricequant <br/> 2. 中信 DMA: citic_dma <br/> 3. 中金 DMA: cicc_dma <br> 4. 招商 DMA: cms_dma |

- 返回

| **字段**          | **类型** | **是否必须** | **说明**                     |
|-----------------|--------|----------|----------------------------|
| confirmation_id | str    | 是        | 凭证 id                      |
| date            | str    | 是        | 持仓单日期                      |
| effect_count    | int    | 是        | 该条持仓单导入情况 0 表示未导入， 1 表示已导入 |
| err_msg         | list   | 是        | 持仓单中具体每条持仓导入失败情况           |

---

### **获取资产单元持仓单**

```python
rqamsc.get_positions_statement(
    product_id_or_name: str, asset_unit_id: str, start_date: datetime_like, end_date: datetime_like
) -> List[Dict]
```

- 参数

| **参数**             | **类型**                | **是否必须** | **说明**      |
|--------------------|-----------------------|----------|-------------|
| product_id_or_name | str                   | 是        | 产品 id 或产品名称 |
| asset_unit_id      | str                   | 是        | 资产单元 id     |
| start_date         | int,str,datetime,date | 是        | 开始日期        |
| end_date           | int,str,datetime,date | 是        | 结束日期        |

- 返回

| **字段**                                         | **类型**     | **是否必须** | **说明** |
|------------------------------------------------|------------|----------|--------|
| positions_statement_id                         | str        | 是        | 持仓单 id |
| date                                           | str        | 是        | 持仓单日期  |
| file_name                                      | str        | 是        | 持仓单文件名 |
| positions                                      | List[Dict] | 是        | 持仓详情   |
| &nbsp;&nbsp;&nbsp;&nbsp;_[asset_class](#资产类型)_ | str        | 是        | 资产类型   |
| &nbsp;&nbsp;&nbsp;&nbsp;_[direction](#持仓方向)_   | str        | 是        | 持仓方向   |
| &nbsp;&nbsp;&nbsp;&nbsp;order_book_id          | str        | 是        | 资产代码   |
| &nbsp;&nbsp;&nbsp;&nbsp;symbol                 | str        | 是        | 资产名称   |
| &nbsp;&nbsp;&nbsp;&nbsp;quantity               | float      | 是        | 持仓数量   |

---

### **删除资产单元持仓单**

```python
rqamsc.delete_positions_statement(
    product_id_or_name: str, asset_unit_id: str, positions_statement_ids: List[Union[str, ObjectId]]
) -> Dict
```

- 参数

| **参数**                  | **类型**              | **是否必须** | **说明**                        |
|-------------------------|---------------------|----------|-------------------------------|
| product_id_or_name      | str                 | 是        | 产品 id 或产品名称                   |
| asset_unit_id           | str                 | 是        | 资产单元 id                       |
| positions_statement_ids | List[str, ObjectId] | 是        | 持仓单 id 可参考[获取持仓](#获取资产单元持仓单)中返回结果 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**        |
|--------------|--------|----------|---------------|
| effect_count | int    | 是        | 删除数量(每条持仓记 1) |

---

## 估值表管理

### **查看产品已导入估值表信息**

```python
rqamsc.list_inserted_valuation_reports(
    product_id_or_name: str, start_date: optional_datetime_like = None, end_date: optional_datetime_like = None,
) -> List[Dict]
```

- 参数

| **参数**             | **类型**                | **是否必须** | **说明**          |
|--------------------|-----------------------|----------|-----------------|
| product_id_or_name | str                   | 是        | 产品 id 或产品名称     |
| start_date         | int,str,datetime,date | 否        | 开始日期，不填默认产品开始日期 |
| end_date           | int,str,datetime,date | 否        | 结束日期，不填则表示今日    |

- 返回

| **参数**              | **类型** | **是否必须** | **说明** |
|---------------------|--------|----------|--------|
| date                | str    | 是        | 估值表日期  |
| file_name           | str    | 是        | 估值表名称  |
| valuation_report_id | str    | 是        | 估值表 id |

```python
# 返回数据示例：
result = [
    {
        'date': '2022-03-25',
        'file_name': '估值表文件名称',
        'valuation_report_id': '6243c819894ef8b1047b99d9'
    }
]
```

---

### **给产品导入估值表_v2**

```python
rqamsc.upload_valuation_reports(
        product_id_or_name: str, files_or_directories: Union[List[str], str, List[BytesIO], BytesIO, Dict, List[Dict]],
        show_upload_progress: bool = False, replace_dates: List[optional_datetime_like] = None
) -> List[Dict]
```

- 参数

| **参数**               | **类型**                                                   | **是否必须** | **说明**                                                                                                                                                                                                                                          |
|----------------------|----------------------------------------------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| product_id_or_name   | str                                                      | 是        | 产品 id 或产品名称                                                                                                                                                                                                                                     |
| files_or_directories | list[str], str, list[BytesIO], BytesIO, list[dict], dict | 是        | 可传以下类型：<br/> 1. 文件(夹)路径列表 <br/> 2. 单个文件(夹)路径的字符 <br> 3. BytesIO 对象（该对象本身不存储文件名，若需要系统保存文件名，可参考下方操作） <br/> 4. 由 BytesIO 对象组成的列表 <br> 5. 字典，需要的字段可参考 [_估值表对象_](#估值表对象)， 代码示例可参考 [_使用 openapi 方式给产品导入估值表_](#给产品导入估值表_v2) <br> 6. 由字典构成的列表 |
| show_upload_progress | bool                                                     | 否        | 是否显示批量上传估值表文件的进度(一批为 10 个文件， 默认否)                                                                                                                                                                                                               |
| replace_dates        | list[datetime_like]                                      | 否        | 列表中日期表示在该日期已有估值表的情况下仍然覆盖<br/>eg: ['20150101', '2015-01-01', datetime.date(2015, 1, 1), datetime.datetime(2015, 1, 1)]                                                                                                                           |

BytesIO 对象设置文件名称

```python
import rqamsc
from io import BytesIO

bytes_data = b'xxxxxx'  # 从文件读取的字节码
bytesio_object = BytesIO(bytes_data)
bytesio_object.name = '估值表文件名称'

rqamsc.init(username='用户名', password='密码')
res = rqamsc.insert_valuation_reports('一个产品', bytesio_object)
print(res)
```

- 返回

| **字段**          | **类型**                | **是否必须** | **说明**    |
|-----------------|-----------------------|----------|-----------|
| file            | str                   | 是        | 估值表文件名    |
| err_msg         | Union[List[str], str] | 是        | 估值表识别错误提示 |
| effect_count    | int                   | 否        | 成功导入数量    |
| confirmation_id | str                   | 否        | 凭证 id     |

### **给产品导入估值表_v1**

```python
rqamsc.upload_valuation_reports(
    product_id_or_name: str, files_or_directories: Union[List[str], str, List[BytesIO], BytesIO, Dict, List[Dict]],
    show_upload_progress: bool = False, replace_dates: List[optional_datetime_like] = None
) -> List[Dict]
```

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 [给产品导入估值表_v2](#给产品导入估值表_v2) API。
> 旧函数名 `insert_valuation_reports` 同样已废弃，为 `upload_valuation_reports` 的别名。

可参考 [给产品导入估值表_v2](#给产品导入估值表_v2)

### **上传估值表文件_v1**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 [给产品导入估值表_v2](#给产品导入估值表_v2) API。

```python
rqamsc.upload_valuation_reports_in_directories(
    product_id_or_name: str, files_or_directories: Union[List[str], str, List[BytesIO], BytesIO, Dict, List[Dict]],
    show_upload_progress: bool = False, replace_dates: List[optional_datetime_like] = None
) -> List[Dict]
```

可参考 [给产品导入估值表_v2](#给产品导入估值表_v2)

---

### **删除产品已导入的估值表**

```python
rqamsc.delete_product_valuation_reports(
    product_id_or_name: str, deleted_dates: Union[List[datetime_like], datetime_like]
) -> Dict
```

- 参数

| **参数**             | **类型**                               | **是否必须** | **说明**                                                                                                 |
|--------------------|--------------------------------------|----------|--------------------------------------------------------------------------------------------------------|
| product_id_or_name | str                                  | 是        | 产品 id 或产品名称                                                                                            |
| deleted_dates      | datetime_like or List[datetime_like] | 是        | 列表中需要指定每个要删除的估值表的日期,若需要删除某个时间区间内的所有估值表，可使用如下方式：<br/> list(pandas.date_range('2023-01-01', '20230201')) |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**   |
|--------------|--------|----------|----------|
| effect_count | int    | 是        | 删除估值表的数量 |

---

### **下载已导入的估值表文件**

```python
rqamsc.download_product_valuation_reports(
        product_id_or_name: str, report_save_path: str, start_date: optional_datetime_like = None,
        end_date: optional_datetime_like = None
) -> Dict
```

- 参数

| **参数**             | **类型**                | **是否必须** | **说明**          |
|--------------------|-----------------------|----------|-----------------|
| product_id_or_name | str                   | 是        | 产品 id 或产品名称     |
| report_save_path   | str                   | 是        | 文件保存地址          |
| start_date         | int,str,datetime,date | 否        | 开始日期，不填默认产品开始日期 |
| end_date           | int,str,datetime,date | 否        | 结束日期，不填则表示今日    |

- 返回

| **字段**                            | **类型**     | **是否必须** | **说明**     |
|-----------------------------------|------------|----------|------------|
| successful                        | List[Dict] | 否        | 下载成功的估值表信息 |
| &nbsp;&nbsp;&nbsp;&nbsp;file_name | str        | 是        | 估值表文件名称    |
| failed                            | List[Dict] | 否        | 下载失败的估值表信息 |
| &nbsp;&nbsp;&nbsp;&nbsp;file_name | str        | 是        | 估值表文件名称    |
| &nbsp;&nbsp;&nbsp;&nbsp;reason    | str        | 是        | 下载失败原因     |

---

### **本地估值表文件自动化导入**

```python
rqamsc.run_vr_importer(
    user_name=None, password=None, workspace=None, ams_uri=None, ssl_verify=True, config_file='config.yaml', mode='full'
)
```

对于存放在本地的估值表文件，可使用如下方式自动导入 AMS

- 方式一：通过 python 脚本运行

```python
import rqamsc

rqamsc.init(username='AMS账号', password='AMS密码')  # 具体可参考rqamsc的初始化
rqamsc.choose_workspace('AMS工作空间名称或id')
rqamsc.run_vr_importer()  # 程序启动后默认读取程序工作目录下的 config.yaml 文件, 有关配置文件的内容可参考下方
```

- 方式二：命令行启动

```commandline
run_vr_importer -u AMS账号 -p AMS密码 -w 工作空间名称或id
```

- <span id="parameter">以下为该服务启动时所需的函数/命令参数</span>

| **方式一参数**   | **方式二参数**          | **是否必须** | **说明**                                                                       |
|-------------|--------------------|----------|------------------------------------------------------------------------------|
| user_name   | -u / --user_name   | 否        | AMS 账号，若像方式一中已初始化过则无需指定，方式二则必须指定                                             |
| password    | -p / --password    | 否        | AMS 密码，若像方式一中已初始化过则无需指定，方式二则必须指定                                             |
| workspace   | -w / --workspace   | 否        | 需要导入的流水所在产品的工作空间名称或 id，若像方式一中已初始化过则无需指定，方式二则必须指定                             |
| config_file | -c / --config_file | 否        | 配置文件的绝对路径，默认为程序工作目录下的 config.yaml, 该配置文件需要记录估值表文件和产品的对应关系及导入行为, 有关配置内容详情可见下方 |
| mode        | -m / --mode        | 否        | 导入模式，默认为全量导入(full), 可指定增量导入(increment)，即筛选出最近七个交易日的估值表文件导入来节省运行时间            |
| ams_uri     | --ams_uri          | 否        | AMS 网页端地址，默认为线上，私有化部署用户可按实际情况指定                                              |
| ssl_verify  | --ssl_verify       | 否        | 是否进行安全检测，线上默认为 True, 私有化部署若未使用 https 需置为 False                               |

- 服务运行需要依赖 config.yaml 配置文件来明确要导入的流水文件与产品之间的关系，以及可以指定一些导入设置，其示例及参数如下

```yaml
path: D:\估值表文件目录
product_vr_map:
  - product: 产品1 # AMS中产品名称
    full_name: xxxx一号证券投资基金委托资产估值表 # 注意：1.该字段与AMS产品的"产品全称"字段保持一致 2. 该字段包含于估值表文件名称中且区别与其他估值表文件名称
    is_overwrite: true # 是否采用估值表对账中自动覆盖方式（true则表示使用估值表文件作为产品当天的估值结果）
  - product: 产品2
    full_name: xxxx二号证券投资基金委托资产估值表
```

---

## 模拟交易

### **获取所有模拟交易**

```python
rqamsc.list_paper_trading() -> List[Dict]
```

- 返回

当 `strategy_model = "general"` 时，表示通用策略，常见返回字段如下：

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| strategy_model | str | 是 | 固定为 `general` |
| stock_min_fee | float | 是 | 股票最小手续费 |
| stock_commission_rate | float | 是 | 股票佣金费率 |
| loan_rate | float | 是 | 融资利率 |
| margin_rate | float | 是 | 融券利率 |
| futures_float_rate | float | 否 | 期货佣金上浮比例 |
| futures_float_amount | float | 否 | 期货佣金上浮金额 |
| slippage_rate | float | 否 | 成交价劣化比例 |
| slippage_ticks | float | 否 | 成交价劣化跳数 |

当 `strategy_model = "equity_long"` 时，表示权益类多头策略，常见返回字段如下：

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| strategy_model | str | 是 | 固定为 `equity_long` |
| algo | str | 是 | 模拟交易算法，取值如 `open`、`vwap`、`twap` |
| init_amount | float | 是 | 初始资金 |
| start_time | str | 否 | 开始时间，只能填写以五分钟为倍数的时间 |
| end_time | str | 否 | 结束时间，只能填写以五分钟为倍数的时间 |
| commission_rate | float | 否 | 佣金费率 |
| min_fee | float | 否 | 最低费用 |
| slippage_rate | float | 否 | 成交价劣化比例 |
| slippage_ticks | int | 否 | 成交价劣化跳数 |

---

### **获取单个产品的模拟交易配置**

```python
rqamsc.get_paper_trading(product_id_or_name: str) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明**     |
|--------------------|--------|----------|------------|
| product_id_or_name | str    | 是       | 产品 ID 或产品名 |

- 返回

参考 [_获取所有模拟交易_](#获取所有模拟交易) 的返回

---

### **更新模拟交易配置**

```python
rqamsc.update_paper_trading(
    product_id_or_name: str,
    channel_config_or_update_fields: Union[PaperTradingChannel, PaperTradingV2, Dict],
) -> Dict
```

- 参数

| **参数**                           | **类型** | **是否必需** | **说明** |
|----------------------------------|--------|----------|--------|
| product_id_or_name               | str    | 是       | 产品 ID 或产品名 |
| channel_config_or_update_fields  | PaperTradingChannel / PaperTradingV2 / Dict | 是 | 模拟交易配置更新字段 |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| update_fields | List[str] | 否 | 本次更新的字段名列表 |
| effect_count | int | 是 | 本次受影响的信号数量 |
| deleted_trade_count | int | 否 | 因重算被删除的交易流水数量 |

---

### **删除模拟交易配置**

```python
rqamsc.delete_paper_trading(product_id_or_name: str) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明**     |
|--------------------|--------|----------|------------|
| product_id_or_name | str    | 是       | 产品 ID 或产品名 |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| effect_count | int | 是 | 删除效果数量 |

---

### **重新计算模拟交易**

```python
rqamsc.recompute_paper_trading(
    product_id_or_name: str,
    date: optional_datetime_like = None,
) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明**     |
|--------------------|--------|----------|------------|
| product_id_or_name | str    | 是       | 产品 ID 或产品名 |
| date               | int/str/datetime/date | 否 | 从该日期开始重算；不传则重算全部 |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| effect_count | int | 是 | 本次参与重算的信号数量 |

---

### **上传模拟交易文件**

```python
rqamsc.upload_paper_trading_file(
    product_id_or_name: str,
    file_path_or_df: Union[str, List[str], pandas.DataFrame, List[pandas.DataFrame]],
    filenames: Union[str, List[str]] = None,
    show_progress: bool = False,
) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明** |
|--------------------|--------|----------|--------|
| product_id_or_name | str | 是 | 产品 ID 或产品名 |
| file_path_or_df | str / List[str] / pandas.DataFrame / List[pandas.DataFrame] | 是 | 文件路径、文件列表、DataFrame 或 DataFrame 列表 |
| filenames | str / List[str] | 否 | 当 `files` 为 DataFrame 或 DataFrame 列表时使用 |
| show_progress | bool | 否 | 是否展示进度信息 |

- 返回


| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| 文件名 | Dict | 是 | 每个文件对应一个结果对象 |
| &ensp;&ensp;new_id | str | 否 | 上传成功时的新信号 ID |
| &ensp;&ensp;err_msg | str | 否 | 上传失败时的错误原因 |

---

### **获取模拟交易信号列表**

```python
rqamsc.list_paper_trading_signals(
    product_id_or_name: str,
    start_date: optional_datetime_like = None,
    end_date: optional_datetime_like = None,
) -> List[Dict]
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明** |
|--------------------|--------|----------|--------|
| product_id_or_name | str | 是 | 产品 ID 或产品名 |
| start_date | int/str/datetime/date | 否 | 开始日期 |
| end_date | int/str/datetime/date | 否 | 结束日期 |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| _id | str | 是 | 信号 ID |
| filename | str | 是 | 原始文件名 |
| fs_id | str | 否 | 原始文件存储 ID |
| date | str/datetime | 是 | 信号日期 |
| status | str | 是 | 信号状态 |
| hash | str | 否 | 文件内容哈希；权益类多头策略默认会返回 |

---

### **删除模拟交易信号**

```python
rqamsc.delete_paper_trading_signals(
    product_id_or_name: str,
    start_date: optional_datetime_like = None,
    end_date: optional_datetime_like = None,
    signal_ids: List[str] = None,
) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明** |
|--------------------|--------|----------|--------|
| product_id_or_name | str | 是 | 产品 ID 或产品名 |
| start_date | int/str/datetime/date | 否 | 开始日期 |
| end_date | int/str/datetime/date | 否 | 结束日期 |
| signal_ids | List[str] | 否 | 指定信号 ID 列表；仅在支持的底层实现中生效 |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| effect_count | int | 是 | 删除的信号数量 |
| deleted_trade_count | int | 否 | 删除的交易流水数量 |

---

### **获取模拟交易信号撮合详情**

```python
rqamsc.get_paper_trading_signal_details(product_id_or_name: str, signal_id: str) -> Dict
```

- 参数

| **参数**             | **类型** | **是否必需** | **说明** |
|--------------------|--------|----------|--------|
| product_id_or_name | str | 是 | 产品 ID 或产品名 |
| signal_id | str | 是 | 信号 ID |

- 返回

| **字段** | **类型** | **是否必需** | **说明** |
|--------|--------|----------|--------|
| date | str/datetime | 是 | 信号日期 |
| deal_time | str/datetime | 否 | 成交时间或执行结束时间 |
| matching_results | List[Dict] | 是 | 撮合结果列表 |
| &ensp;&ensp;_[asset_class](#资产类型)_ | str | 是 | 资产类型 |
| &ensp;&ensp;_[direction](#持仓方向)_ | str | 是 | 交易方向 |
| &ensp;&ensp;order_book_id | str | 是 | 合约 ID |
| &ensp;&ensp;symbol | str | 是 | 合约名称 |
| &ensp;&ensp;_[transaction_type](#交易类型)_ | str | 是 | 交易类型 |
| &ensp;&ensp;status | str | 是 | 撮合或成交结果状态 |
| &ensp;&ensp;deal_datetime | str/datetime | 是 | 成交时间 |
| &ensp;&ensp;price | float | 否 | 成交价格 |
| &ensp;&ensp;quantity | int | 否 | 成交数量 |
| &ensp;&ensp;commission | float | 否 | 佣金 |
| &ensp;&ensp;tax | float | 否 | 税费 |
| &ensp;&ensp;slippage_cost | float | 否 | 滑点成本 |
| orders | List[Dict] | 否 | 原始信号内容 |

---

## 持仓及衍生指标

### **获取产品或产品组单日头寸**

```python
rqamsc.get_balance(
    product_like_id_or_name: str, dt: optional_datetime_like = None, ** kwargs
) -> Dict

```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**              |
|-------------------------|-----------------------|----------|---------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称       |
| dt                      | int,str,datetime,date | 否        | 日期，未来时间或不填则表示获取实时持仓 |

- 返回

| **字段**             | **子字段**                  | **类型**     | **是否必须** | **说明**                               |
|--------------------|--------------------------|------------|----------|--------------------------------------|
| units              |                          | float      | 是        | 份额                                   |
| unit_net_value     |                          | float      | 是        | 单位净值                                 |
| acc_unit_net_value |                          | float      | 是        | 累计净值                                 |
| adjusted_net_value |                          | float      | 是        | 复权净值                                 |
| total_assets       |                          | float      | 是        | 总资产                                  |
| total_equity       |                          | float      | 是        | 净资产                                  |
| daily_pnl          |                          | float      | 是        | 当日盈亏                                 |
| daily_returns      |                          | float      | 是        | 当日盈亏率                                |
| risk_exposure      |                          | float      | 是        | 风险总敞口                                |
| net_risk_exposure  |                          | float      | 是        | 风险净敞口                                |
| positions          |                          | list[dict] | 是        | 持仓                                   |
|                    | order_book_id            | str        | 是        | 合约 id                                |
|                    | symbol                   | str        | 是        | 合约名称                                 |
|                    | _[asset_class](#资产类型)_   | str        | 是        | 合约资产类型                               |
|                    | _[direction](#持仓方向)_     | str        | 是        | 持仓方向                                 |
|                    | quantity                 | float      | 是        | 持仓数量                                 |
|                    | avg_price                | float      | 是        | 开仓均价                                 |
|                    | avg_price_include_fee    | float      | 是        | 开仓均价（含费）                             |
|                    | fair_value               | float      | 是        | 公允价格                                 |
|                    | market_value             | float      | 是        | 市值                                   |
|                    | clean_price_market_value | float      | 是        | 净价市值                                 |
|                    | floating_pnl             | float      | 是        | 浮动盈亏                                 |
|                    | floating_pnl_percentage  | float      | 是        | 浮动盈亏率                                |
|                    | acc_pnl                  | float      | 是        | 累计盈亏                                 |
|                    | acc_pnl_rate             | float      | 是        | 累计盈亏率                                |
|                    | accrued_interest         | float      | 否        | 应记利息                                 |
|                    | exchange_rate            | float      | 是        | 汇率                                   |
|                    | currency                 | str        | 是        | 币种                                   |
|                    | bonus_share_receivable   | float      | 否        | 应收红股                                 |
|                    | asset_unit_id            | str        | 否        | 资产单元 id                              |
|                    | children                 | list[dict] | 否        | 对应资产单元下的子持仓，结构可直接参考产品头寸顶层的 positions |

---

### **获取产品或产品组指标**

```python
rqamsc.get_indicators(
    product_like_id_or_name: str,
start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None,
** kwargs
) -> Dict
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                                                                                                                                                                                                                         |
|-------------------------|-----------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称                                                                                                                                                                                                                                                                                  |
| start_date              | int,str,datetime,date | 否        | 开始日期，不填表示产品(组)开始日期                                                                                                                                                                                                                                                                             |
| end_date                | int,str,datetime,date | 否        | 结束日期，不填则表示昨日                                                                                                                                                                                                                                                                                   |
| benchmark(关键字参数)        | str                   | 否        | 基准(默认使用产品(组)中所设置基准)，所传值如 000300.XSHG 或 自定义基准 id                                                                                                                                                                                                                                                |
| extra_indicators(关键字参数) | str                   | 否        | 额外指标,可指定额外返回以下指标（多个指标使用英文逗号相连）<br/> 1.returns_summary: 收益概览 <br/> 2. asset_series: 组合指标序列 <br/> 3. benchmark_series: 基准收益序列 <br/> 4. excess_returns: 主动收益序列 <br/> 5. monthly_returns: 组合年月周度收益 <br/> 6. leverage_ratio: 杠杆率序列 <br/> 7. ashares_market_value: 市值分布 <br/> 8. annual_risk: 年度风险指标 |

- 返回

| **字段**                                  | **子字段**                                 | **孙字段**                              | **类型**     | **是否必须** | **说明**                |
|-----------------------------------------|-----------------------------------------|--------------------------------------|------------|----------|-----------------------|
| daily_risk / weekly_risk / monthly_risk |                                         |                                      | dict       | 是        | 区间日/周/月频业绩总览指标        |
|                                         | alpha                                   |                                      | float      | 是        | 阿尔法                   |
|                                         | information_ratio                       |                                      | float      | 是        | 信息比率                  |
|                                         | beta                                    |                                      | float      | 是        | 贝塔                    |
|                                         | sharpe                                  |                                      | float      | 是        | 夏普率                   |
|                                         | excess_sharpe                           |                                      | float      | 是        | 超额夏普率                 |
|                                         | annual_tracking_error                   |                                      | float      | 是        | 年化跟踪误差                |
|                                         | annual_downside_risk                    |                                      | float      | 是        | 年化下行风险                |
|                                         | annual_volatility                       |                                      | float      | 是        | 年化波动率                 |
|                                         | arithmetic_excess_annual_return         |                                      | float      | 是        | 年化(算术)超额收益            |
|                                         | geometric_excess_annual_return          |                                      | float      | 是        | 年化(几何)超额收益            |
|                                         | excess_annual_volatility                |                                      | float      | 是        | 年化超额波动率               |
|                                         | max_drawdown                            |                                      | float      | 是        | 最大回撤                  |
|                                         | geometric_excess_max_drawdown           |                                      | float      | 是        | (几何)超额最大回撤            |
| annual_risk                             |                                         |                                      | dict       | 否        | 区间内年度总览指标             |
|                                         | daily_risk / weekly_risk / monthly_risk |                                      | dict       | 否        | 每年日/周/月频业绩指标          |
|                                         |                                         | alpha                                | float      | 是        | 年度阿尔法                 |
|                                         |                                         | information_ratio                    | float      | 是        | 年度信息比率                |
|                                         |                                         | beta                                 | float      | 是        | 年度贝塔                  |
|                                         |                                         | correlation                          | float      | 是        | 年度相关系数                |
|                                         |                                         | sharpe                               | float      | 是        | 年度夏普率                 |
|                                         |                                         | excess_sharpe                        | float      | 是        | 年度超额夏普率               |
|                                         |                                         | dividend_ratio                       | float      | 是        | 年度分红率                 |
|                                         |                                         | annual_tracking_error                | float      | 是        | 年度年化跟踪误差              |
|                                         |                                         | annual_downside_risk                 | float      | 是        | 年度年化下行风险              |
|                                         |                                         | excess_annual_return                 | float      | 是        | 年度年化超额收益              |
|                                         |                                         | annual_volatility                    | float      | 是        | 年度年化波动率               |
|                                         |                                         | arithmetic_excess_annual_return      | float      | 是        | 年度年化(算术)超额收益          |
|                                         |                                         | geometric_excess_annual_return       | float      | 是        | 年度年化(几何)超额收益          |
|                                         |                                         | excess_annual_volatility             | float      | 是        | 年度年化超额波动率             |
|                                         |                                         | max_drawdown                         | float      | 是        | 年度最大回撤                |
|                                         |                                         | geometric_excess_max_drawdown        | float      | 是        | 年度(几何)超额最大回撤          |
|                                         |                                         | total_returns                        | float      | 是        | 年度总收益                 |
|                                         |                                         | total_annual_returns                 | float      | 是        | 年度年化总收益（复利）           |
|                                         |                                         | annual_simple_interest               | float      | 是        | 年度年化总收益（单利）           |
|                                         |                                         | total_geometric_excess_return        | float      | 是        | 年度(几何)超额收益            |
|                                         |                                         | total_arithmetic_excess_return       | float      | 是        | 年度(算术)超额收益            |
| returns_summary                         |                                         |                                      | dict       | 否        | 期间收益概览                |
|                                         | total                                   |                                      | float      | 是        | 期间收益                  |
|                                         | arithmetic_excess                       |                                      | float      | 是        | 期间(算术)超额收益            |
|                                         | geometric_excess                        |                                      | float      | 是        | 期间(几何)超额收益            |
|                                         | annual                                  |                                      | float      | 是        | 期间年化收益（复利）            |
|                                         | annual_simple_interest                  |                                      | float      | 是        | 期间年化收益（单利）            |
|                                         | annual_oneside_turnover_rate            |                                      | float      | 是        | 年化单边换手率               |
|                                         | this_week                               |                                      | float      | 是        | 近一周收益                 |
|                                         | this_month                              |                                      | float      | 是        | 近一月收益                 |
|                                         | this_quarter                            |                                      | float      | 是        | 近一季度收益                |
|                                         | this_year                               |                                      | float      | 是        | 近一年收益                 |
| asset_series                            |                                         |                                      | list[dict] | 否        | 组合指标序列                |
|                                         | daily / weekly /monthly                 |                                      | dict       | 否        | 组合日/周/月指标序列           |
|                                         |                                         | date                                 | str        | 是        | 日期                    |
|                                         |                                         | daily_returns                        | float      | 是        | 每日收益率                 |
|                                         |                                         | cumulative_returns                   | float      | 是        | 累计收益率                 |
| benchmark_series                        |                                         |                                      | list[dict] | 否        | 基准收益序列                |
|                                         | daily                                   |                                      | dict       | 否        | 基准日/周/月收益序列           |
|                                         |                                         | date                                 | str        | 是        | 日期                    |
|                                         |                                         | daily_returns                        | float      | 是        | 每日收益率                 |
|                                         |                                         | cumulative_returns                   | float      | 是        | 累计收益率                 |
|                                         | weekly / monthly                        |                                      | dict       | 否        | 基准周/月收益序列             |
|                                         |                                         | date                                 | str        | 是        | 日期                    |
|                                         |                                         | benchmark_returns                    | float      | 是        | 周/月度收益率               |
|                                         |                                         | benchmark_cumulative_returns         | float      | 是        | 周/月度累计收益率             |
| excess_returns                          |                                         |                                      | list[dict] | 否        | 超额收益序列                |
|                                         | daily / weekly /monthly                 |                                      | dict       | 否        | 日/周/月度超额收益序列          |
|                                         |                                         | date                                 | str        | 是        | 日期                    |
|                                         |                                         | daily_arithmetic_excess_returns      | float      | 是        | 当日(算术)超额收益率           |
|                                         |                                         | cumulative_arithmetic_excess_returns | float      | 是        | 累计(算术)超额收益率           |
|                                         |                                         | cumulative_geometric_excess_returns  | float      | 是        | 累计(几何)超额收益率           |
| monthly_returns                         |                                         |                                      | list[dict] | 否        | 年月周度收益                |
|                                         | date                                    |                                      | str        | 是        | 年度(2022)              |
|                                         | portfolio_returns                       |                                      | float      | 是        | 组合收益                  |
|                                         | benchmark_returns                       |                                      | float      | 是        | 基准收益                  |
|                                         | arithmetic_excess_returns               |                                      | float      | 是        | (算术)超额收益              |
|                                         | geometric_excess_returns                |                                      | float      | 是        | (几何)超额收益              |
|                                         | children                                |                                      | list[dict] | 是        | 月度收益数据                |
|                                         |                                         | date                                 | str        | 是        | 月度(2022-01)           |
|                                         |                                         | portfolio_returns                    | float      | 是        | 组合收益                  |
|                                         |                                         | benchmark_returns                    | float      | 是        | 基准收益                  |
|                                         |                                         | arithmetic_excess_returns            | float      | 是        | (算术)超额收益              |
|                                         |                                         | geometric_excess_returns             | float      | 是        | (几何)超额收益              |
|                                         |                                         | children                             | list[dict] | 是        | 周度收益数据                |
|                                         |                                         | children.date                        | str        | 是        | 周度(1,表示第一周)           |
|                                         |                                         | children.portfolio_returns           | float      | 是        | 组合收益                  |
|                                         |                                         | children.benchmark_returns           | float      | 是        | 基准收益                  |
|                                         |                                         | children.arithmetic_excess_returns   | float      | 是        | (算术)超额收益              |
|                                         |                                         | children.geometric_excess_returns    | float      | 是        | (几何)超额收益              |
| leverage_ratio                          |                                         |                                      | list[dict] | 否        | 杠杆率                   |
|                                         | daily / weekly / monthly                |                                      | dict       | 否        | 日/周/月度杠杆率             |
|                                         |                                         | date                                 | str        | 是        | 日期                    |
|                                         |                                         | total_asset                          | float      | 是        | 总资产                   |
|                                         |                                         | total_equity                         | float      | 是        | 净资产                   |
|                                         |                                         | leverage_ratio                       | float      | 是        | 杠杆率                   |
| ashares_market_value                    |                                         |                                      | dict       | 否        | 市值分布                  |
|                                         | sh_market_value                         |                                      | float      | 是        | 沪市市值                  |
|                                         | sz_market_value                         |                                      | float      | 是        | 深市市值                  |
|                                         | sh_market_value_prev                    |                                      | float      | 是        | T-21 到 T-2 之间的沪市市值平均值 |
|                                         | sz_market_value_prev                    |                                      | float      | 是        | T-21 到 T-2 之间的深市市值平均值 |

---

### **获取产品或产品组时序指标**

```python
rqamsc.get_indicators_series(
    product_like_id_or_name: str,
start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None,
indicators: Optional[List[str]] = None,
** kwargs
) -> Dict
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
|-------------------------|-----------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| start_date              | int,str,datetime,date | 否        | 开始日期，不填表示昨日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| end_date                | int,str,datetime,date | 否        | 结束日期，不填则表示昨日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| indicators              | List[str]             | 否        | 可指定所需指标, 不传默认返回全部指标, 可选指标如下:<br/> 1. 单位净值: unit_net_value <br/> 2. 累计净值: acc_unit_net_value <br/> 3. 复权净值: adjusted_net_value <br/> 4. 总资产: total_assets <br/> 5. 净资产: total_equity <br/> 6. 当日盈亏: daily_pnl <br/> 7. 权益净敞口：equity_net_exposure <br/> 8. 现金：cash <br/> 9. 买入金额: buy_amount <br/> 10. 卖出金额: sell_amount <br/> 11. 净投入：net_cash_in <br/> 12. 申购份额：subscribe_units <br/> 13. 申购金额：subscribe_amount <br/> 14. 赎回份额：redeem_units <br/> 15. 赎回金额：redeem_amount <br/> 16. 风险总敞口: risk_exposure <br/> 17 风险净敞口: net_risk_exposure |

- 返回

| **字段** | **子字段** | **类型** | **是否必须** | **说明**                   |
|--------|---------|--------|----------|--------------------------|
| 指标名称   |         | dict   | 是        |                          |
|        | 日期      | str    | 是        | key 为日期, value 所对应指标当日的值 |

e.g.

```python
{
    "unit_net_value": {
        "2015-01-01": 1,
        "2015-01-02": 1.1,
        "2015-01-03": 1.3
    },
    "daily_pnl": {
        "2015-01-01": 1000,
        "2015-01-02": 1000,
        "2015-01-03": 1000
    }
    ...
}
```

---

### **获取产品或产品组实时信息**

```python
rqamsc.get_asset_snapshot(
    product_like_id_or_name: str, fields: List[str] = None, flatten_positions = True, ** kwargs
) -> Dict
```

- 参数

| **参数**                  | **类型**    | **是否必须** | **说明**                                                                                                            |
|-------------------------|-----------|----------|-------------------------------------------------------------------------------------------------------------------|
| product_like_id_or_name | str       | 是        | 产品(组)id 或名称                                                                                                       |
| fields                  | List[str] | 否        | 除默认字段外，可指定返回一些额外字段如:<br/> 1. risk_exposure: 风险总敞口 <br/> 2. net_risk_exposure: 风险净敞口 <br/> 3. excess_returns: 超额收益 |
| flatten_positions       | bool      | 否        | 是否将持仓平铺, 默认平铺                                                                                                     |

- 返回

| **字段**                 | **子字段**                  | **类型**        | **是否必须** | **说明**                                         |
|------------------------|--------------------------|---------------|----------|------------------------------------------------|
| date                   |                          | str           | 是        | 日期                                             |
| name                   |                          | str           | 是        | 产品名称                                           |
| unit_net_value         |                          | float         | 是        | 单位净值                                           |
| units                  |                          | float         | 是        | 份额                                             |
| prev_unit_net_value    |                          | float         | 是        | 昨日净值                                           |
| total_assets           |                          | float         | 是        | 总资产                                            |
| total_equity           |                          | float         | 是        | 净资产                                            |
| total_liabilities      |                          | float         | 是        | 总负债                                            |
| daily_pnl              |                          | float         | 是        | 当日盈亏                                           |
| daily_returns          |                          | float         | 是        | 当日盈亏率                                          |
| long_market_value      |                          | float         | 是        | 多头市值                                           |
| short_market_value     |                          | float         | 是        | 空头市值                                           |
| capital_efficiency     |                          | float         | 是        | 资金使用率(期货杠杆率)                                   |
| returns_from_establish |                          | float         | 是        | 成立以来回报率                                        |
| pnl_this_year          |                          | float         | 是        | 今年以来盈亏(元)                                      |
| returns_this_year      |                          | float         | 是        | 今年以来盈亏(%)                                      |
| risk_exposure          |                          | float         | 否        | 风险总暴露                                          |
| net_risk_exposure      |                          | float         | 否        | 风险净敞口                                          |
| long_leverage          |                          | float         | 否        | 多头杠杆倍数                                         |
| long_net_risk_exposure |                          | float         | 否        | 多头净暴露                                          |
| benchmark_returns      |                          | float         | 否        | 基准收益率                                          |
| excess_returns         |                          | float         | 否        | 超额收益率                                          |
| positions              |                          | list[dict]    | 否        | 持仓明细                                           |
|                        | order_book_id            | str           | 是        | 合约 id                                          |
|                        | symbol                   | str           | 是        | 合约名称                                           |
|                        | _[asset_class](#资产类型)_   | str           | 是        | 合约资产类型                                         |
|                        | _[direction](#持仓方向)_     | str           | 是        | 持仓方向                                           |
|                        | quantity                 | float         | 是        | 持仓数量                                           |
|                        | price_change             | float         | 是        | 涨跌                                             |
|                        | price_change_percentage  | float         | 是        | 涨跌幅度                                           |
|                        | avg_price                | float         | 是        | 开仓均价                                           |
|                        | avg_price_include_fee    | float         | 是        | 开仓均价（含费）                                       |
|                        | fair_value               | float         | 是        | 公允价格                                           |
|                        | price_limit              | optional[str] | 是        | 是否涨跌停： 涨停(limit_up); 跌停(limit_down); 未发生涨跌停则为空 |
|                        | has_settlement           | bool          | 是        | 是否已更新结算价                                       |
|                        | market_value             | float         | 是        | 市值                                             |
|                        | clean_price_market_value | float         | 是        | 净价市值                                           |
|                        | floating_pnl             | float         | 是        | 浮动盈亏                                           |
|                        | floating_pnl_percentage  | float         | 是        | 浮动盈亏率                                          |
|                        | accrued_interest         | float         | 是        | 应记利息                                           |
|                        | exchange_rate            | float         | 是        | 汇率                                             |
|                        | currency                 | str           | 是        | 币种                                             |
|                        | bonus_share_receivable   | float         | 是        | 应收红股                                           |
|                        | update_time              | str           | 是        | 公允价更新时间                                        |

---

### **获取产品或产品组头寸序列**

```python
rqamsc.get_balance_series(
    product_like_id_or_name: str, start_date: optional_datetime_like, end_date: optional_datetime_like = None,
fields: Optional[List[str]] = None, ** kwargs
) -> List[Dict]
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                        |
|-------------------------|-----------------------|----------|-----------------------------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称                                 |
| start_date              | int,str,datetime,date | 是        | 开始日期                                          |
| end_date                | int,str,datetime,date | 否        | 结束日期，不填则表示今日                                  |
| fields                  | List[str]             | 否        | 除必须字段可选择返回的持仓字段，不填则仅返回必须的持仓字段，字段值可参考下述返回的持仓字段 |

- 返回

List 中字典结构如下

| **字段**        | **子字段**                  | **类型**     | **是否必须** | **说明**   |
|---------------|--------------------------|------------|----------|----------|
| date          |                          | str        | 是        | 日期       |
| total_assets  |                          | float      | 是        | 总资产      |
| total_equity  |                          | float      | 是        | 净资产      |
| daily_pnl     |                          | float      | 是        | 当日盈亏     |
| daily_returns |                          | float      | 是        | 当日盈亏率    |
| positions     |                          | list[dict] | 否        | 持仓明细     |
|               | order_book_id            | str        | 是        | 合约 id    |
|               | symbol                   | str        | 是        | 合约名称     |
|               | _[asset_class](#资产类型)_   | str        | 是        | 合约资产类型   |
|               | _[direction](#持仓方向)_     | str        | 是        | 持仓方向     |
|               | quantity                 | float      | 是        | 持仓数量     |
|               | market_value             | float      | 是        | 市值       |
|               | price_change             | float      | 否        | 涨跌       |
|               | price_change_percentage  | float      | 否        | 涨跌幅度     |
|               | avg_price                | float      | 否        | 开仓均价     |
|               | avg_price_include_fee    | float      | 否        | 开仓均价（含费） |
|               | fair_value               | float      | 否        | 公允价格     |
|               | clean_price_market_value | float      | 否        | 净价市值     |
|               | daily_pnl                | float      | 否        | 当日盈亏     |
|               | daily_pnl_rate           | float      | 否        | 当日盈亏率    |
|               | floating_pnl             | float      | 否        | 浮动盈亏     |
|               | floating_pnl_percentage  | float      | 否        | 浮动盈亏率    |
|               | acc_pnl                  | float      | 否        | 累计盈亏     |
|               | acc_pnl_rate             | float      | 否        | 累计盈亏率    |
|               | accrued_interest         | float      | 否        | 应记利息     |
|               | bonus_share_receivable   | float      | 否        | 应收红股     |
|               | acc_dividend_received    | float      | 否        | 累计股息收入   |
|               | acc_interest_received    | float      | 否        | 累计利息收入   |

---

### **获取产品或产品组净值周度报告**

```python
rqamsc.get_weekly_net_value_report(
    product_id_or_name: str, report_save_path: str, start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> str
```

**参数**

| **参数**                  | **类型**                | **是否必须** | **说明**              |
|-------------------------|-----------------------|----------|---------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称       |
| report_save_path        | str                   | 是        | 报告 excel 保存路径(到文件夹) |
| start_date              | int,str,datetime,date | 否        | 开始日期                |
| end_date                | int,str,datetime,date | 否        | 结束日期                |

**返回**

成功的字符信息 or 抛出错误

---

## 绩效归因

### **获取产品或产品组绩效归因**

```python
rqamsc.get_performance_attribution(
    product_like_id_or_name: str, start_date: optional_datetime_like, end_date: optional_datetime_like,
benchmark_id: Union[ObjectId, str] = '000300.XSHG', template: PATemplate = PATemplate.BRINSON,
industry_standard: str = 'sws', drilldown: bool = False, only_returns_decomposition: bool = False
) -> Dict
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                                                                                                                                                            |
|-------------------------|-----------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称                                                                                                                                                                                                                     |
| start_date              | int,str,datetime,date | 是        | 开始日期                                                                                                                                                                                                                              |
| end_date                | int,str,datetime,date | 是        | 结束日期                                                                                                                                                                                                                              |
| benchmark_id            | Union[ObjectId, str]  | 否        | 基准 id(默认为沪深 300):<br/> 1. 沪深 300: 000300.XSHG <br/> 2. 中证 500: 000905.XSHG <br/> 3. 中证 800: 000906.XSHG <br/> 4. 中证 1000: 000852.XSHG <br/> 5. 米筐小市值概念指数: 866002.RI <br/> 6. 一年期国债: china_treasury_bonds <br/> 7. 自定义基准：传合约 id 即可 |
| template                | PATemplate            | 否        | 分析模板 可参考[PATemplate](#业绩归因模板对象)，默认为 brinson 归因                                                                                                                                                                                    |
| industry_standard       | str                   | 否        | 行业分类（默认为申万一级）:<br/> 1. 申万一级: sws <br/> 2. 中信一级: citics <br> 3. 申万二级: sws_second <br> 4. 中信二级: citics_second                                                                                                                       |

- 返回

| **字段**                                                 | **类型**               | **是否必须** | **说明**         |
|--------------------------------------------------------|----------------------|----------|----------------|
| attribution                                            | Dict                 | 是        |                |
| &ensp;&ensp;brinson                                    | Dict                 | 否        | brinson 归因结果   |
| &ensp;&ensp;&ensp;&ensp;industry                       | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;allocation_risk                | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;selection_risk                 | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;interaction_risk               | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;allocation_return              | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;portfolio_weight               | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;benchmark_weight               | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;selection_return               | float                | 是        |                |
| &ensp;&ensp;factor_attribution                         | Dict                 | 否        | 因子贡献           |
| &ensp;&ensp;&ensp;&ensp;type                           | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;factors                        | List[Dict]           | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;factor             | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;portfolio_return   | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;portfolio_exposure | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;benchmark_return   | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;benchmark_exposure | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;portfolio_risk     | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;benchmark_risk     | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;active_risk        | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;active_exposure    | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;active_return      | float                | 是        |                |
| &ensp;&ensp;factor_exposure                            | Dict                 | 否        | 因子暴露度          |
| &ensp;&ensp;&ensp;&ensp;factor                         | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;data                           | List[Dict]           | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;date               | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;portfolio          | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;normalized         | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;active             | float                | 是        |                |
| &ensp;&ensp;sensitivity                                | Dict                 | 否        | 敏感性            |
| &ensp;&ensp;&ensp;&ensp;date                           | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;data                           | List[Dict]           | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;factor             | str                  | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;portfolio          | float                | 是        |                |
| &ensp;&ensp;&ensp;&ensp;&ensp;&ensp;t_statistics       | float                | 是        |                |
| return_decomposition                                   | List[Dict]           | 否        |                |
| &ensp;&ensp;factor                                     | float                | 是        |                |
| &ensp;&ensp;value                                      | float                | 是        |                |
| &ensp;&ensp;chlidren                                   | Optional[List[Dict]] | 是        | 拆解后的子收益，结构同父节点 |

### **获取产品或产品组收益拆解**

```python
rqamsc.get_returns_decomposition(
    product_like_id_or_name: str, start_date: optional_datetime_like, end_date: optional_datetime_like,
benchmark_id: Union[ObjectId, str] = '000300.XSHG'
) -> List
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                                                                                                                                                                                                                            |
|-------------------------|-----------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称                                                                                                                                                                                                                     |
| start_date              | int,str,datetime,date | 是        | 开始日期                                                                                                                                                                                                                              |
| end_date                | int,str,datetime,date | 是        | 结束日期                                                                                                                                                                                                                              |
| benchmark_id            | Union[ObjectId, str]  | 否        | 基准 id(默认为沪深 300):<br/> 1. 沪深 300: 000300.XSHG <br/> 2. 中证 500: 000905.XSHG <br/> 3. 中证 800: 000906.XSHG <br/> 4. 中证 1000: 000852.XSHG <br/> 5. 米筐小市值概念指数: 866002.RI <br/> 6. 一年期国债: china_treasury_bonds <br/> 7. 自定义基准：传合约 id 即可 |

- 返回

列表内元素结构如下

| **字段**               | **类型**               | **是否必须** | **说明**         |
|----------------------|----------------------|----------|----------------|
| &ensp;&ensp;factor   | float                | 是        |                |
| &ensp;&ensp;value    | float                | 是        |                |
| &ensp;&ensp;chlidren | Optional[List[Dict]] | 是        | 拆解后的子收益，结构同父节点 |

---

## 投资驾驶舱

### **批量获取产品或产品组概览指标**

```python
rqamsc.get_investment_overview_summary_indicator(
    product_like_ids_or_names: Union[List[str], str], start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> List
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

列表内字典元素结构如下

| **字段层级**                                    | **类型**        | **是否必须** | **说明**              |
|---------------------------------------------|---------------|----------|---------------------|
| id                                          | str           | 是        | 产品或产品组 id           |
| name                                        | str           | 是        | 产品或产品组名称            |
| start_date                                  | str           | 是        | 产品开始日期              |
| net_value                                   | null or float | 是        | 最新净值                |
| annual_twoside_turnover_rate                | float         | 是        | 年化双边换手率             |
| period_acc_returns                          | float         | 是        | 区间回报                |
| total_geometric_excess_return               | float         | 是        | 总几何超额收益             |
| daily                                       | dict          | 是        | 日频指标                |
| &ensp;&ensp;alpha                           | float         | 是        | 阿尔法                 |
| &ensp;&ensp;beta                            | float         | 是        | 贝塔                  |
| &ensp;&ensp;sharpe                          | float         | 是        | 夏普率                 |
| &ensp;&ensp;excess_sharpe                   | float         | 是        | 超额夏普率               |
| &ensp;&ensp;max_drawdown                    | float         | 是        | 最大回撤                |
| &ensp;&ensp;annual_downside_risk            | float         | 是        | 年化下行风险              |
| &ensp;&ensp;information_ratio               | float         | 是        | 信息比率                |
| &ensp;&ensp;geometric_excess_annual_return  | float         | 是        | 几何超额年化收益率           |
| &ensp;&ensp;arithmetic_excess_annual_return | float         | 是        | 算术超额年化收益率           |
| &ensp;&ensp;annual_volatility               | float         | 是        | 年化波动率               |
| &ensp;&ensp;excess_annual_volatility        | float         | 是        | 超额年化波动率             |
| &ensp;&ensp;annual_tracking_error           | float         | 是        | 年化跟踪误差              |
| &ensp;&ensp;geometric_excess_max_drawdown   | float         | 是        | 几何超额最大回撤            |
| &ensp;&ensp;total_returns                   | float         | 是        | 总收益率                |
| &ensp;&ensp;total_geometric_excess_return   | float         | 是        | 总几何超额收益             |
| &ensp;&ensp;total_arithmetic_excess_return  | float         | 是        | 总算术超额收益             |
| &ensp;&ensp;total_annual_returns            | float         | 是        | 总年化收益率              |
| &ensp;&ensp;net_cash_in                     | float         | 是        | 净投入                 |
| &ensp;&ensp;period_pnl                      | float         | 是        | 区间盈亏                |
| &ensp;&ensp;equity_net_exposure             | float         | 是        | 权益净敞口               |
| &ensp;&ensp;period_buy_amount               | float         | 是        | 区间买入金额              |
| &ensp;&ensp;period_sell_amount              | float         | 是        | 区间卖出金额              |
| &ensp;&ensp;cash                            | float         | 是        | 现金                  |
| &ensp;&ensp;total_equity                    | float         | 是        | 净资产                 |
| &ensp;&ensp;period_acc_returns              | float         | 是        | 区间累计收益率             |
| &ensp;&ensp;cn_stock_market_value           | float         | 是        | A 股总市值              |
| &ensp;&ensp;hk_stock_market_value           | float         | 是        | 港股总市值               |
| weekly                                      | dict          | 是        | 周频指标                |
| &ensp;&ensp;alpha                           | float         | 是        | 阿尔法                 |
| &ensp;&ensp;beta                            | float         | 是        | 贝塔                  |
| &ensp;&ensp;sharpe                          | float         | 是        | 夏普率                 |
| &ensp;&ensp;excess_sharpe                   | float         | 是        | 超额夏普率               |
| &ensp;&ensp;max_drawdown                    | float         | 是        | 最大回撤                |
| &ensp;&ensp;annual_downside_risk            | float         | 是        | 年化下行风险              |
| &ensp;&ensp;information_ratio               | float         | 是        | 信息比率                |
| &ensp;&ensp;geometric_excess_annual_return  | float         | 是        | 几何超额年化收益率           |
| &ensp;&ensp;arithmetic_excess_annual_return | float         | 是        | 算术超额年化收益率           |
| &ensp;&ensp;annual_volatility               | float         | 是        | 年化波动率               |
| &ensp;&ensp;excess_annual_volatility        | float         | 是        | 超额年化波动率             |
| &ensp;&ensp;annual_tracking_error           | float         | 是        | 年化跟踪误差              |
| &ensp;&ensp;geometric_excess_max_drawdown   | float         | 是        | 几何超额最大回撤            |
| &ensp;&ensp;total_returns                   | float         | 是        | 总收益率                |
| &ensp;&ensp;total_geometric_excess_return   | float         | 是        | 总几何超额收益             |
| &ensp;&ensp;total_arithmetic_excess_return  | float         | 是        | 总算术超额收益             |
| &ensp;&ensp;total_annual_returns            | float         | 是        | 总年化收益率              |
| monthly                                     | dict          | 是        | 月频指标（字段与 weekly 相同） |

- 返回示例

```python
[
    {
        "id": "67d945ed3fc21df7d82acc4b",
        "name": "测试产品A",
        "start_date": "2024-01-01",
        "net_value": 1.2345,
        "annual_twoside_turnover_rate": 2.5,
        "period_acc_returns": 0.1234,
        "total_geometric_excess_return": 0.0523,
        "daily": {
            "alpha": 0.0234,
            "beta": 0.9876,
            "sharpe": 1.2345,
            "excess_sharpe": 1.1234,
            "max_drawdown": -0.0567,
            "annual_downside_risk": 0.0789,
            "information_ratio": 0.8765,
            "geometric_excess_annual_return": 0.0678,
            "arithmetic_excess_annual_return": 0.0712,
            "annual_volatility": 0.1523,
            "excess_annual_volatility": 0.0834,
            "annual_tracking_error": 0.0923,
            "geometric_excess_max_drawdown": -0.0234,
            "total_returns": 0.2345,
            "total_geometric_excess_return": 0.0523,
            "total_arithmetic_excess_return": 0.0567,
            "total_annual_returns": 0.1896,
            "net_cash_in": 10000000.0,
            "period_pnl": 1234567.89,
            "equity_net_exposure": 0.95,
            "period_buy_amount": 2000000.0,
            "period_sell_amount": 1500000.0,
            "cash": 500000.0,
            "total_equity": 12345678.9,
            "period_acc_returns": 0.1234,
            "cn_stock_market_value": 11000000.0,
            "hk_stock_market_value": 800000.0
        },
        "weekly": {
            "alpha": 0.0223,
            "beta": 0.9823,
            "sharpe": 1.1987,
            "excess_sharpe": 1.0876,
            "max_drawdown": -0.0534,
            "annual_downside_risk": 0.0756,
            "information_ratio": 0.8234,
            "geometric_excess_annual_return": 0.0634,
            "arithmetic_excess_annual_return": 0.0689,
            "annual_volatility": 0.1467,
            "excess_annual_volatility": 0.0789,
            "annual_tracking_error": 0.0867,
            "geometric_excess_max_drawdown": -0.0212,
            "total_returns": 0.2234,
            "total_geometric_excess_return": 0.0498,
            "total_arithmetic_excess_return": 0.0534,
            "total_annual_returns": 0.1823
        },
        "monthly": {
                   // 字段结构与weekly相同
    }
}
]
```

---

### **批量获取产品或产品组回报趋势**

```python
rqamsc.get_investment_overview_returns_series(
    product_like_ids_or_names: Union[List[str], str], benchmark_id: str, start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> List
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| benchmark_id              | str                   | 是        | 基准合约代码或自定义基准 id           |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

列表内字典元素结构如下

| **字段层级**                                        | **类型**     | **是否必须** | **说明**                              |
|-------------------------------------------------|------------|----------|-------------------------------------|
| id                                              | str        | 是        | 产品/产品组/基准的 id                       |
| type                                            | str        | 是        | 类型（benchmark/product/group）         |
| name                                            | str        | 是        | 产品/产品组/基准名称                         |
| daily                                           | list[dict] | 是        | 日频时序数据                              |
| &ensp;&ensp;date                                | str        | 是        | 日期                                  |
| &ensp;&ensp;cumulative_returns                  | float      | 是        | 累计收益率                               |
| &ensp;&ensp;daily_returns                       | float      | 是        | 日收益率                                |
| &ensp;&ensp;geometric_excess_cumulative_returns | float      | 否        | 几何超额累计收益率（type=product/group 时存在）   |
| &ensp;&ensp;excess_earnings                     | float      | 否        | 超额收益率（type=product/group 时存在）       |
| weekly                                          | list[dict] | 是        | 周频时序数据                              |
| &ensp;&ensp;date                                | str        | 是        | 日期                                  |
| &ensp;&ensp;cumulative_returns                  | float      | 是        | 累计收益率                               |
| &ensp;&ensp;daily_returns                       | float      | 否        | 日收益率（仅 type=benchmark 时存在）          |
| &ensp;&ensp;geometric_excess_cumulative_returns | float      | 否        | 几何超额累计收益率（仅 type=product/group 时存在） |
| monthly                                         | list[dict] | 是        | 月频时序数据（字段结构与 weekly 相同）             |

- 返回示例

```python
[
    {
        "id": "000300.XSHG",
        "type": "benchmark",
        "name": "沪深300",
        "daily": [
            {
                "date": "2025-07-01",
                "daily_returns": 0.0019565917768269436,
                "cumulative_returns": 0.0019565917768269436
            }
        ],
        "weekly": [
            {
                "date": "2025-07-01",
                "daily_returns": 0.0019565917768269436,
                "cumulative_returns": 0.0019565917768269436
            }
        ],
        "monthly": [
            {
                "date": "2025-07-01",
                "daily_returns": 0.0019565917768269436,
                "cumulative_returns": 0.0019565917768269436
            }
        ]
    },
    {
        "id": "67d945ed3fc21df7d82acc4b",
        "type": "product",
        "name": "测试产品A",
        "daily": [
            {
                "date": "2025-07-01",
                "cumulative_returns": -0.9934833520008146,
                "geometric_excess_cumulative_returns": -0.993496077522052,
                "daily_returns": -0.9934833520008146,
                "excess_earnings": -0.9954399437776416
            }
        ],
        "weekly": [
            {
                "date": "2025-07-01",
                "cumulative_returns": -0.9934833520008146,
                "geometric_excess_cumulative_returns": -0.993496077522052
            }
        ],
        "monthly": [
            {
                "date": "2025-07-01",
                "cumulative_returns": -0.9934833520008146,
                "geometric_excess_cumulative_returns": -0.993496077522052
            }
        ]
    },
]
```

---

### **批量获取产品或产品组资产规模走势**

```python
rqamsc.get_investment_overview_asset_capital_size(
    product_like_ids_or_names: Union[List[str], str], start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> List
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

列表内字典元素结构如下

| **字段**                       | **类型** | **是否必须** | **说明** |
|------------------------------|--------|----------|--------|
| date                         | str    | 是        | 日期     |
| asset_classes                | str    | 是        | 日收益了   |
| &ensp;&ensp;asset_class_name | str    | 是        | 分类名称   |
| &ensp;&ensp;value            | str    | 是        | 资产规模   |

---

### **批量获取产品或产品组资产配置**

```python
rqamsc.get_investment_overview_asset_allocation(
    product_like_ids_or_names: Union[List[str], str], start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> Dict
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

数据结构参考如下, 字典第一层 key 为资产大类，下一层 key 为细分类型，值为权重

```python
{
    "现金": {
        "活期存款": 0.044613278988563695
    },
    "股票": {
        "主板": 0.9265354318110066,
        "创业板": 0.02864459520020655
    },
    "期货": {
        "商品期货": 0.010632638580291408
    }
}
```

---

### **批量获取产品或产品组超额收益相关性**

```python
rqamsc.get_investment_overview_excess_correlation(
    product_like_ids_or_names: Union[List[str], str], benchmark_id: str, start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> Dict
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| benchmark_id              | str                   | 是        | 基准合约代码或自定义基准 id           |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

字典结构如下

| **字段层级**                       | **类型** | **是否必须** | **说明**                                |
|--------------------------------|--------|----------|---------------------------------------|
| daily                          | dict   | 否        | 日频相关性矩阵                               |
| &ensp;&ensp;产品名称 A             | dict   | 否        | 产品 A 与其他产品的相关性字典                      |
| &ensp;&ensp;&ensp;&ensp;产品名称 B | float  | 否        | 产品 A 与产品 B 的相关系数 (-1 到 1 之间，对角线为 1.0) |
| weekly                         | dict   | 否        | 周频相关性矩阵（字段结构与 daily 相同）               |
| monthly                        | dict   | 否        | 月频相关性矩阵（字段结构与 daily 相同）               |

- 返回示例

```python
{
    "daily": {
        "测试产品A": {
            "测试产品A": 1.0,
            "测试产品B": 0.7234,
        },
        "测试产品B": {
            "测试产品A": 0.7234,
            "测试产品B": 1.0,
        },
    },
    "weekly": {
        "测试产品A": {
            "测试产品A": 1.0,
            "测试产品B": 0.7156,
        },
        "测试产品B": {
            "测试产品A": 0.7156,
            "测试产品B": 1.0,
        },
    },
    "monthly": {
        "测试产品A": {
            "测试产品A": 1.0,
            "测试产品B": 0.7089,
        },
        "测试产品B": {
            "测试产品A": 0.7089,
            "测试产品B": 1.0,
        },
    }
}
```

---

### **批量获取产品或产品组收益相关性**

```python
rqamsc.get_investment_overview_returns_correlation(
    product_like_ids_or_names: Union[List[str], str], start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None, ** kwargs
) -> Dict
```

- 参数

| **参数**                    | **类型**                | **是否必须** | **说明**                    |
|---------------------------|-----------------------|----------|---------------------------|
| product_like_ids_or_names | list[str] or str      | 是        | 产品(组)的名字或 id，单个传字符串，多个传列表 |
| start_date                | int,str,datetime,date | 否        | 分析开始日期，不填默认取三个月前的日期       |
| end_date                  | int,str,datetime,date | 否        | 分析结束日期，不填默认为当天            |

- 返回

字典结构如下

| **字段层级**                       | **类型** | **是否必须** | **说明**                                  |
|--------------------------------|--------|----------|-----------------------------------------|
| daily                          | dict   | 否        | 日频收益相关性矩阵                               |
| &ensp;&ensp;产品名称 A             | dict   | 否        | 产品 A 与其他产品的相关性字典                        |
| &ensp;&ensp;&ensp;&ensp;产品名称 B | float  | 否        | 产品 A 与产品 B 的收益相关系数 (-1 到 1 之间，对角线为 1.0) |
| weekly                         | dict   | 否        | 周频收益相关性矩阵（字段结构与 daily 相同）               |
| monthly                        | dict   | 否        | 月频收益相关性矩阵（字段结构与 daily 相同）               |

- 返回示例

返回结构与超额收益相关性相同，请参考上方 [
_get_investment_overview_excess_correlation_](#批量获取产品或产品组超额收益相关性) 的示例。

---

## 自定义基准管理

### **查看自定义基准列表**

```python
rqamsc.list_customized_benchmarks() -> List[CustomizedBenchmark]

>>> [
    CustomizedBenchmark(
        name='固定数值基准',
        type='fixed_rates',
        workspace_id='60e8048fb79f4103f403940e',
        user_id=347418,
        remarks=None,
        id='61274ea78c06c70572c0e1f0',
        weights=[],
        rates=0.8
    ),
    CustomizedBenchmark(
        name='多时段自定义权重基准',
        type='composite',
        workspace_id='60e8048fb79f4103f403940e',
        user_id=347418,
        remarks=None,
        id='6214506b7abdc4b73a34df73',
        weights=[
            {
                'start_date': datetime.date(2022, 2, 1),
                'weights': [{'order_book_id': '000003.XSHE', 'weight': 1}]
            }
        ],
        rates=0
    )
]

```

- 返回

_List[[CustomizedBenchmark](#自定义基准对象)]_

---

### **创建一个自定义基准**

```python
rqamsc.create_customized_benchmark(customized_benchmark: Union[Dict, CustomizedBenchmark]) -> CustomizedBenchmark
```

- 参数
  customized_benchmark 参数构建可参考 [CustomizedBenchmark](#自定义基准对象)
- 返回

_[CustomizedBenchmark](#自定义基准对象)_

---

### **获取某个自定义基准信息**

```python
rqamsc.get_customized_benchmark(customized_benchmark_id: str) -> CustomizedBenchmark
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**                                |
|-------------------------|--------|----------|---------------------------------------|
| customized_benchmark_id | str    | 是        | 自定义基准的 id, 可通过[_基准列表_](#查看自定义基准列表) 获取 |

- 返回

_[CustomizedBenchmark](#自定义基准对象)_

---

### **更新某个自定义基准信息**

```python
rqamsc.update_customized_benchmark(
    customized_benchmark_id: str, customized_benchmark: Union[Dict, CustomizedBenchmark]
) -> Tuple[Dict, CustomizedBenchmark]
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**                                |
|-------------------------|--------|----------|---------------------------------------|
| customized_benchmark_id | str    | 是        | 自定义基准的 id, 可通过[_基准列表_](#查看自定义基准列表) 获取 |

- 返回

| **字段**   | **类型**                            | **是否必须** | **说明**   |
|----------|-----------------------------------|----------|----------|
| modified | boolean                           | 是        | 是否更新成功   |
|          | _[CustomizedBenchmark](#自定义基准对象)_ | 是        | 修改后的基准对象 |

---

### **删除某个自定义基准**

```python
rqamsc.delete_customized_benchmark(customized_benchmark_id: str) -> Dict
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**                                |
|-------------------------|--------|----------|---------------------------------------|
| customized_benchmark_id | str    | 是        | 自定义基准的 id, 可通过[_基准列表_](#查看自定义基准列表) 获取 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**         |
|--------------|--------|----------|----------------|
| effect_count | int    | 是        | 1 表示成功， 0 表示失败 |

---

## 自定义合约管理

### **查看自定义合约列表**

```python
rqamsc.list_customized_instruments() -> List[CustomInstruments]
```

- 返回

_[CustomInstruments](#自定义合约对象)_

---

### **新增自定义合约_v2**

```python
rqamsc.create_customized_instrument(customized_instrument: Union[CustomInstruments, Dict]) -> Dict
```

- 参数

_[CustomInstruments](#自定义合约对象)_

- 返回

| **字段**            | **类型** | **是否必须** | **说明**      |
|-------------------|--------|----------|-------------|
| customized_ins_id | str    | 是        | 新增自定义合约的 id |

---

### **新增自定义合约_v1**

> ⚠️ **废弃警告**: 此 API 已不推荐使用，将在未来版本中被废弃。推荐使用 [`create_customized_instrument`](#新增自定义合约_v2) API。

```python
rqamsc.add_customized_instrument(customized_instrument: Union[CustomInstruments, Dict]) -> Dict
```

参数和返回值与新接口 `create_customized_instrument` 完全相同，请参考 [新增自定义合约_v2](#新增自定义合约_v2)。

---

### **获取某个自定义合约价格**

```python
rqamsc.get_customized_instrument_price(customized_ins_id: str) -> List[Dict]
```

- 参数

| **参数**            | **类型** | **是否必须** | **说明**    |
|-------------------|--------|----------|-----------|
| customized_ins_id | str    | 是        | 自定义合约的 id |

- 返回

| **字段** | **类型** | **是否必须** | **说明** |
|--------|--------|----------|--------|
| date   | str    | 是        | 日期     |
| value  | int    | 是        | 价格     |

---

### **上传更新某个自定义合约价格**

```python
rqamsc.upload_customized_instrument_price(customized_ins_id: str, file_path: str) -> Dict
```

- 参数

| **参数**            | **类型** | **是否必须** | **说明**                           |
|-------------------|--------|----------|----------------------------------|
| customized_ins_id | str    | 是        | 自定义合约的 id                        |
| file_path         | str    | 是        | 需要上传的价格文件路径（文件格式可参考 web 端中的模板文件） |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**    |
|--------------|--------|----------|-----------|
| effect_count | int    | 是        | 成功导入的价格数量 |

---

### **删除某些自定义合约**

```python
rqamsc.delete_customized_instrument(customized_ins_id_or_list: [str, List[str], ObjectId, List[ObjectId]]) -> Dict
```

- 参数

| **参数**                    | **类型**                                   | **是否必须** | **说明**                |
|---------------------------|------------------------------------------|----------|-----------------------|
| customized_ins_id_or_list | str, ObjectID, list[str], list[ObjectId] | 是        | 自定义合约的 id, 或存有 id 的列表 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**  |
|--------------|--------|----------|---------|
| effect_count | int    | 是        | 成功删除的数量 |

---

## 托管事件管理

### **获取某个产品的托管事件列表**

```python
rqamsc.list_custodian_events(
    product_id_or_name: str, start_date: optional_datetime_like = None, end_date: optional_datetime_like = None,
) -> List[CustodianEvent]
```

- 参数

| **参数**             | **类型** | **是否必须** | **说明**                      |
|--------------------|--------|----------|-----------------------------|
| product_id_or_name | str    | 是        | 产品名称或 id                    |
| start_date         | str    | 否        | 只获取该日期之后的托管事件，若该字段为空则不做范围限制 |
| end_date           | str    | 否        | 只获取该日期之前的托管事件，若该字段为空则不做范围限制 |

- 返回

List[_[CustodianEvent](#托管事件对象)_]

---

### **给某个产品增加托管事件**

```python
rqamsc.insert_custodian_events(
    product_id_or_name: str, custodian_event_or_list: Union[Dict, CustodianEvent, List[Dict], List[CustodianEvent]]
) -> Dict
```

- 参数

| **参数**                  | **类型**                                                        | **是否必须** | **说明**                                                    |
|-------------------------|---------------------------------------------------------------|----------|-----------------------------------------------------------|
| product_id_or_name      | str                                                           | 是        | 产品名称或 id                                                  |
| custodian_event_or_list | Union[Dict, CustodianEvent, List[Dict], List[CustodianEvent]] | 是        | _[托管事件(对象/字典)](#托管事件对象)_ 或 _[托管事件(对象/字典)](#托管事件对象)_ 组成的列表 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**      |
|--------------|--------|----------|-------------|
| effect_count | int    | 是        | 成功导入的托管事件数量 |

- 示例代码可参考 [托管事件相关教程](tutorial-rqamsc.md#托管事件相关教程)

---

### **修改产品下的一个托管事件**

```python
rqamsc.update_custodian_event(
    product_id_or_name: str, custodian_event: Union[Dict, CustodianEvent]
) -> Dict
```

关于 custodian_event 参数数据的构建可以参考 [增加托管事件 api](#给某个产品增加托管事件) 中构建示例

- 参数

| **参数**             | **类型**                      | **是否必须** | **说明**                   |
|--------------------|-----------------------------|----------|--------------------------|
| product_id_or_name | str                         | 是        | 产品名称或 id                 |
| custodian_event    | Union[Dict, CustodianEvent] | 是        | _[托管事件(对象/字典)](#托管事件对象)_ |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**                |
|--------------|--------|----------|-----------------------|
| effect_count | int    | 是        | 是否修改成功(1 表示成功 0 表示失败) |

---

### **删除产品的一些托管事件**

```python
rqamsc.delete_custodian_events(
    product_id_or_name: str, event_id_or_list: Union[ObjectId, str, List[ObjectId], List[str]]
) -> Dict
```

- 参数

| **参数**             | **类型**                                          | **是否必须** | **说明**                             |
|--------------------|-------------------------------------------------|----------|------------------------------------|
| product_id_or_name | str                                             | 是        | 产品名称或 id                           |
| event_id_or_list   | Union[ObjectId, str, List[ObjectId], List[str]] | 是        | 托管事件 id(字符/ObjectId)或托管事件 id 组成的列表 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**      |
|--------------|--------|----------|-------------|
| effect_count | int    | 是        | 成功删除的托管事件数量 |

---

## 份额事件管理

### **获取某个产品的份额事件列表**

```python
rqamsc.list_unit_events(
    product_id_or_name: str, start_date: optional_datetime_like = None, end_date: optional_datetime_like = None, include_auto_units: bool = False
) -> List[UnitEvent]
```

- 参数

| **参数**             | **类型**                | **是否必须** | **说明**                             |
|--------------------|-----------------------|----------|------------------------------------|
| product_id_or_name | str                   | 是        | 产品名称或 id                           |
| start_date         | int,str,datetime,date | 否        | 只获取该日期之后的份额事件，若该字段为空则不做范围限制        |
| end_date           | int,str,datetime,date | 否        | 只获取该日期之前的份额事件，若该字段为空则不做范围限制        |
| include_auto_units | bool                  | 否        | 是否返回自动份额事件，默认为 False（只返回手工录入的份额事件） |

- 返回

List[_[UnitEvent](#份额事件对象)_]

---

### **给某个产品增加份额事件**

```python
rqamsc.insert_unit_events(
    product_id_or_name: str, unit_event_or_list: Union[Dict, UnitEvent, List[Dict], List[UnitEvent]]
) -> Dict
```

- 参数

| **参数**             | **类型**                                              | **是否必须** | **说明**                             |
|--------------------|-----------------------------------------------------|----------|------------------------------------|
| product_id_or_name | str                                                 | 是        | 产品名称或 id                           |
| unit_event_or_list | Union[Dict, UnitEvent, List[Dict], List[UnitEvent]] | 是        | _[份额事件(对象/字典)](#份额事件对象)_ 或 由其组成的列表 |

- 返回

| **字段**       | **类型**    | **是否必须** | **说明**          |
|--------------|-----------|----------|-----------------|
| effect_count | int       | 是        | 成功导入的份额事件数量     |
| err_msg      | List[str] | 否        | 返回失败的的份额事件的报错信息 |

---

### **修改产品下的一个份额事件**

```python
rqamsc.update_unit_event(product_id_or_name: str, unit_event: Union[Dict, UnitEvent]) -> Dict
```

关于 unit_event 参数数据的构建可以参考 [增加份额事件 api](#给某个产品增加份额事件) 中构建示例

- 参数

| **参数**             | **类型**                 | **是否必须** | **说明**                       |
|--------------------|------------------------|----------|------------------------------|
| product_id_or_name | str                    | 是        | 产品名称或 id                     |
| unit_event         | Union[Dict, UnitEvent] | 是        | 若传对象可参考_[份额事件(对象)](#份额事件对象)_ |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**                |
|--------------|--------|----------|-----------------------|
| effect_count | int    | 是        | 是否修改成功(1 表示成功 0 表示失败) |

---

### **删除产品的一些份额事件**

```python
rqamsc.delete_unit_events(
    product_id_or_name: str, event_id_or_list: Union[ObjectId, str, List[ObjectId], List[str]]
) -> Dict
```

- 参数

| **参数**             | **类型**                                          | **是否必须** | **说明**                             |
|--------------------|-------------------------------------------------|----------|------------------------------------|
| product_id_or_name | str                                             | 是        | 产品名称或 id                           |
| event_id_or_list   | Union[ObjectId, str, List[ObjectId], List[str]] | 是        | 托管事件 id(字符/ObjectId)或托管事件 id 组成的列表 |

- 返回

| **字段**       | **类型** | **是否必须** | **说明**      |
|--------------|--------|----------|-------------|
| effect_count | int    | 是        | 成功删除的份额事件数量 |

---

## 自定义指标管理

### **获取产品或产品组下的自定义指标**

```python
rqamsc.get_customized_indicators(product_like_id_or_name: str) -> Dict
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**        |
|-------------------------|--------|----------|---------------|
| product_like_id_or_name | str    | 是        | 产品(组)的 id 或名称 |

- 返回字典结构如下

| **字段**                                                     | **类型**          | **是否必须** | **说明**                     |
|------------------------------------------------------------|-----------------|----------|----------------------------|
| risk_monitor                                               | dict            | 是        | 对应实时监控页面下的指标               |
| &nbsp;&nbsp;&nbsp;&nbsp;realtime_customized_indicators     | list[dict]      | 否        | 如果有该指标，会在实时收益率曲线右侧另开一片区域展示 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;key        | str             | 是        | 指标名称                       |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;value      | str, int, float | 是        | 指标值                        |
| &nbsp;&nbsp;&nbsp;&nbsp;history_indicators                 | list[dict]      | 否        | 对应历史净值曲线中展示的指标             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;key        | str             | 是        | 指标名称                       |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;value      | str, int, float | 是        | 指标值                        |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;start_date | str             | 是        | 开始日期                       |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;end_date   | str             | 是        | 结束日期                       |

具体可参考如下格式

```python
{
    "risk_monitor": {  # 对应实时监控页面下的指标
        "realtime_customized_indicators": [  # 对应实时收益率曲线上方指标
            {
                "key": "对冲比例",  # 指标名称
                "value": 0.95  # 指标值
            },
            {
                "key": "策略类型",
                "value": "多空对冲"
            }
        ],
        "history_indicators": [  # 对应历史净值曲线中展示的指标
            {
                "key": "策略类型",
                "value": "多空杠杆",
                "start_date": "2024-01-01",  # 开始日期
                "end_date": "2024-04-30"  # 结束日期
            },
            {
                "key": "策略类型",
                "value": "多空",
                "start_date": "2024-05-01",
                "end_date": "2024-12-10"
            }
        ]
    }
}
```

---

### **创建或修改产品或产品组下的自定义指标**

```python
rqamsc.upsert_customized_indicators(product_like_id_or_name: str, customized_indicators: Dict) -> Dict
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**                                   |
|-------------------------|--------|----------|------------------------------------------|
| product_like_id_or_name | str    | 是        | 产品(组)的 id 或名称                            |
| customized_indicators   | dict   | 是        | 可参考[_获取自定义指标_](#获取产品或产品组下的自定义指标) 接口中数据格式 <br>  注意：需要将所有指标上传，即修改和未修改指标都要上传|

- 返回字典结构如下

| **字段**       | **类型** | **是否必须** | **说明**        |
|--------------|--------|----------|---------------|
| effect_count | int    | 是        | 1 表示成功，0 表示失败 |

---

### **创建产品或产品组下的自定义指标**

```python
rqamsc.insert_customized_indicators(product_like_id_or_name: str, customized_indicators: Dict) -> Dict
```
可参考 [_创建或修改产品或产品组下的自定义指标_](#创建或修改产品或产品组下的自定义指标)

---

### **修改产品或产品组下的自定义指标**

```python
rqamsc.update_customized_indicators(product_like_id_or_name: str, customized_indicators: Dict) -> Dict
```
可参考 [_创建或修改产品或产品组下的自定义指标_](#创建或修改产品或产品组下的自定义指标)

---

### **删除产品或产品组下的自定义指标**

```python
rqamsc.delete_customized_indicators(product_like_id_or_name: str) -> Dict
```

- 参数

| **参数**                  | **类型** | **是否必须** | **说明**        |
|-------------------------|--------|----------|---------------|
| product_like_id_or_name | str    | 是        | 产品(组)的 id 或名称 |

- 返回字典结构如下

| **字段**       | **类型** | **是否必须** | **说明**        |
|--------------|--------|----------|---------------|
| effect_count | int    | 是        | 1 表示成功，0 表示失败 |

---

## 交易分析

### 获取产品或产品组交易分析列表

```python
rqamsc.get_trading_analysis_list(
    product_like_id_or_name: str,
start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None,
) -> List[Dict]
```

- 参数

| **参数**                  | **类型**                | **是否必须** | **说明**                   |
|-------------------------|-----------------------|----------|--------------------------|
| product_like_id_or_name | str                   | 是        | 产品(组)的 id 或名称            |
| start_date              | int,str,datetime,date | 否        | 开始日期(如果不传则为产品/产品组的交易起始日) |
| end_date                | int,str,datetime,date | 否        | 结束日期(如果不传则为今天)           |

- 返回

区间交易分析结果列表，每个元素包含以下字段：

| **字段**         | **类型**                 | **是否必须** | **说明** |
|----------------|------------------------|----------|--------|
| date           | str                    | 是        | 日期     |
| order_book_id  | str                    | 是        | 资产代码   |
| asset_category | str                    | 是        | 资产类型   |
| symbol         | str                    | 是        | 资产名称   |
| asset_class    | _[asset_class](#资产类型)_ | 是        | 资产类别   |
| direction      | _[direction](#持仓方向)_   | 是        | 交易方向   |
| period_pnl     | float                  | 是        | 区间盈亏   |

---

### 获取单个交易分析

```python
rqamsc.get_single_trading_analysis(
    product_like_id_or_name: str,
order_book_id: str,
asset_class: str,
direction: Direction,
start_date: optional_datetime_like = None,
end_date: optional_datetime_like = None,
) -> Dict
```

- 参数

| **参数**                  | **类型**                 | **是否必须** | **说明**                   |
|-------------------------|------------------------|----------|--------------------------|
| product_like_id_or_name | str                    | 是        | 产品(组)的 id 或名称            |
| order_book_id           | str                    | 是        | 合约 ID                    |
| asset_class             | _[asset_class](#资产类型)_ | 是        | 资产类别                     |
| direction               | _[direction](#持仓方向)_   | 是        | 交易方向                     |
| start_date              | int,str,datetime,date  | 否        | 开始日期(如果不传则为产品/产品组的交易起始日) |
| end_date                | int,str,datetime,date  | 否        | 结束日期(如果不传则为今天)           |

- 返回字典结构如下：

| **字段**                     | **子字段**   | **类型**     | **是否必须** | **说明**  |
|----------------------------|-----------|------------|----------|---------|
| prev_adjusted_price_series |           | list[dict] | 是        | 价格前复权序列 |
|                            | date      | str        | 是        | 日期      |
|                            | price     | float      | 是        | 复权价格    |
| position_quantity_series   |           | list[dict] | 是        | 持仓数量序列  |
|                            | date      | str        | 是        | 日期      |
|                            | quantity  | float      | 是        | 持仓数量    |
| pnl_series                 |           | list[dict] | 是        | 盈亏序列    |
|                            | date      | str        | 是        | 日期      |
|                            | pnl       | float      | 是        | 累计盈亏    |
|                            | daily_pnl | float      | 是        | 当日盈亏    |
| buy_points                 |           | list[str]  | 是        | 买入时点列表  |
| sell_points                |           | list[str]  | 是        | 卖出时点列表  |

---

- 使用说明及示例：

  `get_single_trading_analysis` 的参数 `order_book_id`、`asset_class`、`direction` 可以直接从 `get_trading_analysis_list`
  的返回结果中获取。

  **注意：传入的 `order_book_id`、`asset_class`、`direction` 必须在对应产品/产品组的持仓中存在，否则无法返回正确的信息。**

```python
# 先获取交易分析列表
analysis_list = rqamsc.get_trading_analysis_list(
    product_like_id_or_name="产品名称或ID", start_date="2023-01-01", end_date="2023-12-31"
)

# 假设我们取第一个分析结果
item = analysis_list[0]

# 提取参数
order_book_id = item["order_book_id"]
asset_class = item["asset_class"]
direction = item["direction"]

# 获取单个交易分析
single_analysis = rqamsc.get_single_trading_analysis(
    product_like_id_or_name="产品名称或ID",
    order_book_id=order_book_id,
    asset_class=asset_class,
    direction=direction,
    start_date="2023-01-01",
    end_date="2023-12-31"
)

print(single_analysis)
```

---

## 一些字段的取值参考

### 交易属性

| **交易属性取值**           | **交易属性描述** | **该交易属性代码可能的米筐标准后缀**                       |
|----------------------|------------|--------------------------------------------|
| stock                | 股票         | ['.XSHG'(上交所), '.XSHE'(深交所), '.XHKG'(港股通)] |
| futures              | 期货         |                                            |
| bond                 | 债券         | ['.SH'(上交所), '.SZ'(深交所), '.IB'(银行间)]       |
| option               | 期权         |                                            |
| convertible          | 可转债        | ['.XSHG'(上交所), '.XSHE'(深交所)]               |
| repo                 | 回购         | ['.XSHG'(上交所), '.XSHE'(深交所)]               |
| fund                 | 基金         | ['.XSHG'(上交所), '.XSHE'(深交所)]               |
| total_return_swap    | 收益互换       |                                            |
| interest_return_swap | 利率互换       |                                            |
| cash                 | 现金         | order_book_id 为'CNY'                       |

---

## 一些关键的类

### 工作空间对象

```python
from rqamsc import WorkSpace
```

| **字段**      | **类型**      | **说明**     |
|-------------|-------------|------------|
| id          | str         | 工作空间 id    |
| name        | str         | 工作空间名称     |
| admin       | str         | 工作空间管理员 id |
| capacity    | str         | 工作空间人数上限   |
| ctime       | str         | 工作空间创建时间   |
| description | str         | 工作空间描述     |
| users       | str or list | 工作空间的成员列表  |

---

### 产品对象

```python
from rqamsc import Product
```

该对象的构建和使用如下示例

```python
import datetime

from bson import ObjectId

from rqamsc import Product, ValuationSettings, ETFValuationAccordingField, ExchangeRateSettings, ExchangeRateType

product_doc = {
    "_id": ObjectId("6177c9ea528f3ac1ce662abb"),
    "name": "300估值因子增强_347418",
    "data_source": "trade_and_valuation_report",
    "start_date": datetime.datetime(2019, 1, 3),
    "trading_start_date": datetime.datetime(2019, 1, 3),
    "investment_category": "equity",
    "strategy_category": "index_enhanced",
    "realtime_period_type": "daytime",
    "benchmark": {
        "type": "index",
        "id": "000300.XSHG"
    },
    "calendar": "exchange",
    "accounts": [
        {
            "name": "300估值因子增强_托管账户",
            "is_custodian": True,
            "account_number": "3eb0b699-7ca8-481a-883a-25ff81ea8ad0",
            "broker": "ricequant"
        },
        {
            "name": "300估值因子增强_交易账户",
            "is_custodian": False,
            "account_number": "8e6827c0-3bdf-4c17-b7fb-e643af1cb6da",
            "broker": "ricequant"
        }
    ],
    "fee_settings": {},
    "user_id": 12345,
    "workspace_id": ObjectId("5f19620f7e8e904a613f5482"),
    "auto_equity": True,
    "unit_policy": "auto_prev_unit_net_value",
    "full_name": "300估值因子增强_347418_全名",
    "create_time": datetime.datetime(2021, 10, 26),
    "fund_code": "",
    "manager": "",
    "invest_advisor": "",
    "invest_manager": "",
    "maturity_date": datetime.datetime(2999, 12, 31),
    "label": "paper",
    "valuation_settings": ValuationSettings(etf=ETFValuationAccordingField.iopv),
    "exchange_rate_settings": ExchangeRateSettings(HKD=ExchangeRateType.sh)
}

# 使用 from_doc 方法将dict数据转化为产品对象
product = Product.from_doc(product_doc)
# 即可调用对象属性
product_id = product.id  # ObjectId("6177c9ea528f3ac1ce662abb")    note: _id被转换为id
trading_start_date = product.trading_start_date  # datetime.datetime(2019, 1, 3)

# 产品对象也可以使用 to_dict 方法转化为字典
product.to_dict()  # 输出结果即与product_doc一致    note: 对象中的id字段在字典中key仍为id

```

| **字段**                 | **子字段**               | **类型**                                   | **是否必须** | **说明**                                                                                                                                                                                                                                                                                                         |
|------------------------|-----------------------|------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| id                     |                       | str                                      | 是        | 产品 id(不可修改)                                                                                                                                                                                                                                                                                                    |
| user_id                |                       | str                                      | 是        | 创建者 id(不可修改)                                                                                                                                                                                                                                                                                                   |
| workspace_id           |                       | str                                      | 是        | 所属 workspace id(不可修改)                                                                                                                                                                                                                                                                                          |
| name                   |                       | str                                      | 是        | 产品名称                                                                                                                                                                                                                                                                                                           |
| full_name              |                       | str                                      | 是        | 产品全名                                                                                                                                                                                                                                                                                                           |
| report_name            |                       | str                                      | 是        | 产品报告名称，主要用于对外。 如导出周度报告时报告名称会以该名称命名                                                                                                                                                                                                                                                                             |
| start_date             |                       | datetime,date                            | 是        | 产品开始日期                                                                                                                                                                                                                                                                                                         |
| trading_start_date     |                       | datetime,date                            | 是        | 产品开始交易日期                                                                                                                                                                                                                                                                                                       |
| data_source            |                       | str                                      | 是        | 产品数据来源(不可修改)：<br> 1. 交易流水及估值表类型产品(trade_and_valuation_report) <br> 2. 交易流水型产品(trade) <br> 3. 估值表类型产品(valuation_report)                                                                                                                                                                                         |
| benchmark              |                       | dict                                     | 是        | 产品基准                                                                                                                                                                                                                                                                                                           |
|                        | type                  | str                                      | 是        | 基准类型:<br/> 1. index(目前仅支持沪深 300、中证 500 以及中证 1000) <br/> 2. customized_index 为[自定义基准](#自定义基准对象)                                                                                                                                                                                                                 |
|                        | id                    | str                                      | 是        | index 的基准代码 或 自定义基准的 id                                                                                                                                                                                                                                                                                        |
| calendar               |                       | str                                      | 是        | 产品日历：<br> 1. 交易所日历(exchange) <br> 2. 银行间交易日历(interbank) <br> 3. 自然日(natural)                                                                                                                                                                                                                                   |
| auto_equity            |                       | bool                                     | 是        | 是否自动权益                                                                                                                                                                                                                                                                                                         |
| unit_policy            |                       | str                                      | 是        | 份额管理方式：<br> 1. 自动份额管理(auto_prev_unit_net_value) <br> 2. 手动份额管理(manual)                                                                                                                                                                                                                                         |
| accounts               |                       | List[dict], List[ProductAccount]         | 是        | 账户信息                                                                                                                                                                                                                                                                                                           |
|                        | account_number        | str                                      | 是        | 资金账号                                                                                                                                                                                                                                                                                                           |
|                        | name                  | str                                      | 是        | 账户名称                                                                                                                                                                                                                                                                                                           |
|                        | broker                | str                                      | 是        | 账户通道                                                                                                                                                                                                                                                                                                           |
|                        | is_custodian          | bool                                     | 是        | 是否是托管账户                                                                                                                                                                                                                                                                                                        |
| fee_settings           |                       | dict, ProductFeeSettings                 | 是        | 费用信息                                                                                                                                                                                                                                                                                                           |
|                        | management_fee        | float                                    | 是        | 管理费                                                                                                                                                                                                                                                                                                            |
|                        | custodian_fee         | float                                    | 是        | 托管费                                                                                                                                                                                                                                                                                                            |
|                        | sales_and_service_fee | float                                    | 是        | 销售服务费                                                                                                                                                                                                                                                                                                          |
|                        | operation_fee         | float                                    | 是        | 运营费                                                                                                                                                                                                                                                                                                            |
|                        | performance_pay       | float                                    | 是        | 业绩报酬                                                                                                                                                                                                                                                                                                           |
| realtime_period_type   |                       | str, RealtimePeriodType                  | 是        | 实时估值类型:<br/> 1. daytime: 仅白天 09:30 - 15:00 <br/> 2. natural: 自然日 09:00 - 02:30 (+1) <br/> 3. valuation_day: 估值表日 21:00 - 15:00 (+1)                                                                                                                                                                            |
| create_time            |                       | datetime, str                            | 是        | 创建时间                                                                                                                                                                                                                                                                                                           |
| label                  |                       | str, ProductLabel                        | 是        | 产品标签，默认 paper：<br/> 1. live: 实盘 <br/> 2. paper: 模拟 <br/> 3. paper_trading: 模拟交易                                                                                                                                                                                                                              |
| investment_category    |                       | str, ProductInvestmentCategory           | 是        | 投资类型                                                                                                                                                                                                                                                                                                           |
| strategy_category      |                       | str, StrategyCategory                    | 是        | 策略类型:<br/> 1. index_enhanced: 指数增强 <br/> 2. equity_market_neutral: 市场中性 <br/> 3. stock_long: 股票多头 <br/> 4. commodity_trading_advisor: CTA <br/> 5. mixed: 混合策略 <br/> 6. long_short_stock: 股票多空 <br/> 7. stock_leverage_neutral: 股票杠杆中性 <br> 8. stock_leverage_long_short: 股票杠杆多空 <br> 9. unconventionality: 其他 |
| valuation_settings     |                       | dict, ValuationSettings                  | 否        | 设置资产估值方式                                                                                                                                                                                                                                                                                                       |
|                        | etf                   | str, ETFValuationAccordingField          | 否        | ETF 基金估值设置:<br/> 1. close: 收盘价 </br > 2. iopv: 当日净值                                                                                                                                                                                                                                                            |
|                        | fut_opt               | str, FutOptValuationAccordingField       | 否        | 期货期权估值设置:<br/> 1. close: 收盘价 </br > 2. settlement: 结算价                                                                                                                                                                                                                                                         |
|                        | acc_net_value         | str, AccUnitValueValuationAccordingField | 否        | 累计净值估值设置:<br/> 1. acc_unit_dividend: T 日单位净值+产品起始日至今累计单位份额分红 </br > 2. last_unit_net_value: T-1 日累计净值+T 日单位净值-T-1 日单位净值+T 日产品单位份额分红                                                                                                                                                                            |
| exchange_rate_settings |                       | dict, ExchangeRateSettings               | 否        | 设置估值汇率                                                                                                                                                                                                                                                                                                         |
|                        | HKD                   | str, ExchangeRateType                    | 否        | 港股通汇率设置:<br/> 1. sh: 沪港通中间价 <br/> 2. sz: 深港通中间价                                                                                                                                                                                                                                                                |
| fund_code              |                       | str                                      | 否        | 基金代码                                                                                                                                                                                                                                                                                                           |
| manager                |                       | str                                      | 否        | 管理人                                                                                                                                                                                                                                                                                                            |
| invest_advisor         |                       | str                                      | 否        | 投资顾问                                                                                                                                                                                                                                                                                                           |
| invest_manager         |                       | str                                      | 否        | 投资经理                                                                                                                                                                                                                                                                                                           |
| maturity_date          |                       | date, str, none                          | 否        | 产品到日期                                                                                                                                                                                                                                                                                                          |
| closing_date           |                       | date, str, none                          | 否        | 封账日                                                                                                                                                                                                                                                                                                            |
| description            |                       | str                                      | 否        | 产品描述                                                                                                                                                                                                                                                                                                           |

---

### 产品组对象

```python
from rqamsc import ProductGroup
```

| **字段**              | **子字段** | **类型**                               | **返回时是否必须** | **说明**                                                                                         |
|---------------------|---------|--------------------------------------|-------------|------------------------------------------------------------------------------------------------|
| id                  |         | str                                  | 是           | 产品组 id(不可修改)                                                                                   |
| name                |         | str                                  | 是           | 产品组名称                                                                                          |
| report_name         |         | str                                  | 是           | 产品组报告名称，主要用于对外。 如导出周度报告时报告名称会以该名称命名                                                            |
| products            |         | List[dict]                           | 是           | 各个产品成分:<br/> 1. id: 产品 id <br/> 2. name: 产品名称                                                  |
| product_weights     |         | dict                                 | 否           | 各个产品成分权重(key 为产品 id, value 为权重值)<br/>1. 若该字段存在时，产品组为权重产品组 <br/>2. 若不存在该字段，产品组为聚合产品组            |
| benchmark           |         | dict                                 | 是           | 产品组基准                                                                                          |
|                     | type    | str                                  | 是           | 基准类型:<br/> 1. index(目前仅支持沪深 300、中证 500 以及中证 1000) <br/> 2. customized_index 为[自定义基准](#自定义基准对象) |
|                     | id      | str                                  | 是           | index 的基准代码 或 自定义基准的 id                                                                        |
| label               |         | str, ProductLabel                    | 是           | 产品标签，默认 paper：<br/> 1. live: 实盘 <br/> 2. paper: 模拟 <br/> 3. ~~paper_trading: 模拟交易~~（产品组暂不支持） |
| start_date          |         | str                                  | 是           | 估值起始日 <br> 聚合型产品组：取子产品中最早的产品起始日 <br> 权重型产品组: 取所有子产品头寸中都有单位净值的最早日期                              |
| trading_start_date  |         | str                                  | 是           | 交易起始日，不能小于产品组的估值起始日                                                                            |
| strategy_category   |         | List[str, ProductInvestmentCategory] | 是           | 策略类型列表(子产品策略类型的集合)                                                                             |
| accessible_err_msg  |         | List[str]                            | 否           | 若产品组状态异常将在该字段中展示                                                                               |
| create_time         |         | str                                  | 是           | 创建时间                                                                                           |
| rebalance_frequency |         | str                                  | 否           | 再平衡频率，当产品组为权重产品组时必传，为聚合产品组时不传                                                                  |
| description         |         | str                                  | 否           | 产品描述                                                                                           |

---

### 估值表对象

```python
from rqamsc import ValuationReportBalance
```

| **字段**             | **子字段**                    | **类型**                        | **是否必须** | **说明**                          |
|--------------------|----------------------------|-------------------------------|----------|---------------------------------|
| date               |                            | str                           | 是        | 持仓单日期                           |
| total_equity       |                            | float                         | 是        | 净资产                             |
| units              |                            | float                         | 是        | 份额                              |
| unit_net_value     |                            | float                         | 是        | 单位净值                            |
| acc_unit_net_value |                            | float                         | 否        | 单位累计净值                          |
| positions          |                            | List[ValuationReportPosition] | 是        | 持仓详情                            |
|                    | _[asset_class](#资产类型)_     | str                           | 是        | 资产类型                            |
|                    | _[direction](#持仓方向)_       | str                           | 是        | 持仓方向                            |
|                    | order_book_id              | str                           | 是        | 资产代码                            |
|                    | symbol                     | str                           | 是        | 资产名称                            |
|                    | market_value               | float                         | 是        | 持仓市值                            |
|                    | quantity                   | float                         | 否        | 持仓数量([_现金类资产_](#资产类型) 可不填，其余必填) |
|                    | cost_price                 | float                         | 否        | 单位成本([_现金类资产_](#资产类型) 可不填，其余必填) |
|                    | cost                       | float                         | 否        | 成本                              |
|                    | fair_value                 | float                         | 否        | 公允价格                            |
|                    | accrued_interest           | float                         | 否        | 应记利息                            |
|                    | sterilisation_market_value | float                         | 否        | 冲销市值(期货类资产必填)                   |

### 交易流水对象

```python
from rqamsc import Trade
```

| **参数**                         | **类型**            | **上传时字段是否必须** | **获取时字段是否会返回** | **说明**                                                                                             |
|--------------------------------|-------------------|---------------|----------------|----------------------------------------------------------------------------------------------------|
| _[trading_asset_class](#交易属性)_ | str               | 否             | 否              | 交易属性, 提供可以提高识别精准度(绝大部分情况可不提供)                                                                      |
| _[asset_class](#资产类型)_         | str               | 否             | 是              | 资产类型                                                                                               |
| _[transaction_type](#交易类型)_    | str               | 是             | 是              | 交易类型                                                                                               |
| account                        | str               | 否             | 是              | 交易账户名称，不提供则默认第一个产品账户                                                                               |
| datetime                       | str,datetime,date | 是             | 是              | 交易时间                                                                                               |
| trading_date                   | str,datetime,date | 否             | 是              | 交易日期                                                                                               |
| order_book_id                  | str               | 是             | 是              | 合约 id，[_现金类资产_](#资产类型) 传“CNY”                                                                      |
| symbol                         | str               | 是             | 是              | 合约名称                                                                                               |
| quantity                       | float             | 否             | 是              | 交易数量([_现金类资产_](#资产类型) 可不填，其余必填)                                                                    |
| price                          | float             | 否             | 是              | 交易价格<br> • 回购类所传价格表示利率，如文件中为 1.2 表示利率为 1.2%，可直接传小数 1.2， 也可以传 0.012<br> • [_现金类资产_](#资产类型) 可不填，其余必填 |
| settlement_amount              | float             | 否             | 是              | 交易金额(涉及金额的交易类型需要设置该字段，eg. 分红、转债回售、付息、出入金、现金存取、基金申购金额等，具体哪些交易类型需要该字段可参考[交易类型枚举文档](#交易类型))           |
| commission                     | float             | 否             | 是              | 交易佣金                                                                                               |
| tax                            | float             | 否             | 是              | 交易税                                                                                                |
| other_fees                     | float             | 否             | 是              | 其他费用                                                                                               |
| exchange_rate                  | float             | 否             | 是              | 汇率，不指定时默认使用官方汇率参估值                                                                                 |
| remarks                        | str               | 否             | 是              | 备注                                                                                                 |
| [_source_](#交易流水来源)            | str               | 否             | 是              | 流水来源                                                                                               |
| foreign_id                     | str               | 否             | 是              | 外部标识 id                                                                                            |
| asset_unit_id                  | str               | 否             | 是              | 资产单元 id                                                                                            |
| \_id                           | str               | 否             | 是              | AMS 系统内流水的唯一 id                                                                                    |

### 交易流水来源

```python
from rqamsc import TradeSource
```

| **流水来源取值**             | **流水来源描述**                                                                                                                                                                                                                                                                                  |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| manual                 | 手工录入                                                                                                                                                                                                                                                                                        |
| settlement_upload      | 日终结算流水文件导入<br/> 1. 上传流水时会删除同账号相同日期下已有的 日终结算流水、日内流水及 open_api 流水，并采用最新上传的流水覆盖                                                                                                                                                                                                                |
| intraday_upload        | 日内流水文件导入<br/> 1. 上传流水时会删除同账号相同日期下已有的 日内流水及 open_api 流水，并采用最新上传的流水覆盖 <br/> 2. 如果同账号相同日期下已有日终结算流水则不能上传日内流水                                                                                                                                                                                    |
| open_api               | 通常是 rqamsc 导入的流水<br/> 1. 每次上传流水都视为新增，若流水附带 foreign_id 字段则对相同 foreign_id 的流水覆盖 <br/> 2. 如果同账号相同日期下已有日终结算流水则不能上传 openapi 流水 <br/> 3. 流水列表可以传入历史的流水, 但该历史流水导入行为依旧符合上述 1 和 2 两条规则 <br/> 4. 若流水列表中都为当日流水，尽量导入最新的流水，如上一批流水最晚的时间是9:45,则本次导入9:50~10:00的流水会更快的获取估值结果，但如果本次导入包含 9:40 的流水，可能无法迅速得到估值结果 |
| auto_balance           | 自动权益下自动生成的流水                                                                                                                                                                                                                                                                                |
| netting_derived_shadow | 估值表覆盖 AMS 头寸后，根据前后持仓倒推的流水                                                                                                                                                                                                                                                                   |

---

### 资产类型

```python
from rqamsc import AssetClass
```

| **资产类型取值**                     | **资产类型描述**   |
|--------------------------------|--------------|
| stock                          | 股票           |
| convertible_bond               | 可转债          |
| bond                           | 债券           |
| repo                           | 正回购          |
| repo_accrued_interest          | 回购应计利息(现金类)  |
| reverse_repo                   | 逆回购          |
| reverse_repo_accrued_interest  | 逆回购应计利息(现金类) |
| closed_end_fund                | 封闭式基金        |
| open_end_fund                  | 开放式基金        |
| etf_fund                       | ETF 基金       |
| lof_fund                       | LOF 基金       |
| reits                          | REITS 基金     |
| money_market_fund              | 货币基金         |
| other_fund                     | 其他基金         |
| commodity_futures              | 商品期货         |
| commodity_option               | 商品期权         |
| stock_index_futures            | 股指期货         |
| stock_index_option             | 股指期权         |
| interest_rate_futures          | 利率期货         |
| otc_futures                    | 场外期货         |
| otc_option                     | 场外期权         |
| total_return_swap              | 收益互换         |
| interest_return_swap           | 利率互换         |
| other_derivatives              | 其他衍生品        |
| current_deposit                | 活期存款(现金类)    |
| asset_unit                     | 资产单元         |
| reservation_deposit            | 结算备付金(现金类)   |
| refundable_deposit             | 存出保证金(现金类)   |
| securities_settlement_accounts | 证券清算款(现金类)   |
| dividend_receivable            | 应收股利(现金类)    |
| other_interest_receivable      | 其他应收利息(现金类)  |
| subscription_receivable        | 应收申购款(现金类)   |
| other_receivable               | 其他应收款(现金类)   |
| other_asset                    | 其他资产(现金类)    |
| cash_debt                      | 现金类负债(现金类)   |
| other_interest_payable         | 其他应付利息(现金类)  |
| management_fee_payable         | 计提管理费(现金类)   |
| sales_and_service_fee_payable  | 计提销售服务费(现金类) |
| custodian_fee_payable          | 计提托管费(现金类)   |
| performance_pay_payable        | 计提业绩报酬(现金类)  |
| operation_fee_payable          | 计提运营费(现金类)   |
| tax_payable                    | 应付税(现金类)     |
| other_payable                  | 其他应付款(现金类)   |
| other_liability                | 其他负债(现金类)    |

---

### 交易类型

```python
from rqamsc import TransactionType
```

| **交易类型取值**                        | **交易类型描述** | **需要 settlement_amount(结算金额)字段** | **备注**                                  |
|-----------------------------------|------------|----------------------------------|-----------------------------------------|
| buy                               | 买入         |                                  |                                         |
| sell                              | 卖出         |                                  |                                         |
| buy_open                          | 多头开仓       |                                  |                                         |
| sell_close                        | 多头平仓       |                                  |                                         |
| sell_open                         | 空头开仓       |                                  |                                         |
| buy_close                         | 空头平仓       |                                  |                                         |
| subscribe                         | 申购         |                                  |                                         |
| redeem                            | 赎回         |                                  |                                         |
| transfer_in                       | 划入         |                                  | 持仓成本不变，数量增加                             |
| transfer_out                      | 划出         |                                  | 持仓成本不变，数量减少                             |
| custodian_transfer_in             | 托管划入       |                                  | 和开仓类流水效果一致                              |
| custodian_short_transfer_in       | 托管空头划入     |                                  | 和开仓类流水效果一致                              |
| custodian_transfer_out            | 托管划出       |                                  | 和平仓类流水效果一致                              |
| custodian_short_transfer_out      | 托管空头划出     |                                  | 和平仓类流水效果一致                              |
| etf_subscription_transfer_in      | ETF 申购划入   |                                  | ETF 0 元开仓，应该和 ETF 申购划出成对出现（即有一篮子股票对应平仓） |
| etf_redeem_transfer_out           | ETF 赎回划出   |                                  | ETF 0 元平仓，应该和 ETF 赎回划入成对出现（即有一篮子股票对应开仓） |
| etf_subscription_transfer_out     | ETF 申购划出   |                                  | 股票 0 元平仓                                |
| etf_redeem_transfer_in            | ETF 赎回划入   |                                  | 股票 0 元开仓                                |
| etf_cash_replacement_transfer_in  | ETF 现金替代划入 | ✓                                |                                         |
| etf_cash_replacement_transfer_out | ETF 现金替代划出 | ✓                                |                                         |
| etf_cash_difference_transfer_in   | ETF 现金差额划入 | ✓                                |                                         |
| etf_cash_difference_transfer_out  | ETF 现金差额划出 | ✓                                |                                         |
| withdraw                          | 活期存款取出     | ✓                                | 不会影响份额                                  |
| deposit                           | 活期存款存入     | ✓                                | 不会影响份额                                  |
| loan                              | 活期存款借入     | ✓                                |                                         |
| loan_repayment                    | 活期存款借款归还   | ✓                                |                                         |
| cash_in                           | 入金         | ✓                                | 若产品设置"自动份额管理", 同时会调整份额                  |
| cash_out                          | 出金         | ✓                                | 若产品设置"自动份额管理", 同时会调整份额                  |
| interest_income                   | 利息收入       | ✓                                |                                         |
| interest_payment                  | 利息支出       | ✓                                |                                         |
| interest_tax_payment              | 利息税支出      | ✓                                |                                         |
| hkt_portfolio_fee_payment         | 港股通组合费支出   | ✓                                |                                         |
| covered_sell_open                 | 备兑空头开仓     |                                  |                                         |
| covered_buy_close                 | 备兑空头平仓     |                                  |                                         |
| holder_match                      | 多头对冲轧平     |                                  |                                         |
| seller_match                      | 空头对冲轧平     |                                  |                                         |
| ipo_subscribed                    | 新股申购       |                                  |                                         |
| shares_allotted                   | 新股中签       |                                  |                                         |
| subscription_fund_unfrozen        | 申购款解冻      |                                  |                                         |
| shares_listed                     | 上市流通       |                                  |                                         |
| buy_on_margin                     | 融资买入       |                                  |                                         |
| short_sell                        | 融券卖出       |                                  |                                         |
| sell_to_repay                     | 卖券还款       |                                  |                                         |
| buy_to_return                     | 买券还券       |                                  |                                         |
| return_securities                 | 直接还券       |                                  |                                         |
| cash_repayment                    | 直接还款       | ✓                                |                                         |
| refund_securities                 | 多还退券       |                                  |                                         |
| dividend_payment                  | 红利入账       | ✓                                |                                         |
| dividend_reinvestment             | 红利再投资      |                                  |                                         |
| dividend_tax_payment              | 红利税支付      | ✓                                |                                         |
| bonus_share                       | 红股         |                                  |                                         |
| pre_dividend_payment              | 分红预处理      | ✓                                |                                         |
| pre_bonus_share                   | 送股预处理      |                                  |                                         |
| dividend_on_borrowed              | 借券红利       | ✓                                |                                         |
| bonus_share_on_borrowed           | 借券红股       |                                  |                                         |
| convertible_sell_back             | 可转债回售      | ✓                                |                                         |
| convertible_redemption            | 可转债赎回      | ✓                                |                                         |
| cb_to_stock                       | 转债转股       |                                  | 标的可以是股票或转债                              |
| reverse_repo                      | 逆回购        |                                  |                                         |
| repo                              | 正回购        |                                  |                                         |
| reverse_repo_repurchase           | 逆回购购回      |                                  |                                         |
| repo_repurchase                   | 正回购购回      |                                  |                                         |
| long_deliver                      | 期货多头交割     |                                  |                                         |
| short_deliver                     | 期货空头交割     |                                  |                                         |
| holder_exercise                   | 期权多头行权     |                                  |                                         |
| seller_exercise                   | 期权空头行权     |                                  |                                         |
| holder_expire                     | 期权多头到期     |                                  |                                         |
| seller_expire                     | 期权空头到期     |                                  |                                         |
| coupon_payment                    | 债券付息       | ✓                                |                                         |
| principal_payment                 | 债券偿付本金     | ✓                                |                                         |
| bond_expire                       | 债券到期       |                                  |                                         |

---

### 持仓方向

```python
from rqamsc import Direction
```

| **持仓方向取值** | **持仓方向描述** |
|------------|------------|
| long       | 多头         |
| short      | 空头         |

---

### 业绩归因模板对象

```python
from rqamsc import PATemplate
```

| **字段**    | **类型** | **说明**     |
|-----------|--------|------------|
| BRINSON   | str    | brinson 归因 |
| FACTOR    | str    | 多因子归因      |
| FACTOR_V2 | str    | 多因子归因 V2   |

---

### 自定义基准对象

```python
from rqamsc import CustomizedBenchmark
```

该对象属性构成如下， 具体使用可参考下方代码示例

| **字段**       | **类型**                                           | **是否必须** | **说明**                                      |
|--------------|--------------------------------------------------|----------|---------------------------------------------|
| name         | str                                              | 是        | 自定义基准名称                                     |
| type         | str                                              | 是        | 自定义基准类型, composite(复合指数)，fixed_rates(收益率指数) |
| weights      | List[[CustomizedBenchmarkWeights](#自定义基准成分权重对象)] | 否        | composite(复合指数) 时必须有此字段                     |
| rates        | float                                            | 否        | fixed_rates(收益率指数) 时必须有此字段                  |
| id           | str                                              | 是        | 自定义基准 id, 在创建修改时构建该对象不需要此字段                 |
| user_id      | str                                              | 是        | 创建者 id, 在创建修改时构建该对象不需要此字段                   |
| workspace_id | str                                              | 是        | 所属 workspace id, 在创建修改时构建该对象不需要此字段          |
| remark       | str                                              | 否        | 备注信息                                        |

- 对象初始化方式一

```python
import datetime
from rqamsc import CustomizedBenchmark

customized_benchmark = CustomizedBenchmark(
    name='多时段自定义权重基准',
    type='composite',
    weights=[
        {
            'start_date': datetime.date(2015, 1, 1),
            'weights': [
                {'order_book_id': '000001.XSHE', 'weight': 0.5},
                {'order_book_id': '000002.XSHE', 'weight': 0.5}
            ]
        }
    ]
)
```

- 对象初始化方式二

```python
# 自定义基准对象可调用方法 from_doc & to_dict 示例如下
import datetime
from rqamsc import CustomizedBenchmark

customized_benchmark_doc = {
    "name": "多时段自定义权重基准",
    "type": "composite",
    "weights": [
        {
            "start_date": "2015-01-01",
            "weights": [
                {
                    "order_book_id": "000001.XSHE",
                    "weight": 0.5
                },
                {
                    "order_book_id": "000002.XSHE",
                    "weight": 0.5
                }
            ]
        }
    ]
}
# 使用 from_doc 可将dict数据转换为相应对象
customized_benchmark = CustomizedBenchmark.from_doc(customized_benchmark_doc)  # 该函数执行结果(customized_benchmark)如下
# 输出 customized_benchmark 对象如下
# CustomizedBenchmark(
#     name='多时段自定义权重基准',
#     type='composite',
#     weights=[
#         {
#             'start_date': datetime.date(2015, 1, 1),
#             'weights': [
#                 {'order_book_id': '000001.XSHE', 'weight': 0.5},
#                 {'order_book_id': '000002.XSHE', 'weight': 0.5}
#             ]
#         }
#     ]
# )
```

- 初始化后的对象可直接调用其属性来使用

```python
>>> customized_benchmark.name
'多时段自定义权重基准'
```

- 该对象也可以通过 to_dict 方法转化为字典

```python
>>> customized_benchmark.to_dict()
{
    'name': '多时段自定义权重基准',
    'type': 'composite',
    'workspace_id': None,
    'user_id': None,
    'remarks': None,
    'id': None,
    'weights': [
        {
            'start_date': datetime.date(2015, 1, 1),
            'weights': [
                {'order_book_id': '000001.XSHE', 'weight': 0.5},
                {'order_book_id': '000002.XSHE', 'weight': 0.5}
            ],
            'customized_benchmark_id': None,
            'id': None
        }
    ],
    'rates': 0
}
```

---

### 自定义基准成分权重对象

```python
from rqamsc import CustomizedBenchmarkWeights
```

该对象使用方式可参考 [自定义基准对象](#自定义基准对象)

| **字段**                  | **子字段**       | **类型**     | **是否必须** | **说明**                                                                    |
|-------------------------|---------------|------------|----------|---------------------------------------------------------------------------|
| start_date              |               | str        | 是        | 权重开始生效时，修改权重成分时以 start_date 作为搜索条件修改成分数据，若该 start_date 没有搜索到数据则添加该成分到基准中间 |
| customized_benchmark_id |               | str        | 是        | 自定义基准 id, 在创建修改时构建该对象不需要此字段                                               |
| weights                 |               | List[Dict] | 是        | 自定义基准类型, composite(复合指数)，fixed_rates(收益率指数)                               |
|                         | order_book_id | str        | 是        | 权重成分中资产代码                                                                 |
|                         | weight        | float      | 是        | 权重成分中资产的权重(权重之和要等于 1)                                                     |

---

### 自定义合约对象

```python
from rqamsc import CustomInstruments
```

该对象使用方式可参考 [自定义基准对象](#自定义基准对象)

| **字段**        | **类型** | **是否必须** | **说明**                                                                                                                                                                                                   |
|---------------|--------|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| asset_class   | str    | 是        | 资产类型, 可为如下类型:<br/> 1. 股票(stock) <br/> 2. 期货(otc_futures) <br/> 3. 期权(otc_option) <br/> 4. 基金(other_fund) <br/> 5. 收益互换(total_return_swap) <br/> 6. 债券(bond) <br/> 7. 回购(repo) <br/> 8. 逆回购(reverse_repo) |
| order_book_id | str    | 是        | OTC 合约代码                                                                                                                                                                                                 |
| symbol        | str    | 是        | 合约名称                                                                                                                                                                                                     |
| product_id    | str    | 是        | 归属产品 id                                                                                                                                                                                                  |
| id            | str    | 否        | 自定义合约 id                                                                                                                                                                                                 |

---

### 托管事件对象

```python
from rqamsc import CustodianEvent
```

该对象使用方式可参考 [自定义基准对象](#自定义基准对象)

| **字段**               | **类型** | **是否必须** | **说明**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
|----------------------|--------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| custodian_event_type | str    | 是        | 业务类型，字段枚举：<br> 1. 申购款入账(subscription_fund_received) <br> 2. 赎回款出账(redemption_paid) <br> 3. 产品分红(product_dividend_paid) <br> 4. 产品费用实付(product_cost_paid) <br> 5. 科目调整(subject_adjusted)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| date                 | str    | 是        | 托管事件发生日期                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| amount               | float  | 是        | 托管事件发生金额                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| sr_open_date         | str    | 否        | 申赎开放日，只有业务类型为"申购"、"赎回"时必填，一般情况应为出入账日期上一交易日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| product_cost_type    | str    | 否        | 产品费用类型，只有在业务类型为"产品费用实付"时为必填，字段枚举:<br> 1. 管理费(management_fee) <br> 2. 托管费(custodian_fee) <br> 3. 业绩报酬(performance_pay) <br> 4. 运营费(operation_fee) <br> 5. 销售服务费(sales_and_service_fee)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| adjust_target        | str    | 否        | 科目调整项，只有在业务类型为"科目调整"时为必填，字段枚举:<br> 1.活期存款(current_deposit) <br> 2. 结算备付金(reservation_deposit) <br> 3. 存出保证金(refundable_deposit) <br> 4. 证券清算款(securities_settlement_accounts) <br> 5. 期货清算款(futures_settlement_accounts) <br> 6. 其他应收利息(other_interest_receivable) <br> 7. 应收申购款(subscription_receivable) <br> 8. 其他应收款(other_receivable) <br> 9. 现金类负债(cash_debt) <br> 10. 其他应付利息(other_interest_payable) <br> 11. 计提管理费(management_fee_payable) <br> 12. 计提托管费(custodian_fee_payable) <br> 13. 计提运营费(operation_fee_payable) <br> 14. 计提销售服务费(sales_and_service_fee_payable) <br> 15. 计提业绩报酬(performance_pay_payable) <br> 16. 应付税(tax_payable) <br> 17. 其他应付款(other_payable) <br> 18. 其他类型(other_asset) <br> 19. 其他负债(other_liability) |
| adjust_operation     | str    | 否        | 科目调整方向，只有在业务类型为"科目调整"时为必填，字段枚举:<br> 1. 调增(increase) <br> 2. 调减(decrease) <br> 3. 调整到(adjust_to)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| remarks              | str    | 否        | 可填写该事件的备注信息                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| unit_net_value       | float  | 否        | 申赎单位净值，申赎事件必传，通过该字段指定的净值计算份额变动                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| id                   | str    | 否        | 托管事件的 id                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| product_id           | str    | 否        | 托管事件所属产品 id                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

---

### 份额事件对象

```python
from rqamsc import UnitEvent
```

该对象使用方式可参考 [自定义基准对象](#自定义基准对象)

| **字段**             | **类型**        | **是否必须** | **说明**                                           |
|--------------------|---------------|----------|--------------------------------------------------|
| date               | datetime.date | 是        | 事件日期                                             |
| subscription_units | float         | 否        | 申购份额(与赎回份额必须二选一)                                 |
| redemption_units   | float         | 否        | 赎回份额(与申购份额必须二选一)                                 |
| source             | str           | 否        | 事件来源:<br/> 1. 手工录入(manual) <br/> 2. 系统自动生成(auto) |
| id                 | str           | 否        | 事件 id                                            |
| product_id         | str           | 否        | 事件所属产品 id                                        |

---

### 通用异常对象(exception, 可用于捕获处理对应异常)

```python
from rqamsc.exception import IllegalInput, ForbiddenException, UnauthorizedException
```

| **名称**                | **说明**      |
|-----------------------|-------------|
| IllegalInput          | 表示 API 输入有误 |
| UnauthorizedException | 表示鉴权失败      |
| ForbiddenException    | 表示无权执行该操作   |
