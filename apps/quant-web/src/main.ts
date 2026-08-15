import { createApp } from 'vue'
import { router } from './app/router'
import App from './App.vue'
import './style.css'
import { purgeLegacyWebCredentials } from './utils/settings'

// 应用入口：挂载 Vue Router 后渲染根组件
purgeLegacyWebCredentials()
const app = createApp(App)
app.use(router)
app.mount('#app')
