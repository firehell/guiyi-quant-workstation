<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NButtonGroup, NCard, NDescriptions, NDescriptionsItem, NSpin, NTag } from 'naive-ui'
import { executionReviewErrorMessage, getReconstruction } from '@/api/executionReview'
import type { Direction, EventReconstructionResponse, ReconstructionMode, ReconstructionReason } from '@/types/executionReview'
import { initialReconstructionMode } from '@/utils/executionReview'

const props = defineProps<{ eventId: number; direction: Direction }>()
const result = ref<EventReconstructionResponse | null>(null)
const mode = ref<ReconstructionMode>(initialReconstructionMode())
const loading = ref(false)
const error = ref('')
let generation = 0

const reasonText: Record<ReconstructionReason, string> = {
  MARKET_HISTORY_NOT_READY: '正式历史行情尚未就绪',
  MARKET_IDENTITY_CONFLICT: '历史主力身份与信号合约不一致',
  MARKET_PARTITION_UNAVAILABLE: '历史行情分区暂不可用',
}

async function load(requestedMode: ReconstructionMode) {
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const next = await getReconstruction(props.eventId, requestedMode)
    if (current === generation) result.value = next
  } catch (reason) {
    if (current === generation) error.value = executionReviewErrorMessage(reason)
  } finally {
    if (current === generation) loading.value = false
  }
}

function setMode(next: ReconstructionMode) {
  if (mode.value === next) return
  mode.value = next
  void load(next)
}

watch(() => props.eventId, () => {
  mode.value = initialReconstructionMode()
  result.value = null
  void load(mode.value)
})

onMounted(() => void load(mode.value))
</script>

<template>
  <NCard class="reconstruction" data-testid="reconstruction-panel" size="small">
    <template #header>
      <div class="reconstruction__header">
        <div>
          <strong>Post-hoc reconstruction</strong>
          <span>事后历史重建</span>
        </div>
        <NButtonGroup size="small">
          <NButton :type="mode === 'signal' ? 'primary' : 'default'" @click="setMode('signal')">信号当时</NButton>
          <NButton :type="mode === 'full' ? 'primary' : 'default'" @click="setMode('full')">完整走势</NButton>
        </NButtonGroup>
      </div>
    </template>
    <NSpin :show="loading">
      <NAlert v-if="error" type="warning">{{ error }}</NAlert>
      <template v-else-if="result">
        <NDescriptions :column="2" size="small" label-placement="left">
          <NDescriptionsItem label="品种 / 合约">{{ result.event.symbol.toUpperCase() }} / {{ result.event.contract }}</NDescriptionsItem>
          <NDescriptionsItem label="方向">{{ direction }}</NDescriptionsItem>
          <NDescriptionsItem label="周期 / Bar">{{ result.event.frequency }} / {{ result.event.bar_end }}</NDescriptionsItem>
          <NDescriptionsItem label="5m 同向确认">{{ result.event.lower_tf_confirmation ? '是' : '否' }}</NDescriptionsItem>
        </NDescriptions>
        <NAlert v-if="result.status === 'UNAVAILABLE'" type="warning" class="reconstruction__availability">
          <strong>历史行情暂不可重建</strong>
          <span>{{ result.reason ? reasonText[result.reason] : '正式历史行情暂不可用' }}</span>
        </NAlert>
        <div v-else class="reconstruction__bars">
          <NTag :bordered="false">5m {{ result.bars_5m.length }} 根</NTag>
          <NTag :bordered="false">15m {{ result.bars_15m.length }} 根</NTag>
          <span v-if="result.window">窗口 {{ result.window.start_trading_day }} → {{ result.window.end_trading_day }}</span>
        </div>
      </template>
    </NSpin>
  </NCard>
</template>

<style scoped>
.reconstruction__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.reconstruction__header > div { display: grid; gap: 2px; }
.reconstruction__header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.reconstruction__availability { margin-top: 12px; }
.reconstruction__availability :deep(.n-alert-body__content) { display: grid; gap: 3px; }
.reconstruction__bars { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
@media (max-width: 760px) { .reconstruction__header { align-items: flex-start; flex-direction: column; } }
</style>
