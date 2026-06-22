import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getStrategies } from '@/api/strategy'
import type { StrategyInfo } from '@/types/strategy'

export const useStrategyStore = defineStore('strategy', () => {
  const strategies = ref<StrategyInfo[]>([])
  const loading = ref(false)

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
