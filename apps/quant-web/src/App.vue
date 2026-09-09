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
      <aside v-if="candidatePreview.enabled" data-testid="candidate-preview-banner" class="candidate-preview-banner">
        本地候选只读预览 · 非实时 · {{ previewState }}<br>
        代码 {{ candidatePreview.codeSha }} · K线 / 牛哇截止上限 {{ candidatePreview.asOf }}<br>
        候选查询来源 127.0.0.1:8010；首页投影与主力元数据使用各自时间戳。<br>
        受监督正式状态来源 127.0.0.1:8000，仅 Runtime health / 当前事件，保留各自时间戳。<br>
        仅首页与牛哇视角可预览；其他接口明确返回 PREVIEW_ROUTE_FORBIDDEN。
      </aside>
      <RouterView v-if="previewReady" />
    </NMessageProvider>
  </NConfigProvider>
</template>

<style scoped>
.candidate-preview-banner { padding: 10px 20px; background: #fff4d6; color: #59400e; font-size: 13px; overflow-wrap: anywhere; border-bottom: 1px solid #e8d18a; }
</style>
