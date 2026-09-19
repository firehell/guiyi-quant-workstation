export interface KlineReferenceCallout { id: string; time: string; physicalContract: string; price: string; title: string; detail: string; tone: 'gain' | 'loss' | 'neutral'; above: boolean }
export interface KlineReferenceSelection { time: string; physicalContract: string }
export interface KlineReferenceIndicator { bar_end: string; physical_contract: string; segment_id: string; calculation_segment_id?: string; dif: string | null; dea: string | null; macd: string | null; ema21: string | null }
export interface KlineQualityBreak { id: string; time: string; label: string; detail: string }
