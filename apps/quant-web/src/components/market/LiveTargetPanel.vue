<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAlert, NCard, NSpin, NTag } from 'naive-ui'
import { getLiveTargets } from '@/api/market'
import type { LiveTargetContractsResponse } from '@/types/market'
import StatusTag from '@/components/common/StatusTag.vue'

const props = withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  { compact: false },
)

const loading = ref(false)
const error = ref<string | null>(null)
const targets = ref<LiveTargetContractsResponse | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    targets.value = await getLiveTargets()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 live targets 失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

defineExpose({ reload: load })
</script>

<template>
  <NCard class="live-target" :class="{ 'live-target--compact': compact }" :title="compact ? undefined : 'Live 目标合约池'" size="small" :bordered="!compact">
    <NSpin :show="loading">
      <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
      <template v-else-if="targets">
        <div class="live-target__summary">
          <StatusTag :status="targets.readiness_status" />
          <NTag size="small" type="warning">Preview Only</NTag>
          <span v-if="targets.trade_date" class="live-target__muted">映射日 {{ targets.trade_date }}</span>
        </div>
        <div class="live-target__items">
          <div v-for="item in targets.items" :key="item.product" class="live-target__item">
            <div class="live-target__row">
              <strong>{{ item.product.toUpperCase() }}</strong>
              <StatusTag :status="item.readiness_status" />
            </div>
            <div class="live-target__row live-target__muted">
              <span>主连 {{ item.continuous_contract }}</span>
              <span>真实 {{ item.actual_contract || '—' }}</span>
            </div>
            <div v-if="item.blocked_reasons.length" class="live-target__blocked">
              {{ item.blocked_reasons.join(' · ') }}
            </div>
          </div>
        </div>
        <NAlert type="info" :bordered="false" style="margin-top: 8px">
          只读观察，不写 SignalEvent，不自动下单。
        </NAlert>
      </template>
    </NSpin>
  </NCard>
</template>

<style scoped>
.live-target {
  min-width: 0;
  background: var(--gy-bg-panel);
  container-type: inline-size;
}

.live-target__summary {
  display: flex;
  align-items: center;
  gap: var(--gy-space-2);
  margin-bottom: var(--gy-space-3);
  flex-wrap: wrap;
}

.live-target__items {
  display: grid;
  gap: var(--gy-space-2);
}

.live-target__item + .live-target__item {
  padding-top: var(--gy-space-2);
  border-top: 1px solid var(--gy-border);
}

.live-target__row {
  display: flex;
  justify-content: space-between;
  gap: var(--gy-space-2);
  font-size: var(--gy-font-size-base);
}

.live-target__muted {
  color: var(--gy-text-muted);
}

.live-target__blocked {
  margin-top: 4px;
  font-size: var(--gy-font-size-sm);
  color: var(--gy-status-warning);
}

.live-target--compact :deep(.n-spin-content) {
  display: grid;
  grid-template-columns: 1fr;
  align-items: center;
  gap: var(--gy-space-4);
}

.live-target--compact .live-target__summary {
  margin-bottom: 0;
}

.live-target--compact .live-target__items {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.live-target--compact :deep(.n-alert) {
  margin-top: 0 !important;
}

@container (min-width: 700px) {
  .live-target--compact :deep(.n-spin-content) {
    grid-template-columns: auto minmax(0, 1fr) minmax(260px, auto);
  }
}
</style>
