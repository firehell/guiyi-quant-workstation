import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/** 应用路由表：Market 工作台；meta.title 供导航使用 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/workstation',
    children: [
      { path: 'workstation', name: 'operations', component: () => import('@/pages/workstation/OperationsPage.vue'), meta: { title: '运行台' } },
      { path: 'strategies/:strategyId?', name: 'strategies', component: () => import('@/pages/workstation/StrategyCenterPage.vue'), meta: { title: '策略中心' } },
      { path: 'backtests/:runId?', name: 'backtests', component: () => import('@/pages/workstation/BacktestCenterPage.vue'), meta: { title: '回测中心' } },
      { path: 'simulations', name: 'simulations', component: () => import('@/pages/workstation/SimulationCenterPage.vue'), meta: { title: '模拟交易中心' } },
      { path: 'trade-journal/:caseId?', name: 'trade-journal', component: () => import('@/pages/workstation/TradeJournalPage.vue'), meta: { title: '交易日志与复盘中心' } },
      { path: 'research/statistics/:taskId?', name: 'statistics-research', component: () => import('@/pages/workstation/StatisticsResearchPage.vue'), meta: { title: '统计与研究中心' } },
      { path: 'research', name: 'research', component: () => import('@/pages/workstation/ResearchPage.vue'), meta: { title: '研究' } },
      {
        path: 'market',
        name: 'market',
        component: () => import('@/pages/market/index.vue'),
        meta: { title: '行情看板' },
      },
      {
        path: 'market/chart',
        name: 'market-chart',
        component: () => import('@/pages/market/chart.vue'),
        meta: { title: '品种行情' },
      },
      { path: 'research/subing-decision', name: 'subing-decision', component: () => import('@/pages/research/SubingDecisionPage.vue'), meta: { title: '苏冰决策' } },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/pages/NotFound.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

/** Vue Router 实例，使用 HTML5 History 模式 */
export const router = createRouter({
  history: createWebHistory(),
  routes,
})
