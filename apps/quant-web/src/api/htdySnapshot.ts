import { normalizeHtdySnapshot } from '../utils/htdySnapshot.ts'
export async function getHtdySnapshot(product:string, signal:AbortSignal, snapshot?:string, before?:string) {
 const {default:request}=await import('./request.ts')
 return normalizeHtdySnapshot(await request.get<never, unknown>(`/market/${encodeURIComponent(product)}/htdy/snapshot`, {signal, params:{limit:50,...(snapshot?{snapshot_id:snapshot}:{}),...(before?{before}:{})}}), product, snapshot)
}
