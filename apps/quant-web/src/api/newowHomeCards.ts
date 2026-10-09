import request from './request'
import { normalizeHomeCards } from '../utils/newowHomeCards.ts'

export function getNewowHomeCards(products: string[], signal: AbortSignal) {
  return request.get<never, unknown>('/market/newow/home-cards', { params: { products: products.join(',') }, signal, timeout: 180_000 })
    .then(value => normalizeHomeCards(value, products))
}
