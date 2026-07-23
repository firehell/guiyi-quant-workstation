import { defineStore } from 'pinia'
import { ref } from 'vue'
import { normalizeApiBaseURL } from '@/utils/network'
import { loadAppSettings, saveAppSettings, type AppSettings } from '@/utils/settings'

/** 全局应用状态：布局、主题、API/WS 地址与用户设置 */
export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const theme = ref<'light' | 'dark'>('dark')
  const settings = ref<AppSettings>(loadAppSettings())
  // 优先用户设置，其次 Vite 环境变量
  const apiBaseUrl = ref(
    settings.value.apiBaseUrl.trim()
      || normalizeApiBaseURL(import.meta.env.VITE_API_BASE_URL),
  )
  const wsUrl = ref(settings.value.wsUrl || import.meta.env.VITE_WS_URL || '')

  /** 切换侧边栏展开/折叠 */
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  /** 在浅色与深色主题间切换 */
  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  /** 更新用户设置；API/WS 地址仅保留在当前 session。 */
  function updateSettings(next: AppSettings) {
    settings.value = next
    apiBaseUrl.value = next.apiBaseUrl.trim() || normalizeApiBaseURL(import.meta.env.VITE_API_BASE_URL)
    wsUrl.value = next.wsUrl
    saveAppSettings(next)
  }

  return {
    sidebarCollapsed,
    theme,
    settings,
    apiBaseUrl,
    wsUrl,
    toggleSidebar,
    toggleTheme,
    updateSettings,
  }
})
