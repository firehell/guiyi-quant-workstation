import { defineStore } from 'pinia'
import { ref } from 'vue'
import { normalizeApiBaseURL } from '@/utils/network'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const theme = ref<'light' | 'dark'>('light')
  const apiBaseUrl = ref(normalizeApiBaseURL(import.meta.env.VITE_API_BASE_URL) || 'same-origin')

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  return { sidebarCollapsed, theme, apiBaseUrl, toggleSidebar, toggleTheme }
})
