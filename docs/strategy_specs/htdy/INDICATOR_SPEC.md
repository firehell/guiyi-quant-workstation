# 火天大有 HTDY 指标公式规范

生成时间：2026-07-12

## 1. 定位

`huotian_dayou_original_v0` 是用户提供的通达信「火天大有」原始指标公式整理版。本文件只做公式归档、变量拆解和观察语义说明。

当前状态：

- `status=observation_only`
- `repainting_risk=known`
- `backtest_capable=false`
- `live_capable=false`
- `alert_capable=false`

原始公式含 `XMA(XMA(...))`，属于未来函数 / 重绘公式。所有由 `XMA` 派生的通道、黄K/白K、三连提示、`XG`、`XG2` 只能用于 Web 人工观察，不得进入可信回测、正式策略信号、`signal_events`、live evaluator 或企业微信提醒。

## 2. 原始通达信公式

```text
{==== 背景 ====}
DRAWGBK(C>O,RGB(60,0,0),RGB(0,0,0),1,2,1);

{==== 板块信息 ====}
Z1:=STRCAT(HYBLOCK,' ');
Z2:=STRCAT(Z1,DYBLOCK);
Z3:=STRCAT(Z2,' ');
DRAWTEXT_FIX(ISLASTBAR,0,0,0,STRCAT(Z3,GNBLOCK)),COLORRED;

{==== 通道线 ====}
ZK1:(XMA(XMA(H,25),25)-XMA(XMA(L,25),25))*1+XMA(XMA(H,25),25),DOTLINE,COLORBLUE;
ZD1:XMA(XMA(L,25),25)-(XMA(XMA(H,25),25)-XMA(XMA(L,25),25))*1,LINETHICK2,COLORRED;
ZD2:EMA(ZD1,25),LINETHICK2;

DRAWBAND(ZD1,RGB(55,0,0),ZD2,RGB(0,91,0));

{==== K线 ====}
DRAWKLINE(H,O,L,C);

{==== 实体超过蓝色上轨ZK1的部分变白 ====}
BODYH:=MAX(O,C);
BODYL:=MIN(O,C);
OVERLOW:=MAX(BODYL,ZK1);

STICKLINE(BODYH>ZK1 AND BODYH>OVERLOW,BODYH,OVERLOW,2,0),COLORWHITE;

{==== ZD1压制/覆盖K线时变黄色 ====}
STICKLINE(ZD1>LOW AND ZD1<HIGH,ZD1,MIN(MIN(OPEN,CLOSE),ZD1),2,0),COLORYELLOW;
STICKLINE(ZD1>MIN(C,O) AND ZD1<MAX(C,O),ZD1,MIN(OPEN,CLOSE),2,0),COLORYELLOW;
STICKLINE(ZD1>HIGH,OPEN,CLOSE,2,0),COLORYELLOW;
STICKLINE(ZD1>HIGH,HIGH,LOW,0,0),COLORYELLOW;

{================================================}
{==== 新增：连续3根黄色/白色K线提示与预警 ====}
{================================================}

{黄色K定义：对应上面黄色STICKLINE的触发条件}
黄K:=(ZD1>LOW AND ZD1<HIGH)
    OR (ZD1>MIN(C,O) AND ZD1<MAX(C,O))
    OR (ZD1>HIGH);

{白色K定义：对应实体超过蓝色上轨ZK1的白色部分}
白K:=BODYH>ZK1 AND BODYH>OVERLOW;

{连续3根刚刚成立，只在第3根提示一次}
买多信号:=黄K AND REF(黄K,1) AND REF(黄K,2) AND NOT(REF(黄K,3));
卖空信号:=白K AND REF(白K,1) AND REF(白K,2) AND NOT(REF(白K,3));

DRAWTEXT(买多信号,L*0.995,'买多'),COLORYELLOW;
DRAWTEXT(卖空信号,H*1.005,'卖空'),COLORWHITE;

买多预警:买多信号,NODRAW,COLORYELLOW;
卖空预警:卖空信号,NODRAW,COLORWHITE;

{==== 原指标：回调买逻辑 ====}
VAR23:=100*XMA(XMA((C-REF(C,1)),6),6)/XMA(XMA(ABS((C-REF(C,1))),6),6);

回调买:=LLV(VAR23,2)=LLV(VAR23,7) AND COUNT(VAR23<0,2) AND CROSS(VAR23,MA(VAR23,2));

XG:=ZD1>HIGH AND 回调买 AND L<=ZD1;

DRAWTEXT(XG,L,'▲买入'),COLORRED;

{==== 原指标：资金/抓牛逻辑 ====}
JJ:=(HIGH+LOW+CLOSE)/3;

QJ0:=VOL/IF(HIGH=LOW,4,HIGH-LOW);

QJ1:=IF(CAPITAL=0,QJ0*(JJ-MIN(CLOSE,OPEN)),QJ0*IF(HIGH=LOW,1,(MIN(OPEN,CLOSE)-LOW)));
QJ2:=IF(CAPITAL=0,QJ0*(MIN(OPEN,CLOSE)-LOW),QJ0*IF(HIGH=LOW,1,(JJ-MIN(CLOSE,OPEN))));
QJ3:=IF(CAPITAL=0,QJ0*(HIGH-MAX(OPEN,CLOSE)),QJ0*IF(HIGH=LOW,1,(HIGH-MAX(OPEN,CLOSE))));
QJ4:=IF(CAPITAL=0,QJ0*(MAX(CLOSE,OPEN)-JJ),QJ0*IF(HIGH=LOW,1,(MAX(CLOSE,OPEN)-JJ)));

DDX:=((QJ1+QJ2)-(QJ3+QJ4))/IF(CAPITAL=0,10000,10000),COLOR00AAAA,LINETHICK;

V2:=SMA(IF(C>=REF(C,1),DDX,-DDX/100),2,1);
V5:=SMA(V2*120/FROMOPEN*5,2,1);
V10:=SMA(V5,5,1);
V20:=SMA(V10,5,1);

DY:=CURRBARSCOUNT=1 AND C<REF(C,1);
DY2:=REF(V2,1)-DY;

XG2:=C>O AND DY2<0.02 AND MA(C,5)>MA(C,60) AND C/REF(C,1)>=1.02 AND H<ZK1;

DRAWTEXT(XG2 AND L<ZD1,L,'↖黑马暴涨'),COLORRED;
```

