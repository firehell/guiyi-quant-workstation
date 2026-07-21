/**
 * 将 API / 运行时错误转为可展示文案：保留错误类型与建议，脱敏路径与密钥。
 */

const ABSOLUTE_PATH_RE =
  /(?:^|[\s"'`(=])((?:\/(?:Users|Volumes|home|var|tmp|opt|root|private)\/[^\s"'`)}\]]+)|(?:[A-Za-z]:\\[^\s"'`)}\]]+))/g

const SECRET_RE =
  /(?:webhook|token|password|passwd|cookie|license|authorization|api[_-]?key|secret)[=:\s]+[^\s,;]+/gi

const SQL_RE =
  /\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|ALTER|DROP)\b[\s\S]{0,200}/gi

const TRACEBACK_RE = /(?:Traceback \(most recent call last\):|File ".*?", line \d+)/gi

export type SafeErrorInfo = {
  message: string
  errorType: string
  suggestion: string
}

function classifyError(err: unknown): { errorType: string; raw: string } {
  if (err == null) return { errorType: 'UNKNOWN', raw: '' }
  if (typeof err === 'string') return { errorType: 'MESSAGE', raw: err }

  const anyErr = err as {
    code?: string
    message?: string
    name?: string
    response?: { status?: number; data?: { detail?: unknown; message?: unknown } }
  }

  if (anyErr.response?.status) {
    const detail = anyErr.response.data?.detail ?? anyErr.response.data?.message
    const raw =
      typeof detail === 'string'
        ? detail
        : detail != null
          ? JSON.stringify(detail)
          : anyErr.message || `HTTP ${anyErr.response.status}`
    return { errorType: `HTTP_${anyErr.response.status}`, raw }
  }

  if (anyErr.code === 'ECONNABORTED' || /timeout/i.test(anyErr.message || '')) {
    return { errorType: 'TIMEOUT', raw: anyErr.message || 'request timeout' }
  }

  if (anyErr.code === 'ERR_NETWORK' || /Network Error/i.test(anyErr.message || '')) {
    return { errorType: 'NETWORK', raw: anyErr.message || 'network error' }
  }

  return {
    errorType: anyErr.code || anyErr.name || 'UNKNOWN',
    raw: anyErr.message || String(err),
  }
}

/** 脱敏敏感片段，供日志与 UI 共用。 */
export function redactSensitiveText(input: string): string {
  let text = input
  text = text.replace(ABSOLUTE_PATH_RE, (_m, path: string) => {
    const prefix = _m.slice(0, _m.indexOf(path))
    return `${prefix}[redacted-path]`
  })
  text = text.replace(SECRET_RE, (m) => {
    const key = m.split(/[=:\s]/)[0]
    return `${key}=[redacted]`
  })
  text = text.replace(SQL_RE, '[redacted-sql]')
  text = text.replace(TRACEBACK_RE, '[redacted-traceback]')
  // 兜底：长 Unix 绝对路径
  text = text.replace(/(?:^|[\s])(\/(?:[\w.-]+\/){2,}[\w.-]+)/g, (m, path: string) =>
    m.replace(path, '[redacted-path]'),
  )
  return text.trim()
}

function suggestionFor(errorType: string): string {
  if (errorType === 'TIMEOUT') return '请求超时，请缩小查询范围后重试。'
  if (errorType === 'NETWORK') return '网络不可用，请检查 API 连接后重试。'
  if (errorType === 'HTTP_404') return '资源不存在或已归档，请刷新列表。'
  if (errorType === 'HTTP_401' || errorType === 'HTTP_403') return '无权限访问该资源。'
  if (errorType.startsWith('HTTP_5')) return '服务暂时不可用，请稍后重试。'
  return '请重试；若持续失败，查看运行状态页。'
}

/**
 * 将任意错误转为安全展示信息（不含路径 / token / SQL / traceback）。
 */
export function toSafeErrorInfo(err: unknown, fallback = '操作失败'): SafeErrorInfo {
  const { errorType, raw } = classifyError(err)
  const redacted = redactSensitiveText(raw)
  const message =
    redacted && redacted !== '[redacted-path]' && redacted !== '[redacted-sql]'
      ? redacted
      : fallback
  return {
    message: message.slice(0, 280),
    errorType,
    suggestion: suggestionFor(errorType),
  }
}

/** 页面常用：单行安全错误文案（含类型提示）。 */
export function toSafeApiError(err: unknown, fallback: string): string {
  const info = toSafeErrorInfo(err, fallback)
  if (info.message === fallback) return `${fallback}（${info.errorType}）。${info.suggestion}`
  return `${info.message}（${info.errorType}）。${info.suggestion}`
}

/** 开发环境日志摘要：仅方法、路径、类型与耗时，不含 body / 密钥。 */
export function formatApiLogSummary(parts: {
  method: string
  url: string
  status: 'ok' | 'error'
  durationMs: number
  errorType?: string
}): string {
  const base = `[API] ${parts.method} ${parts.url} duration=${parts.durationMs}ms status=${parts.status}`
  return parts.errorType ? `${base} type=${parts.errorType}` : base
}

export function isProductionBuild(): boolean {
  return import.meta.env.PROD === true
}
