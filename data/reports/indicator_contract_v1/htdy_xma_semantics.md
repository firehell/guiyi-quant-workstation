# HTDY XMA 语义审计

审计任务：`HTDY-SOURCE-XMA-AUDIT-400`
最终 Gate：`HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`

## 1. 结论边界

已确认：

- 通达信官方函数表将 `XMA(X,N)` 定义为偏移移动平均，明确说明它使用当日以后 `N/2` 日的数据、属于未来函数且只供内部测试使用（[官方函数表](https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html)）。因此原公式中的 `XMA` 及其派生字段会使用未来 bar 并重绘。
- 仓库 Python PoC 与 Web observation overlay 实现了相同的自定义切片算法；代码锚点分别是 `experiments/htdy_indicator/htdy_original_core.py:100-120` 的 `normalize_period` / `xma` 和 `apps/quant-web/src/utils/indicators.ts:235-259` 的 `tdxXma` / `sliceLikeNumpy`。
- `REF`、`EMA`、`MA`、`SMA`、`LLV`、`COUNT`、`CROSS` 单独使用时只读取当前或过去值。用户公式没有出现 `BACKSET`、`FILTER` 或 `BARSLAST`。
- 仓库已有测试证明当前 Python/Web 算法会因未来尾部变化而改变历史输出；strict 实现的 trailing double EMA 已有 future-tail 与 prefix/batch 回归证据。

仍未解决：

- 官方函数表没有完全定义奇偶周期取整、窗口端点是否包含、序列头尾如何填充、无效值如何处理，也没有给出可复算的数值向量。
- 本次没有通达信数值导出或可调用的通达信计算 oracle。因此本文只描述“仓库实现语义”，不把 Python/Web 算法称为“通达信数值等价”。
- 既有截图视觉验收不能替代逐点数值 oracle，尤其不能关闭 XMA 的边界语义问题。

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

## 3. 非 XMA 语义差异

### 3.1 `CURRBARSCOUNT`

通达信官方函数表将 `CURRBARSCOUNT` 定义为“从最新一根 K 线倒数编号，从 1 开始”。原式：

```text
DY:=CURRBARSCOUNT=1 AND C<REF(C,1);
```

只应在当前图表最后一根 bar 上可能为真。Python PoC 在 `experiments/htdy_indicator/htdy_original_core.py:274-275` 计算 `dy = c < prev_close`，使每个下跌历史行都为真；metadata 的 `each_row_treated_as_chart_last_bar_for_poc`（`:318`）只是说明近似假设，不能使批量序列与原图表语义等价。这是已确认的 original-v0 mismatch。

### 3.2 `FROMOPEN`

官方函数表把 `FROMOPEN` 定义为当前时刻距开盘的分钟数。Python PoC 只接收一个标量 `from_open`，默认 `1.0`（`htdy_original_core.py:227,239-240,271,317`），并把它用于所有 bar。它没有交易日历、夜盘、午休、周期或逐 bar 已开盘分钟语义，因此只是显式近似/默认值，不是通达信等价实现。Web 和 strict 均未实现该资金区块。

## 4. 数值 Oracle 最小要求

必须由同一次通达信运行导出逐 bar、未四舍五入数据，并保留以下证据。只有截图或末值不足以判断切片端点、取整与尾部行为。

| 类别 | 必须提供的字段/证据 | 目的 |
|---|---|---|
| 输入 | O/H/L/C/V 原始数值 | 固定公式输入，排除复权或数据源差异 |
| 时间 | 每根 bar 时间戳、周期、市场/合约、时区/交易日 | 锁定顺序、夜盘与缺口语义 |
| 环境 | 通达信客户端完整版本、公式文本、公式文件或文本 SHA-256 | 锁定计算实现和输入公式 |
| 25 周期内层 | `XMA(H,25)`、`XMA(L,25)` | 判断单层窗口、端点、边界填充 |
| 25 周期外层 | `XMA(XMA(H,25),25)`、`XMA(XMA(L,25),25)` | 判断两层有限值/无效值传播 |
| 通道输出 | `ZK1`、`ZD1`（建议同时导出 `ZD2`） | 验证最终通道组合与 EMA seed |
| 6 周期分子 | `XMA(C-REF(C,1),6)`、外层 `XMA(XMA(C-REF(C,1),6),6)` | 验证偶数周期取整和嵌套范围 |
| 6 周期分母 | `XMA(ABS(C-REF(C,1)),6)`、外层对应值 | 验证无效值与零分母路径 |
| 动量输出 | `VAR23` | 验证分子/分母组合 |
| 覆盖区域 | warm-up 头部、稳定中段、最终 tail；每区至少覆盖完整 25 周期窗口，tail 需逐次追加 bar | 判断头尾填充、重绘和 append 行为 |

建议用至少两组数据：一组确定性递增序列用于识别端点；一组真实 OHLCV 用于覆盖 NaN、平盘、高低相等、夜盘和交易时段。还需分别测试 25 与 6，以避免用奇数周期结论外推偶数周期。

## 5. 安全分级与建议

### P0

- `huotian_dayou_original_v0` 必须继续为 `observation_only`；禁止进入正式回测、Signal、live evaluator、alert、通知或交易链。
- 缺少通达信数值 oracle 时，禁止把仓库 Python/Web XMA 标为 Tongdaxin-equivalent，禁止宣告 `HTDY_FORMULA_SOURCE_AUDITED`、`XMA_SEMANTICS_MATCHED` 或 `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`。

### P1

- strict 的正式显示名称应为 `火天大有（因果改写）`，并保留独立版本 `huotian_dayou_strict_v1`；它是 causal adaptation，不是原公式复刻。
- 进入 Stage 5 前仍需同时满足 confirmed-only、无未来引用和 future-tail 稳定性 Gate，并由独立任务审查正式 Profile/lineage、成交时点、成本、回撤和连续亏损。

### P2

- 增加基于通达信逐点数值导出的跨语言 golden vectors，覆盖上述 oracle 表中的头部、中段、尾部和嵌套中间值。

建议：三份审计报告可以合并；不得继续推进 original 公式 formal 化。strict 只可保留为 formal candidate，待数值语义/公式来源 Gate 与 Stage 5 独立安全 Gate 完成后再评估。

`D4-01` 对非 HTDY 调用方的盘点结论不受影响；其中 HTDY readiness 行在 `D4-00` 阻塞期间仅为 provisional，不得作为 Stage 5 准入。
