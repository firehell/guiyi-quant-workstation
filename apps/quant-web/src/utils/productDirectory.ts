/** Market 首页的一级研究板块标签；品种到板块的映射由后端 taxonomy 提供。 */
import type { DominantContractItem } from '@/types/market'

export const PRODUCT_SECTORS = [
  { id: 'black', label: '黑色系' },
  { id: 'steel', label: '钢铁' },
  { id: 'building', label: '建材' },
  { id: 'nonferrous', label: '有色' },
  { id: 'precious', label: '贵金属' },
  { id: 'energy', label: '能源' },
  { id: 'chemical', label: '化工' },
  { id: 'new_energy', label: '新能源' },
  { id: 'agriculture', label: '农产品' },
  { id: 'other', label: '航运/其他' },
] as const

export type ProductSector = (typeof PRODUCT_SECTORS)[number]['id']

const PRODUCT_SECTOR_IDS = new Set<string>(PRODUCT_SECTORS.map((sector) => sector.id))
const PRODUCT_SECTOR_LABELS = new Map<string, string>(
  PRODUCT_SECTORS.map((sector) => [sector.id, sector.label]),
)

export const DEFAULT_PRODUCT_SECTOR: ProductSector = 'black'

/** 未知或缺失 taxonomy 不阻塞页面，但只能进入 other，禁止浏览器猜测。 */
export function normalizeProductSector(value: string | null | undefined): ProductSector {
  const normalized = value?.trim().toLowerCase() ?? ''
  return PRODUCT_SECTOR_IDS.has(normalized) ? normalized as ProductSector : 'other'
}

export function productSectorLabel(value: string | null | undefined): string {
  return PRODUCT_SECTOR_LABELS.get(normalizeProductSector(value)) ?? '航运/其他'
}

export interface ProductDirectoryGroup {
  id: ProductSector
  items: DominantContractItem[]
}

/** 只按后端 taxonomy 分组，不在浏览器维护品种目录。 */
export function groupDominantsBySector(items: DominantContractItem[]): ProductDirectoryGroup[] {
  const grouped = new Map<ProductSector, DominantContractItem[]>()
  for (const item of items) {
    const sector = normalizeProductSector(item.sector)
    const group = grouped.get(sector) ?? []
    group.push(item)
    grouped.set(sector, group)
  }
  return PRODUCT_SECTORS.flatMap((sector) => {
    const group = grouped.get(sector.id)
    if (!group?.length) return []
    return [{
      id: sector.id,
      items: [...group].sort((left, right) => left.product.localeCompare(right.product)),
    }]
  })
}
