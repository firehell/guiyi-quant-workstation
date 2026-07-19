# HTDY XMA 语义审计

审计任务：`HTDY-SOURCE-XMA-AUDIT-400`
最终 Gate：`HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`

## 1. 结论边界

已确认：

- 通达信官方函数表将 `XMA(X,N)` 定义为偏移移动平均，明确说明它使用当日以后 `N/2` 日的数据、属于未来函数且只供内部测试使用（[官方函数表](https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html)）。因此原公式中的 `XMA` 及其派生字段会使用未来 bar 并重绘。
- 仓库 Python PoC 与 Web observation overlay 实现了相同的自定义切片算法；代码锚点分别是 `experiments/htdy_indicator/htdy_original_core.py:100-120` 的 `normalize_period` / `xma` 和 `apps/quant-web/src/utils/indicators.ts:235-259` 的 `tdxXma` / `sliceLikeNumpy`。
- 用户提供的 `JM2609_火天大有逐点数值.xlsx` 已形成可复算的 XMA(25) 组合输出 oracle。在等权 25 点偏移均值候选中，稳定区间和 tail 唯一支持对称窗口 `[-12,+12]`，并确认仓库 Python/Web 当前 `[-13,+11]` 实现存在一根 bar 的 off-by-one，不与该通达信导出等价。
- `REF`、`EMA`、`MA`、`SMA`、`LLV`、`COUNT`、`CROSS` 单独使用时只读取当前或过去值。用户公式没有出现 `BACKSET`、`FILTER` 或 `BARSLAST`。
- 仓库已有测试证明当前 Python/Web 算法会因未来尾部变化而改变历史输出；strict 实现的 trailing double EMA 已有 future-tail 与 prefix/batch 回归证据。

仍未解决：

- 当前导出没有 `XMA(...,6)` 的内层/外层中间值或 `VAR23`，不能判断偶数周期取整及 XMA(6) 头尾行为。
- 当前导出没有单层 XMA(25) 中间值，但对称截断候选的双层 ZK1/ZD1 从首行到末行均与两位小数 oracle 高度一致，足以判定组合通道的 head/tail 行为；每一内层的无效值传播仍缺少直接字段。
- 工作簿没有通达信客户端版本、导出时公式 hash、明确 timeframe/时区，也只保留两位小数的指标值。最后一行是 `2026/07/20`，晚于审计自然日 `2026/07/19`，只能按可能的当前交易日 partial daily bar 处理，不能用作 confirmed-bar 信号证据。

### 1.1 Canonical source-freeze evidence

本审计冻结的 canonical 公式来源是 reviewed repository commit
`fe05f5419fa28476d719baccb1b9406c76a286bf` 中的
`docs/strategy_specs/htdy/INDICATOR_SPEC.md`。精确提取该 commit 的物理行
22--107（含首尾行）：该 UTF-8 字节序列包含所有空行和注释行，并包含最终换行。
提取共 86 个物理行，SHA-256 为：

```text
2e987ebe295d36db58c7b6d9aeae3325f35f83190b145ee88af5279ce5a835fc
```

这只冻结了本审计所映射的 source identity，确保 45 条逻辑可执行语句的来源可复查；它本身不解决通达信 `XMA` 的数值语义。下节 numeric oracle 已关闭 XMA(25) 组合窗口偏移并确认 repository mismatch，但 XMA(6)、直接内层字段和 provenance 仍未关闭，因此最终 Gate 继续为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。

### 1.2 2026-07-19 numeric oracle evidence

