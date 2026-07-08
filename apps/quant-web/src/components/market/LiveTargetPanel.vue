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
  <NCard :title="compact ? undefined : 'Live 目标合约池'" size="small" :bordered="!compact">
    <NSpin :show="loading">
      <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
      <template v-else-if="targets">
        <div class="live-target__summary">
          <StatusTag :status="targets.readiness_status" />
          <NTag size="small" type="warning">Preview Only</NTag>
          <span v-if="targets.trade_date" class="live-target__muted">映射日 {{ targets.trade_date }}</span>
        </div>
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
        <NAlert type="info" :bordered="false" style="margin-top: 8px">
          只读观察，不写 SignalEvent，不自动下单。
        </NAlert>
      </template>
    </NSpin>
  </NCard>
</template>

<style scoped>
.live-target__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.live-target__item + .live-target__item {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--gy-border, #2a3344);
}

.live-target__row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.live-target__muted {
  color: var(--gy-text-muted, #94a3b8);
}

.live-target__blocked {
  margin-top: 4px;
  font-size: 12px;
  color: #f59e0b;
}
</style>
