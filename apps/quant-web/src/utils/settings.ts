const STORAGE_KEY = 'guiyi_app_settings'
const CONNECTION_STORAGE_KEY = 'guiyi_connection_overrides'

/** 删除旧 Web 凭据与连接/应用设置；连接仅由 Vite 环境或同源默认值决定。 */
export function purgeLegacyWebCredentials() {
  storageOf('local')?.removeItem('token')
  storageOf('session')?.removeItem('token')
  storageOf('local')?.removeItem(STORAGE_KEY)
  storageOf('session')?.removeItem(CONNECTION_STORAGE_KEY)
}

function storageOf(kind: 'local' | 'session'): Storage | null {
  if (typeof globalThis === 'undefined') return null
  return kind === 'local'
    ? (typeof globalThis.localStorage === 'undefined' ? null : globalThis.localStorage)
    : (typeof globalThis.sessionStorage === 'undefined' ? null : globalThis.sessionStorage)
}
