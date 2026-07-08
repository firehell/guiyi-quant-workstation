import { defineStore } from 'pinia'
import { ref } from 'vue'
import { normalizeApiBaseURL } from '@/utils/network'
import { loadAppSettings, saveAppSettings, type AppSettings } from '@/utils/settings'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const theme = ref<'light' | 'dark'>('dark')
  const settings = ref<AppSettings>(loadAppSettings())
  const apiBaseUrl = ref(
    settings.value.apiBaseUrl || normalizeApiBaseURL(import.meta.env.VITE_API_BASE_URL) || '',
  )
  const wsUrl = ref(settings.value.wsUrl || import.meta.env.VITE_WS_URL || '')

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  function updateSettings(next: AppSettings) {
    settings.value = next
    apiBaseUrl.value = next.apiBaseUrl
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
