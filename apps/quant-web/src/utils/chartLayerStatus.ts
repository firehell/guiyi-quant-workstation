import type { LayerStatus } from '@guiyi/quant-chart'

export const chartLayerStatusLabels: Record<LayerStatus, string> = {
  ready: '就绪',
  hidden: '已隐藏',
  loading: '加载中',
  missing_input: '缺少输入',
  warming: '预热中',
  invalid_source: '来源无效',
  compute_error: '计算错误',
  catalog_mismatch: '指标目录不匹配',
  renderer_failure: '渲染错误',
  retired: '已退役',
}
