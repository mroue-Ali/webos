import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In development the API runs on the host (see README); production serves this build
    // from the backend itself, so there is never a cross-origin request.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
