import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getStrategies } from '@/api/strategy'
import type { StrategyInfo } from '@/types/strategy'

/** 策略列表缓存，供下拉选择与回测表单复用 */
export const useStrategyStore = defineStore('strategy', () => {
  const strategies = ref<StrategyInfo[]>([])
  const loading = ref(false)

  /** 从后端拉取策略列表并更新本地缓存 */
  async function fetchStrategies() {
    loading.value = true
    try {
      strategies.value = await getStrategies()
    } finally {
      loading.value = false
    }
  }

  return { strategies, loading, fetchStrategies }
})
