<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{
  option: EChartsOption
  height?: string
}>()

const chartHeight = props.height || '320px'
</script>

<template>
  <VChart :option="props.option" :style="{ height: chartHeight, width: '100%' }" autoresize />
</template>
