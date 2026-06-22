/** 数据同步状态 */
export interface DataSyncStatus {
  symbol: string
  exchange: string
  period: string
  lastSyncTime: string
  totalBars: number
  status: 'synced' | 'syncing' | 'failed'
  fileSize: number
}
