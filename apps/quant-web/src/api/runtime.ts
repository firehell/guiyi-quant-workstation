import request from '@/api/request'
import type { RuntimeHealth } from '@/types/runtime'

export function getRuntimeHealth() {
  return request.get<any, RuntimeHealth>('/api/runtime/health')
}
