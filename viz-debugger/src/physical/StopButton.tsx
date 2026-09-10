/**
 * src/physical/StopButton.tsx (260910 신설 — 화면 연결 §4)
 *
 * **화면에 이미 있던 「■ 중단」을 살린 것이다.** 새 버튼이 아니라, 셸(`AppShell`)과 단독
 * 상단 바(`TopBar`)가 각자 그리던 그 버튼을 한 부품으로 모아 실제로 동작하게 했다.
 * 두 곳에 같은 동작을 손으로 적으면 언젠가 한쪽만 고쳐진다.
 *
 * ## 지키는 것 넷
 *
 *  - **어느 화면에 있든 보인다** — 머리줄에 있으므로 마일스톤이든 뷰 노드든 늘 떠 있다
 *  - **확인 대화상자를 띄우지 않는다** — 한 번 누르면 멈춘다
 *  - **크고, 색이 다르고, 다른 버튼과 떨어져 있다** — 잘못 누르는 것보다 못 누르는 게 나쁘다
 *  - **연결이 없어도 비활성화하지 않는다** — 누를 수 있어야 하고 못 보냈으면 그렇게 말한다
 *
 * ## 이건 안전장치가 아니다
 *
 * 화면의 정지는 네트워크를 타고 나간다. 브로커가 죽었거나 Wi-Fi 가 끊기면 안 나간다.
 * **물리적 비상 정지는 로봇 본체와 조종기 쪽에 있다** — 시험할 때도 발표할 때도 조종기를
 * 든 사람이 옆에 있어야 한다.
 */

import { emergencyStop } from './robotCommands.ts';
import { robotClient } from './robotClient.ts';
import { useRobotSession } from './robotSession.ts';

export function StopButton() {
  const session = useRobotSession();
  const locked = session.stopped !== null;
  return <button
    type="button"
    className={`robot-stop${locked ? ' robot-stop--locked' : ''}`}
    // **비활성화하지 않는다.** 연결이 없어도 누를 수 있어야 한다 — 2·3·4 는 그래도 일어난다.
    onClick={() => void emergencyStop(robotClient())}
    title="로봇을 즉시 멈춥니다 — 화면의 정지는 소프트웨어 정지입니다"
  >
    ■ 중단
  </button>;
}
