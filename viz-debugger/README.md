# viz-debugger

임무 실행 기록을 되짚는 디버깅 도구의 HCI 프로토타입이다. **이 폴더는 `web-dashboard`를 대체하지 않는다.** 현재 게이트웨이와 데이터는 목이며, 화면 상단에도 그 사실을 표시한다.

```bash
npm install
npm run dev
```

브라우저는 `http://127.0.0.1:5174`, 목 WebSocket 게이트웨이는 `ws://127.0.0.1:8790`을 사용하므로 기존 대시보드(5173/8787)와 동시에 실행할 수 있다.

화면은 마일스톤과 노드를 클릭해 다음 계층으로 이동한다. 마일스톤 카드 배정, 그래프 노드 자유 배치, DAG/트리 전환, 노드 더블클릭, 임무 이력 리플레이, 실패 파라미터 수정이 동작한다. 정적 전달본과 논의 항목은 [HANDOFF.md](./HANDOFF.md)에 정리했다.

검증은 `npm run verify:scenario`, `npm run verify:layout`, `npm run verify:hierarchy`, `npm run verify:adapter-swap`, `npm run verify:transport`, `npm run typecheck`, `npm run build`로 실행한다.
