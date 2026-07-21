<script setup lang="ts">
/** 根组件：Naive UI 主题、消息 Provider 与路由出口 */
import { darkTheme, NConfigProvider, NMessageProvider } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { themeOverrides } from '@/styles/theme'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const { theme } = storeToRefs(appStore)
</script>

<template>
  <NConfigProvider :theme="theme === 'dark' ? darkTheme : null" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <RouterView />
    </NMessageProvider>
  </NConfigProvider>
</template>
