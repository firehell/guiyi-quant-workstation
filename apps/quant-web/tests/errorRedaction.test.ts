import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatApiLogSummary,
  redactSensitiveText,
  toSafeApiError,
  toSafeErrorInfo,
} from '../src/utils/errorRedaction.ts'

test('redactSensitiveText removes absolute unix paths', () => {
  const raw = 'failed reading /Volumes/扩展盘/guiyi-quant-workstation/data/raw/jm.parquet'
  const out = redactSensitiveText(raw)
  assert.equal(out.includes('/Volumes/'), false)
  assert.match(out, /\[redacted-path\]/)
})

test('redactSensitiveText removes tokens and webhooks', () => {
  const raw = 'webhook=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc token=secret123'
  const out = redactSensitiveText(raw)
  assert.equal(out.includes('secret123'), false)
  assert.equal(out.includes('key=abc'), false)
  assert.match(out, /\[redacted\]/)
})

test('redactSensitiveText removes SQL and traceback fragments', () => {
  const raw = 'SELECT * FROM users WHERE id=1 Traceback (most recent call last): File "app.py", line 1'
  const out = redactSensitiveText(raw)
  assert.equal(out.includes('SELECT'), false)
  assert.equal(out.includes('Traceback'), false)
})

test('toSafeErrorInfo keeps error type and suggestion', () => {
  const info = toSafeErrorInfo(
    { code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded' },
    '加载失败',
  )
  assert.equal(info.errorType, 'TIMEOUT')
  assert.match(info.suggestion, /重试/)
})

test('toSafeApiError does not leak file paths from axios detail', () => {
  const msg = toSafeApiError(
    {
      response: {
        status: 500,
        data: { detail: 'open /Users/zhangzhao/.env failed password=hunter2' },
      },
      message: 'Request failed',
    },
    '加载失败',
  )
  assert.equal(msg.includes('/Users/'), false)
  assert.equal(msg.includes('hunter2'), false)
  assert.match(msg, /HTTP_500/)
})

test('formatApiLogSummary stays free of query bodies', () => {
  const line = formatApiLogSummary({
    method: 'GET',
    url: '/data/coverage',
    status: 'ok',
    durationMs: 12,
  })
  assert.equal(line, '[API] GET /data/coverage duration=12ms status=ok')
})
