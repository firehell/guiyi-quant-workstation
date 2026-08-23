<script setup lang="ts">
/** 内联 SVG 图标：按 name 切换 path，避免额外图标库依赖 */
withDefaults(
  defineProps<{
    name: string
    size?: number
  }>(),
  { size: 18 },
)
</script>

<template>
  <svg
    class="ui-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'dashboard'">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </template>
    <template v-else-if="name === 'market'">
      <path d="M3 17l5-5 4 3 7-9" />
      <path d="M16 6h3v3" />
    </template>
    <template v-else-if="name === 'signal'">
      <circle cx="12" cy="12" r="2.5" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </template>
    <template v-else-if="name === 'strategy'">
      <path d="M5 4v16M12 4v16M19 4v16" />
      <path d="M3 8h4M10 15h4M17 10h4" />
    </template>
    <template v-else-if="name === 'review'">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7v5l3 2" />
    </template>
    <template v-else-if="name === 'data'">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </template>
    <template v-else-if="name === 'runtime'">
      <circle cx="12" cy="12" r="8" />
      <path d="M8 12h2l1.3-3 2.1 6 1.3-3H17" />
    </template>
    <template v-else-if="name === 'backtest'">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M8 15l3-3 2 2 3-4" />
      <path d="M14 10h2v2" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 11a8 8 0 10-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </template>
    <template v-else-if="name === 'shield'">
      <path d="M12 3l7 3v5c0 4.5-2.8 8-7 10-4.2-2-7-5.5-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-5" />
    </template>
    <template v-else-if="name === 'arrow-up'">
      <path d="M12 19V5M6 11l6-6 6 6" />
    </template>
    <template v-else-if="name === 'arrow-down'">
      <path d="M12 5v14M6 13l6 6 6-6" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4M12 16h.01" />
    </template>
  </svg>
</template>

<style scoped>
.ui-icon {
  display: block;
  flex: 0 0 auto;
}
</style>
