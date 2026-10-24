import { createReadAdmission, READ_PRIORITY } from '../utils/readAdmission.ts'
// These read-only replay endpoints share one server-side computation gate.
// Queue before transport so chart history and statistics do not race into BUSY.
const admit = createReadAdmission(1)
export async function withReferenceRead<T>(read: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  const release = await admit(signal, READ_PRIORITY.history)
  try { return await read() } finally { release() }
}
