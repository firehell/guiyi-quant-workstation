<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NBreadcrumb, NBreadcrumbItem, NTag, NButton } from 'naive-ui'
import type { MenuOption } from 'naive-ui'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const menuOptions: MenuOption[] = [
  { label: '仪表盘', key: 'dashboard' },
  { label: '行情看板', key: 'market' },
  { label: '回测中心', key: 'backtest' },
  { label: '信号监控', key: 'signal' },
  { label: '运行状态', key: 'runtime' },
  { label: '复盘分析', key: 'review' },
  { label: '数据中心', key: 'data' },
  { label: '策略中心', key: 'strategy' },
  { label: '系统设置', key: 'settings' },
]

const CHILD_ROUTE_MENU_KEY: Record<string, string> = {
  'market-chart': 'market',
  'backtest-batch': 'backtest',
}

const activeKey = computed(() => {
  const name = route.name as string
  return CHILD_ROUTE_MENU_KEY[name] || name
})

const breadcrumbTitle = computed(() => {
  if (route.name === 'market-chart') return '品种行情'
  if (route.name === 'backtest-batch') return '批量回测'
  return String(route.meta.title || '归一量化工作站')
})

function handleMenuSelect(key: string) {
  if (activeKey.value === key) return
  void router.push({ name: key })
}
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
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo" :class="{ 'logo--collapsed': collapsed }">
        <span v-if="!collapsed">归一量化</span>
        <span v-else>GY</span>
      </div>
      <NMenu
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        :value="activeKey"
        @update:value="handleMenuSelect"
      />
    </NLayoutSider>

    <NLayout>
      <NLayoutHeader bordered class="header">
        <div class="header__left">
          <NBreadcrumb>
            <NBreadcrumbItem>{{ breadcrumbTitle }}</NBreadcrumbItem>
          </NBreadcrumb>
          <NTag size="small" type="warning">research_only</NTag>
          <div class="header__actions">
            <NButton size="small" quaternary @click="router.push({ name: 'signal' })">信号</NButton>
            <NButton size="small" quaternary @click="router.push({ name: 'backtest' })">回测</NButton>
          </div>
        </div>
      </NLayoutHeader>
      <NLayoutContent class="content">
        <RouterView :key="String(route.name)" />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.main-layout {
  height: 100vh;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: var(--gy-text-primary);
  border-bottom: 1px solid var(--gy-border);
}

.header {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 20px;
}

.header__left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header__actions {
  display: flex;
  gap: 4px;
}

.content {
  padding: 20px;
  height: calc(100vh - 56px);
  overflow-y: auto;
  background: var(--gy-bg-base);
}
</style>
