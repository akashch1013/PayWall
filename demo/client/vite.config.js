import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const api = 'http://localhost:4000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': api,
      '/uploads': api,
      '/seed-images': api,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.js'],
    globals: true,
  },
});
