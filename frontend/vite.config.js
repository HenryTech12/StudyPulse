import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000', '/uploads': 'http://localhost:8000', '/ws': { target: 'ws://localhost:8000', ws: true } } },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.js',
    include: ['src/**/*.test.jsx'],
    testTimeout: 20000,
    env: { VITE_API_URL: process.env.E2E_API || 'http://127.0.0.1:8765' },
  },
});
