RQData 是一个基于 Python 的金融数据工具包。它为量化工程师们提供了丰富整齐的历史数据以及简单高效的 API 接口，最大限度地免除了您进行数据搜索、清洗的烦恼。这样的数据服务是整个 Ricequant SDK 的基础，取决于您的需求，它可以独立使用而不依赖 Ricequant SDK 的其他组件。

## 关于 RQData 的一些基础知识 {#rqdata-basics}

### 关于架构 {#rqdata-arch}

RQData 的基本架构为客户端——服务端模式，即数据存储在服务端，而客户端向服务端发送数据请求，服务端向客户端返回数据的模式。因此客户端被叫做`rqdatac`，这里`c`代表`client`，即客户端的意思。

### 安装 {#rqdata-install}

Rqdatac 的安装：

```sh
pip install rqdatac
```

若您有 rqdatac_fund 和 rqdatac_news 包,请执行以下代码同时安装 rqdatac 和对应包
仅安装其中一个包，请将[]中名字换成您的包名

```sh
pip install "rqdatac[fund]"
```

同时安装多个包

```sh
pip install "rqdatac[fund,news]"
```

### RQData 初始化 {#rqdata-init}

跟所有的 Python 包一样，如果要使用它，就必须导入它。使用 RQData 只需要在安装了 Ricequant SDK 的虚拟环境中运行 Python 代码，并在调用任何金融数据之前导入一个`rqdatac`的包。

随后调用`rqdatac.init()`来对 RQData 进行初始化。在首次调用 RQData 的任何 API 之前都必须执行该语句，但例外的是如果您在 Ricequant SDK 环境下使用`rqsdk shell`命令调出的 iPython 环境不需要执行`rqdatac.init()`语句，而是`import rqdatac`之后可以直接调用其他 API。

```python
import rqdatac
rqdatac.init()
```

### 查看版本号及登录信息 {#rqdata-info}

就像任何软件一样，RQData 也有它自己的版本号，可以通过下面的 API 检查当前的登录状态版本号：

### rqdatac.info {#rqdata-API-info}

获取用户当前登录版本、服务器信息

#### 返回

rqdatac version: 当前使用的 rqdata 版本号<br/>server address：域名:端口

#### 范例

- 获取用户登录信息

```python
[In]
info()
[Out]
rqdatac version: 2.6.0
sever address: rqdatad-pro.ricequant.com:16011
You are using account: +86186XXXX6610
```

### 流量配额 {#rqdata-quota}

在非本地化部署的情况下，RQData 的每一次调用都需要从服务端拉取对应的数据，这些数据量将会产生流量。米筐为每日可拉取的最高流量做了限制，您可以通过下面的 API 来查看当前的流量使用情况。同时还能查看当前许可证的到期期限和许可证类型。

客户端与服务端之间的传输协议为米筐为数据传输开发的二进制协议，并在传输时对数据进行了压缩，因此传输流量大概在实际数据量的三分之一左右。而米筐的流量配额是按实际传输流量来计算的，因此完全可以满足正常的甚至突发的使用情况。

为避免影响正式的客户，RQData 对于试用账户进行了每天 1G 的配额限制。普通的限额账户在上述的压缩算法下，已经完全满足绝大部分的使用需求了。

如果您对这些信息有任何疑虑，请立即联系我们的技术支持团队。

#### rqdatac.user.get_quota - 获取用户配额信息 {#rqdata-API-user-get_quota}

获取用户当前配额使用信息，目前可以提供的有今日已用流量、今日可用流量上限。

##### 返回

_dict_

| 字段           | 类型  | 说明                                                |
| -------------- | ----- | --------------------------------------------------- |
| bytes_limit    | _int_ | 每日流量使用上限（单位为字节），如为 0 则表示不受限 |
| bytes_used     | _int_ | 当日已用流量（单位为字节）                          |
| remaining_days | _int_ | 剩余期限（单位为天）                                |
| license_type   | _str_ | “TRIAL” 表示试用账户,“FULL” 表示付费用户            |

##### 范例

- 获取用户配额信息

```python
[In]
rqdatac.user.get_quota()

[Out]
{'bytes_limit': 0, 'bytes_used': 954'remaining_days': 16,'license_type': 'TRIAL'}

```

### API 中关于日期的格式支持 {#rqdata-date-format}