| 项目 | 证据 |
|---|---|
| 文件 | `/Users/zhangzhao/Downloads/JM2609_火天大有逐点数值.xlsx` |
| SHA-256 | `e289cce7b61269ebacce6a8c7587afa87234bf00f925892968aa0ae2b39af5c3` |
| 文件大小/生成时间 | `88,883 bytes`；workbook metadata `2026-07-19T01:26:16Z` |
| 容器 provenance | core creator=`openpyxl`；footer 写明“数据来源:通达信”，但没有通达信原生导出签名或客户端版本 |
| 工作表 | `火天大有逐点数据!A1:X842`；1 个表、无 Excel 公式 |
| 数据范围 | 840 行日粒度 OHLCV，`2023/01/20..2026/07/20`；另有 1 行 header 和 1 行“数据来源:通达信”footer |
| 明确字段 | OHLCV、ZK1、ZD1、ZD2、买多预警、卖空预警 |
| 缺失字段 | 单层 XMA(25)、双层中间值、XMA(6) 分子/分母、VAR23、客户端版本、公式 hash、明确 timeframe/时区 |

本次只读比较直接使用工作簿保存值，没有把截图或 Web 显示值作为数值输入。由于 ZK1/ZD1 是双层 XMA(H/L) 的线性组合，它们足以区分当前仓库偏移和对称 25 周期偏移，并验证组合通道的序列两端；但仍不足以独立观察每一内层的无效值传播，也不能外推到周期 6。

## 2. Python/Web XMA 精确算法

令输入长度为 `L`，调用周期为 `N`，索引 `i` 从 0 开始：

```text
n = int(N)                         # Web 为 Math.trunc(N)
n' = n + 1 if n is even else n    # 偶数向上归一为奇数
p = (n' - 1) / 2
start = i - p - 1                  # inclusive
end = i + (n' - p) - 1            # exclusive
window = values[start:end]         # NumPy 风格负索引与越界裁剪
window = finite(window)            # 丢弃 NaN/undefined/inf
output[i] = mean(window)            # 无有限值时 NaN/undefined
```

Python 对 `N<=0` 抛错；Web 的 `calculateHuoTianDaYou` 在 `period<=0` 时返回空点列。正常 HTDY 调用只使用正周期 25 和 6。

### 2.1 有效偏移

| 调用 | 归一周期 | 单层名义输入偏移 | 双层名义原始输入偏移 | 说明 |
|---|---:|---|---|---|
| `XMA(...,25)` | 25 | `[-13, +11]` | `[-26, +22]` | `end` 为 exclusive；不是对称的 `[-12,+12]` |
| `XMA(...,6)` | 7 | `[-4, +2]` | `[-8, +4]` | 偶数 6 先变为 7 |

这些偏移是无边界裁剪时的仓库算法依赖范围。双层范围是两次单层偏移的组合；每层有限值过滤会使实际参与均值的点数随位置变化。

通达信导出对等权移动平均候选强支持的 XMA(25) 组合语义是：

```text
single_xma25[i] = mean(values[max(0, i-12) : min(L, i+13)])
double dependency = [-24, +24]
```

这与仓库算法相差一根 bar。它仍然读取未来 12 根输入；双层组合最多读取未来 24 根原始 bar，重绘分类不变。

### 2.2 序列头部与尾部

- 头部：负 `start` 不会简单裁成 0，而是先按 NumPy 语义转换为 `L + start`。当归一后的 `end <= start` 时窗口为空。对长度足够的 25 周期输入，单层 XMA 在 `i=0..12` 为空，从 `i=13` 开始有值；第二层会过滤第一层的 NaN，所以也可能从 `i=13` 开始基于不完整的有限子集输出，而不是再等待 25 个完整有效值。
- 尾部：正 `end` 裁到 `L`，窗口逐步缩短，但只要仍有有限值就继续输出。仓库实现不会把最后 `p` 个点统一置空。
- 无效值：Python 只平均 `np.isfinite` 的值；Web 只平均有限 `number`。窗口内的 NaN、undefined 与无穷值被删除，而不是使整个窗口无效。
- 嵌套：外层 XMA 会再次读取内层 XMA 的未来输出；内层输出本身已读取更远的未来原始 bar。因此双层 `XMA` 扩大了历史重绘传播范围。

### 2.3 公式中的实际依赖

