export const workstationUiVersion = 'workstation-ui/v0.1.2'

export const workstationPages = [
  { name: 'market-chart', title: '我的看盘', group: '工作台', icon: 'chart' },
  { name: 'operations', title: '运行总览', group: '工作台', icon: 'pulse' },
  { name: 'strategies', title: '策略中心', group: '量化运行', icon: 'layers' },
  { name: 'simulations', title: '模拟交易', group: '量化运行', icon: 'wallet' },
  { name: 'backtests', title: '回测中心', group: '研究分析', icon: 'history' },
  { name: 'research', title: '研究中心', group: '研究分析', icon: 'flask' },
  { name: 'trade-journal', title: '交易复盘', group: '研究分析', icon: 'book' },
  { name: 'system', title: '数据与系统', group: '基础设施', icon: 'server' },
] as const

export function workstationSection(name: unknown) {
  if (name === 'market') return 'market-chart'
  if (name === 'statistics-research' || name === 'subing-decision' || name === 'new-subing-research') return 'research'
  return name
}
