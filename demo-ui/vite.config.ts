import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    // Loopback only: the API trusts dev sign-in from loopback, so the proxy must not be reachable from the LAN.
    host: '127.0.0.1',
    proxy: {
      // Tabula product API (FastAPI, scripts/dev.sh).
      '/v1': { target: 'http://127.0.0.1:8080', changeOrigin: false },
      '/api': {
        target: 'http://localhost:8004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
    fs: {
      allow: ['..'],
    },
  },
});
