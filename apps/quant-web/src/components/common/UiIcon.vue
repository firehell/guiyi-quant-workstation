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
    <template v-if="name === 'market'">
      <path d="M3 17l5-5 4 3 7-9" />
      <path d="M16 6h3v3" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 11a8 8 0 10-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </template>
    <template v-else-if="name === 'shield'">
      <path d="M12 3l7 3v5c0 4.5-2.8 8-7 10-4.2-2-7-5.5-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-5" />
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
