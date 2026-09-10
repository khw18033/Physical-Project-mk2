/**
 * src/physical/robotClient.ts (260910 신설 — 화면 연결)
 *
 * **화면이 쓰는 클라이언트 하나.** 여러 화면이 각자 만들면 브로커에 여러 번 붙고,
 * 그중 하나만 정지 명령을 받는 날이 온다.
 *
 * 만들기만 하고 **붙지는 않는다** — 붙는 것은 사람이 「연결 확인」을 누를 때다.
 * 화면을 열자마자 브로커를 찾아 나서면, 브로커가 없는 개발 자리에서 매번 실패 로그가 쌓인다.
 */

import { PhysicalClient } from './PhysicalClient.ts';
import { issuePing } from './robotCommands.ts';
import { setConnection } from './robotSession.ts';

let singleton: PhysicalClient | null = null;

export function robotClient(): PhysicalClient {
  if (singleton === null) {
    singleton = new PhysicalClient('robot-01');
    // **연결 상태는 만들 때 잇는다** (260910). 화면 부품이 구독하게 두면 그 부품이 안 떠
    // 있는 동안의 변화를 놓치고, 「붙었는데 세션은 모른다」가 된다 — 승인 순간에 그게
    // 나면 대본 타이머가 돌아 로봇보다 화면이 앞서 간다.
    singleton.onStatus(setConnection);
  }
  return singleton;
}

/**
 * 연결 관리가 쓰는 얇은 면 (`PhysicalProbe`). **주소·토픽은 여기서도 안 샌다** —
 * 팝업은 「붙어라 · 물어봐라」만 알고 어디에 어떻게 붙는지는 모른다.
 */
export function robotProbe() {
  const client = robotClient();
  return {
    connect: () => client.connect(),
    getStatus: () => client.getStatus(),
    ping: () => issuePing(client),
  };
}
