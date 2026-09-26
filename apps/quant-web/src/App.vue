<script setup lang="ts">
/** 根组件：Naive UI 主题、消息 Provider 与路由出口 */
import { NConfigProvider, NMessageProvider } from 'naive-ui'
import { themeOverrides } from '@/styles/theme'
import { onMounted, ref } from 'vue'
import { candidatePreview, matchesPreviewIdentity } from './utils/candidatePreview.ts'

const previewReady = ref(!candidatePreview.enabled)
const previewState = ref('正在核对候选 API 身份')
onMounted(async () => {
  if (!candidatePreview.enabled) return
  try {
    const response = await fetch('/api/preview/identity', { cache: 'no-store', signal: AbortSignal.timeout(10000) })
    if (!response.ok || !matchesPreviewIdentity(await response.json())) throw new Error()
    previewReady.value = true
    previewState.value = '身份已核对'
  } catch {
    previewState.value = 'PREVIEW_IDENTITY_MISMATCH：候选 API 不可用或版本、截止时间不匹配'
  }
})
</script>

<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <NMessageProvider>
      <p v-if="candidatePreview.enabled && !previewReady" role="status">{{ previewState }}</p>
      <RouterView v-if="previewReady" />
    </NMessageProvider>
  </NConfigProvider>
</template>
