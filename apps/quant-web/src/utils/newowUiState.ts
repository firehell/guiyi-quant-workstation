import type { NewowResourceLifecycle } from '../types/newowProduct.ts'
const labels: Record<NewowResourceLifecycle, string> = {
  not_requested: '尚未读取', loading: '正在读取', ready: '已读取', warming: '输入预热中', evidence_required: '证据不足',
  unavailable: '当前不可用', not_applicable: '当前组合不适用', stale: '保留上次已验证结果', input_conflict: '输入身份冲突', busy: '服务繁忙', cancelled: '读取已取消',
}
export function newowUiStateLabel(state: NewowResourceLifecycle): string { return labels[state] }
