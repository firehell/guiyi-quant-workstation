import type { NewowAuxiliaryComponent } from '../types/newowProduct.ts'
export interface NewowUiPreferences {
  auxiliary?: NewowAuxiliaryComponent
  scrollTop?: number
  chart?: { axis: string; range: { from: number; to: number } | null; detail: boolean; actions: boolean; structure: boolean; hints: boolean }
}
// Presentation only, bounded to the most recent 16 identities in this app session.
const entries = new Map<string, NewowUiPreferences>()
export function readNewowUiPreferences(key: string): NewowUiPreferences { return entries.get(key) ?? {} }
export function rememberNewowUiPreferences(key: string, patch: NewowUiPreferences): void {
  const value = { ...readNewowUiPreferences(key), ...patch }
  entries.delete(key); entries.set(key, value)
  while (entries.size > 16) entries.delete(entries.keys().next().value!)
}
