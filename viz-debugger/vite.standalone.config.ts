import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
// 기능 상태 서비스를 옮기는 창구 (260920) — **통합 설정과 같은 것을 쓴다.**
import { capabilityRelay } from './scripts/capability-relay.mjs';

/**
 * 탭① **단독 빌드**. 캔버스만 담는 전달본이고 논문 측정축 D(계측 오버헤드)를 이것으로 잰다.
 *
 * ## 창구는 왜 여기도 있나 (260920)
 *
 * 단독본은 `screen: 'milestones'` 로 열린다 — **전달본을 켜면 제일 먼저 보이는 화면에
 * 기능 판이 있다.** 그런데 여기에는 창구가 없어서, 그 판만 늘 「못 읽었습니다」였다.
 * 통합 빌드에서는 되고 전달본에서만 안 되는 것은 전달본을 받은 사람에게 설명할 수 없다.
 *
 * **번들에는 한 바이트도 안 들어간다.** 창구는 개발·미리보기 서버의 미들웨어이고
 * `vite build` 는 `configureServer`·`configurePreviewServer` 를 부르지 않는다 —
 * 측정축 D 는 그대로다.
 *
 * 다른 파트의 창구(`/detect-sample` · `/autodrive-ai` · 임무 기록)는 **여기 안 넣는다.**
 * 그쪽은 이번에 건드린 것이 아니고, 넣으면 단독본의 성격이 조용히 통합본 쪽으로 옮겨 간다.
 */
export default defineConfig({
  base: './',
  plugins: [react(), capabilityRelay()],
  build: {
    outDir: 'dist-standalone',
    emptyOutDir: true,
    rollupOptions: { input: { standalone: resolve(__dirname, 'standalone.html') } },
  },
  /**
   * 지은 것을 **실제로 열어 보는 길** (`npm run preview:standalone`). 전까지는 짓기만 하고
   * 띄우는 길이 없어서, 전달본이 어떻게 보이는지 아무도 확인하지 않은 채 나갔다.
   * 5174(통합)·5173(web-dashboard)과 안 겹치게 5175 다.
   */
  preview: { port: 5175, strictPort: true },
  server: { port: 5175, strictPort: true },
});
