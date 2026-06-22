<script setup lang="ts">
import { NTag } from 'naive-ui'

defineProps<{
  status: 'running' | 'stopped' | 'error' | 'pending'
}>()

const statusMap = {
  running: { type: 'success' as const, label: '运行中' },
  stopped: { type: 'default' as const, label: '已停止' },
  error: { type: 'error' as const, label: '异常' },
  pending: { type: 'warning' as const, label: '等待中' },
}
</script>

<template>
  <NTag :type="statusMap[$props.status].type" size="small" round>
    {{ statusMap[$props.status].label }}
  </NTag>
</template>
