import { createConditionalHomeRead } from './homeConditionalRead'
import { normalizeHomeProjection } from '../utils/newowHomeProjection.ts'

// Only persisted projection reads. No product-sized computation queue or lazy PnL.
export const getNewowHomeProjection = createConditionalHomeRead('/market/newow/home-projection', normalizeHomeProjection)
