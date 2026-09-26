/** Documentation-only public formulas; never evaluated by the chart or strategy. */
export const NEWOW_FORMULA_HELP = {
  "trend": {
    "title": "趋势黄蓝带",
    "formula": "T=(H+L+C)/3；A=MAp(T,7)；B=MAp(T,10)\nC≥B 为黄，否则蓝；蓝→黄建仓，黄→蓝清仓；参考价 B。",
    "boundary": "第 0 根只给状态，不补建仓；没有配对入场的清仓不显示收益。A 参与画带，不决定颜色。",
    "source": "公式附册 §3.1"
  },
  "oscillation": {
    "title": "震荡区间",
    "formula": "U=HHV(H,10)；D=LLV(L,10)，含当前根，须满 10 根。\n持有且 H≥U：先清仓，参考价 H。\n空仓且 L≤D，且本根未清仓：建仓，参考价 L。",
    "boundary": "已持有且同根触上下沿，清仓后不重建；空仓同触只建仓。图标注与其他回测路径不能混用。",
    "source": "公式附册 §3.3"
  },
  "main_rise": {
    "title": "主升浪",
    "formula": "T=(H+L+C)/3；fast=MAp(T,35)；slow=MAp(T,45)\nfast≥slow 为黄，否则蓝；正常建清仓参考价均为 slow。",
    "boundary": "J 减仓与 D1–D6 是独立过程提示，不自行改主状态或参考交易。公共部分窗口初始化与归一输入预热按各自版本区分。",
    "source": "公式附册 §3.2、§4.1"
  },
  "macd": {
    "title": "MACD",
    "formula": "DIF=EMA(C,12)−EMA(C,26)\nDEA=EMA(DIF,9)；柱=2×(DIF−DEA)。",
    "boundary": "副图读数来自已接受的服务端指标；不在浏览器重复算指标或产生动作。",
    "source": "归一 MACD 显示合同"
  },
  "zhaoyao_mirror": {
    "title": "主力照妖镜",
    "formula": "P=前根 OHLC 均值（首根用自身）\nA=EMA(SMA(|L−P|,13,1)/(SMA(max(L−P,0),10,1)或1),10)\nB=EMA(SMA(|H−P|,13,1)/(SMA(|min(H−P,0)|,10,1)或1),10)\nI=EMA(L≤LLV10 ? A : 0,3)\nE=EMA(H≥HHV10 ? B : 0,3)\nT=EMA(H≥HHV10 ? A : 0,3)",
    "boundary": "I 上/下行=进场/洗盘；E 上/下行=出货/拉高；T 上/下行=退场/诱多。黄色宽柱拉高、蓝色窄柱出货按绘图字段；原站图例文字反向。小心使用 5% ZigZag 回填，明确会重绘，仅供历史回看。",
    "source": "公式附册 §10.2；原站绘图字段"
  },
  "up_down_energy": {
    "title": "涨跌动能",
    "formula": "B=(MA5(C)−MA120(C))/MA120(C)\nQ=MA(RSV10,3)，RSV 满 10 根后须满 3 个非空值。\n波段：C>MA120，Q[-1]<30，Q>Q[-1]<Q[-2]\n反弹：Q[-1]<5，Q>Q[-1]<Q[-2]，B<−0.3\n超跌：Q[-1]≤5<Q，B<−0.4\n命中输出80，否则基线50。",
    "boundary": "柱连接 Q[-1] 和 Q；C≥MA10 红，否则绿。阈值为公式条件，不是成功概率或下一根幅度预测；它与 D4–D6 不同。",
    "source": "公式附册 §10.3"
  },
  "main_force_control": {
    "title": "主力控盘",
    "formula": "X=EMA(EMA(C,9),9)\nKP=1000×(X/X[-1]−1)；首根或前 X=0 时 KP=0。\nEMA50(C) 辅助判断高控 / 出货叠加。",
    "boundary": "价格代理标签，不代表真实主力账户。优先级：开始控盘→上升有庄→高控且下降叠加→高控→下降出货→负值无庄→继承。",
    "source": "公式附册 §10.1"
  },
  "trend_reversal": {
    "title": "趋势转折",
    "formula": "U=HHV(H,20)；D=LLV(L,20)\nWR1=100×(U−C)/(U−D)\nbias=100×(C/MA(C,120)−1)\nWR1>97：反弹；WR1<3：调整。",
    "boundary": "3 与 97 是严格不等号；不足 120 根可有图形，但仍标预热。标记只描述区间位置，不预测方向。",
    "source": "公式附册 §10.4"
  },
  "cycles": {
    "title": "4 / 7 / 11 周期",
    "formula": "低锚：L=LLV60，且 REF(LLV3,3)>L、REF(LLV3,1)>L\n高锚：H=HHV60，且 REF(HHV3,3)<H、REF(HHV3,1)<H\n选择较近锚；距离相等取低锚。距锚 4/7/11 根输出周期提示。",
    "boundary": "数字表示当前周期的 Bar 根数。只读当前与此前；不引入未来三根，不预测 11 根后的涨跌。",
    "source": "公式附册 §4.3"
  },
  "escape": {
    "title": "D1–D6 与 J",
    "formula": "Z=MAp(C,120)；Q10/20=round4(MAp(RSV10/20,3))\nBH=round4((MAp(H,5)−Z)/Z)；BC=round4((MAp(C,5)−Z)/Z)\nD1：Q10 下穿95且 BH>0.3\nD2：Q10 下穿93且 HHV30/LLV30>1.1、Z[-1]/Z>0.997\nD3：C<Z<Z[-1]且 Q10[-1]>90、Q10 回落成峰\nD4：C>Z、Q20[-1]<30、Q20 回升成谷\nD5：Q20[-1]<7、回升成谷、BC<−0.1\nD6：Q20[-1]≤5<Q20、BC<−0.3",
    "boundary": "独立 if，可同根多标；四位舍入后比阈值。J=round4(3K−2D)，RSV9 经系数0.5两次 EMA；前峰>80、当前下降>0.01、前根非 SELL 时 REDUCE，价 H；不等于账户减仓。",
    "source": "公式附册 §4.1–4.2"
  }
} as const
export type NewowFormulaTopic = keyof typeof NEWOW_FORMULA_HELP
