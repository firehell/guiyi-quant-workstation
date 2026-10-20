import type { FrozenRecord, FuturesPart, FuturesSnapshot } from '../types/newowFutures.ts'
import { futuresChartMarkers } from './newowFuturesSnapshot.ts'
import { futuresTime } from './newowFuturesPresentation.ts'
export type FuturesLocateEndpoint='entry'|'exit'|'at'
export function futuresRecordKey(row:FrozenRecord):string{return String(row.reference_trade_id??row.trade_id??row.action_id??row.decision_id??[row.at,row.action,row.physical_contract].join(':'))}
export function locateFuturesRecord(packet:FuturesSnapshot,row:FrozenRecord,endpoint:FuturesLocateEndpoint,source:FuturesPart|'reference-actions'):
  {kind:'unavailable';message:string}|{kind:'located';message:string;barEnd:string;physicalContract:string;sourceAt:string}{
  const raw=endpoint==='entry'?row.entry_bar_end??row.entry_at:endpoint==='exit'?row.exit_bar_end??row.exit_at:row.at??row.bar_end
  if(typeof raw!=='string'||!Number.isFinite(Date.parse(raw)))return {kind:'unavailable',message:'该记录没有可定位的实际时间'}
  const bars=packet.chart.bars,time=Date.parse(raw)
  if(!bars.length||time<Date.parse(String(bars[0]!.bar_end))||time>Date.parse(String(bars.at(-1)!.bar_end)))return {kind:'unavailable',message:'超出当前冻结图表窗口'}
  if(typeof row.physical_contract!=='string')return {kind:'unavailable',message:'记录缺少物理合约身份，无法精确定位'}
  let target=raw
  if(source==='reference-actions'&&endpoint==='at'){
    const proof=packet.reference.actions.find(action=>action.action_id===row.action_id&&action.at===row.at&&action.bar_end===row.bar_end&&action.physical_contract===row.physical_contract)
    if(proof){const marker=futuresChartMarkers(packet).find(marker=>marker.id===String(proof.action_id));if(marker)target=marker.time}
  }
  const bar=bars.find(bar=>Date.parse(String(bar.bar_end))===Date.parse(target)&&bar.physical_contract===row.physical_contract
    &&(!row.owner_segment_id||bar.owner_segment_id===row.owner_segment_id))
  if(!bar)return {kind:'unavailable',message:'该实际时间与合约没有对应的冻结图表Bar，无法精确定位'}
  return {kind:'located',sourceAt:raw,barEnd:String(bar.bar_end),physicalContract:String(bar.physical_contract),message:Date.parse(raw)===Date.parse(String(bar.bar_end))?`已定位 ${futuresTime(raw)} · ${bar.physical_contract}`:`实际 ${futuresTime(raw)}，图上归入 ${futuresTime(bar.bar_end)} · ${bar.physical_contract}`}
}
