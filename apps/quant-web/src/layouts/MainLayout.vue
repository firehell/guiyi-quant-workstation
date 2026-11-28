<script setup lang="ts">
import { computed, onErrorCaptured, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RouteErrorFallback from '@/components/common/RouteErrorFallback.vue'
import UiIcon from '@/components/common/UiIcon.vue'
import { workstationPages, workstationSection, workstationUiVersion } from '@/utils/workstationNavigation'
import { lastWorkstationChart } from '@/utils/workstationRoutes'
import '@/styles/workstation.css'

const route = useRoute()
const router = useRouter()
const section = computed(() => workstationSection(route.name))
const current = computed(() => workstationPages.find(page => page.name === section.value))
const now = ref(new Date())
const clock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hourCycle: 'h23', hour: '2-digit', minute: '2-digit', second: '2-digit' })
const clockText = computed(() => clock.format(now.value))
const routeError = ref<unknown>(null)
let timer: number | undefined
onMounted(() => { timer = window.setInterval(() => { now.value = new Date() }, 1000) })
onUnmounted(() => window.clearInterval(timer))
onErrorCaptured((error) => {
  routeError.value = error
  console.error('[RouteError]', error instanceof Error ? error.name : 'UNKNOWN')
  return false
})
watch(() => route.fullPath, () => {
  routeError.value = null
  document.title = `${String(route.meta.title ?? '工作台')} · 归一量化`
}, { immediate: true })
function destination(name: string) {
  return name === 'market-chart' ? lastWorkstationChart() : { name }
}
function openPage(event: Event) {
  void router.push(destination((event.target as HTMLSelectElement).value))
}
</script>

<template>
  <div class="ws-shell" :data-section="section">
    <header class="ws-mast">
      <RouterLink class="ws-brand" to="/" aria-label="归一量化 · 我的看盘">
        <span class="ws-monogram" aria-hidden="true">归</span>
        <span>归一量化<small>GUIYI QUANT</small></span>
      </RouterLink>
      <span class="ws-current">{{ route.meta.title }}</span>
      <select class="ws-picker" aria-label="切换页面" :value="current?.name ?? ''" @change="openPage">
        <option v-if="!current" value="" disabled>{{ route.meta.title }}</option>
        <option v-for="page in workstationPages" :key="page.name" :value="page.name">{{ page.title }}</option>
      </select>
      <div id="ws-mast-tools" />
      <div class="ws-mast-right">
        <RouterLink to="/market?tab=messages" :aria-current="route.name === 'market' && route.query.tab === 'messages' ? 'page' : undefined"><UiIcon name="bell" :size="14" />消息</RouterLink>
        <time :datetime="now.toISOString()">北京 {{ clockText }}</time>
      </div>
    </header>
    <aside class="ws-rail">
      <nav aria-label="工作站主导航">
        <template v-for="(page, index) in workstationPages" :key="page.name">
          <span v-if="!index || page.group !== workstationPages[index - 1]?.group" class="ws-nav-group">{{ page.group }}</span>
          <RouterLink :to="destination(page.name)" :aria-current="section === page.name ? 'page' : undefined">
            <UiIcon :name="page.icon" :size="16" />{{ page.title }}
          </RouterLink>
        </template>
      </nav>
      <RouterLink class="ws-version" to="/system#versions" :title="workstationUiVersion">UI {{ workstationUiVersion.split('/')[1] }}</RouterLink>
    </aside>
    <div class="ws-content">
      <RouteErrorFallback v-if="routeError" :error="routeError" :reset="() => { routeError = null }" />
      <RouterView v-else v-slot="{ Component }"><component :is="Component" :key="String(route.name)" /></RouterView>
    </div>
  </div>
</template>
