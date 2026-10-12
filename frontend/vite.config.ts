import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // В разработке API запущен отдельно (uvicorn на 8000)
    proxy: { '/api': 'http://localhost:8000' },
  },
})
