import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // In dev, serve from root so router and API proxy work without /admin prefix complexity.
  // In build, assets land at /admin/static/app/assets/ which Flask's static handler serves.
  base: command === 'serve' ? '/' : '/admin/static/app/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Proxy all /admin/* API calls to the Flask daemon, stripping the prefix.
      // Vite serves its own assets before the proxy, so /admin/static/app/ is safe.
      '/admin': {
        target: 'http://127.0.0.1:10222',
        rewrite: (path) => path.replace(/^\/admin/, '') || '/',
        changeOrigin: true,
      },
    },
  },
}))