- 通道：`xma(xma(H,25),25)` 与 `xma(xma(L,25),25)`，仓库名义上最多读取当前位置后 22 根原始 H/L；`ZK1`、`ZD1`、`ZD2`、黄/白 K、三连观察和 `XG` 继承此风险。
- `VAR23`：分子与分母分别对 `C-REF(C,1)` 及其绝对值做双层 6 周期 XMA，归一后名义上最多读取当前位置后 4 根 delta；`回调买` 与 `XG` 继承此风险。
- `XG2`：其 DDX/SMA/REF/MA 子链本身可后向计算，但条件 `H<ZK1` 重新引入双层 25 周期 XMA 风险。
- `confirmed bar` 不能消除该问题：即便当前位置 bar 已收盘，完整序列预计算仍读取其后的 bar；未来 bar 新增或修订会改变历史输出。

### 2.4 逐点比较结果

比较使用 840 行工作簿 OHLCV 重算候选结果。稳定区间取 0-based `30..809` 共 780 行；tail 取最后 24 行。由于 oracle 指标只保留两位小数，同时报告两位小数匹配和未四舍五入候选误差。

| 实现/字段 | 区间 | 两位小数匹配 | MAE | 最大绝对误差 | 判定 |
|---|---|---:|---:|---:|---|
| 仓库 `[-13,+11]` ZK1 | stable 780 | `0/780` | `9.141588` | `27.041200` | 明确不等价 |
| 仓库 `[-13,+11]` ZD1 | stable 780 | `0/780` | `8.600512` | `28.407200` | 明确不等价 |
| 对称 `[-12,+12]` ZK1 | all 840 | `829/840` | `0.002548` | `0.005650` | 全序列高度一致，支持 head/tail 截断 |
| 对称 `[-12,+12]` ZD1 | all 840 | `828/840` | `0.002477` | `0.005200` | 全序列高度一致，支持 head/tail 截断 |
| 对称 `[-12,+12]` ZK1 | stable 780 | `771/780` | `0.002546` | `0.005600` | 与两位小数 oracle 高度一致；少数行处于舍入临界 |
| 对称 `[-12,+12]` ZD1 | stable 780 | `768/780` | `0.002477` | `0.005200` | 与两位小数 oracle 高度一致；少数行处于舍入临界 |
| 对称 `[-12,+12]` ZK1/ZD1 | tail 24 | `24/24` / `24/24` | `0.002501` / `0.002494` | `0.004918` / `0.004414` | 当前序列 tail 与缩短窗口一致 |
| 对称通道后的 ZD2 | settled 610 | `606/610` | `0.002441` | `0.005232` | 早期差异来自缺失的导出前 EMA seed history |

以对称 XMA(25) 重算黄/白条件及第三根一次性提示后，`买多预警`、`卖空预警` 在全部 840 行均逐行一致，事件数分别为 `17 / 10`。当前仓库算法只有 `823/840` 买多行和 `831/840` 卖空行一致，事件数为 `18 / 11`。这证明 off-by-one 已经改变 observation 历史，不只是小数显示差异。

## 3. 非 XMA 语义差异

### 3.1 `CURRBARSCOUNT`

通达信官方函数表将 `CURRBARSCOUNT` 定义为“从最新一根 K 线倒数编号，从 1 开始”。原式：

```text
DY:=CURRBARSCOUNT=1 AND C<REF(C,1);
```

只应在当前图表最后一根 bar 上可能为真。Python PoC 在 `experiments/htdy_indicator/htdy_original_core.py:274-275` 计算 `dy = c < prev_close`，使每个下跌历史行都为真；metadata 的 `each_row_treated_as_chart_last_bar_for_poc`（`:318`）只是说明近似假设，不能使批量序列与原图表语义等价。这是已确认的 original-v0 mismatch。

### 3.2 `FROMOPEN`

官方函数表把 `FROMOPEN` 定义为当前时刻距开盘的分钟数。Python PoC 只接收一个标量 `from_open`，默认 `1.0`（`htdy_original_core.py:227,239-240,271,317`），并把它用于所有 bar。它没有交易日历、夜盘、午休、周期或逐 bar 已开盘分钟语义，因此只是显式近似/默认值，不是通达信等价实现。Web 和 strict 均未实现该资金区块。

