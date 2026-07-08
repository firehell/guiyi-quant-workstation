<script setup lang="ts">
import { computed } from 'vue'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import type { ChartSpec } from '@/types/futuresResearch'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  chart: ChartSpec
  height?: string
}>()

const chartHeight = computed(() => props.height || '260px')

const option = computed<EChartsOption>(() => {
  const { chart } = props
  if (!chart.xAxis.length || !chart.series.length) {
    return {
      backgroundColor: 'transparent',
      title: {
        text: '暂无图表数据',
        left: 'center',
        top: 'middle',
        textStyle: { color: '#94a3b8', fontSize: 13, fontWeight: 400 },
      },
    }
  }

  const isStep = chart.chart_type === 'step'
  const isBar = chart.chart_type === 'bar'
  const hasCategoryY = Boolean(chart.yAxisCategories?.length)

  return {
    backgroundColor: 'transparent',
    color: ['#38bdf8', '#f59e0b', '#22c55e', '#ef4444'],
    grid: { left: 48, right: hasCategoryY ? 72 : 24, top: 36, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111827',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0' },
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? params : [params]
        const first = items[0] as { axisValue?: string; data?: number | string | null; seriesName?: string }
        const lines = [`${first.axisValue || ''}`]
        items.forEach((item) => {
          const row = item as { seriesName?: string; data?: number | string | null }
          let value: string | number | null = row.data ?? null
          if (hasCategoryY && typeof value === 'number' && chart.yAxisCategories) {
            value = chart.yAxisCategories[value] ?? value
          }
          lines.push(`${row.seriesName}: ${value ?? '-'}`)
        })
        return lines.join('<br/>')
      },
    },
    legend: {
      top: 0,
      textStyle: { color: '#94a3b8' },
    },
    xAxis: {
      type: 'category',
      data: chart.xAxis,
      axisLabel: { color: '#94a3b8', hideOverlap: true },
      axisLine: { lineStyle: { color: '#334155' } },
    },
    yAxis: hasCategoryY
      ? [
          {
            type: 'category',
            data: chart.yAxisCategories || [],
            axisLabel: { color: '#94a3b8' },
            axisLine: { lineStyle: { color: '#334155' } },
          },
        ]
      : chart.series.some((item) => item.yAxisIndex === 1)
        ? [
            {
              type: 'value',
              axisLabel: { color: '#94a3b8' },
              splitLine: { lineStyle: { color: '#1f2937' } },
            },
            {
              type: 'value',
              axisLabel: { color: '#94a3b8' },
              splitLine: { show: false },
            },
          ]
        : [
            {
              type: 'value',
              axisLabel: { color: '#94a3b8' },
              splitLine: { lineStyle: { color: '#1f2937' } },
            },
          ],
    series: chart.series.map((item) => ({
      name: item.name,
      type: isBar ? 'bar' : 'line',
      step: isStep ? 'end' : false,
      smooth: !isStep && !isBar,
      showSymbol: false,
      yAxisIndex: item.yAxisIndex || 0,
      data: item.data,
    })),
  }
})
</script>

<template>
  <VChart :option="option" :style="{ height: chartHeight, width: '100%' }" autoresize />
</template>
