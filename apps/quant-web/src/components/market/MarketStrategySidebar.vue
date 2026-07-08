<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NButton, NTag } from 'naive-ui'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import type { BacktestReport } from '@/types/backtest'
import type { StrategySignalRecord } from '@/types/signal'

const props = defineProps<{
  isLiveMode: boolean
  strategyStatus: { label: string; type: 'default' | 'success' | 'warning' | 'error' | 'info'; text: string }
  barsCount: number
  linkedReport?: BacktestReport | null
  latestSignal?: StrategySignalRecord | null
}>()

const emit = defineEmits<{
  openReport: []
  openSignal: []
}>()

const contractSummary = computed(() => {
  const signal = props.latestSignal
  if (!signal) return null
  return {
    continuous: signal.features?.continuous_contract || signal.contract,
    actual: signal.actual_contract || signal.features?.actual_contract || '—',
  }
})
</script>

<template>
  <aside class="strategy-sidebar">
    <LiveTargetPanel compact />

    <section class="side-panel">
      <div class="side-panel__title">
        <span>{{ isLiveMode ? 'Live 策略观察' : '策略状态' }}</span>
        <NTag size="small" :type="strategyStatus.type">{{ strategyStatus.label }}</NTag>
      </div>
      <p>{{ strategyStatus.text }}</p>
      <div class="signal-row">
        <span>K线数量</span>
        <strong>{{ barsCount.toLocaleString('zh-CN') }}</strong>
      </div>
      <div v-if="contractSummary" class="signal-row">
        <span>主连 / 真实</span>
        <strong>{{ contractSummary.continuous }} / {{ contractSummary.actual }}</strong>
      </div>
      <NAlert type="warning" :bordered="false">观察提醒，非交易指令，不自动下单。</NAlert>
      <NButton v-if="latestSignal" size="small" block @click="emit('openSignal')">查看关联信号</NButton>
      <NButton v-if="linkedReport" size="small" secondary block @click="emit('openReport')">返回报告 #{{ linkedReport.id }}</NButton>
    </section>
  </aside>
</template>

<style scoped>
.strategy-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.side-panel {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: 8px;
  padding: 12px;
}

.side-panel__title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.side-panel p {
  color: var(--gy-text-muted);
  font-size: 13px;
  margin-bottom: 8px;
}

.signal-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}
</style>
