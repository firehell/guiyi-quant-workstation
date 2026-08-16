import type {
  Decision,
  DecisionUpdateRequest,
  DispositionCorrectionRequest,
  DispositionCorrectionResponse,
  EpisodeDetailResponse,
  EventReconstructionResponse,
  EventStatesResponse,
  ExecutedRequest,
  ExecutedResponse,
  ExecutionCreateRequest,
  ExecutionResponse,
  ExecutionReviewStatsResponse,
  ExecutionUpdateRequest,
  NotExecutedRequest,
  ReconstructionMode,
  Review,
  ReviewItemFilters,
  ReviewItemsResponse,
  ReviewRequest,
  StatsFilters,
  TimelineReplaceRequest,
  TimelineResponse,
} from '@/types/executionReview'
import type { AxiosRequestConfig } from './request.ts'

interface HttpClient {
  get(url: string, config?: AxiosRequestConfig): Promise<unknown>
  post(url: string, body?: unknown): Promise<unknown>
  put(url: string, body?: unknown): Promise<unknown>
}

export class ExecutionReviewApiError extends Error {
  readonly code: string
  readonly httpStatus: number | null

  constructor(code: string, httpStatus: number | null) {
    super(code)
    this.name = 'ExecutionReviewApiError'
    this.code = code
    this.httpStatus = httpStatus
  }
}

export function toExecutionReviewApiError(error: unknown): ExecutionReviewApiError {
  if (error instanceof ExecutionReviewApiError) return error
  const response = isRecord(error) && isRecord(error.response) ? error.response : null
  const status = response && typeof response.status === 'number' ? response.status : null
  const data = response && isRecord(response.data) ? response.data : null
  const detail = data && isRecord(data.detail) ? data.detail : null
  const code = detail && typeof detail.code === 'string' ? detail.code : 'UNKNOWN'
  return new ExecutionReviewApiError(code, status)
}

const ERROR_MESSAGES: Record<string, string> = {
  OPPOSITE_EPISODE_OPEN: '当前已有反方向交易记录，请先完成原交易',
  OPEN_EPISODE_CONFLICT: '当前存在其他合约的未结束交易记录',
  ROLL_RECONCILIATION_REQUIRED: '主力换月事实暂无法唯一确认，请稍后处理',
  DECISION_ALREADY_EXISTS: '该信号已处理，请刷新查看最新状态',
  EPISODE_ALREADY_CLOSED: '该交易已结束，请刷新记录',
}

export function executionReviewErrorMessage(error: unknown): string {
  const safe = toExecutionReviewApiError(error)
  return ERROR_MESSAGES[safe.code] || '操作暂未完成，请刷新后重试'
}

export function createExecutionReviewApi(client?: HttpClient) {
  const http: HttpClient = client ?? {
    get: async (url, config) => (await import('./request.ts')).default.get(url, config),
    post: async (url, body) => (await import('./request.ts')).default.post(url, body),
    put: async (url, body) => (await import('./request.ts')).default.put(url, body),
  }
  const call = async <T>(operation: () => Promise<unknown>): Promise<T> => {
    try {
      return await operation() as T
    } catch (error) {
      throw toExecutionReviewApiError(error)
    }
  }

  return {
    listItems: (filters: ReviewItemFilters) => call<ReviewItemsResponse>(
      () => http.get('/api/execution-review/items', { params: filters }),
    ),
    getEventStates: (eventIds: number[]) => {
      const params = new URLSearchParams()
      for (const eventId of eventIds) params.append('event_ids', String(eventId))
      return call<EventStatesResponse>(
        () => http.get('/api/execution-review/event-states', { params }),
      )
    },
    getEpisodeDetail: (episodeId: number) => call<EpisodeDetailResponse>(
      () => http.get(`/api/execution-review/episodes/${episodeId}`),
    ),
    getReconstruction: (eventId: number, mode: ReconstructionMode = 'signal') => (
      call<EventReconstructionResponse>(
        () => http.get(`/api/execution-review/events/${eventId}/reconstruction`, { params: { mode } }),
      )
    ),
    getStats: (filters: StatsFilters = {}) => call<ExecutionReviewStatsResponse>(
      () => http.get('/api/execution-review/stats', { params: filters }),
    ),
    recordNotExecuted: (eventId: number, body: NotExecutedRequest) => call<Decision>(
      () => http.post(`/api/execution-review/events/${eventId}/not-executed`, body),
    ),
    recordExecuted: (eventId: number, body: ExecutedRequest) => call<ExecutedResponse>(
      () => http.post(`/api/execution-review/events/${eventId}/executed`, body),
    ),
    appendExecution: (episodeId: number, body: ExecutionCreateRequest) => call<ExecutionResponse>(
      () => http.post(`/api/execution-review/episodes/${episodeId}/executions`, body),
    ),
    submitReview: (episodeId: number, body: ReviewRequest) => call<Review>(
      () => http.post(`/api/execution-review/episodes/${episodeId}/review`, body),
    ),
    updateDecision: (decisionId: number, body: DecisionUpdateRequest) => call<Decision>(
      () => http.put(`/api/execution-review/decisions/${decisionId}`, body),
    ),
    updateExecution: (executionId: number, body: ExecutionUpdateRequest) => call<ExecutionResponse>(
      () => http.put(`/api/execution-review/executions/${executionId}`, body),
    ),
    replaceExecutionTimeline: (episodeId: number, body: TimelineReplaceRequest) => call<TimelineResponse>(
      () => http.put(`/api/execution-review/episodes/${episodeId}/execution-timeline`, body),
    ),
    updateReview: (reviewId: number, body: ReviewRequest) => call<Review>(
      () => http.put(`/api/execution-review/reviews/${reviewId}`, body),
    ),
    correctDisposition: (decisionId: number, body: DispositionCorrectionRequest) => call<DispositionCorrectionResponse>(
      () => http.post(`/api/execution-review/decisions/${decisionId}/correct-disposition`, body),
    ),
  }
}

const api = createExecutionReviewApi()

export const listItems = api.listItems
export const getEventStates = api.getEventStates
export const getEpisodeDetail = api.getEpisodeDetail
export const getReconstruction = api.getReconstruction
export const getStats = api.getStats
export const recordNotExecuted = api.recordNotExecuted
export const recordExecuted = api.recordExecuted
export const appendExecution = api.appendExecution
export const submitReview = api.submitReview
export const updateDecision = api.updateDecision
export const updateExecution = api.updateExecution
export const replaceExecutionTimeline = api.replaceExecutionTimeline
export const updateReview = api.updateReview
export const correctDisposition = api.correctDisposition

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
