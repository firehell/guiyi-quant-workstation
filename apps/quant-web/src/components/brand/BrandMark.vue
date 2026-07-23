<script setup lang="ts">
import brandSymbolUrl from '@/assets/brand/brand-symbol.svg'

withDefaults(
  defineProps<{
    size?: number
    label?: string
  }>(),
  {
    size: 32,
    label: '归一量化',
  },
)
</script>

<template>
  <img
    class="brand-mark"
    :src="brandSymbolUrl"
    :width="size"
    :height="size"
    :alt="label"
  />
</template>

<style scoped>
.brand-mark {
  display: block;
  flex: 0 0 auto;
  object-fit: contain;
}
</style>
