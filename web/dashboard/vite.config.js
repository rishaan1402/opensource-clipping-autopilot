import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        // In Docker Compose this resolves via the 'backend' service name;
        // for local (non-Docker) dev, override with VITE_API_TARGET.
        target: process.env.VITE_API_TARGET || 'http://backend:8000',
        changeOrigin: true,
      },
    },
    watch: {
      usePolling: true,
    },
  },
})
