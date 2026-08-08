import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://api:8000',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // Serve the pmtiles base map through the same origin as the page so the
      // browser does not make a cross-origin fetch (which would require CORS).
      // Range requests used by the pmtiles protocol pass through the proxy.
      '/tiles': {
        target: 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
})
