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
import {
  canApproach, issueApproach, issueSdkAuto, issueSdkStart, issueSdkStop, stopFailureMessage,
} from './robotCommands.ts';
import { isStanding } from './uplink.ts';
import { SdkState } from './DeviceFacts.tsx';
import { SDK_ACTIONS } from './presets.ts';
import { NO_NODE } from './missionLink.ts';
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
    {/*
      **일시정지 중.** 정지와 다른 띠다 — 잠긴 것이 아니라 멈춰 있는 것이고, 여덟 칸도
      진행률도 그대로 남아 있다. 재시작이 무엇을 할지 **미리 적는다**: 로봇에 이어 하기가
      없어서 그 단계를 처음부터 다시 한다. 「이어서 간다」고 읽으면 발표자가 세 걸음째부터
      돌 줄 알고 기다린다.
    */}
    {session.paused !== null && <p className="robot-paused">
      <b>일시정지</b> {new Date(session.paused.atIso).toLocaleTimeString()}
      {session.paused.published ? ' · 로봇에 정지를 보냈습니다' : ' · 로봇에 못 보냈습니다'}
      {session.paused.failure !== null && <em> — {session.paused.failure}</em>}
      <span>진행상황은 그대로 있습니다. 재시작하면 {session.paused.taskId === null
        ? '멈춘 자리에서 다시 시작합니다'
        : `${session.paused.taskId} 를 처음부터 다시 합니다 — 로봇에 이어 하기가 없습니다`}.</span>
    </p>}

    {stopped !== null && <p className="robot-locked">
      <b>정지됨</b> {new Date(stopped.atIso).toLocaleTimeString()}
      {stopped.published && ' · 정지 명령을 보냈습니다'}
      <button type="button" className="robot-release" onClick={() => releaseStopped()}>
        정지 해제 — 다시 승인해야 합니다
      </button>
    </p>}

    {/*
      **로봇이 일어서는 중** (연동 가이드 §4-3).

      구동 브리지는 평시에 내려가 있다 — 기동하는 순간 로봇이 일어서기 때문이다. 이동
      명령이 오면 알아서 띄우고, 그 몇 초 동안은 `sdk_starting` 만 오고 임무 ACK 는 하나도
      안 온다. 그 구간에 화면이 조용하면 **명령이 안 갔다고 읽힌다.**

      가이드가 「화면에 그대로 드러내야 한다」고 못박은 자리다.
    */}
    {isStanding(session.stage) && <p className="robot-standing" role="status">
      <b>로봇이 일어서는 중입니다</b> — 구동 브리지를 띄우고 있습니다. 기립에 몇 초 걸립니다.
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

    {/*
      **로봇이 이미 걸었다** (260910 실측).

      스캔에 `forward_m: 0` 을 보내는데도 끝에 직진 한 걸음이 붙어서 온다. 0 을 「안 준
      것」으로 읽고 기본값을 쓰는 듯하다. 그러면 「접근 시작」은 **두 번째** 걸음이 된다.

      모르고 누르면 로봇이 왜 두 번 가는지 아무도 모른다. 누르기 전에 말한다.
    */}
    {session.walked !== null && <p className="robot-walked" role="alert">
      <b>스캔 중에 로봇이 이미 앞으로 걸었습니다</b> — <code>{session.walked}</code>.
      직진 없이(<code>forward_m 0</code>) 보냈는데도 왔습니다. 「접근 시작」을 누르면 한 번 더 갑니다.
    </p>}

    {/*
      **「문으로 판단했다」고 쓰면 안 된다** (연동 가이드 §5-3 · 260910 갱신).

      한동안 그렇게 적었다. 틀렸다 — **문 탐지 기능이 아직 없다.** `door_turn` 의 회전
      목표는 `-step_deg × (steps-1)` 로 고정된 기하값이고, 로봇이 방향을 고르는 절차는
      존재하지 않는다. 초록 칸은 「찾았다」가 아니라 **「지금 이쪽을 보고 있다」**다.

      문 유무는 탐지 담당이 붙을 때까지 **비어 있는 것이 맞다.** 지어 채우지 않는다.
    */}
    {session.doorTurn !== null && <p className="robot-door">
      {session.doorIndex === null
        ? '문 방향을 아직 못 정했습니다'
        : `${session.doorIndex + 1}번째 방향을 문으로 칩니다`}
      <em className="robot-door-temp">임시</em>
      <small>
        {/* 두 가지를 **갈라서** 적는다. 로봇이 바라보는 쪽과 우리가 문으로 친 쪽은 지금
            서로 무관하다 — 하나로 뭉쳐 적으면 로봇이 골랐다고 읽힌다. */}
        문 탐지가 아직 안 붙어서 여덟 중 하나를 무작위로 정했습니다.
        {session.doorTurn.chosenIndex !== null
          && ` 로봇이 실제로 바라보는 쪽은 ${session.doorTurn.chosenIndex + 1}번째입니다`}
        {session.doorTurn.yawDeg !== null && ` (${session.doorTurn.yawDeg}°)`}.
      </small>
    </p>}

    {/*
      **구동 준비 — 사람이 쥐는 손잡이** (260910 지시).

      평시에는 「연결만 된 상태」이고 임무가 붙어 이동 명령이 나갈 때 브리지가 알아서 뜬다.
      그게 기본 흐름이라 시연에서는 아무것도 안 눌러도 된다. 이 셋은 그 자동을 **미리
      당겨 쓰거나 아예 막고 싶을 때**의 자리다.

      `sdk_start` 는 **로봇을 일으켜 세운다** — 버튼 글씨에 그렇게 적는다. 「준비」라고만
      적으면 무엇이 일어나는지 모르고 누른다.
    */}
    {client !== null && <div className="robot-sdk">
      <span className="robot-sdk-label" title="구동 브리지(go1-sdk)는 평시에 내려가 있습니다">구동</span>
      <SdkState entityId="robot-01" />
      <button type="button" onClick={() => void issueSdkStart(client)}>
        미리 세우기 — 로봇이 일어섭니다
      </button>
      <button type="button" onClick={() => void issueSdkStop(client)}>
        내리기 — 선 채로 남습니다
      </button>
      <button type="button" onClick={() => void issueSdkAuto(client, false)}
        title="끄면 이동 명령이 go1_sdk_not_running 으로 거절됩니다">
        자동 기동 끄기
      </button>
      <button type="button" onClick={() => void issueSdkAuto(client, true)}>자동 기동 켜기</button>
      {/*
        **눌러도 안 되는 버튼을 조용히 두지 않는다** (260910 실측).

        가이드 §4-2 에 적힌 브리지 어휘가 지금 pi7 에 올라가 있지 않다 —
        `UNIMPLEMENTED: action not supported` 로 돌아온다. 비활성으로 감추면 「왜 회색이지」가
        되고, 그냥 두면 발표자가 계속 누른다. 한 번 듣고 나면 화면이 그 사실을 말한다.

        **하드웨어가 올리는 날 저절로 풀린다** — 거절이 멈추면 이 줄이 사라진다.
      */}
      {sdkUnsupported(session.unsupported) && <span className="robot-sdk-none">
        이 로봇 노드에는 구동 명령이 아직 없습니다 — <code>UNIMPLEMENTED</code>.
        이동 명령이 브리지를 알아서 띄우는 경로는 그대로 돕니다.
      </span>}
    </div>}

    {/* 거절과 실패 — **코드와 문구를 그대로** 올린다 (§3). */}
    {Object.values(session.commands).filter((c) => c.state === 'failed').map((c) => (
      <p key={c.commandId} className="robot-reject" role="alert">
        {/* 노드가 없는 명령은 **명령 이름**으로 부른다 — `no-node` 는 우리 내부의 자리
            이름이지 사람이 읽을 말이 아니다. 실제로 화면에 샜다 (260910). */}
        {c.taskId === NO_NODE ? c.action : c.taskId} 실패 — <code>{c.code ?? '사유 없음'}</code> {c.message}
      </p>
    ))}
  </section>;
}

/** 셋 중 하나라도 「그런 명령 없다」를 들었으면 어휘 자체가 안 올라간 것이다. */
function sdkUnsupported(unsupported: Readonly<Record<string, true>>): boolean {
  return Object.values(SDK_ACTIONS).some((action) => unsupported[action] === true);
}

/** 지금까지 실제로 채워진 칸 수. 화면이 그리는 것과 같은 열을 센다. */
function cellsFilled(total: number): number {
  const fill = reduceFrames(emptyFill(total), framesUpTo(Number.MAX_SAFE_INTEGER));
  return cellsInOrder(fill).filter((cell) => cell.phase !== 'pending').length;
}
