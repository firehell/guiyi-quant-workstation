export function rangeDetectorStatusText(status: string, count: number): string {
  if (status === 'loading') return '箱体识别：正在补充可见区间的历史预热数据…'
  if (status === 'failed') return '箱体识别：历史读取失败；已加载范围仍可展示，关闭后重新开启可重试。'
  if (status === 'insufficient') return '箱体识别：当前可见区间的同合约／质量分段预热不足；已充分预热的其他区间仍可展示。'
  if (status === 'ready') return count ? `箱体识别：当前可见区间有 ${count} 段历史箱体。` : '箱体识别：已完成计算，当前可见区间未识别出箱体。'
  return '箱体识别：等待已完成行情。'
}

/** Count boxes/active levels intersecting the visible completed-Bar time interval. */
export function visibleRangeDetectorCount(ranges: readonly { visualStartAt: string; detectionRightAt: string; levelsActiveUntil: string | null }[], from: string | null, to: string | null, last: string | null): number {
  if (!from || !to || !last) return 0
  return ranges.filter(range => Date.parse(range.visualStartAt) <= Date.parse(to)
    && Math.max(Date.parse(range.detectionRightAt), Date.parse(range.levelsActiveUntil ?? last)) >= Date.parse(from)).length
}
