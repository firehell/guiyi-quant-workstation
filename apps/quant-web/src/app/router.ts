import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/** 应用路由表：Market、人工 Execution Review 与本机研究回测；meta.title 供导航使用 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/market',
    children: [
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
        path: 'trade-records',
        name: 'trade-records',
        component: () => import('@/pages/trade-records/index.vue'),
        meta: { title: '交易记录', icon: 'review' },
      },
      {
        path: 'backtests',
        name: 'backtests',
        component: () => import('@/pages/backtests/index.vue'),
        meta: { title: 'RQAlpha 回测', icon: 'backtest' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/pages/NotFound.vue'),
        meta: { title: '页面不存在', icon: 'shield' },
      },
    ],
  },
]

/** Vue Router 实例，使用 HTML5 History 模式 */
export const router = createRouter({
  history: createWebHistory(),
  routes,
})
