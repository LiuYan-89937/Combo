import '@unocss/reset/tailwind.css'
import 'uno.css'
import '@/rendering/markdown/styles.css'
import '@/App.vue'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import ProbeRoot from './ProbeRoot.vue'
import { installShowcaseServer } from '@/showcase/fakeServer'

installShowcaseServer()

const app = createApp(ProbeRoot)
app.use(createPinia())
app.use(naive)
app.mount('#app')
