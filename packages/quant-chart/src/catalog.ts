import type { VolumePolicy } from './volume.js'

export const CHART_MANIFEST = Object.freeze({
  name: '@guiyi/quant-chart',
  version: '0.1.5',
  catalogSchemaVersion: 1,
  rendererVersion: 1,
  preferenceSchemaVersion: 1,
  lightweightChartsVersion: '5.2.0',
})

export type RendererId = 'candles' | 'line' | 'histogram' | 'band' | 'marker' | 'price_level_zone' | 'primitive'
export type PaneRole = 'main' | 'volume' | 'auxiliary'
type DisplaySource =
  | { type: 'quant_feature'; featureId: string; schema: string; outputs: readonly string[] }
  | { type: 'business_fact'; owner: string }
  | { type: 'display_transform'; version: string }
export interface DisplayDefinition {
  label: string
  pane: PaneRole
  renderers: readonly [RendererId, ...RendererId[]]
  source: DisplaySource
  retrospective?: boolean
  retired?: boolean
}

function feature(
  label: string, featureId: string, schema: string, outputs: readonly string[],
  pane: PaneRole, ...renderers: DisplayDefinition['renderers']
): DisplayDefinition {
  return { label, pane, renderers, source: { type: 'quant_feature', featureId, schema, outputs } }
}

function fact(label: string, owner: string, pane: PaneRole, ...renderers: DisplayDefinition['renderers']): DisplayDefinition {
  return { label, pane, renderers, source: { type: 'business_fact', owner } }
}

function display(label: string, version: string, pane: PaneRole, ...renderers: DisplayDefinition['renderers']): DisplayDefinition {
  return { label, pane, renderers, source: { type: 'display_transform', version } }
}

