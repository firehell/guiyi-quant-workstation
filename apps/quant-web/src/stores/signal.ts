import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SignalRecord } from '@/types/signal'

export const useSignalStore = defineStore('signal', () => {
  const signals = ref<SignalRecord[]>([])
  const connected = ref(false)

  function addSignal(signal: SignalRecord) {
    signals.value.unshift(signal)
    if (signals.value.length > 200) {
      signals.value = signals.value.slice(0, 200)
    }
  }

  function clearSignals() {
    signals.value = []
  }

  return { signals, connected, addSignal, clearSignals }
})
