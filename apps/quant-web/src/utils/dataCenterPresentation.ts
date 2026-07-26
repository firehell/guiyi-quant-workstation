import { summarizeDataVersion } from './marketEvidencePresentation.ts'

type CoverageLike = {
  provider?: string | null
  data_role?: string | null
  quality_status?: string | null
  binding_status?: string | null
  latest_bar_time?: string | null
  end_time?: string | null
  data_version?: string | null
}

const ACTIVE_PROVIDERS = new Set(['rqdata', 'local_parquet'])

function formatTimestamp(value: string | null): string {
  if (!value) return '未提供'
  return value.replace('T', ' ').slice(0, 16)
}

export function buildDataCenterOverview(rows: CoverageLike[]) {
  const qualityCounts = new Map<string, number>()
  rows.forEach((row) => {
    const status = row.quality_status || 'unknown'
    qualityCounts.set(status, (qualityCounts.get(status) || 0) + 1)
  })
  const failed = qualityCounts.get('failed') || 0
  const warning = qualityCounts.get('warning') || 0
  const unbound = rows.filter((row) => row.binding_status !== 'active').length
  const latest = rows
    .map((row) => row.latest_bar_time || row.end_time || '')
    .filter(Boolean)
    .sort()
    .at(-1) || null
  const versions = rows.map((row) => row.data_version || '').filter(Boolean)
  const eligibleAssets = rows.filter(
    (row) =>
      ACTIVE_PROVIDERS.has(row.provider || '') &&
      row.data_role === 'primary' &&
      row.quality_status !== 'failed',
  ).length

  let priority = '当前快照无明确阻塞'
  if (failed) priority = `先处理 ${failed} 个 failed 资产`
  else if (warning) priority = `复核 ${warning} 个 warning 资产`
  else if (unbound) priority = `检查 ${unbound} 个未绑定资产`

  return {
    latestDate: formatTimestamp(latest),
    eligibleAssets,
    qualitySummary: [...qualityCounts.entries()]
      .map(([status, count]) => `${count} ${status}`)
      .join(' · ') || '暂无质量事实',
    priority,
    versionSummary: summarizeDataVersion(versions.at(-1), versions, rows.length),
  }
}