export const DISPLAY_CATALOG: Readonly<Record<string, DisplayDefinition>> = Object.freeze({
  price: fact('K 线', 'market_data_service.completed_bars', 'main', 'candles'),
  price_preview: fact('未确认 K 线', 'market_data_service.bar_preview', 'main', 'candles'),
  ema_10: feature('EMA10', 'ema10', 'aligned_points_v1', ['value'], 'main', 'line'),
  ema_21: feature('EMA21', 'ema21', 'aligned_points_v1', ['value'], 'main', 'line'),
  ema_60: feature('EMA60', 'ema60', 'aligned_points_v1', ['value'], 'main', 'line'),
  boll: feature('BOLL', 'boll', 'aligned_points_v1', ['upper', 'middle', 'lower'], 'main', 'band', 'line'),
  macd: feature('MACD', 'macd', 'aligned_points_v1', ['dif', 'dea', 'histogram'], 'auxiliary', 'histogram', 'line', 'price_level_zone'),
  atr: feature('ATR', 'atr', 'aligned_points_v1', ['value'], 'auxiliary', 'line'),
  stddev: feature('STDDEV', 'stddev', 'aligned_points_v1', ['value'], 'auxiliary', 'line'),
  obv: feature('OBV', 'obv', 'aligned_points_v1', ['value'], 'auxiliary', 'line'),
  range_detector: feature('箱体识别（Lux Range）', 'range_detector_lux', 'range_detector_v1', ['points', 'ranges'], 'main', 'band', 'primitive'),
  htdy: { ...feature('火天大有（原始观察）', 'htdy_original', 'htdy_original_observation_v1', ['zk1', 'zd1', 'zd2', 'buy_observation', 'sell_observation'], 'main', 'line', 'marker'), retrospective: true },
  ths_macd: display('MACD（同花顺展示）', 'ths_macd_display_v1', 'auxiliary', 'histogram', 'line', 'marker', 'price_level_zone'),
  auxiliary_axis: display('副图时间轴', 'auxiliary_axis_v1', 'auxiliary', 'line', 'price_level_zone'),
  generic_volume: display('成交量', 'guiyi_volume_display_v1', 'volume', 'histogram'),
  subing_volume: display('苏冰成交量倍数', 'subing_volume_tier_display_v1', 'volume', 'histogram', 'primitive'),
  newow_volume: display('牛哇成交量', 'newow_volume_display_v1', 'volume', 'histogram'),
  dynamic_range: fact('动态箱体', 'market_detail.saved_dynamic_range', 'main', 'primitive'),
  saved_reference: fact('保存的价位', 'market_detail.saved_reference_price', 'main', 'line', 'price_level_zone'),
  trade_reference: fact('参考交易价位', 'strategy_reference_trades', 'main', 'line', 'price_level_zone', 'marker'),
  alerts: fact('预警事件', 'alert_event_store', 'main', 'marker'),
  research_actions: fact('研究标记', 'strategy_research_projection', 'main', 'marker'),
  display_markers: display('主图标记排布', 'main_marker_layout_v1', 'main', 'marker'),
  reconciliation_executions: fact('账户对账委托和成交', 'tq_simulation_account.executions', 'main', 'primitive'),
  reconciliation_execution_markers: fact('账户对账成交标记', 'tq_simulation_account.executions', 'main', 'marker'),
  paper_executions: fact('模型委托和成交', 'paper_execution_ledger', 'main', 'primitive'),
  newow_trend: fact('趋势带与通道', 'newow.chart.trend', 'main', 'band', 'line', 'primitive'),
  newow_oscillation: fact('震荡区间', 'newow.chart.oscillation', 'main', 'band', 'line', 'primitive'),
  newow_main_rise: fact('主升浪均线与状态', 'newow.chart.main_rise', 'main', 'line', 'primitive'),
  newow_process: fact('D1–D6 过程提示', 'newow.chart.process_hints', 'main', 'marker'),
  newow_pattern: { ...display('回看形态', 'newow_public_patterns_v3379_v1', 'main', 'primitive'), retrospective: true },
  newow_actions: fact('参考策略动作', 'newow.chart.actions', 'main', 'marker'),
  newow_hints: fact('参考策略提示', 'newow.chart.hints', 'main', 'marker'),
  newow_breakouts: fact('突破形态', 'newow.chart.breakout_events', 'main', 'marker'),
  newow_breakout_reference: display('突破价位', 'newow_oscillation_breakout_line_page_v1', 'main', 'price_level_zone'),
  newow_wicks: fact('影线形态', 'newow.chart.breakout_events', 'main', 'marker'),
  newow_display_events: fact('破位与 J 风险提示', 'newow.chart.display_events', 'main', 'marker'),
  newow_caution: { ...fact('小心提示', 'newow.chart.caution_events', 'main', 'marker'), retrospective: true },
  newow_attack: fact('主力攻击线', 'newow.chart.force_attack', 'main', 'primitive'),
  newow_price_reference: fact('目标价与吸筹价', 'newow.product_detail.price_projection', 'main', 'price_level_zone'),
  newow_detail: display('详细标注', 'newow_detail_labels_v1', 'main', 'marker'),
  newow_donchian: display('唐奇安通道', 'newow_donchian_display_v1', 'main', 'band'),
  newow_stop: display('止损参考线', 'newow_build_stop_display_v1', 'main', 'price_level_zone'),
  newow_annotations: display('高低点与九转', 'newow_chart_annotations_v1', 'main', 'primitive'),
  newow_dual_background: display('双策略得分背景', 'newow_dual_background_v1', 'main', 'primitive'),
  'newow.main_force_control': feature('主力控盘', 'newow.main_force_control', 'newow_auxiliary_v1', ['kongpan', 'status', 'current_status'], 'auxiliary', 'primitive'),
  'newow.up_down_energy': feature('涨跌动能', 'newow.up_down_energy', 'newow_auxiliary_v1', ['var4', 'ma10', 'band_entry', 'rebound_entry', 'oversold_entry', 'var3', 'ma120'], 'auxiliary', 'primitive'),
  'newow.zhaoyao_mirror': { ...feature('主力照妖镜', 'newow.zhaoyao_mirror', 'newow_auxiliary_v1', ['entry', 'wash', 'distribution', 'markup', 'exit', 'inducement', 'peaks', 'caution', 'repainting', 'formal_signal_eligible'], 'auxiliary', 'primitive'), retrospective: true },
  'newow.trend_reversal': feature('趋势转折', 'newow.trend_reversal', 'newow_auxiliary_v1', ['wr1', 'wr2', 'bias', 'rebound', 'adjust', 'ma120', 'hhv', 'llv', 'enough', 'bar_count'], 'auxiliary', 'primitive'),
})

