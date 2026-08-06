import assert from 'node:assert/strict'
import { afterEach, beforeEach, describe, it } from 'node:test'

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() { return this.values.size }
  clear() { this.values.clear() }
  getItem(key: string) { return this.values.get(key) ?? null }
  key(index: number) { return [...this.values.keys()][index] ?? null }
  removeItem(key: string) { this.values.delete(key) }
  setItem(key: string, value: string) { this.values.set(key, value) }
}

describe('settings storage security', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: new MemoryStorage(), configurable: true })
    Object.defineProperty(globalThis, 'sessionStorage', { value: new MemoryStorage(), configurable: true })
  })

  afterEach(() => {
    delete (globalThis as { localStorage?: Storage }).localStorage
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage
  })

  it('does not expose browser-persisted application or connection settings', async () => {
    const settings = await import('../src/utils/settings.ts')

    assert.equal('loadAppSettings' in settings, false)
    assert.equal('saveAppSettings' in settings, false)
    assert.equal('resolvedApiBaseUrl' in settings, false)
    assert.equal('resolvedWsUrl' in settings, false)
  })

  it('purges legacy bearer token and application/connection storage keys', async () => {
    localStorage.setItem('token', 'legacy-secret')
    localStorage.setItem('guiyi_app_settings', '{"apiBaseUrl":"http://legacy.invalid"}')
    sessionStorage.setItem('guiyi_connection_overrides', '{"wsUrl":"ws://legacy.invalid"}')
    const { purgeLegacyWebCredentials } = await import('../src/utils/settings.ts')
    purgeLegacyWebCredentials()
    assert.equal(localStorage.getItem('token'), null)
    assert.equal(sessionStorage.getItem('token'), null)
    assert.equal(localStorage.getItem('guiyi_app_settings'), null)
    assert.equal(sessionStorage.getItem('guiyi_connection_overrides'), null)
  })
})
