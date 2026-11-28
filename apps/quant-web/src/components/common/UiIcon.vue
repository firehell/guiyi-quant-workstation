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
    <path v-else-if="name === 'chart'" d="M3 20h18 M6 5v11m-2-8h4v5H4z M13 3v14m-2-10h4v6h-4z M19 5v12" />
    <path v-else-if="name === 'pulse'" d="M2 12h5l3-7 4 14 3-7h5" />
    <path v-else-if="name === 'layers'" d="m12 3 9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5" />
    <path v-else-if="name === 'wallet'" d="M3 6h16v4 M3 6l13-3v3 M3 6v14h17V10H3 M15 13h6v4h-6z" />
    <path v-else-if="name === 'history'" d="M3 8v5h5 M4 12a8 8 0 1 1 2 6 M12 7v5l4 2" />
    <path v-else-if="name === 'flask'" d="M9 3h6 M10 3v6L4 18q-1 3 2 3h12q3 0 2-3l-6-9V3 M7 15h10" />
    <path v-else-if="name === 'book'" d="M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3z M12 6v15" />
    <path v-else-if="name === 'server'" d="M3 3h18v7H3z M3 14h18v7H3z M6 6h2 M6 17h2" />
    <path v-else-if="name === 'bell'" d="M4 17h16l-2-3V9a6 6 0 0 0-12 0v5z M9 20q3 3 6 0" />
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
