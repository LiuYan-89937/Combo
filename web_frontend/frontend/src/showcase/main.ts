import '@unocss/reset/tailwind.css'
import 'uno.css'
import '@/rendering/markdown/styles.css'
import '@/App.vue'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import ShowcaseRoot from './ShowcaseRoot.vue'
import { installShowcaseServer } from './fakeServer'
import { showcaseRouter } from './router'

installShowcaseServer()

const app = createApp(ShowcaseRoot)
app.use(createPinia())
app.use(showcaseRouter)
app.use(naive)

void showcaseRouter.replace({ name: 'ChatNew' }).then(() => {
  app.mount('#app')
})
