<script setup lang="ts">
import { darkTheme, NConfigProvider, NMessageProvider } from 'naive-ui'
</script>

<template>
  <NConfigProvider :theme="darkTheme">
    <NMessageProvider>
      <RouterView />
    </NMessageProvider>
  </NConfigProvider>
</template>
