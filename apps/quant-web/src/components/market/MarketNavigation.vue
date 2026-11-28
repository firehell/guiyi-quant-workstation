<script setup lang="ts">
// The shell owns primary navigation. Market pages supply only their contextual tools.
defineProps<{ activeTab?: string | null; mast?: boolean }>()
</script>

<template>
  <Teleport to="#ws-mast-tools" :disabled="!mast" defer>
    <div v-if="$slots.search || $slots.actions" class="market-navigation" role="group" aria-label="页面工具">
      <div v-if="$slots.search" class="market-navigation__search"><slot name="search" /></div>
      <div v-if="$slots.actions" class="market-navigation__actions"><slot name="actions" /></div>
    </div>
  </Teleport>
</template>

<style scoped>
.market-navigation { position: relative; z-index: 20; display: flex; gap: 14px; align-items: center; padding: 5px 16px; border-bottom: 1px solid var(--gy-border); background: var(--gy-bg-panel); }
.market-navigation__search { width: min(100%, 350px); min-width: 0; }
.market-navigation__actions { display: flex; align-items: center; gap: 14px; margin-left: auto; }
</style>
