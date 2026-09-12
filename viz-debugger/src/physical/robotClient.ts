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
import { issuePing, issueScan, shouldIssueScan } from './robotCommands.ts';
import { robotSession, setConnection, subscribeRobot } from './robotSession.ts';
import { currentMission } from '../data/scenario.ts';
import { receiveDeviceMessage } from './deviceState.ts';

let singleton: PhysicalClient | null = null;
/** 마지막으로 스캔을 시도한 조건. 같은 조건이면 다시 안 쏜다 (아래 주석). */
let lastScanAttempt = '';

export function robotClient(): PhysicalClient {
  if (singleton === null) {
    singleton = new PhysicalClient('robot-01');
    // **연결 상태는 만들 때 잇는다** (260910). 화면 부품이 구독하게 두면 그 부품이 안 떠
    // 있는 동안의 변화를 놓치고, 「붙었는데 세션은 모른다」가 된다 — 승인 순간에 그게
    // 나면 대본 타이머가 돌아 로봇보다 화면이 앞서 간다.
    singleton.onStatus(setConnection);
    // 장비 상태도 만들 때 잇는다 — 화면 부품이 안 떠 있는 동안의 값을 놓치면
    // 하드웨어 카드가 「모른다」로 남는다.
    singleton.onDevice(receiveDeviceMessage);
    /**
     * **승인이 스캔을 쏘는 자리도 여기다** (260911 — 두 판째에 안 나가던 자리).
     *
     * 전에는 화면의 `useEffect` 가 `session.approved` 가 바뀌는 것을 보고 쐈다. 한 판을
     * 돌린 뒤 같은 임무를 다시 올리면 `approved` 는 **true → false → true** 로 한 틱 안에
     * 오간다(`activateMission` 이 세션을 비우고 곧바로 승인이 다시 걸린다). React 가 그
     * 둘을 한 번의 그리기로 묶으면 **의존값이 안 바뀐 것으로 보여 효과가 안 돈다.**
     * 그러면 승인은 됐는데 로봇에는 아무것도 안 간다.
     *
     * 그래서 그리기와 무관한 자리로 옮겼다 — 세션이 바뀔 때마다 조건을 다시 보고, 참이면
     * 쏜다. 관문(`markScanIssued`)이 한 번만 열리게 스스로 빗장을 건다.
     *
     * 연결 상태·장비 상태를 여기서 잇는 것과 같은 이유이고 같은 자리다.
     */
    subscribeRobot(() => {
      if (!shouldIssueScan()) return;
      /**
       * **같은 조건으로 두 번 시도하지 않는다** (260912 — 브라우저가 멎었다).
       *
       * 발행이 실패하면 `issueScan` 이 관문을 도로 내린다(다시 시도할 수 있게). 그런데 그
       * 내림 자체가 세션 변경이라 이 구독이 다시 불리고, 조건이 그대로니 또 쏘고, 또 실패해
       * **한 틱 안에서 무한히 돈다.** 화면이 통째로 멎는다.
       *
       * 실제로 그렇게 멎었다 — 연결 상태만 `open` 이고 소켓은 안 붙은 상태에서.
       *
       * 그래서 **무엇이 바뀌었을 때만** 시도한다. 승인이나 연결 상태가 그대로면 한 번으로
       * 끝이고, 사유는 화면에 남는다. 다시 하려면 사람이 「처음부터」를 누른다.
       */
      const session = robotSession();
      const attempt = `${session.started}|${session.approved}|${session.connection.state}|${session.startedAtMs ?? 0}`;
      if (attempt === lastScanAttempt) return;
      lastScanAttempt = attempt;
      void issueScan(singleton as PhysicalClient, currentMission().params);
    });
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
