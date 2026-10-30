import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The Pages site (src/site.tsx): Brain and Cases as static pages with relative paths, built into dist/site beside the app.
// Wizard copies them to the site's branch when the person publishes (services/api/wizard_api/site.py).
export default defineConfig({
  base: './',
  resolve: {tsconfigPaths: true},
  plugins: [react(), tailwindcss()],
  build: {outDir: 'dist/site', emptyOutDir: true, assetsDir: 'assets', sourcemap: false, chunkSizeWarningLimit: 1500,
    rollupOptions: {input: 'site.html'}},
});
