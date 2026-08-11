/** Market 首页的只读展示目录：中文名称与一级板块均不改变后端事实。 */
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

export interface ProductDirectoryEntry {
  name: string
  sector: ProductSector
}

export interface ProductDisplay extends ProductDirectoryEntry {
  symbol: string
}

export const DEFAULT_PRODUCT_SECTOR: ProductSector = 'black'

/** active 60 的唯一展示映射。黑色上游与钢材成材分开，避免品种重叠。 */
export const PRODUCT_DIRECTORY: Record<string, ProductDirectoryEntry> = {
  a: { name: '豆一', sector: 'agriculture' },
  ag: { name: '白银', sector: 'precious' },
  al: { name: '铝', sector: 'nonferrous' },
  ao: { name: '氧化铝', sector: 'nonferrous' },
  ap: { name: '苹果', sector: 'agriculture' },
  au: { name: '黄金', sector: 'precious' },
  b: { name: '豆二', sector: 'agriculture' },
  bu: { name: '沥青', sector: 'energy' },
  bz: { name: '纯苯', sector: 'chemical' },
  c: { name: '玉米', sector: 'agriculture' },
  cf: { name: '棉花', sector: 'agriculture' },
  cj: { name: '红枣', sector: 'agriculture' },
  cu: { name: '铜', sector: 'nonferrous' },
  eb: { name: '苯乙烯', sector: 'chemical' },
  ec: { name: '集运欧线', sector: 'other' },
  eg: { name: '乙二醇', sector: 'chemical' },
  fg: { name: '玻璃', sector: 'building' },
  fu: { name: '燃料油', sector: 'energy' },
  hc: { name: '热轧卷板', sector: 'steel' },
  i: { name: '铁矿石', sector: 'black' },
  j: { name: '焦炭', sector: 'black' },
  jd: { name: '鸡蛋', sector: 'agriculture' },
  jm: { name: '焦煤', sector: 'black' },
  l: { name: '聚乙烯', sector: 'chemical' },
  lc: { name: '碳酸锂', sector: 'new_energy' },
  lh: { name: '生猪', sector: 'agriculture' },
  m: { name: '豆粕', sector: 'agriculture' },
  ma: { name: '甲醇', sector: 'chemical' },
  ni: { name: '镍', sector: 'nonferrous' },
  oi: { name: '菜籽油', sector: 'agriculture' },
  p: { name: '棕榈油', sector: 'agriculture' },
  pb: { name: '铅', sector: 'nonferrous' },
  pd: { name: '钯金', sector: 'precious' },
  pf: { name: '短纤', sector: 'chemical' },
  pg: { name: '液化石油气', sector: 'energy' },
  pk: { name: '花生', sector: 'agriculture' },
  pl: { name: '瓶片', sector: 'chemical' },
  pp: { name: '聚丙烯', sector: 'chemical' },
  pr: { name: '丙烯', sector: 'chemical' },
  ps: { name: '多晶硅', sector: 'new_energy' },
  pt: { name: '铂金', sector: 'precious' },
  px: { name: '对二甲苯', sector: 'chemical' },
  rb: { name: '螺纹钢', sector: 'steel' },
  rm: { name: '菜粕', sector: 'agriculture' },
  rs: { name: '油菜籽', sector: 'agriculture' },
  ru: { name: '天然橡胶', sector: 'chemical' },
  sa: { name: '纯碱', sector: 'building' },
  sc: { name: '原油', sector: 'energy' },
  sf: { name: '硅铁', sector: 'black' },
  sh: { name: '烧碱', sector: 'chemical' },
  si: { name: '工业硅', sector: 'new_energy' },
  sm: { name: '锰硅', sector: 'black' },
  sn: { name: '锡', sector: 'nonferrous' },
  sr: { name: '白糖', sector: 'agriculture' },
  ss: { name: '不锈钢', sector: 'steel' },
  ta: { name: 'pta', sector: 'chemical' },
  ur: { name: '尿素', sector: 'chemical' },
  v: { name: 'pvc', sector: 'chemical' },
  y: { name: '豆油', sector: 'agriculture' },
  zn: { name: '锌', sector: 'nonferrous' },
}

/** 返回首页显示所需的中文名称和唯一板块；目录外品种不阻塞页面。 */
export function describeProduct(symbol: string, fallbackName: string): ProductDisplay {
  const normalized = symbol.trim().toLowerCase()
  const entry = PRODUCT_DIRECTORY[normalized]
  return {
    symbol: normalized,
    name: entry?.name || fallbackName || normalized.toUpperCase(),
    sector: entry?.sector || 'other',
  }
}
