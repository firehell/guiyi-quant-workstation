import request from './request'
import type { HtdyObservationAlertList, HtdyObservationAlertRecord } from '@/types/observation'

export function listHtdyObservationAlerts(params: { limit?: number; offset?: number } = {}) {
  return request.get<any, HtdyObservationAlertList>('/api/observations/htdy/alerts', { params })
}

export function getHtdyObservationAlert(alertId: number) {
  return request.get<any, HtdyObservationAlertRecord>(`/api/observations/htdy/alerts/${alertId}`)
}
