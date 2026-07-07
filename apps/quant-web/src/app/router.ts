import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/pages/dashboard/index.vue'),
        meta: { title: '仪表盘', icon: 'dashboard' },
      },
      {
        path: 'data',
        name: 'data',
        component: () => import('@/pages/data/index.vue'),
        meta: { title: '数据中心', icon: 'database' },
      },
      {
        path: 'market',
        name: 'market',
        component: () => import('@/pages/market/index.vue'),
        meta: { title: '行情看板', icon: 'chart' },
      },
      {
        path: 'market/chart',
        name: 'market-chart',
        component: () => import('@/pages/market/chart.vue'),
        meta: { title: '品种行情', icon: 'chart' },
      },
      {
        path: 'strategy',
        name: 'strategy',
        component: () => import('@/pages/strategy/index.vue'),
        meta: { title: '策略管理', icon: 'strategy' },
      },
      {
        path: 'backtest',
        name: 'backtest',
        component: () => import('@/pages/backtest/index.vue'),
        meta: { title: '回测中心', icon: 'backtest' },
      },
      {
        path: 'backtest/batch',
        name: 'backtest-batch',
        component: () => import('@/pages/backtest/batch.vue'),
        meta: { title: '批量回测', icon: 'backtest' },
      },
      {
        path: 'signal',
        name: 'signal',
        component: () => import('@/pages/signal/index.vue'),
        meta: { title: '信号监控', icon: 'signal' },
      },
      {
        path: 'review',
        name: 'review',
        component: () => import('@/pages/review/index.vue'),
        meta: { title: '复盘分析', icon: 'review' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/pages/settings/index.vue'),
        meta: { title: '系统设置', icon: 'settings' },
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
