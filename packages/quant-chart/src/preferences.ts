import { CHART_MANIFEST, CHART_PROFILES, DISPLAY_CATALOG, type ChartProfileId } from './catalog.js'

export interface LayerPreference {
  id: string
  hidden?: boolean
  color?: string
  height?: number
}
export interface ChartPreferences {
  schemaVersion: number
  layers: readonly LayerPreference[]
}

export function readChartPreferences(raw: unknown, profile: ChartProfileId, legacyLayers: readonly string[] = []): ChartPreferences {
  const version = CHART_MANIFEST.preferenceSchemaVersion
  const allowed: readonly string[] = CHART_PROFILES[profile].allowed
  if (raw && typeof raw === 'object' && 'schemaVersion' in raw && raw.schemaVersion !== version) {
    throw new Error('CHART_PREFERENCE_SCHEMA_UNSUPPORTED')
  }
  const stored = raw && typeof raw === 'object' && 'layers' in raw && Array.isArray(raw.layers)
    ? raw.layers : legacyLayers.map(id => ({ id }))
  const layers: LayerPreference[] = []
  for (const item of stored) {
    if (!item || typeof item.id !== 'string' || !allowed.includes(item.id) || layers.some(layer => layer.id === item.id)) continue
    layers.push({
      id: item.id,
      ...(item.hidden === true ? { hidden: true } : {}),
      ...(typeof item.color === 'string' && /^#[0-9a-f]{6}$/i.test(item.color) ? { color: item.color } : {}),
      ...(typeof item.height === 'number' && Number.isInteger(item.height) && item.height >= 48 && item.height <= 480
        ? { height: item.height } : {}),
    })
  }
  return { schemaVersion: version, layers }
}

export function setChartLayer(
  preferences: ChartPreferences,
  profile: ChartProfileId,
  id: string,
  patch: Omit<LayerPreference, 'id'> | null,
): ChartPreferences {
  const allowed: readonly string[] = CHART_PROFILES[profile].allowed
  const existing = preferences.layers.find(layer => layer.id === id)
  if (!allowed.includes(id) || (!existing && DISPLAY_CATALOG[id]?.retired)) throw new Error(`CHART_LAYER_NOT_SELECTABLE: ${id}`)
  return readChartPreferences({
    schemaVersion: preferences.schemaVersion,
    layers: patch === null ? preferences.layers.filter(layer => layer.id !== id)
      : existing ? preferences.layers.map(layer => layer === existing ? { ...layer, ...patch } : layer)
        : [...preferences.layers, { id, ...patch }],
  }, profile)
}
