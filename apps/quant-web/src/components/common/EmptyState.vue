<script setup lang="ts">
import { NEmpty } from 'naive-ui'

defineProps<{
  description?: string
}>()
</script>

<template>
  <NEmpty :description="$props.description || '暂无数据'" style="padding: 40px 0" />
</template>
