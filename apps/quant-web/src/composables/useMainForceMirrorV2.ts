import { ref } from 'vue'

import type {
  MainForceMirrorV2Identity,
  MainForceMirrorV2Indicator,
  MainForceMirrorV2MemberDataset,
  MainForceMirrorV2PageRequest,
  MainForceMirrorV2PageResponse,
  MainForceMirrorV2Point,
  MainForceMirrorV2RequestIdentity,
} from '../types/market.ts'

const DEFAULT_PAGE_LIMIT = 1200
const UNAVAILABLE_MESSAGE = '主力照妖镜 V2 暂不可用'

export interface MainForceMirrorV2Dependencies {
  fetchPage?: (params: MainForceMirrorV2PageRequest) => Promise<MainForceMirrorV2PageResponse>
}

async function defaultFetchPage(
  params: MainForceMirrorV2PageRequest,
): Promise<MainForceMirrorV2PageResponse> {
  const { getMainForceMirrorV2Page } = await import('../api/market')
  return getMainForceMirrorV2Page(params)
}

function toRequest(
  identity: MainForceMirrorV2Identity,
  before: string | null = null,
): MainForceMirrorV2PageRequest {
  return {
    series_kind: identity.seriesKind,
    symbol: identity.symbol,
    contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    frequency: identity.frequency,
    before,
    limit: identity.limit ?? DEFAULT_PAGE_LIMIT,
  }
}

function sameRequestIdentity(
  actual: MainForceMirrorV2RequestIdentity,
  expected: MainForceMirrorV2PageRequest,
): boolean {
  return actual.series_kind === expected.series_kind
    && actual.symbol === expected.symbol
    && actual.contract === (expected.contract ?? null)
    && actual.frequency === expected.frequency
    && actual.before === expected.before
    && actual.limit === expected.limit
}

function sameIndicator(left: MainForceMirrorV2Indicator, right: MainForceMirrorV2Indicator): boolean {
  return left.indicator_code === right.indicator_code
    && left.indicator_version === right.indicator_version
    && left.formal_policy_id === right.formal_policy_id
    && left.parameters_hash === right.parameters_hash
    && left.interpretation === right.interpretation
    && left.observation_only === right.observation_only
    && left.historical_only === right.historical_only
    && left.auto_order === right.auto_order
}

function sameMemberDataset(
  left: MainForceMirrorV2MemberDataset,
  right: MainForceMirrorV2MemberDataset,
): boolean {
  return left.status === right.status
    && left.dataset_id === right.dataset_id
    && left.schema_version === right.schema_version
    && left.admitted_product === right.admitted_product
    && left.coverage?.start === right.coverage?.start
    && left.coverage?.end === right.coverage?.end
}

function mergePoints(
  current: MainForceMirrorV2Point[],
  incoming: MainForceMirrorV2Point[],
): MainForceMirrorV2Point[] {
  const byEnd = new Map(current.map((point) => [point.bar_end, point]))
  for (const point of incoming) byEnd.set(point.bar_end, point)
  return [...byEnd.values()].sort((left, right) => left.bar_end.localeCompare(right.bar_end))
}

export function useMainForceMirrorV2(dependencies: MainForceMirrorV2Dependencies = {}) {
  const points = ref<MainForceMirrorV2Point[]>([])
  const memberDataset = ref<MainForceMirrorV2MemberDataset | null>(null)
  const canonicalEnd = ref<string | null>(null)
  const nextBefore = ref<string | null>(null)
  const hasMoreBefore = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const fetchPage = dependencies.fetchPage ?? defaultFetchPage
  let generation = 0
  let identity: MainForceMirrorV2Identity | null = null
  let indicator: MainForceMirrorV2Indicator | null = null

  function clearPageState(): void {
    points.value = []
    memberDataset.value = null
    canonicalEnd.value = null
    nextBefore.value = null
    hasMoreBefore.value = false
  }

  function failCurrentRequest(): void {
    clearPageState()
    identity = null
    indicator = null
    error.value = UNAVAILABLE_MESSAGE
  }

  function acceptReplacement(page: MainForceMirrorV2PageResponse, request: MainForceMirrorV2PageRequest): boolean {
    if (!sameRequestIdentity(page.request, request)) return false
    points.value = mergePoints([], page.points)
    memberDataset.value = page.member_dataset
    canonicalEnd.value = points.value.at(-1)?.bar_end ?? null
    nextBefore.value = page.page.next_before
    hasMoreBefore.value = page.page.has_more_before
    indicator = page.indicator
    return true
  }

  function acceptsPrepend(page: MainForceMirrorV2PageResponse, request: MainForceMirrorV2PageRequest): boolean {
    return memberDataset.value !== null
      && indicator !== null
      && sameRequestIdentity(page.request, request)
      && sameIndicator(page.indicator, indicator)
      && sameMemberDataset(page.member_dataset, memberDataset.value)
  }

  async function replace(nextIdentity: MainForceMirrorV2Identity): Promise<void> {
    const requestGeneration = ++generation
    identity = { ...nextIdentity }
    indicator = null
    clearPageState()
    error.value = null
    loading.value = true
    const request = toRequest(nextIdentity)
    try {
      const page = await fetchPage(request)
      if (requestGeneration !== generation) return
      if (!acceptReplacement(page, request)) failCurrentRequest()
    } catch {
      if (requestGeneration === generation) failCurrentRequest()
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  async function loadMoreBefore(): Promise<void> {
    if (!identity || !hasMoreBefore.value || nextBefore.value === null || loading.value) return
    const requestGeneration = generation
    const request = toRequest(identity, nextBefore.value)
    loading.value = true
    try {
      const page = await fetchPage(request)
      if (requestGeneration !== generation) return
      if (!acceptsPrepend(page, request)) {
        failCurrentRequest()
        return
      }
      points.value = mergePoints(points.value, page.points)
      nextBefore.value = page.page.next_before
      hasMoreBefore.value = page.page.has_more_before
    } catch {
      if (requestGeneration === generation) failCurrentRequest()
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function clear(): void {
    generation += 1
    identity = null
    indicator = null
    clearPageState()
    error.value = null
    loading.value = false
  }

  return {
    points,
    memberDataset,
    canonicalEnd,
    nextBefore,
    hasMoreBefore,
    loading,
    error,
    replace,
    loadMoreBefore,
    clear,
  }
}