## 4. 剩余 Oracle 最小要求

必须由同一次通达信运行导出逐 bar、未四舍五入数据，并保留以下证据。只有截图或末值不足以判断切片端点、取整与尾部行为。

| 类别 | 必须提供的字段/证据 | 目的 |
|---|---|---|
| 输入 | 已有 O/H/L/C/V；如需独立关闭 ZD2 seed，补充导出起始日前相同口径 ZD1/EMA history | 关闭 ZD2 初始 seed 问题 |
| 时间 | 补充明确周期、市场/合约、时区/交易日及最后一根 confirmed 状态 | 锁定 partial-bar 和夜盘语义 |
| 环境 | 通达信客户端完整版本、实际执行公式文本或 SHA-256 | 锁定计算实现和输入公式 |
| 25 周期内层 | 补充 `XMA(H,25)`、`XMA(L,25)` | 独立确认每层无效值传播；窗口偏移和组合 head/tail 已确认 |
| 25 周期外层 | 已有 ZK1/ZD1 可解组合；建议仍直接导出两条外层值 | 减少线性反解和两位小数舍入不确定性 |
| 通道输出 | 已有 ZK1、ZD1、ZD2 | 组合输出已足以确认当前仓库 off-by-one |
| 6 周期分子 | `XMA(C-REF(C,1),6)`、外层 `XMA(XMA(C-REF(C,1),6),6)` | 验证偶数周期取整和嵌套范围 |
| 6 周期分母 | `XMA(ABS(C-REF(C,1)),6)`、外层对应值 | 验证无效值与零分母路径 |
| 动量输出 | `VAR23` | 验证分子/分母组合 |
| 覆盖区域 | warm-up 头部、稳定中段、最终 tail；每区至少覆盖完整 25 周期窗口，tail 需逐次追加 bar | 判断头尾填充、重绘和 append 行为 |

建议用至少两组数据：一组确定性递增序列用于识别端点；一组真实 OHLCV 用于覆盖 NaN、平盘、高低相等、夜盘和交易时段。还需分别测试 25 与 6，以避免用奇数周期结论外推偶数周期。

## 5. 安全分级与建议

### P0

- `huotian_dayou_original_v0` 必须继续为 `observation_only`；禁止进入正式回测、Signal、live evaluator、alert、通知或交易链。
- 已确认仓库 Python/Web XMA(25) 存在 off-by-one，禁止把它们标为 Tongdaxin-equivalent；在新版本/修复任务完成前，也不应把当前工具继续称为忠实 `original_v0`。
- XMA(6)、VAR23、直接内层无效值传播、ZD2 seed 和 oracle provenance 仍未关闭，禁止宣告 `HTDY_XMA_SEMANTICS_AUDITED` 或 `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`。

### P1

- strict 的正式显示名称应为 `火天大有（因果改写）`，并保留独立版本 `huotian_dayou_strict_v1`；它是 causal adaptation，不是原公式复刻。
- 进入 Stage 5 前仍需同时满足 confirmed-only、无未来引用和 future-tail 稳定性 Gate，并由独立任务审查正式 Profile/lineage、成交时点、成本、回撤和连续亏损。

### P2

- 将本次 XMA(25) 对称窗口结论转为独立修复任务和跨语言 golden vector；补齐 XMA(6)、VAR23、直接中间值和 provenance 后再重跑 D4-00。

重新判定：source freeze、original/strict boundary、XMA25 window offset 和 repository mismatch 的 evidence 均已确认，但它们不作为部分 pass Gate 发出。由于 XMA(6)/VAR23、直接内层字段和 provenance 仍缺失，本任务唯一 Gate 继续为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。不得继续推进 original 公式 formal 化；strict 只可保留为 formal candidate，不能进入 Stage 5 正式报告 Gate。

`D4-01` 对非 HTDY 调用方的盘点结论不受影响；其中 HTDY readiness 行在 `D4-00` 阻塞期间仅为 provisional，不得作为 Stage 5 准入。
