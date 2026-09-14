import '@unocss/reset/tailwind.css'
import 'uno.css'
import '@/rendering/markdown/styles.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import PerfHarness from './tmp-perf.vue'

const started = performance.now()
const app = createApp(PerfHarness)
app.use(createPinia())
app.use(naive)
app.mount('#preview')
;(window as any).__mountMs = performance.now() - started
