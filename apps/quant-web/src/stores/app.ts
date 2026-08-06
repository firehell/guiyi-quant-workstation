import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 全局应用状态：仅保留应用内布局与主题状态。 */
export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const theme = ref<'light' | 'dark'>('dark')

  /** 切换侧边栏展开/折叠 */
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  /** 在浅色与深色主题间切换 */
  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  return {
    sidebarCollapsed,
    theme,
    toggleSidebar,
    toggleTheme,
  }
})
