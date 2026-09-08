export interface KlineReferenceCallout { id: string; time: string; physicalContract: string; price: string; title: string; detail: string; tone: 'gain' | 'loss' | 'neutral'; above: boolean }
export interface KlineReferenceSelection { time: string; physicalContract: string }
