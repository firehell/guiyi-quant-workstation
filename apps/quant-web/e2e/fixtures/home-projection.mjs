export function homeProjection(items, requested_at = '2026-09-04T07:01:00Z') {
  return { schema_version: 'newow_home_projection_v1', requested_at, generated_at: requested_at,
    page_parity: true, executable: false,
    items: items.map(item => ({ ...item, projection_status: 'ready',
      computed_at: requested_at, period_status: { '1d': 'ready', '1w': 'ready' },
      source_versions: { '1d': 'a'.repeat(64), '1w': 'b'.repeat(64) } })) }
}
