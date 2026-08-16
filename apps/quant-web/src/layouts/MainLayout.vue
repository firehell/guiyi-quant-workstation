<script setup lang="ts">
/** 主布局：侧栏导航、面包屑、响应式折叠与页面过渡容器。 */
import { computed, h, onErrorCaptured, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NBreadcrumb,
  NBreadcrumbItem,
  NButton,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NTooltip,
  type MenuOption,
} from 'naive-ui'
import BoundaryBadge from '@/components/common/BoundaryBadge.vue'
import BrandLogo from '@/components/brand/BrandLogo.vue'
import RouteErrorFallback from '@/components/common/RouteErrorFallback.vue'
import UiIcon from '@/components/common/UiIcon.vue'
import WorkspaceContext from '@/components/workspace/WorkspaceContext.vue'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const userSetCollapsed = ref(false)
const now = ref(new Date())
const routeError = ref<unknown>(null)
let clockTimer: number | null = null

onErrorCaptured((err) => {
  routeError.value = err
  console.error('[RouteError]', err instanceof Error ? err.name : 'UNKNOWN')
  return false
})

watch(
  () => route.fullPath,
  () => {
    routeError.value = null
  },
)

function clearRouteError() {
  routeError.value = null
}

function renderIcon(name: string) {
  return () => h(UiIcon, { name, size: 18 })
}

const menuOptions: MenuOption[] = [
  {
    type: 'group',
    label: '工作',
    key: 'work-group',
    children: [
      { label: 'Market 工作台', key: 'market', icon: renderIcon('market') },
      { label: '交易记录', key: 'trade-records', icon: renderIcon('review') },
    ],
  },
]

/** 子路由映射到父级菜单高亮（如 market-chart → market）。 */
const CHILD_ROUTE_MENU_KEY: Record<string, string> = {
  'market-chart': 'market',
}

const activeKey = computed(() => {
  const name = route.name as string
  return CHILD_ROUTE_MENU_KEY[name] || name
})

const breadcrumbItems = computed(() => {
  if (route.name === 'market-chart') return ['行情看板', '品种行情']
  if (route.name === 'trade-records') return ['交易记录']
  if (route.name === 'not-found') return ['页面不存在']
  return [String(route.meta.title || '归一量化工作站')]
})

const clockText = computed(() =>
  new Intl.DateTimeFormat('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(now.value),
)

/** 窄屏自动折叠侧栏；用户手动操作后不再自动覆盖。 */
function syncResponsiveCollapse() {
  // 1440 以下折叠；1024/1280 桌面断点共用紧凑侧栏
  if (!userSetCollapsed.value) collapsed.value = window.innerWidth < 1440
}

function setCollapsed(value: boolean) {
  userSetCollapsed.value = true
  collapsed.value = value
}

function handleMenuSelect(key: string) {
  if (activeKey.value === key) return
  void router.push({ name: key })
}

function reloadPage() {
  window.location.reload()
}

onMounted(() => {
  syncResponsiveCollapse()
  window.addEventListener('resize', syncResponsiveCollapse)
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncResponsiveCollapse)
  if (clockTimer !== null) window.clearInterval(clockTimer)
})
</script>

