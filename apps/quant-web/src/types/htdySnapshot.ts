import type { HtdyHistoricalResponse } from './htdyReference.ts'
import type { HistoricalChartAction } from './historicalChartAction.ts'
export interface HtdySnapshot extends HtdyHistoricalResponse {
 snapshot_id: string; generated_at: string; formula_versions: string[]; reference_model_version: string
 executable: false; auto_order: false; actions: HistoricalChartAction[]
 curve: {bar_end:string; value:string; reference_trade_id:string; segment?:string; date?:string}[]
}
