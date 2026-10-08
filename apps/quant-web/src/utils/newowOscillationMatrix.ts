// Public AI_ADVICE_MATRIX, snapshot 3.3.79, SHA256 661da186d387bf553bc17b37bee5fbc1e1a5649a4b2312da4cb0704cb41e7ae6.
// Historical 27-row explanation only; never changes strategy/exposure or adopts newer page decisions.
export const OSCILLATION_MATRIX = {
  "holding-holding-holding": {
    "label": "周日共振建仓",
    "advice": "吸筹洗盘完成，坚定持有",
    "granularity": "日线",
    "risk": "bullish",
    "riskLabel": "积极做多"
  },
  "holding-holding-cleared": {
    "label": "周日建仓·日内兑现",
    "advice": "60min 拉高兑现后低吸回补",
    "granularity": "60分钟",
    "risk": "bullish",
    "riskLabel": "积极做多"
  },
  "holding-holding-idle": {
    "label": "周日建仓·日内观望",
    "advice": "持仓待 60min 建仓信号",
    "granularity": "60分钟",
    "risk": "bullish",
    "riskLabel": "积极做多"
  },
  "holding-cleared-holding": {
    "label": "日线兑现·日内已回补",
    "advice": "日线已兑现、60分钟回补，仅作提示，不改动周线底仓",
    "granularity": "60分钟",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "holding-cleared-cleared": {
    "label": "周线独撑·短周期离场",
    "advice": "周线仍持仓、日线已兑现，仅作提示，不改动现有仓位。关注周线是否转弱",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "holding-cleared-idle": {
    "label": "波段持仓·日线已兑现",
    "advice": "波段持仓、日线已兑现，仅作提示，不改动现有仓位",
    "granularity": "60分钟",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "holding-idle-holding": {
    "label": "周线建仓·日内试盘",
    "advice": "等日线确认建仓信号",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "holding-idle-cleared": {
    "label": "周线建仓·短周期离场",
    "advice": "观察日线方向",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "holding-idle-idle": {
    "label": "周线建仓·待日线确认",
    "advice": "等日线跟上再加大仓位",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "cleared-holding-holding": {
    "label": "周线离场·短周期博弈",
    "advice": "仅短线参与，不追高",
    "granularity": "60分钟",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "cleared-holding-cleared": {
    "label": "周线离场·日内兑现",
    "advice": "等周线信号再定",
    "granularity": "日线",
    "risk": "warning",
    "riskLabel": "减仓观望"
  },
  "cleared-holding-idle": {
    "label": "周线离场·日线试仓",
    "advice": "观察周线是否修复",
    "granularity": "日线",
    "risk": "warning",
    "riskLabel": "减仓观望"
  },
  "cleared-cleared-holding": {
    "label": "周日离场·60分试盘",
    "advice": "60min 试盘，等大周期确认",
    "granularity": "60分钟",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "cleared-cleared-cleared": {
    "label": "全周期离场",
    "advice": "拉高出货完成，空仓观望",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "cleared-cleared-idle": {
    "label": "周日共振离场",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "cleared-idle-holding": {
    "label": "周线离场·60分试盘",
    "advice": "谨慎参与，快进快出",
    "granularity": "60分钟",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "cleared-idle-cleared": {
    "label": "周线离场·日内试仓",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "cleared-idle-idle": {
    "label": "周线离场",
    "advice": "空仓等待新信号",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "idle-holding-holding": {
    "label": "日线建仓·多周期共振",
    "advice": "跟随日线信号建仓",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "idle-holding-cleared": {
    "label": "日线试仓已兑现",
    "advice": "观察周线是否跟上",
    "granularity": "日线",
    "risk": "warning",
    "riskLabel": "减仓观望"
  },
  "idle-holding-idle": {
    "label": "日线建仓中",
    "advice": "观察周线是否跟上",
    "granularity": "日线",
    "risk": "cautious",
    "riskLabel": "谨慎持仓"
  },
  "idle-cleared-holding": {
    "label": "日线清仓·60分试盘",
    "advice": "谨慎参与",
    "granularity": "60分钟",
    "risk": "warning",
    "riskLabel": "减仓观望"
  },
  "idle-cleared-cleared": {
    "label": "日线清仓·短周期离场",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "idle-cleared-idle": {
    "label": "日线清仓",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "idle-idle-holding": {
    "label": "60分试仓",
    "advice": "试盘，等周/日确认",
    "granularity": "60分钟",
    "risk": "warning",
    "riskLabel": "减仓观望"
  },
  "idle-idle-cleared": {
    "label": "60分短暂离场",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  },
  "idle-idle-idle": {
    "label": "暂无信号",
    "advice": "空仓等待",
    "granularity": "观望",
    "risk": "bearish",
    "riskLabel": "空仓防御"
  }
} as const