export interface ComputeDisplayManifest {
  compute_contract_version: string
  features: Readonly<Record<string, {
    output_schema_version: string
    outputs: readonly string[]
    allowed_uses: readonly string[]
    repainting: boolean
  }>>
}

export function validateDisplayCatalog(manifest: ComputeDisplayManifest): void {
  if (manifest.compute_contract_version !== 'guiyi_quant_compute_v1') throw new Error('CHART_COMPUTE_CONTRACT_UNSUPPORTED')
  for (const [id, item] of Object.entries(DISPLAY_CATALOG)) {
    const source = item.source
    if (source.type !== 'quant_feature') continue
    const definition = manifest.features[source.featureId]
    if (!definition) throw new Error(`CHART_COMPUTE_FEATURE_UNRESOLVED: ${id} -> ${source.featureId}`)
    if (definition.output_schema_version !== source.schema || source.outputs.some(output => !definition.outputs.includes(output))
      || !definition.allowed_uses.includes('web') || definition.repainting !== Boolean(item.retrospective)) {
      throw new Error(`CHART_COMPUTE_SCHEMA_MISMATCH: ${id} -> ${source.featureId}`)
    }
  }
}

export interface ChartProfile {
  volume: VolumePolicy
  mainDefaults: readonly string[]
  auxiliaryDefault: string | null
  allowed: readonly string[]
}

const generic = ['price', 'price_preview', 'generic_volume', 'ema_10', 'ema_21', 'ema_60', 'boll', 'range_detector', 'dynamic_range',
  'saved_reference', 'trade_reference', 'alerts', 'research_actions', 'display_markers', 'reconciliation_executions',
  'paper_executions', 'auxiliary_axis', 'ths_macd', 'macd', 'atr', 'stddev', 'obv'] as const
const newowDefaults = ['newow_actions', 'newow_hints', 'newow_breakouts', 'newow_wicks', 'newow_detail', 'newow_price_reference', 'newow_annotations'] as const
const newow = ['price', 'price_preview', 'newow_volume', ...newowDefaults, 'newow_pattern', 'newow_stop', 'newow_donchian',
  'newow_display_events', 'newow_caution', 'newow_breakout_reference',
  'newow_dual_background', 'reconciliation_executions', 'paper_executions', 'auxiliary_axis', 'macd', 'newow.main_force_control',
  'newow.up_down_energy', 'newow.zhaoyao_mirror', 'newow.trend_reversal'] as const

function newowProfile(...layers: string[]): ChartProfile {
  return {
    volume: 'newow', mainDefaults: [...newowDefaults, ...layers], auxiliaryDefault: 'newow.zhaoyao_mirror',
    allowed: [...newow, ...layers],
  }
}

export const CHART_PROFILES = Object.freeze({
  free: { volume: 'subing', mainDefaults: [], auxiliaryDefault: 'ths_macd', allowed: [...generic, 'subing_volume'] },
  htdy: { volume: 'subing', mainDefaults: ['htdy'], auxiliaryDefault: 'ths_macd', allowed: [...generic, 'htdy', 'subing_volume', 'reconciliation_execution_markers'] },
  subing: { volume: 'subing', mainDefaults: [], auxiliaryDefault: 'ths_macd', allowed: [...generic, 'subing_volume'] },
  backtest: { volume: 'generic', mainDefaults: [], auxiliaryDefault: null, allowed: generic },
  newow_trend: newowProfile('newow_trend'),
  newow_oscillation: newowProfile('newow_oscillation', 'newow_attack'),
  newow_main_rise: newowProfile('newow_main_rise', 'newow_process'),
  newow_dual: newowProfile('newow_trend', 'newow_oscillation', 'newow_dual_background', 'newow_attack'),
} satisfies Record<string, ChartProfile>)
export type ChartProfileId = keyof typeof CHART_PROFILES
