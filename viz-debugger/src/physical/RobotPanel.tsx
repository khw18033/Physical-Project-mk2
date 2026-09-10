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

import { PhysicalClient } from './PhysicalClient.ts';
import { canApproach, issueApproach, stopFailureMessage } from './robotCommands.ts';
import { releaseStopped, useRobotSession } from './robotSession.ts';
import { cellsInOrder, emptyFill, reduceFrames } from '../viewpoint/fill.ts';
import { framesUpTo } from '../viewpoint/store.ts';

export function RobotPanel({ client, params }: {
  client: PhysicalClient | null;
  params: Record<string, unknown> | null;
}) {
  const session = useRobotSession();

  // 연결 상태를 여기서 구독하지 않는다 — `robotClient()` 가 만들 때 이어 둔다.
  // 이 부품이 안 떠 있는 동안의 변화를 놓치면 「붙었는데 세션은 모른다」가 된다.

  /**
   * **uplink 수신과 스캔 발행은 여기 없다** (260910 실측). 이 패널은 마일스톤 화면에만
   * 있어서, 로봇이 도는 중에 노드를 눌러 그래프로 들어가면 사라진다 — 그동안의 응답이
   * 통째로 버려졌다. 배선은 두 빌드가 공유하는 뿌리 화면으로 옮겼다(`useRobotUplink`).
   *
   * 여기 남은 것은 **사람이 누르는 것**과 지금까지 받은 것을 그리는 일뿐이다.
   */

  // 우리가 실제로 채운 칸 — 화면과 같은 값이다.
  const total = typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8;
  const filled = Object.keys(session.warnings).length > 0 || session.progress !== null
    ? cellsFilled(total)
    : 0;

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

      {/*
        진행률 — **우리가 센 것을 앞에 둔다.**

        로봇의 `ack` 는 문서상 「이번 임무의 ACK 순번」인데 실제로는 명령마다 10씩 **누적**된다
        (260910 실측: 30 → 40 → 50). 그걸 그대로 「50 / 10」으로 띄우면 보는 사람이 못 읽는다.
        그렇다고 고쳐 적으면 어긋난 사실이 묻히므로, **우리 값을 앞에 두고 로봇 값을 그대로
        옆에 붙인다.** 하드웨어 쪽에 물어볼 숫자다.
      */}
      {filled > 0 && <span className="robot-progress">{filled} / {total} 칸</span>}
      {session.progress !== null && <span
        className={`robot-ack${session.progress.ack > session.progress.of ? ' robot-ack--odd' : ''}`}
        title="로봇이 보낸 ACK 순번 · 문서는 임무별이라고 했으나 실측은 누적"
      >ACK {session.progress.ack}/{session.progress.of}</span>}

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

    {/* **어긋남을 보여 주지 않는다** (260910 지적). 로봇이 고른 쪽이 곧 화면이 고른
        쪽이므로 어긋날 것이 없다 — 로봇이 문으로 판단한 칸에 초록이 켜지고 거기서
        「문에 접근한다」로 선이 이어진다. */}
    {session.doorTurn !== null && <p className="robot-door">
      로봇이 {session.doorTurn.chosenIndex === null
        ? '문 방향으로 돌았습니다 — 어느 걸음인지는 못 짚었습니다'
        : `${session.doorTurn.chosenIndex + 1}번째 방향을 문으로 판단했습니다`}
      {session.doorTurn.yawDeg !== null && ` (${session.doorTurn.yawDeg}°)`}
    </p>}

    {/* 거절과 실패 — **코드와 문구를 그대로** 올린다 (§3). */}
    {Object.values(session.commands).filter((c) => c.state === 'failed').map((c) => (
      <p key={c.commandId} className="robot-reject" role="alert">
        {c.taskId} 실패 — <code>{c.code ?? '사유 없음'}</code> {c.message}
      </p>
    ))}
  </section>;
}

/** 지금까지 실제로 채워진 칸 수. 화면이 그리는 것과 같은 열을 센다. */
function cellsFilled(total: number): number {
  const fill = reduceFrames(emptyFill(total), framesUpTo(Number.MAX_SAFE_INTEGER));
  return cellsInOrder(fill).filter((cell) => cell.phase !== 'pending').length;
}
