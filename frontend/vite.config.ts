import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Proxy API and WebSocket calls to the FastAPI backend during development.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
  build: {
    // Output to ../src/openplot/static for bundling into the Python package.
    outDir: '../src/openplot/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }

          if (
            id.includes('react-markdown') ||
            id.includes('remark-gfm') ||
            id.includes('micromark') ||
            id.includes('mdast') ||
            id.includes('hast') ||
            id.includes('unist') ||
            id.includes('vfile')
          ) {
            return 'markdown'
          }

          if (id.includes('@iconify') || id.includes('@iconify-icons')) {
            return 'iconify'
          }

          if (id.includes('@base-ui') || id.includes('react-resizable-panels')) {
            return 'ui'
          }

          if (id.includes('lucide-react')) {
            return 'lucide'
          }

          if (id.includes('react') || id.includes('scheduler')) {
            return 'react-vendor'
          }

          return undefined
        },
      },
    },
  },
})
