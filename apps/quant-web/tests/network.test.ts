import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeApiBaseURL, resolveWsURL } from '../src/utils/network.ts'

test('normalizeApiBaseURL uses same-origin when no API base is configured', () => {
  assert.equal(normalizeApiBaseURL(undefined), '')
  assert.equal(normalizeApiBaseURL(''), '')
})

test('normalizeApiBaseURL removes trailing API path and slashes from configured URL', () => {
  assert.equal(normalizeApiBaseURL('https://workstation.yanyi.com/api/'), 'https://workstation.yanyi.com')
  assert.equal(normalizeApiBaseURL('http://127.0.0.1:8000/api/v1'), 'http://127.0.0.1:8000')
})

test('resolveWsURL uses current HTTPS origin when no WebSocket URL is configured', () => {
  assert.equal(
    resolveWsURL(undefined, { protocol: 'https:', host: 'workstation.yanyi.com' }),
    'wss://workstation.yanyi.com/ws',
  )
})

test('resolveWsURL preserves explicitly configured WebSocket URL without trailing slashes', () => {
  assert.equal(resolveWsURL('ws://127.0.0.1:8000/ws/'), 'ws://127.0.0.1:8000/ws')
})
