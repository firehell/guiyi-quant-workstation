<script setup lang="ts">
import { useId } from 'vue'
import type { returnCurveLayout } from '../../utils/returnCurveLayout'
defineProps<{
  plot: ReturnType<typeof returnCurveLayout>
  label: string
  area?: boolean
  zeroLine?: boolean
  role?: 'group' | 'img'
}>()
const emit = defineEmits<{ click: [event: MouseEvent]; mousemove: [event: MouseEvent]; mouseleave: [event: MouseEvent] }>()
const gradient = `return-curve-${useId()}`
</script>
<template>
  <div class="return-curve">
    <p v-if="plot.message" role="status">{{ plot.message }}</p>
    <div v-else class="return-curve__area">
      <svg viewBox="0 0 712 140" preserveAspectRatio="none" :role="role ?? 'img'" :aria-label="label" @click="emit('click', $event)" @mousemove="emit('mousemove', $event)" @mouseleave="emit('mouseleave', $event)">
        <defs><linearGradient :id="gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" class="return-curve__gradient-start"/><stop offset="100%" class="return-curve__gradient-end"/></linearGradient></defs>
        <line v-for="level in plot.levels" :key="level.y" class="return-curve__grid" x1="0" x2="712" :y1="level.y" :y2="level.y"/>
        <polygon v-for="(part,i) in area ? plot.areas : []" :key="`area-${i}`" :points="part" :fill="`url(#${gradient})`"/>
        <line v-if="zeroLine" class="return-curve__zero" x1="0" x2="712" :y1="plot.zero" :y2="plot.zero" stroke-dasharray="4 4"/>
        <polyline v-for="(part,i) in plot.segments" :key="i" :points="part" class="return-curve__line" fill="none" vector-effect="non-scaling-stroke"/>
        <slot />
      </svg>
      <span v-for="level in plot.levels" :key="level.y" class="return-curve__value" :style="{top:`${level.y / 140 * 100}%`}">{{ level.label }}</span>
      <span v-for="tick in plot.ticks" :key="tick.x" class="return-curve__date" :data-anchor="tick.anchor" :title="tick.day" :style="{left:`${tick.x / 712 * 100}%`}">{{ tick.label }}</span>
    </div>
  </div>
</template>
<style scoped>
.return-curve { position:relative; height:180px; --curve-line:var(--return-curve-line,#ff403a); --curve-grid:var(--return-curve-grid,#f2f3f5); }
.return-curve__area { position:absolute; top:20px; bottom:20px; left:44px; right:30px; }
.return-curve__area svg { display:block; width:100%; height:100%; min-height:0; margin:0; overflow:visible; }
.return-curve__line { stroke:var(--curve-line); stroke-width:var(--return-curve-width,1.8); }
.return-curve__grid { stroke:var(--curve-grid); }
.return-curve__zero { stroke:var(--return-curve-zero,#d0d5dd); }
.return-curve__gradient-start { stop-color:var(--curve-line); stop-opacity:var(--return-curve-opacity,.14); }
.return-curve__gradient-end { stop-color:var(--curve-line); stop-opacity:.01; }
.return-curve__value { position:absolute; right:calc(100% + 4px); transform:translateY(-50%); color:var(--return-curve-axis,#999); font:10px/12px Arial,sans-serif; white-space:nowrap; }
.return-curve__date { position:absolute; top:calc(100% + 5px); transform:translateX(-50%); color:var(--return-curve-axis,#999); font:10px/12px Arial,sans-serif; white-space:nowrap; }
.return-curve__date[data-anchor="start"] { transform:none; }.return-curve__date[data-anchor="end"] { transform:translateX(-100%); }
</style>
