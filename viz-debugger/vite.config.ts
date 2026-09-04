// 이식: web-dashboard/vite.config.ts @ 605eb73 — 포트만 변경
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    // 계약(`contracts/*.schema.json`)이 저장소 루트에 있고 `src/generate/` 가 그것을
    // 직접 import 한다 — **계약이 원본**이므로 사본을 두지 않는다(260904 §3).
    // 개발 서버는 기본적으로 프로젝트 루트 밖 파일을 못 내주므로 그 한 칸만 연다.
    fs: { allow: ['..'] },
  },
  build: { rollupOptions: { input: { app: resolve(__dirname, 'index.html') } } },
});