RQData 的 API 中设计日期作为参数的非常多，因此对于日期格式的支持也非常丰富。具体支持见下表：

| 格式描述           | 格式示例                       |
| ------------------ | ------------------------------ |
| 数字 YYYYDDMM      | 20150101                       |
| 字符串"YYYY-DD-MM" | "2015-01-01"                   |
| datetime 对象      | datetime.datetime (2015, 1, 3) |
| date 对象          | datetime.date (2015, 1, 3)     |
| Pandas Timestamp   | pandas.Timestamp ('20150103')  |

#### 范例

```python
import rqdatac, pandas, datetime

rqdatac.init()

rqdatac.get_price('000001.XSHE', start_date=20150101, end_date="2015-02-01")

rqdatac.get_price('000002.XSHE', start_date=pandas.Timestamp("20150101"), end_date=datetime.datetime(2015,2,1))
```

### 保存数据为 csv 文件 {#rqdata-save-csv}

通过 RQData API 返回的数据绝大部分为[Pandas](https://pandas.pydata.org/)的`DataFrame`格式，方便您通过 Pandas 强大的 API 进行后续的分析工作。但是如果您已有用其他语言编写的投研工具，只是希望获得 RQData 中的原始金融数据，则可以通过下面的方法输出原始数据为 csv 文件：

```python
import rqdatac
rqdatac.init()
# get_price的返回值为Pandas.DataFrame类型，可以直接调用其to_csv接口
value = rqdatac.get_price('000001.XSHE', start_date=20150101, end_date=20150201)
value.to_csv('xxxx.csv')
```

### RQData 内部的专有名词解释 {#rqdata-about-symbols}

- **rqdatac**：RQData 客户端（即 RQData Client）。
- **rqdatad**：RQData 服务端（即 RQData Daemon）。
- **order_book_id**：这是米筐内部对于合约代码、股票代码、债券代号等指向某个金融产品实例的编号的统称。这是米筐为了兼容多市场而自定义的一个字段，它的取值在任何时间跨度内全局唯一。

## 快速上手 {#rqdata-get-started}

### 安装及配置

RQData 的安装根据于您的使用方式也会有所不同。

#### 使用线上平台的 IPython Notebook 环境及回测环境

不需要任何的安装或配置，而且所有的包已经预先导入，您无需使用前述的`import rqdatac`或`rqdatac.init()`，在使用 RQData API 时也无需添加`rqdatac`的前缀，可以直接使用，例如：

```python
get_price('000001.XSHE', start_date=20150101, end_date=20150201)
```

#### 本地安装 RQData

请参考[Ricequant SDK 安装教程](../../rqsdk/manual-rqsdk#rqsdk-installation)。在您完成 Ricequant SDK 的安装之后，您的环境里即可以使用 RQData。

米筐也提供独立的 RQData 安装方式，请在申请试用或开通正式账户后查收米筐为您准备的安装指引邮件。米筐推荐使用 Ricequant SDK 的方式安装并管理 RQData 及其许可证信息。

_如果您在回测引擎 RQAlpha Plus 中使用 RQData，可以省略`rqdatac.init()`语句的调用。_

#### 私有化部署的安装

将 RQData 的服务端`rqdatad`及其依赖的数据库部署到本地服务中以实现局域网环境低时延的访问体验，是 RQData 产品提供的私有化部署方案。如果您有这方面的需求，请联系我们的销售。

私有化部署的服务端将由米筐工作人员为您完成，您只需要提供服务器的访问端口即可。而客户端的安装与互联网版本的 RQData 并无二致，米筐技术支持会提供详细的安装帮助。

### 开始使用

前文已描述过 RQData 的安装及其在不同环境中的初始化过程，事实上所有的准备工作就已经就绪了。

而使用 RQData 则异常简单，只需要直接调用您想要的 API 获取数据即可。具体的 API 使用示范都在 API 参考中列出。

RQData 客户端`rqdatac`以框架+模块的形式提供了丰富的金融数据。你只需要在[文档目录](index-rqdatac.md#rqdata-doc-index)中找到相应的金融产品类型即可。但是在查阅具体金融产品类型之前，我们推荐您先浏览一下 RQData 的基础 API，也可在[文档目录](index-rqdatac.md#rqdata-doc-index)中找到相关链接，或直接点击[这里](generic-api.md)。
