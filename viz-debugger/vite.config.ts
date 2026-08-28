// 이식: web-dashboard/vite.config.ts @ 605eb73 — 포트만 변경
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  base: './',
  plugins: [react()],
  server: { port: 5174, strictPort: true },
  build: { rollupOptions: { input: { app: resolve(__dirname, 'index.html') } } },
});
