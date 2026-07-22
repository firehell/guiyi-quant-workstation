import { createApp } from 'vue'
import { pinia } from './app/pinia'
import { router } from './app/router'
import App from './App.vue'
import './style.css'
import { purgeLegacyWebCredentials } from './utils/settings'

// 应用入口：挂载 Pinia 状态与 Vue Router 后渲染根组件
purgeLegacyWebCredentials()
const app = createApp(App)
app.use(pinia)
app.use(router)
app.mount('#app')
