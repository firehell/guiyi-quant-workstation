<script setup lang="ts">
/** 折线图快捷封装：categories + values → ECharts option */
import BaseChart from './BaseChart.vue'
import type { EChartsOption } from 'echarts'

defineProps<{
  categories: string[]
  values: number[]
  title?: string
}>()

/** 构建面积折线 option */
function buildOption(categories: string[], values: number[], title?: string): EChartsOption {
  return {
    title: title ? { text: title, left: 'center' } : undefined,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: categories },
    yAxis: { type: 'value' },
    series: [{ type: 'line', data: values, smooth: true, areaStyle: {} }],
  }
}
</script>

<template>
  <BaseChart :option="buildOption($props.categories, $props.values, $props.title)" />
</template>