## 3. 输入字段

| 字段 | 含义 | 当前项目映射 |
|---|---|---|
| `O` / `OPEN` | 开盘价 | `open` |
| `H` / `HIGH` | 最高价 | `high` |
| `L` / `LOW` | 最低价 | `low` |
| `C` / `CLOSE` | 收盘价 | `close` |
| `VOL` | 成交量 | `volume` |
| `CAPITAL` | 流通股本/市场上下文字段 | 期货场景按 `CAPITAL=0` 分支研究 |
| `FROMOPEN` | 当日已开盘分钟数 | V0 不实现正式语义，后续 PoC 需显式定义 |
| `CURRBARSCOUNT` | 到最后一根 K 线的距离 | 图表语义字段，不能直接用于 live/回测 |
| `HYBLOCK/DYBLOCK/GNBLOCK` | 板块显示信息 | A 股显示字段，期货 V1 忽略 |

## 4. 输出字段

| 输出 | 类型 | 用途 | 当前能力 |
|---|---|---|---|
| `ZK1` | 通道上轨 | Web 主图观察线 | observation-only |
| `ZD1` | 通道下轨/压制线 | Web 主图观察线、黄K判断 | observation-only |
| `ZD2` | `EMA(ZD1,25)` | 色带辅助线 | observation-only |
| `黄K` | 布尔 | `ZD1` 压制/覆盖 K 线 | observation-only |
| `白K` | 布尔 | 实体超过 `ZK1` | observation-only |
| `买多信号` | 布尔 | 连续 3 根黄K刚成立 | observation-only，不是正式买入信号 |
| `卖空信号` | 布尔 | 连续 3 根白K刚成立 | observation-only，不是正式卖出信号 |
| `VAR23` | 数值 | 原指标回调买中间变量 | forbidden for backtest/signal |
| `回调买` | 布尔 | `VAR23` 派生条件 | observation-only |
| `XG` | 布尔 | 原指标 `▲买入` | observation-only |
| `DDX/V2/V5/V10/V20` | 数值 | 资金/抓牛中间变量 | rewrite candidate |
| `XG2` | 布尔 | 原指标 `黑马暴涨` | observation-only |

## 5. 公式拆解

### 5.1 通道线

```text
XH = XMA(XMA(H,25),25)
XL = XMA(XMA(L,25),25)
WIDTH = XH - XL
ZK1 = XH + WIDTH
ZD1 = XL - WIDTH
ZD2 = EMA(ZD1,25)
```

关键风险：`XMA` 是居中/偏移移动平均，会读取未来 bar；双层 `XMA` 会放大历史重绘范围。

### 5.2 黄K/白K和三连提示

```text
BODYH = MAX(O,C)
BODYL = MIN(O,C)
OVERLOW = MAX(BODYL,ZK1)

黄K = (ZD1 > LOW AND ZD1 < HIGH)
   OR (ZD1 > MIN(C,O) AND ZD1 < MAX(C,O))
   OR (ZD1 > HIGH)

白K = BODYH > ZK1 AND BODYH > OVERLOW

买多信号 = 黄K AND REF(黄K,1) AND REF(黄K,2) AND NOT(REF(黄K,3))
卖空信号 = 白K AND REF(白K,1) AND REF(白K,2) AND NOT(REF(白K,3))
```

