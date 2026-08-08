<script setup lang="ts">
/** 路由级异常兜底：页面组件抛错时展示可重试状态，不暴露堆栈。 */
import { NButton, NResult } from 'naive-ui'
import { useRouter } from 'vue-router'

const props = defineProps<{
  error?: unknown
  reset?: () => void
}>()

const router = useRouter()

function goMarket() {
  void router.push({ name: 'market' })
}

function retry() {
  if (props.reset) {
    props.reset()
    return
  }
  window.location.reload()
}
</script>

<template>
  <div class="route-error-fallback" role="alert">
    <NResult status="error" title="页面加载失败" description="路由或页面组件异常。未展示内部堆栈。">
      <template #footer>
        <div class="route-error-fallback__actions">
          <NButton type="primary" @click="retry">重试</NButton>
          <NButton quaternary @click="goMarket">返回行情</NButton>
        </div>
      </template>
    </NResult>
  </div>
</template>

<style scoped>
.route-error-fallback {
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gy-content-padding);
}

.route-error-fallback__actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>
