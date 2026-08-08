<script setup lang="ts">
/** 未知路由兜底页 */
import { NButton } from 'naive-ui'
import { useRouter } from 'vue-router'
import PageShell from '@/components/common/PageShell.vue'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'

const router = useRouter()
</script>

<template>
  <PageShell title="页面不存在" subtitle="路由未匹配，已兜底，未暴露内部路径细节">
    <template #badges>
      <CapabilityBadge kind="unavailable" />
    </template>
    <template #actions>
      <NButton type="primary" @click="router.push({ name: 'market' })">返回行情</NButton>
    </template>
    <p class="not-found__hint">请从侧栏选择已注册页面。未知 URL 不会执行业务请求。</p>
  </PageShell>
</template>

<style scoped>
.not-found__hint {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-base);
}
</style>
