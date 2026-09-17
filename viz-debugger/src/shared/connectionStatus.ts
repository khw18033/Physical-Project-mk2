/**
 * src/shared/connectionStatus.ts (260916 — 단독 빌드 정합 §2)
 *
 * 게이트웨이에 지금 붙어 있는가. **상단 바의 `conn` 배지가 이것 하나를 본다.**
 *
 * ## 왜 `tabs/` 에서 나왔나
 *
 * 이 훅은 `tabs/data/hooks.ts:48` 에 있었다. 그런데 몸통은 `getTransport()` 뿐이고
 * 대시보드 저장소를 한 글자도 안 쓴다 — `tabs/` 에 있을 이유가 없었다.
 *
 * 있을 이유가 없는데 있었던 대가가 컸다. 셸이 배지 하나를 그리려고 `useTabsDataLayer()` 를
 * 불렀고, 그 함수가 구역 축 구독과 AI 실패 알림을 같이 달고 있어서 **대시보드 데이터 계층
 * 전체가 셸에 딸려 들어왔다.** 그래서 셸이 통째로 단독 빌드 금지 목록에 올랐고, 그 김에
 * 모드 스위치·연결 관리·긴급정지까지 19일간 전달본에서 빠져 있었다.
 *
 * `shared/` 로 옮기면 그 사슬이 끊어진다. 배지는 배지대로 뜨고 데이터 계층은 통합 빌드가
 * 주입한다(`shared/appServices.ts`).
 *
 * ## ⚠ 이 훅을 부르면 **연결이 시작된다**
 *
 * `getTransport()` 는 조회 함수가 아니다. 첫 호출에 전송 계층을 만들고 곧바로 `connect()`
 * 한다(`transport/index.ts:67-72`). 그러니 이 훅을 그리는 화면은 **열리는 순간 게이트웨이에
 * 붙으러 간다.**
 *
 * 단독 빌드에서 이것이 동작 변화다. 전에는 `commandCenter.ts:267` 의 지연 경로 하나뿐이라
 * **명령을 내야** 붙었는데, 이제 **열자마자** 붙는다. 붙는지 여부가 아니라 시점이 바뀐 것이다.
 * 막을지 말지는 이 파일이 정하지 않는다 — 관측 결과가 보고서에 있다.
 */

import { useEffect, useState } from 'react';
import { getTransport, type ConnectionStatus } from '../transport/index.ts';

export type { ConnectionStatus };

export function useConnectionStatus(): ConnectionStatus {
  const transport = getTransport();
  const [status, setStatus] = useState<ConnectionStatus>(() => transport.getStatus());
  useEffect(() => transport.onStatus(setStatus), [transport]);
  return status;
}
