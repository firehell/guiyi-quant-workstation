import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_API_BASE_URL, normalizeApiBaseURL, resolveWsURL } from '../src/utils/network.ts'

const externalHost = { protocol: 'http:', host: '124.221.95.93', hostname: '124.221.95.93' }
const localHost = { protocol: 'http:', host: '127.0.0.1:5173', hostname: '127.0.0.1' }

test('normalizeApiBaseURL defaults to same-origin /api/v1 when no API base is configured', () => {
  assert.equal(normalizeApiBaseURL(undefined), DEFAULT_API_BASE_URL)
  assert.equal(normalizeApiBaseURL(''), DEFAULT_API_BASE_URL)
})

test('normalizeApiBaseURL preserves configured URL and removes trailing slashes', () => {
  assert.equal(normalizeApiBaseURL('https://workstation.yanyi.com/api/'), 'https://workstation.yanyi.com/api')
  assert.equal(normalizeApiBaseURL('http://127.0.0.1:8000/api/v1', localHost), 'http://127.0.0.1:8000/api/v1')
  assert.equal(normalizeApiBaseURL('/api/v1/'), '/api/v1')
})

test('normalizeApiBaseURL ignores localhost env on external host', () => {
  assert.equal(
    normalizeApiBaseURL('http://localhost:8000/api/v1', externalHost),
    DEFAULT_API_BASE_URL,
  )
  assert.equal(
    normalizeApiBaseURL('http://127.0.0.1:8000/api/v1', externalHost),
    DEFAULT_API_BASE_URL,
  )
})

test('resolveWsURL uses current HTTPS origin when no WebSocket URL is configured', () => {
  assert.equal(
    resolveWsURL(undefined, { protocol: 'https:', host: 'workstation.yanyi.com', hostname: 'workstation.yanyi.com' }),
    'wss://workstation.yanyi.com/api/v1/market/ws',
  )
})

test('resolveWsURL falls back to the market websocket path when no browser location is available', () => {
  assert.equal(resolveWsURL(undefined), '/api/v1/market/ws')
})

test('resolveWsURL preserves explicitly configured WebSocket URL without trailing slashes', () => {
  assert.equal(resolveWsURL('ws://127.0.0.1:8000/ws/', localHost), 'ws://127.0.0.1:8000/ws')
})

test('resolveWsURL ignores localhost env on external host', () => {
  assert.equal(
    resolveWsURL('ws://localhost:8000/ws', externalHost),
    'ws://124.221.95.93/api/v1/market/ws',
  )
})
