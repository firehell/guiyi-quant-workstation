import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_API_BASE_URL, normalizeApiBaseURL, resolveWsURL } from '../src/utils/network.ts'

test('normalizeApiBaseURL defaults to same-origin /api/v1 when no API base is configured', () => {
  assert.equal(normalizeApiBaseURL(undefined), DEFAULT_API_BASE_URL)
  assert.equal(normalizeApiBaseURL(''), DEFAULT_API_BASE_URL)
})

test('normalizeApiBaseURL preserves configured URL and removes trailing slashes', () => {
  assert.equal(normalizeApiBaseURL('https://workstation.yanyi.com/api/'), 'https://workstation.yanyi.com/api')
  assert.equal(normalizeApiBaseURL('http://127.0.0.1:8000/api/v1'), 'http://127.0.0.1:8000/api/v1')
  assert.equal(normalizeApiBaseURL('/api/v1/'), '/api/v1')
})

test('resolveWsURL uses current HTTPS origin when no WebSocket URL is configured', () => {
  assert.equal(
    resolveWsURL(undefined, { protocol: 'https:', host: 'workstation.yanyi.com' }),
    'wss://workstation.yanyi.com/ws',
  )
})

test('resolveWsURL falls back to relative /ws when no browser location is available', () => {
  assert.equal(resolveWsURL(undefined), '/ws')
})

test('resolveWsURL preserves explicitly configured WebSocket URL without trailing slashes', () => {
  assert.equal(resolveWsURL('ws://127.0.0.1:8000/ws/'), 'ws://127.0.0.1:8000/ws')
})
