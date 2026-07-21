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
import RouteErrorFallback from '@/components/common/RouteErrorFallback.vue'
import UiIcon from '@/components/common/UiIcon.vue'

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
    label: '研究分析',
    key: 'research-group',
    children: [
      { label: '仪表盘', key: 'dashboard', icon: renderIcon('dashboard') },
      { label: '行情看板', key: 'market', icon: renderIcon('market') },
      { label: '信号监控', key: 'signal', icon: renderIcon('signal') },
    ],
  },
  {
    type: 'group',
    label: '策略回测',
    key: 'strategy-group',
    children: [
      { label: '策略中心', key: 'strategy', icon: renderIcon('strategy') },
      { label: '回测中心', key: 'backtest', icon: renderIcon('backtest') },
      { label: '复盘分析', key: 'review', icon: renderIcon('review') },
    ],
  },
  {
    type: 'group',
    label: '数据运维',
    key: 'data-group',
    children: [
      { label: '数据中心', key: 'data', icon: renderIcon('data') },
      { label: '运行状态', key: 'runtime', icon: renderIcon('runtime') },
    ],
  },
  {
    type: 'group',
    label: '系统',
    key: 'system-group',
    children: [{ label: '系统设置', key: 'settings', icon: renderIcon('settings') }],
  },
]

/** 子路由映射到父级菜单高亮（如 market-chart → market）。 */
const CHILD_ROUTE_MENU_KEY: Record<string, string> = {
  'market-chart': 'market',
  'backtest-batch': 'backtest',
}

const activeKey = computed(() => {
  const name = route.name as string
  return CHILD_ROUTE_MENU_KEY[name] || name
})

const breadcrumbItems = computed(() => {
  if (route.name === 'market-chart') return ['行情看板', '品种行情']
  if (route.name === 'backtest-batch') return ['回测中心', '批量回测']
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
        <div class="brand__mark" aria-hidden="true">
          <span /><span /><span />
        </div>
        <div v-if="!collapsed" class="brand__copy">
          <strong>归一量化</strong>
          <small>GUIYI QUANT</small>
        </div>
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
          <BoundaryBadge class="header__boundary" />
          <div class="header__actions">
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton quaternary circle aria-label="打开信号监控" @click="router.push({ name: 'signal' })">
                  <template #icon><UiIcon name="signal" :size="17" /></template>
                </NButton>
              </template>
              信号监控
            </NTooltip>
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton quaternary circle aria-label="打开回测中心" @click="router.push({ name: 'backtest' })">
                  <template #icon><UiIcon name="backtest" :size="17" /></template>
                </NButton>
              </template>
              回测中心
            </NTooltip>
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
  background:
    linear-gradient(180deg, rgba(20, 133, 238, 0.035), transparent 28%),
    var(--gy-bg-canvas);
}

.sidebar::after {
  content: '';
  position: absolute;
  z-index: 2;
  top: 0;
  right: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(20, 133, 238, 0.32), transparent 70%);
  pointer-events: none;
}

.brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 17px;
  border-bottom: 1px solid var(--gy-border);
  overflow: hidden;
}

.brand--collapsed {
  justify-content: center;
  padding: 0;
}

.brand__mark {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  padding: 6px;
  border: 1px solid rgba(20, 133, 238, 0.52);
  border-radius: 8px;
  background: rgba(20, 133, 238, 0.08);
}

.brand__mark span {
  width: 3px;
  border-radius: 2px;
  background: var(--gy-accent-hover);
}

.brand__mark span:nth-child(1) { height: 9px; }
.brand__mark span:nth-child(2) { height: 16px; background: var(--gy-up); }
.brand__mark span:nth-child(3) { height: 12px; background: var(--gy-down); }

.brand__copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.brand__copy strong {
  font-size: 17px;
  letter-spacing: 0.06em;
  white-space: nowrap;
}

.brand__copy small {
  margin-top: 2px;
  color: var(--gy-text-muted);
  font-family: var(--gy-font-mono);
  font-size: 8px;
  letter-spacing: 0.12em;
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
  background: var(--gy-accent-hover);
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
  border-top: 1px solid var(--gy-border);
  background: var(--gy-bg-canvas);
}

.sidebar__boundary-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--gy-status-warning);
  background: var(--gy-status-warning-soft);
  border: 1px solid rgba(255, 143, 31, 0.25);
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
  background: var(--gy-bg-header);
  backdrop-filter: blur(10px);
}

.header__breadcrumb {
  min-width: 0;
}

.header__right,
.header__actions {
  display: flex;
  align-items: center;
}

.header__right {
  gap: var(--gy-space-3);
}

.header__actions {
  gap: 2px;
}

.header__clock {
  min-width: 68px;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
  text-align: right;
}

.content {
  height: calc(100vh - var(--gy-header-height));
  min-width: 0;
  padding: var(--gy-content-padding);
  overflow: auto;
  background-color: var(--gy-bg-app);
  background-image:
    radial-gradient(circle at 12% 0%, rgba(20, 133, 238, 0.055), transparent 34%),
    var(--gy-grid-overlay);
  background-size: auto, 32px 32px;
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
