<script setup lang="ts">
import { computed } from 'vue'

import {
  marketDetailIconDefinition,
  type MarketDetailIconName,
} from '@/utils/marketDetailIcons'

const props = withDefaults(defineProps<{
  name: MarketDetailIconName
  size?: 16 | 18 | 20 | 24
  label?: string
}>(), {
  size: 20,
  label: undefined,
})

const definition = computed(() => marketDetailIconDefinition(props.name))
const accessibleLabel = computed(() => props.label ?? definition.value.label)
</script>

<template>
  <svg
    class="market-detail-icon"
    viewBox="0 0 24 24"
    focusable="false"
    :width="size"
    :height="size"
    :role="label ? 'img' : undefined"
    :aria-label="label ? accessibleLabel : undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <template v-if="definition.mode === 'stroke'">
      <path
        v-for="path in definition.paths"
        :key="path"
        :d="path"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle
        v-for="circle in definition.circles"
        :key="`${circle.cx}-${circle.cy}-${circle.r}`"
        :cx="circle.cx"
        :cy="circle.cy"
        :r="circle.r"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </template>
    <template v-else>
      <circle
        v-for="circle in definition.circles"
        :key="`${circle.cx}-${circle.cy}-${circle.r}`"
        :cx="circle.cx"
        :cy="circle.cy"
        :r="circle.r"
        fill="currentColor"
      />
    </template>
  </svg>
</template>

<style scoped>
.market-detail-icon { display: inline-block; flex: 0 0 auto; vertical-align: middle; }
</style>
