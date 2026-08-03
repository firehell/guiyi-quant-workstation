import type { MarketAccessMode } from '@/types/market'

export type MarketQualificationTone = 'success' | 'warning' | 'error' | 'info'

export interface MarketQualificationInput {
  accessMode: MarketAccessMode
  strictResearchReady: boolean
  qualityStatus: string | null | undefined
  profileId: string | null | undefined
  canonicalIdentity?: boolean
}

export interface MarketQualificationPresentation {
  label: string
  tone: MarketQualificationTone
  summary: string
}

function recognizedDateTokens(value: string) {
  return [...value.matchAll(/20\d{6}/g)]
    .map((match) => match[0])
    .filter((token) => {
      const year = Number(token.slice(0, 4))
      const month = Number(token.slice(4, 6))
      const day = Number(token.slice(6, 8))
      const date = new Date(Date.UTC(year, month - 1, day))
      return (
        date.getUTCFullYear() === year &&
        date.getUTCMonth() === month - 1 &&
        date.getUTCDate() === day
      )
    })
}

function latestVersionToken(value: string) {
  const matches = [...value.matchAll(/(?:^|[^a-z0-9])v(\d+)(?=$|[^a-z0-9])/gi)]
  const version = matches.at(-1)?.[1]
  return version ? `v${version}` : null
}

function formatDateToken(token: string) {
  return `${token.slice(0, 4)}-${token.slice(4, 6)}-${token.slice(6, 8)}`
}

/**
 * 将机器 data_version 提炼成可读摘要。原值始终由 evidence drawer 单独展示；
 * 无法可靠识别时不截断、不猜测含义。
 */
export function summarizeDataVersion(
  rawVersion: string | null | undefined,
  dataVersions: string[],
  assetCount: number,
): string {
  const values = [rawVersion || '', ...dataVersions].filter(Boolean)
  const latestDate = values.flatMap(recognizedDateTokens).sort().at(-1)
  const count = assetCount > 0 ? assetCount : new Set(dataVersions.filter(Boolean)).size

  if (count > 1 && latestDate) {
    return `${count} 个资产版本 · 最新 ${formatDateToken(latestDate)}`
  }
  if (!latestDate) return '版本已绑定'

  const version = latestVersionToken(rawVersion || values.at(-1) || '')
  return version
    ? `${formatDateToken(latestDate)} · ${version}`
    : formatDateToken(latestDate)
}

/** 将后端资格事实映射为用户可读文案，不改变任何访问或质量语义。 */
export function buildMarketQualificationPresentation(
  input: MarketQualificationInput,
): MarketQualificationPresentation {
  const qualityStatus = (input.qualityStatus || 'unknown').toLowerCase()

  if (qualityStatus === 'failed') {
    return {
      label: '数据不可用',
      tone: 'error',
      summary: '数据质量未通过，不能用于当前研究。',
    }
  }
  if (input.accessMode === 'research' && !input.profileId && !input.canonicalIdentity) {
    return {
      label: '缺少 Profile',
      tone: 'warning',
      summary: '严格研究必须先选择明确的 Profile。',
    }
  }
  if (input.accessMode === 'research' && input.strictResearchReady && qualityStatus === 'passed') {
    return {
      label: '可严格研究',
      tone: 'success',
      summary: input.canonicalIdentity
        ? 'DatasetKey、manifest 与 exact window 已通过严格研究资格校验。'
        : 'Profile 与 lineage 已通过严格研究资格校验。',
    }
  }
  if (qualityStatus === 'warning') {
    return {
      label: '仅观察',
      tone: 'warning',
      summary:
        input.accessMode === 'browser'
          ? '当前为浏览模式且数据质量存在警告，不可作为严格研究输入。'
          : '当前数据质量存在警告，不具备严格研究资格。',
    }
  }
  if (input.accessMode === 'browser') {
    return {
      label: '仅观察',
      tone: 'info',
      summary: '浏览模式用于行情观察，不代表严格研究资格。',
    }
  }
  return {
    label: '资格待确认',
    tone: 'info',
    summary: input.canonicalIdentity
      ? '等待 DatasetKey、manifest、质量与 exact window 资格证据。'
      : '等待 Profile、质量与 lineage 资格证据。',
  }
}
