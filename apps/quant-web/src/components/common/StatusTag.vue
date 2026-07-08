<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'

const props = defineProps<{
  status: string
}>()

const tagMeta = computed(() => {
  const normalized = props.status.toLowerCase()
  if (['ready', 'passed', 'success', 'completed', 'running', 'active_passed'].includes(normalized)) {
    return { type: 'success' as const, label: props.status }
  }
  if (['blocked', 'failed', 'error', 'partial_failed'].includes(normalized)) {
    return { type: 'error' as const, label: props.status }
  }
  if (['warning', 'partial', 'active_partial', 'pending', 'queued', 'audit_pending'].includes(normalized)) {
    return { type: 'warning' as const, label: props.status }
  }
  return { type: 'default' as const, label: props.status || 'unknown' }
})
</script>

<template>
  <NTag :type="tagMeta.type" size="small" round>
    {{ tagMeta.label }}
  </NTag>
</template>
