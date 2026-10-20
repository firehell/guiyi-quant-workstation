import { formatDecimalText } from './marketDisplay.ts'
import type { FrozenRecord, FuturesPart, FuturesCurve, FuturesCurveKind } from '../types/newowFutures.ts'
const strategies:Record<string,string>={trend:'趋势策略',oscillation:'震荡策略',dual_fusion:'双策略',main_rise:'主升浪','osc-test':'测试','osc-test2':'测试2','osc-test3':'测试3','osc-test4':'测试4'}
const actions:Record<string,string>={OPEN_LONG:'开多',OPEN_SHORT:'开空',BUILD:'建仓',OPEN:'开仓',ENTER:'安排开仓',CLOSE:'清仓',ADD:'加仓',REDUCE:'减仓',UPGRADE:'升级持有周期',WAIT:'等待',CANCEL:'取消待执行动作',REJECT:'拒绝执行',UNFILLED:'未成交',INTERRUPT:'中断'}
const reasons:Record<string,string>={
  READY:'数据已就绪',COMPLETED:'历史研究已完成',NO_ENTRY:'未出现入场条件',HOLD:'继续持有',ENTRY_TREND:'趋势突破入场',ENTRY_OSCILLATION:'震荡边界入场',ENTRY_MAIN_RISE:'主升浪突破入场',
  MIN_LOT_BUDGET:'资金或风险预算不足，无法开出最小一手',INSUFFICIENT_CAPITAL:'资金不足',ADD_NOT_PROFITABLE:'当前未盈利，未加仓',MIN_LOT_NOT_DIVISIBLE:'仅一手或最小单位不可拆分，未减仓',
  INPUT_UNAVAILABLE:'输入数据不完整',DATA_INSUFFICIENT:'历史数据不足',EXECUTION_FACTS_MISSING:'缺少权威执行事实，模型账户收益不可用',DATA_INTERRUPTED:'数据中断',ROLLOVER_INTERRUPTED:'换月中断，未跨合约续接',PENDING_UNFILLED:'存在未成交动作',
  DAILY_HALT:'当日停止开仓',DAILY_RISK_HALT:'触发当日风控，停止开仓并安排平仓',PROTECTIVE_CLOSE:'触发收盘保护',HOLDING_TREND_EXIT:'持有周期趋势退出',DAY_ONLY_CLOSE:'未满足跨日条件，日内收尾',DAY_END_OPEN_PROHIBITED:'临近日内收尾，禁止开仓',
  OVERNIGHT_ELIGIBILITY_LOST:'跨日资格失效',HOLDING_PERIOD_UPGRADED:'持有周期已升级',UPGRADE_ADD:'周期升级后加仓',BASE_TREND_REDUCTION:'入场周期趋势走弱，减仓',OSC_TARGET:'到达震荡目标',OSC_CONFIRM_REVERSAL:'目标后确认反转退出',
  ZERO_VOLUME:'执行时无成交量，保持未成交',LIMIT_BLOCKED:'涨跌停限制，保持未成交',COOLDOWN:'平仓后等待完整周期',ENTRY_NO_LONGER_VALID:'执行前入场条件已失效',OBSERVATION_INELIGIBLE:'该时段不属于观察范围',NOT_APPLICABLE:'当前策略不适用于该周期',OOS_NOT_PROVEN:'尚未证明样本外表现',RESEARCH_NOT_COVERED:'该品种尚未纳入本轮研究',RESULT_NOT_FOUND:'没有匹配的冻结研究结果',CURVE_BOUNDARY_BUDGET_EXCEEDED:'曲线区段超出显示预算，暂不绘制',
}
export const futuresStrategyLabel=(value:unknown)=>strategies[String(value)]??'未知策略'
export const futuresStateLabel=(value:unknown)=>({LONG:'多头',SHORT:'空头',FLAT:'空仓',UNAVAILABLE:'未知'}[String(value)]??'未知')
export const futuresFrequencyLabel=(value:unknown)=>value==='1d'?'日线':value==='1w'?'周线':typeof value==='string'&&/^\d+m$/.test(value)?`${value.slice(0,-1)}分钟`:'未知'
export const futuresAction=(value:unknown)=>actions[String(value)]??'未识别动作'
export function futuresReason(value:unknown):string{return reasons[String(value)]??(typeof value==='string'&&value.startsWith('SUPERSEDED_BY_')?`已由更高优先级的${futuresAction(value.slice(14))}替代`:'未识别原因')}
export const knownFuturesReason=(value:unknown)=>futuresReason(value)!=='未识别原因'
export const futuresStatus=(value:unknown)=>({OPEN:'持有中',CLOSED:'已完成',UNAVAILABLE:'未知'}[String(value)]??futuresReason(value))
export const futuresNumber=(value:unknown)=>typeof value==='string'||typeof value==='number'?formatDecimalText(String(value),{maximumFractionDigits:2,minimumFractionDigits:2}):'—'
export function futuresTime(value:unknown):string {
  if(typeof value!=='string'||!Number.isFinite(Date.parse(value)))return '—'
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value))
}
export interface FuturesColumn{key:string;label:string;kind?:'number'|'time'|'side'|'status'|'frequency'|'reason'|'action'}
export function futuresTradeColumns(part:FuturesPart):FuturesColumn[]{
  if(part==='decisions')return [{key:'at',label:'决策时间',kind:'time'},{key:'action',label:'动作',kind:'action'},{key:'side',label:'方向',kind:'side'},{key:'holding_frequency',label:'持有周期',kind:'frequency'},{key:'reason',label:'原因',kind:'reason'}]
  if(part==='equity')return [{key:'at',label:'估值时间',kind:'time'},{key:'physical_contract',label:'合约'},{key:'equity',label:'模型账户权益（元）',kind:'number'}]
  if(part==='fills')return [{key:'at',label:'模拟成交时间',kind:'time'},{key:'action',label:'动作',kind:'action'},{key:'side',label:'方向',kind:'side'},{key:'physical_contract',label:'合约'},{key:'qty',label:'手数'},{key:'price',label:'模拟成交价',kind:'number'},{key:'fee',label:'手续费（元）',kind:'number'},{key:'net_pnl',label:'净盈亏（元）',kind:'number'},{key:'reason',label:'原因',kind:'reason'}]
  const reference=part==='reference-trades'
  return [{key:'side',label:'方向',kind:'side'},{key:'status',label:'状态',kind:'status'},{key:'physical_contract',label:'合约'},
    {key:reference?'entry_bar_end':'entry_at',label:'入场时间',kind:'time'},{key:reference?'entry_reference_price':'entry_price',label:reference?'参考入场价':'模拟入场价',kind:'number'},
    {key:reference?'exit_bar_end':'exit_at',label:'退出时间',kind:'time'},{key:reference?'exit_reference_price':'exit_price',label:reference?'参考退出价':'模拟退出价',kind:'number'},
    {key:'qty',label:reference?'累计参考单位层':'手数'},{key:'holding_frequency',label:'持有周期',kind:'frequency'},
    {key:reference?'reference_return_pct':'net_pnl',label:reference?'参考收益（百分点）':'净盈亏（元）',kind:'number'},{key:'reason',label:'原因',kind:'reason'}]
}
export function futuresTableValue(row:FrozenRecord,column:FuturesColumn):string{
  const value=row[column.key]
  if(value===null||value===undefined)return '—'
  switch(column.kind){case'number':return futuresNumber(value);case'time':return futuresTime(value);case'side':return futuresStateLabel(value);case'status':return futuresStatus(value);case'frequency':return futuresFrequencyLabel(value);case'reason':return futuresReason(value);case'action':return futuresAction(value);default:return String(value)}
}
export function validateFuturesCurve(curve:FuturesCurve,runId:string,sha256:string,kind:FuturesCurveKind,asOf:string):FuturesCurve{
  if(curve.run_id!==runId||curve.sha256!==sha256||curve.kind!==kind||!Array.isArray(curve.points)||curve.points.length>2000||!Number.isInteger(curve.total_points)||curve.total_points<curve.points.length||typeof curve.sampled!=='boolean'
    ||(!curve.sampled&&curve.status==='COMPLETED'&&curve.total_points!==curve.points.length)||!['COMPLETED','CURVE_BOUNDARY_BUDGET_EXCEEDED'].includes(curve.status))throw new Error('RESULT_CURVE_IDENTITY_MISMATCH')
  let previous=-Infinity
  for(const point of curve.points){const time=Date.parse(point.at);if(!Number.isFinite(time)||time<=previous||time>Date.parse(asOf)||!/(?:Z|[+-]\d\d:\d\d)$/.test(point.at)||typeof point.value!=='string'||!Number.isFinite(Number(point.value)))throw new Error('RESULT_CURVE_INVALID');previous=time}
  return curve
}
export function futuresCurvePoints(curve:FuturesCurve){return curve.points.map(point=>({value:Number(point.value),date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date(point.at)),position:Date.parse(point.at),segment:point.physical_contract??'frozen-account'}))}

export const futuresAsOfLabel=(kind:unknown)=>kind==='publication_time_only'?'生成时间':'截至'
