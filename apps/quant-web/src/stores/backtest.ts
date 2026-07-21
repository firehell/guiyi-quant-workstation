import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 回测模块跨页面共享状态（当前选中的报告 ID） */
export const useBacktestStore = defineStore('backtest', () => {
  const selectedReportId = ref<number | null>(null)

  /** 设置当前选中的回测报告，传 null 表示取消选中 */
  function setSelectedReportId(reportId: number | null) {
    selectedReportId.value = reportId
  }

  return { selectedReportId, setSelectedReportId }
})
