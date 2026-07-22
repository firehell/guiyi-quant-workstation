<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NButton, NTooltip } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useRuntimePulseStore } from '@/stores/runtimePulse'

const router = useRouter()
const pulse = useRuntimePulseStore()
const { status, loading, error, generatedAt } = storeToRefs(pulse)

const stateClass = computed(() => {
  if (error.value) return 'system-pulse--error'
  if (status.value === 'ok') return 'system-pulse--ok'
  if (status.value === 'failed') return 'system-pulse--error'
  return 'system-pulse--warning'
})

const tooltip = computed(() => {
  if (error.value) return error.value
  return generatedAt.value ? `只读快照 ${generatedAt.value}` : '等待只读运行态快照'
})
</script>

<template>
  <NTooltip placement="bottom">
    <template #trigger>
      <NButton
        quaternary
        size="small"
        class="system-pulse"
        :class="stateClass"
        :loading="loading"
        aria-label="System Pulse"
        @click="router.push({ name: 'runtime' })"
      >
        <span class="system-pulse__dot" aria-hidden="true" />
        <span>System Pulse</span>
        <strong>{{ error ? 'unavailable' : status }}</strong>
      </NButton>
    </template>
    {{ tooltip }}
  </NTooltip>
</template>

<style scoped>
.system-pulse {
  --pulse-color: var(--gy-status-warning);
  color: var(--gy-text-secondary);
}

.system-pulse--ok {
  --pulse-color: var(--gy-status-ok);
}

.system-pulse--error {
  --pulse-color: var(--gy-status-error);
}

.system-pulse__dot {
  width: 7px;
  height: 7px;
  margin-right: 6px;
  background: var(--pulse-color);
  border-radius: 50%;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pulse-color) 18%, transparent);
}

.system-pulse strong {
  margin-left: 6px;
  color: var(--pulse-color);
  font-family: var(--gy-font-mono);
  font-size: 10px;
  font-weight: 600;
}

@media (max-width: 1199px) {
  .system-pulse span:not(.system-pulse__dot) {
    display: none;
  }
}
</style>
