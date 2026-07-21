<script setup lang="ts">
/** 状态标签：将后端状态字符串映射为 Naive UI Tag 色型 */
import { computed } from 'vue'
import { NTag } from 'naive-ui'

const props = defineProps<{
  status: string
  domain?: 'system' | 'quality' | 'task'
}>()

/** success / error / warning / info / default 五档映射 */
const tagMeta = computed(() => {
  const normalized = props.status.toLowerCase()
  if (['ready', 'passed', 'success', 'completed', 'running', 'active_passed', 'ok', 'healthy', 'live'].includes(normalized)) {
    return { type: 'success' as const, label: props.status }
  }
  if (['blocked', 'failed', 'error', 'partial_failed', 'down', 'unhealthy'].includes(normalized)) {
    return { type: 'error' as const, label: props.status }
  }
  if (['warning', 'partial', 'active_partial', 'pending', 'queued', 'audit_pending'].includes(normalized)) {
    return { type: 'warning' as const, label: props.status }
  }
  if (['info', 'readonly', 'research_only', 'preview'].includes(normalized)) {
    return { type: 'info' as const, label: props.status }
  }
  return { type: 'default' as const, label: props.status || 'unknown' }
})
</script>

<template>
  <NTag :type="tagMeta.type" size="small" round :data-domain="domain || 'system'">
    {{ tagMeta.label }}
  </NTag>
</template>
