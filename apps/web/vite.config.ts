import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Built assets go to apps/web/dist and are served by the Wizard API; the dev server proxies /api to it.
export default defineConfig({
  resolve: {tsconfigPaths: true},
  plugins: [react(), tailwindcss()],
  build: {outDir: 'dist', emptyOutDir: true, assetsDir: 'assets', sourcemap: false, chunkSizeWarningLimit: 1500},
  server: {port: 5173, proxy: {'/api': 'http://127.0.0.1:8770'}},
  test: {environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'], globals: false},
});
