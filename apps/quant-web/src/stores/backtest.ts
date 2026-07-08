import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useBacktestStore = defineStore('backtest', () => {
  const selectedReportId = ref<number | null>(null)

  function setSelectedReportId(reportId: number | null) {
    selectedReportId.value = reportId
  }

  return { selectedReportId, setSelectedReportId }
})
