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

  it('keeps connection overrides in sessionStorage and display preferences in localStorage', async () => {
    const { loadAppSettings, saveAppSettings } = await import('../src/utils/settings.ts')
    saveAppSettings({
      apiBaseUrl: 'http://127.0.0.1:8010',
      wsUrl: 'ws://127.0.0.1:8010/ws',
      defaultExchange: 'DCE',
      redUpGreenDown: true,
    })
    assert.doesNotMatch(localStorage.getItem('guiyi_app_settings') || '', /8010|apiBaseUrl|wsUrl/)
    assert.match(sessionStorage.getItem('guiyi_connection_overrides') || '', /8010/)
    assert.equal(loadAppSettings().apiBaseUrl, 'http://127.0.0.1:8010')
  })

  it('purges legacy bearer token and never migrates it', async () => {
    localStorage.setItem('token', 'legacy-secret')
    const { purgeLegacyWebCredentials } = await import('../src/utils/settings.ts')
    purgeLegacyWebCredentials()
    assert.equal(localStorage.getItem('token'), null)
    assert.equal(sessionStorage.getItem('token'), null)
  })
})
