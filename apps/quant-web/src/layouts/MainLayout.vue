<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu } from 'naive-ui'
import type { MenuOption } from 'naive-ui'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const menuOptions: MenuOption[] = [
  { label: '仪表盘', key: 'dashboard' },
  { label: '数据中心', key: 'data' },
  { label: '行情看板', key: 'market' },
  { label: '策略管理', key: 'strategy' },
  { label: '回测中心', key: 'backtest' },
  { label: '信号监控', key: 'signal' },
  { label: '复盘分析', key: 'review' },
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

function handleMenuSelect(key: string) {
  if (activeKey.value === key) return
  void router.push({ name: key })
}
</script>

<template>
  <NLayout has-sider style="height: 100vh">
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
        <span class="header__title">{{ route.meta.title || '归一量化工作站' }}</span>
      </NLayoutHeader>
      <NLayoutContent class="content">
        <RouterView :key="String(route.name)" />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: var(--n-item-text-color);
  border-bottom: 1px solid var(--n-border-color);
}

.header {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 24px;
}

.header__title {
  font-size: 16px;
  font-weight: 600;
}

.content {
  padding: 20px;
  height: calc(100vh - 56px);
  overflow-y: auto;
}
</style>
