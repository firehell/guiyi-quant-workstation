import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/** 应用路由表：主布局包裹各功能页，meta.title 供侧边栏与面包屑使用 */
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
        path: 'signal',
        name: 'signal',
        component: () => import('@/pages/signal/index.vue'),
        meta: { title: '信号监控', icon: 'signal' },
      },
      {
        path: 'runtime',
        name: 'runtime',
        component: () => import('@/pages/runtime/index.vue'),
        meta: { title: '运行状态', icon: 'runtime' },
      },
      {
        path: 'review',
        name: 'review',
        component: () => import('@/pages/review/index.vue'),
        meta: { title: '复盘分析', icon: 'review' },
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
