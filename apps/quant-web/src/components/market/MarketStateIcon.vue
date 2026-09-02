<script setup lang="ts">
import { computed } from 'vue'
import {
  MARKET_HOME_ICON_GLYPHS,
  MARKET_HOME_ICON_SIZES,
  MARKET_HOME_STATE_META,
  type MarketHomeIconSize,
  type MarketHomeIconState,
} from '@/utils/marketHomeIcons'

const props = withDefaults(defineProps<{ state: MarketHomeIconState; size?: MarketHomeIconSize }>(), { size: 'table' })
const meta = computed(() => MARKET_HOME_STATE_META[props.state])
const pixels = computed(() => MARKET_HOME_ICON_SIZES[props.size])
</script>

<template>
  <span
    class="market-state-icon"
    :class="`market-state-icon--${state}`"
    :data-testid="`market-state-icon-${state}-${size}`"
    :style="{ '--market-state-icon-size': `${pixels}px` }"
    role="img"
    :aria-label="meta.label"
  >
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path v-if="state === 'up'" :d="MARKET_HOME_ICON_GLYPHS.up" fill="currentColor" />
      <path v-else-if="state === 'aligned'" :d="MARKET_HOME_ICON_GLYPHS.aligned" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
      <path v-else-if="state === 'down'" :d="MARKET_HOME_ICON_GLYPHS.down" fill="currentColor" />
      <path v-else-if="state === 'neutral'" :d="MARKET_HOME_ICON_GLYPHS.neutral" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
      <circle v-else cx="12" cy="12" r="2.2" fill="currentColor" />
    </svg>
    <span class="market-state-icon__sr-only">{{ meta.label }}</span>
  </span>
</template>

<style scoped>
.market-state-icon { display: inline-grid; width: var(--market-state-icon-size); height: var(--market-state-icon-size); place-items: center; flex: 0 0 var(--market-state-icon-size); border-radius: 50%; color: #fff; }
.market-state-icon svg { width: 100%; height: 100%; }
.market-state-icon--up { background: var(--gy-market-icon-up); }
.market-state-icon--aligned { background: var(--gy-market-icon-aligned); }
.market-state-icon--down { background: var(--gy-market-icon-down); }
.market-state-icon--neutral { background: var(--gy-market-icon-neutral); }
.market-state-icon--unavailable { background: var(--gy-market-icon-unavailable); }
.market-state-icon__sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
</style>
