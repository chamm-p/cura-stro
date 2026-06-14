import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Backend-Ziel für den Dev-Proxy. In der Container-Compose erreichbar als
// http://backend:8000, lokal als http://localhost:9605.
const BACKEND = process.env.BACKEND_PROXY_TARGET || 'http://localhost:9605'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
    },
  },
})
