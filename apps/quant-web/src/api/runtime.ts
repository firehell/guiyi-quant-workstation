import request from '@/api/request'
import type { RuntimeHealth } from '@/types/runtime'

/** 获取运行时健康检查（DB / Redis / 队列等） */
export function getRuntimeHealth() {
  return request.get<any, RuntimeHealth>('/api/runtime/health')
}
