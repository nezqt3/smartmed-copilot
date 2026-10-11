import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/v1': process.env.SMARTMED_API_URL || 'http://127.0.0.1:8000',
      '/health': process.env.SMARTMED_API_URL || 'http://127.0.0.1:8000',
    },
  },
})