<template>
  <NLayout has-sider class="main-layout">
    <NLayoutSider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      show-trigger
      class="sidebar"
      @collapse="setCollapsed(true)"
      @expand="setCollapsed(false)"
    >
      <div class="brand" :class="{ 'brand--collapsed': collapsed }">
        <BrandLogo :collapsed="collapsed" />
      </div>
      <NMenu
        class="sidebar__menu"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="20"
        :indent="18"
        :options="menuOptions"
        :value="activeKey"
        @update:value="handleMenuSelect"
      />
      <div class="sidebar__footer">
        <BoundaryBadge v-if="!collapsed" compact />
        <NTooltip v-else placement="right" trigger="hover">
          <template #trigger>
            <span class="sidebar__boundary-icon" aria-label="研究工作站，不自动下单">
              <UiIcon name="shield" :size="17" />
            </span>
          </template>
          研究工作站 · 不自动下单
        </NTooltip>
      </div>
    </NLayoutSider>

    <NLayout class="workspace">
      <NLayoutHeader bordered class="header">
        <NBreadcrumb class="header__breadcrumb">
          <NBreadcrumbItem v-for="item in breadcrumbItems" :key="item">{{ item }}</NBreadcrumbItem>
        </NBreadcrumb>
        <div class="header__right">
          <WorkspaceContext />
          <BoundaryBadge class="header__boundary" />
          <div class="header__actions">
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton quaternary circle aria-label="刷新当前页" @click="reloadPage">
                  <template #icon><UiIcon name="refresh" :size="17" /></template>
                </NButton>
              </template>
              刷新当前页
            </NTooltip>
          </div>
          <time class="header__clock gy-number">{{ clockText }}</time>
        </div>
      </NLayoutHeader>
      <NLayoutContent class="content">
        <RouteErrorFallback
          v-if="routeError"
          :error="routeError"
          :reset="clearRouteError"
        />
        <RouterView v-else v-slot="{ Component }">
          <Transition name="gy-page" mode="out-in">
            <component :is="Component" :key="String(route.name)" />
          </Transition>
        </RouterView>
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.main-layout {
  height: 100vh;
  min-width: 0;
  background: var(--gy-bg-app);
}

.sidebar {
  position: relative;
  background: var(--gy-shell-bg);
}

.brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 17px;
  border-bottom: 1px solid var(--gy-shell-border);
  overflow: hidden;
}

.brand--collapsed {
  justify-content: center;
  padding: 0;
}

.sidebar__menu {
  height: calc(100vh - 121px);
  padding: 8px 7px 12px;
  overflow-y: auto;
}

.sidebar__menu :deep(.n-menu-item-group-title) {
  padding-top: 14px;
  padding-bottom: 4px;
  font-size: 10px;
  letter-spacing: 0.12em;
}

.sidebar.n-layout-sider--collapsed :deep(.n-menu-item-group-title) {
  display: none;
}

.sidebar.n-layout-sider--collapsed :deep(.n-menu-item-group + .n-menu-item-group) {
  margin-top: 8px;
}

.sidebar__menu :deep(.n-menu-item-content--selected)::before {
  content: '';
  position: absolute;
  left: 0;
  width: 2px;
  height: 22px;
  border-radius: 0 2px 2px 0;
  background: var(--gy-shell-accent);
}

.sidebar__footer {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  min-height: 57px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  border-top: 1px solid var(--gy-shell-border);
  background: var(--gy-shell-bg);
}

.sidebar__boundary-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--gy-status-warning);
  background: var(--gy-status-warning-soft);
  border: 1px solid rgba(247, 144, 9, 0.35);
  border-radius: var(--gy-radius-md);
}

.workspace {
  min-width: 0;
}

.header {
  position: relative;
  z-index: 5;
  height: var(--gy-header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-4);
  padding: 0 var(--gy-content-padding);
  background: var(--gy-shell-bg);
}

.header__breadcrumb {
  min-width: 0;
}

.header__breadcrumb :deep(.n-breadcrumb-item__link) {
  color: var(--gy-shell-text);
}

.header__breadcrumb :deep(.n-breadcrumb-item:last-child .n-breadcrumb-item__link) {
  color: var(--gy-shell-text-active);
}

.header__breadcrumb :deep(.n-breadcrumb-item__separator) {
  color: var(--gy-shell-text-muted);
}

.header__actions :deep(.n-button) {
  color: var(--gy-shell-text);
}

.header__actions :deep(.n-button:hover) {
  color: var(--gy-shell-text-active);
}

.header__right,
.header__actions {
  display: flex;
  align-items: center;
}

.header__right {
  gap: var(--gy-space-3);
  min-width: 0;
}

.header__actions {
  gap: 2px;
}

.header__clock {
  min-width: 68px;
  color: var(--gy-shell-text);
  font-size: var(--gy-font-size-xs);
  text-align: right;
}

.content {
  height: calc(100vh - var(--gy-header-height));
  min-width: 0;
  padding: var(--gy-content-padding);
  overflow: auto;
  background: var(--gy-bg-app);
}

@media (max-width: 1199px) {
  .header__right {
    gap: var(--gy-space-2);
  }
}

@media (max-width: 760px) {
  .header__clock,
  .header__boundary {
    display: none;
  }
}
</style>
