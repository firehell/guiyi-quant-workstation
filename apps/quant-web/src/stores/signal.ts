import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SignalRecord } from '@/types/signal'

/** 实时信号流状态，由 WebSocket 推送写入 */
export const useSignalStore = defineStore('signal', () => {
  const signals = ref<SignalRecord[]>([])
  /** WebSocket 连接是否就绪，由信号页维护 */
  const connected = ref(false)

  /** 将新信号插入列表头部，超出上限时截断保留最新 200 条 */
  function addSignal(signal: SignalRecord) {
    signals.value.unshift(signal)
    if (signals.value.length > 200) {
      signals.value = signals.value.slice(0, 200)
    }
  }

  /** 清空本地信号缓存 */
  function clearSignals() {
    signals.value = []
  }

  return { signals, connected, addSignal, clearSignals }
})
