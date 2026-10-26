import type { NewowCautionEvent } from '../types/newowProduct.ts'
export const CAUTION_DISPLAY_VERSION = 'guiyi_caution_completed_anchor_v1'

/** Exact display contract; absence never means confirmed or permission to show. */
export function normalizeCautionDisplay(raw: unknown): NewowCautionEvent {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('invalid caution display')
  const e = raw as Record<string, unknown>
  const keys = ['event_id','frequency','bar_end','peak_day','peak_bar_end','first_visible_at','confirmed_at','as_of','tentative','display_state','age_bars','home_visible','detail_visible','max_tentative_age_bars','visibility_basis','display_policy_version','physical_contract','segment_id','calculation_segment_id','formula_version','repainting','page_parity','executable']
  if (keys.some(k=>!(k in e)) || Object.keys(e).some(k=>!keys.includes(k))) throw new Error('incomplete caution display')
  const time = (key: string) => {
    const value=e[key]
    if (typeof value!=='string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error('invalid caution time')
    return Date.parse(value)
  }
  const at=time('bar_end'),peak=time('peak_bar_end'),first=time('first_visible_at'),cutoff=time('as_of')
  const confirmation=e.confirmed_at===null?null:time('confirmed_at')
  if (typeof e.event_id!=='string' || !/^[a-f0-9]{64}$/.test(e.event_id)
    || !['1d','1w','60m','1m','5m','15m','30m'].includes(String(e.frequency))
    || typeof e.peak_day!=='string' || !/^\d{4}-\d{2}-\d{2}$/.test(e.peak_day)
    || ['physical_contract','segment_id','calculation_segment_id'].some(k=>typeof e[k]!=='string'||!e[k])
    || typeof e.tentative!=='boolean' || !['tentative','confirmed'].includes(String(e.display_state))
    || e.tentative!==(e.display_state==='tentative') || e.tentative!==(confirmation===null)
    || !Number.isInteger(e.age_bars) || Number(e.age_bars)<0 || e.home_visible!==(Number(e.age_bars)<=1)
    || e.detail_visible!==true || e.max_tentative_age_bars!==10
    || (e.tentative&&(Number(e.age_bars)>10||first!==at))
    || at>peak || peak>cutoff || first<at || first>cutoff
    || (confirmation!==null&&(confirmation<peak||confirmation>cutoff))
    || e.visibility_basis!=='completed_bar' || e.display_policy_version!==CAUTION_DISPLAY_VERSION
    || e.formula_version!=='newow_zhaoyao_mirror_repainting_page_v2'
    || e.repainting!==true || e.page_parity!==false || e.executable!==false) throw new Error('conflicting caution display')
  return {...e} as unknown as NewowCautionEvent
}

export function cautionDisplayTitle(e: NewowCautionEvent): string {
  const state = e.display_state==='tentative' ? '暂定峰，尚未回落5%确认' : `已确认于 ${e.confirmed_at}`
  return `首次可见 ${e.first_visible_at} · 峰位置 ${e.peak_day} · ${state} · 已完成K线参考，非交易信号`
}
