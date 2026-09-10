/**
 * src/physical/RobotPanel.tsx (260910 신설 · 같은 날 연결 관리로 정리)
 *
 * **시연 중에 사람이 누르는 자리.** 임무를 진행시키는 것만 남았다.
 *
 *   1. 발화/텍스트   — 이미 있다
 *   2. 승인          — 기존 승인 버튼. 거기서 스캔이 나간다
 *   3. **접근 시작** — `door_turn` 뒤에 열린다. 자동으로 안 넘어간다
 *   4. **긴급 정지** — 셸 머리줄의 「■ 중단」. 안전 기능이라 시연 화면에 그대로 있다
 *
 * ## 연결에 관한 것은 여기 없다 (연결 관리 통합 §4)
 *
 * 주소·프리셋·연결 확인 버튼을 걷어 냈다. 연결을 **바꾸는** 자리는 「연결 관리」 하나다 —
 * 두 군데 있으면 「어느 쪽이 진짜냐」가 생긴다. 시연 세팅은 무대에 오르기 전에 끝낸다.
 *
 * 끊긴 것을 시연 중에 알아야 하는 건 맞아서 **읽기 전용 표시등**을 셸 머리줄에 뒀다
 * (`ConnectionLamp`). 누르면 연결 관리가 열리고, 고치는 것은 거기서 한다.
 *
 * 남은 것은 연결이 아니라 **임무 진행**이다 — 진행률·접근 버튼·거절 사유, 그리고 정지 표시.
 */

import { useEffect } from 'react';
import { PhysicalClient } from './PhysicalClient.ts';
import { canApproach, issueApproach, stopFailureMessage } from './robotCommands.ts';
import { releaseStopped, setConnection, useRobotSession } from './robotSession.ts';

export function RobotPanel({ client, params }: { client: PhysicalClient | null; params: Record<string, unknown> | null }) {
  const session = useRobotSession();

  // 연결 상태는 표시등이 읽는다 — 여기서는 열에 흘려보내기만 한다.
  useEffect(() => {
    if (client === null) return;
    return client.onStatus(setConnection);
  }, [client]);

  const stopped = session.stopped;
  const failure = stopped === null ? null : stopFailureMessage(stopped);

  return <section className="robot-panel">
    {/* 정지 실패는 가장 위에, 크게. **조용히 성공한 척하는 것이 최악이다.** */}
    {failure !== null && <p className="robot-stopfail" role="alert">{failure}</p>}
    {stopped !== null && <p className="robot-locked">
      <b>정지됨</b> {new Date(stopped.atIso).toLocaleTimeString()}
      {stopped.published && ' · 정지 명령을 보냈습니다'}
      <button type="button" className="robot-release" onClick={() => releaseStopped()}>
        정지 해제 — 다시 승인해야 합니다
      </button>
    </p>}

    <div className="robot-bar">
      {/* **주소도 프리셋도 연결 확인도 여기 없다** (260910 연결 관리 통합 §4).
          연결을 바꾸는 자리는 「연결 관리」 하나다 — 두 군데 있으면 「어느 쪽이 진짜냐」가
          생긴다. 시연 세팅은 무대에 오르기 전에 끝내고, 발표 중에는 팝업을 열지 않는다.

          끊긴 것을 시연 중에 알아야 하는 건 맞아서, 읽기 전용 표시등을 셸 머리줄에 뒀다
          (`ConnectionLamp`) — 누르면 연결 관리가 열린다. */}

      {/* 진행률 — forward_m=0 이면 of 는 9다 (스캔 여덟 + door_turn 하나). */}
      {session.progress !== null && <span className="robot-progress">
        {session.progress.ack} / {session.progress.of}
      </span>}

      {/* 접근 시작 — **door_turn 뒤에만 열린다.** 자동으로 안 넘어간다 (§1). */}
      {canApproach() && client !== null && <button
        type="button"
        className="robot-approach"
        onClick={() => void issueApproach(client, params)}
      >
        접근 시작 — 문 쪽으로
      </button>}

      {/* **정지 버튼은 여기 없다.** 화면에 이미 있는 머리줄의 「■ 중단」을 살렸다
          (`AppShell`·`TopBar`) — 새로 만들지 않는다. 어느 화면에 있든 보여야 하는데
          머리줄은 늘 떠 있고 이 패널은 마일스톤 화면에만 있다. */}
    </div>

    {/* 로봇이 우리와 다른 방향을 보고 있다 — 시연 중에 알아야 하는 사실이다 (§5). */}
    {session.doorTurn?.mismatch != null && <p className="robot-yawoff">
      로봇이 {session.doorTurn.mismatch.robot}°, 화면이 고른 각도는 {session.doorTurn.mismatch.chosen}° —
      {' '}{Math.round(session.doorTurn.mismatch.diff)}° 어긋났습니다
    </p>}

    {/* 거절과 실패 — **코드와 문구를 그대로** 올린다 (§3). */}
    {Object.values(session.commands).filter((c) => c.state === 'failed').map((c) => (
      <p key={c.commandId} className="robot-reject" role="alert">
        {c.taskId} 실패 — <code>{c.code ?? '사유 없음'}</code> {c.message}
      </p>
    ))}
  </section>;
}
