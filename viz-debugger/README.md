# viz-debugger

임무 실행 기록을 되짚는 디버깅 도구의 0단계 골격이다. **이 폴더는 `web-dashboard`를 대체하지 않는다.** 현재 게이트웨이와 데이터는 목이며, 화면 상단에도 그 사실을 표시한다.

```bash
npm install
npm run dev
```

브라우저는 `http://127.0.0.1:5174`, 목 WebSocket 게이트웨이는 `ws://127.0.0.1:8790`을 사용하므로 기존 대시보드(5173/8787)와 동시에 실행할 수 있다.

검증은 `npm run verify:hierarchy`, `npm run verify:adapter-swap`, `npm run verify:transport`, `npm run typecheck`, `npm run build`로 실행한다.
