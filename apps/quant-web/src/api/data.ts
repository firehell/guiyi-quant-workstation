import request from './request'
import type { DataSyncStatus } from '@/types/data'

/** 获取数据同步状态 */
export function getDataSyncStatus() {
  return request.get<any, DataSyncStatus[]>('/api/data/sync-status')
}

/** 触发数据采集 */
export function triggerDataSync(data: {
  symbol: string
  period: string
  startDate: string
  endDate: string
}) {
  return request.post<any, { taskId: string }>('/api/data/sync', data)
}
