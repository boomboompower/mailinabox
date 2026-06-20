import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2'
import './assets/main.css'

createApp(App).use(createPinia()).use(router).mount('#app')