`REF(...,1/2/3)` 本身只读取过去值，但 `黄K` / `白K` 依赖 `ZD1/ZK1`，因此三连提示仍继承 `XMA` 重绘风险。

### 5.3 回调买和 XG

```text
DELTA = C - REF(C,1)
VAR23 = 100 * XMA(XMA(DELTA,6),6) / XMA(XMA(ABS(DELTA),6),6)
回调买 = LLV(VAR23,2)=LLV(VAR23,7)
      AND COUNT(VAR23<0,2)
      AND CROSS(VAR23,MA(VAR23,2))
XG = ZD1 > HIGH AND 回调买 AND L <= ZD1
```

`VAR23` 直接使用双层 `XMA`，`XG` 同时依赖 `ZD1`，因此不能作为可信回测或正式提醒条件。

### 5.4 资金/抓牛和 XG2

期货场景先按 `CAPITAL=0` 分支理解：

```text
JJ = (HIGH + LOW + CLOSE) / 3
QJ0 = VOL / IF(HIGH=LOW, 4, HIGH-LOW)
QJ1 = QJ0 * (JJ - MIN(CLOSE,OPEN))
QJ2 = QJ0 * (MIN(OPEN,CLOSE) - LOW)
QJ3 = QJ0 * (HIGH - MAX(OPEN,CLOSE))
QJ4 = QJ0 * (MAX(CLOSE,OPEN) - JJ)
DDX = ((QJ1+QJ2) - (QJ3+QJ4)) / 10000
```

`DDX` 这部分只使用当前 bar OHLCV，但 `XG2` 最终仍包含：

```text
DY = CURRBARSCOUNT=1 AND C<REF(C,1)
DY2 = REF(V2,1) - DY
XG2 = C>O AND DY2<0.02 AND MA(C,5)>MA(C,60)
   AND C/REF(C,1)>=1.02 AND H<ZK1
```

`XG2` 依赖 `ZK1`，并且 `CURRBARSCOUNT` 是图表末端语义，不适合直接进入历史回测或 live evaluator。

## 6. Web 观察层对齐状态

2026-07-12 已完成第 2 步 Web observation-only 对齐：

- 黄K 按原公式三个严格条件判断；`ZD1` 在 K 线内只绘制对应黄色分段，`ZD1>HIGH` 时才绘制整根黄色实体和影线。
- 白K 按 `BODYH>ZK1 AND BODYH>OVERLOW` 判断，只绘制实体越过 `ZK1` 的部分；仅影线越轨不命中。
- 同一根 K 同时命中黄/白时，按原 `STICKLINE` 顺序先白后黄。
- `XG` 以红色 `XG观察` 显示，只存在于 Web SVG 观察覆盖层，不进入正式 marker 点击、信号或通知链。
- `XG2` 未在 Web 展示；原因是 `CURRBARSCOUNT` 的历史图表语义尚未确定，不代表该字段不存在。
- 页面常驻披露“观察专用·会重绘·XG 已显示·XG2 未展示”。

本步仍不是逐像素通达信截图验收；颜色、字体和标记位置的 Golden Sample 校准保留在第 4 步。

## 7. 下一步

1. [已完成] 原始 observation-only PoC。
2. [已完成] Web 观察层对齐：精确黄K/白K、展示 `XG`、后置 `XG2`。
3. [已完成] Strict backward-looking 方案：另起 `huotian_dayou_strict_v1`，使用 `double_trailing_ema` 替代 `XMA`，不得冒用原始版结果。
4. [已完成] Golden Sample 自动数值验收和外部通达信视觉 oracle 通过，状态为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`；未提供通达信数值导出，不声明逐点数值 oracle pass。
5. [已完成] Offline Candidate Eval：只读输出 `huotian_dayou_strict_v1` candidate events，不接正式策略、可信报告或提醒链路。

第 3 步产物：

- `docs/strategy_specs/htdy/STRICT_V1_SPEC.md`
- `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/vnpy_strategy.py`
- `services/quant-api/tests/test_strategy_indicator_policy_c404.py`

`huotian_dayou_strict_v1` 的指标层仍是 `strict_research_candidate`，不是可信定级指标或正式策略。

第 4 步固定样本、Python/Web 对照和浏览器检查见 `GOLDEN_SAMPLE_ACCEPTANCE.md`。第 5 步离线候选评估见 `OFFLINE_CANDIDATE_EVAL.md`，当前结果不授权正式回测接入。
