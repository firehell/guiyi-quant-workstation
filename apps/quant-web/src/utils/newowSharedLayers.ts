import type { NewowAuxiliaryComponent, NewowProductIdentity, NewowProductMeta, NewowProductSectionResponse } from '../types/newowProduct.ts'
import { previewInstant } from './candidatePreviewInstant.ts'

// A retained display must match this client's supported active kernel version.
// Unknown/new formulas continue through the normal fresh-response path only.
const SHARED_AUXILIARY_FORMULAS: Readonly<Record<NewowAuxiliaryComponent, string>> = {
  macd: 'v1-draft',
  main_force_control: 'newow_main_force_control_page_v1',
  up_down_energy: 'newow_up_down_energy_page_v1',
  trend_reversal: 'newow_trend_reversal_core_1_0_0_futures_segment_v1',
  zhaoyao_mirror: 'newow_zhaoyao_mirror_repainting_page_v2',
  cup_handle: 'newow_cup_handle_v1',
}

export function ownsNewowIdentity(response: NewowProductSectionResponse, identity: NewowProductIdentity, asOf?: string): boolean {
  const actual = response.meta.identity
  return actual.product === identity.product && actual.strategy === identity.strategy
    && actual.frequency === identity.frequency && actual.series_kind === identity.seriesKind
    && (asOf === undefined || previewInstant(response.meta.as_of) === previewInstant(asOf))
}

export function newowChartDisplayCacheKey(identity: NewowProductIdentity): string {
  return `newow:${identity.product}:display:chart:${identity.strategy}:${identity.frequency}:${identity.seriesKind}`
}

export function newowAuxiliaryDisplayCacheKey(response: NewowProductSectionResponse<'auxiliary'>): string {
  return `newow:${response.meta.identity.product}:display:auxiliary:${JSON.stringify([
    sharedMarketKey(response.meta), response.value?.component, response.value?.formula_version,
    response.meta.shared_input_proof?.auxiliary_input_sha256,
  ])}`
}

function sharedMarketKey(meta: NewowProductMeta): string | null {
  const proof = meta.shared_input_proof
  const policy = meta.identity.input_quality_policy ?? 'newow_input_quality_v1'
  const expectedAdaptation = meta.identity.frequency === '1w'
    ? policy === 'newow_weekly_input_quality_v2' ? 'newow_futures_weekly_quality_segment_v2' : 'newow_futures_weekly_quality_segment_v1'
    : meta.identity.frequency === '1d' && policy === 'newow_daily_input_quality_v2'
      ? 'newow_futures_daily_quality_segment_v4' : 'newow_futures_quality_segment_v3'
  if (meta.schema_version !== 'newow_product_detail_v4' || proof?.schema_version !== 'newow_shared_input_proof_v1'
    || !/^[a-f0-9]{64}$/.test(proof.market_input_sha256) || previewInstant(meta.as_of) === null
    || meta.identity.series_kind !== 'actual_dominant'
    || !['newow_input_quality_v1', 'newow_daily_input_quality_v2', 'newow_weekly_input_quality_v2'].includes(policy)
    || (policy === 'newow_daily_input_quality_v2' && meta.identity.frequency !== '1d')
    || (policy === 'newow_weekly_input_quality_v2' && meta.identity.frequency !== '1w')
    || meta.futures_adaptation_version !== expectedAdaptation
    || meta.reference_model_version !== 'newow_marker_reference_zero_cost_v4') return null
  return JSON.stringify([
    meta.schema_version, proof.schema_version, proof.market_input_sha256,
    meta.identity.product, meta.identity.frequency, meta.identity.series_kind,
    policy,
    previewInstant(meta.as_of)!.toString(), meta.data_revision_identity,
    meta.futures_adaptation_version, meta.reference_model_version,
  ])
}

/** Display compatibility only: never copies identity, tokens, actions or decisions. */
export function canShareNewowAuxiliary(
  chart: NewowProductSectionResponse | null,
  auxiliary: NewowProductSectionResponse | null,
  component?: NewowAuxiliaryComponent,
): auxiliary is NewowProductSectionResponse<'auxiliary'> {
  if (chart?.section !== 'chart' || chart.value === null || auxiliary?.section !== 'auxiliary'
    || auxiliary.status.status !== 'ready' || auxiliary.value === null) return false
  const marketKey = sharedMarketKey(chart.meta)
  const layer = auxiliary.value
  const auxiliaryHash = auxiliary.meta.shared_input_proof?.auxiliary_input_sha256
  if (marketKey === null || marketKey !== sharedMarketKey(auxiliary.meta)
    || auxiliaryHash == null || !/^[a-f0-9]{64}$/.test(auxiliaryHash)
    || (component !== undefined && layer.component !== component)
    || layer.formula_version !== SHARED_AUXILIARY_FORMULAS[layer.component]) return false
  if (layer.component === 'cup_handle' && (chart.meta.identity.strategy !== 'trend'
    || auxiliary.meta.identity.strategy !== 'trend' || chart.meta.identity.frequency !== '1d')) return false
  if (layer.component === 'macd' && (layer.display_adapter_version !== 'guiyi_newow_macd_display_v1'
    || layer.parameters_hash !== '5dd0ebd25122eea6')) return false
  const owners = new Map(chart.value.bars.map(bar => [bar.bar_end, `${bar.physical_contract}|${bar.calculation_segment_id}`]))
  let overlap = false
  for (const segment of layer.segments) for (const barEnd of segment.bar_ends) {
    const owner = owners.get(barEnd)
    if (owner === undefined) continue
    if (owner !== `${segment.physical_contract}|${segment.segment_id}`) return false
    overlap = true
  }
  return overlap
}
