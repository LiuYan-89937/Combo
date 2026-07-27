import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { fileURLToPath, URL } from 'node:url'

const backendProxy = {
  '/health': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
  '/events': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [
    vue(),
    UnoCSS(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 3000,
    strictPort: true,
    host: '127.0.0.1',
    proxy: backendProxy,
  },
  preview: {
    port: 3000,
    strictPort: true,
    host: '127.0.0.1',
    proxy: backendProxy,
  },
  build: {
    target: 'esnext',
    minify: 'terser',
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'ui-vendor': ['naive-ui'],
          'editor': ['monaco-editor'],
          'markdown': [
            'unified',
            'remark-parse',
            'remark-gfm',
            'remark-math',
            'remark-rehype',
            'rehype-highlight',
            'rehype-katex',
            'rehype-sanitize',
            'rehype-stringify',
            'unist-util-visit',
            'highlight.js',
            'katex',
            'mermaid',
          ]
        }
      }
    }
  }
})
