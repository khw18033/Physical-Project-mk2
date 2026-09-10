/**
 * src/physical/robotBridge.ts (260910 신설 — 화면 연결 §3)
 *
 * **uplink → 화면 상태.** `effectsOf()` 가 이미 내놓는 것을 잇기만 한다. 여기서 새로
 * 계산하지 않는다 — 계산이 두 곳에 있으면 하나만 고쳐지는 날이 온다.
 *
 * 뷰포인트 프레임은 1단계가 세운 열(`src/viewpoint/store.ts`)로 들어간다. 그 열은
 * 프레임이 로봇에서 왔는지 대본에서 왔는지 모른다 — 260909 §6 의 규칙 그대로다.
 */

import { useEffect } from 'react';
import { appendViewpoint } from '../viewpoint/store.ts';
import { effectsOf, type LinkEffect } from './missionLink.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { advanceRobotHead, receiveRobotProgress } from '../data/scenario.ts';
import type { ScenarioEvent } from '../model/types.ts';
import { elapsedSec, applyEffects, robotSession, useRobotSession } from './robotSession.ts';
import { issueScan, shouldIssueScan } from './robotCommands.ts';
import { robotClient } from './robotClient.ts';
import type { UplinkMessage } from './uplink.ts';

/**
 * uplink 하나를 화면 상태로. 되돌려주는 것은 뷰포인트 열에 넣은 프레임 수다.
 *
 * `chosenAngleDeg` 는 화면이 고른 각도다 — `door_turn` 의 yaw 와 대조해 로봇이 우리와
 * 다른 방향을 보고 있는지 본다.
 */
export function receiveUplink(
  message: UplinkMessage,
  missionId: string,
  atSec: number,
  viewpointCount = 8,
): number {
  const effects = effectsOf(message, {
    // 어느 태스크의 응답인가 — 발행할 때 적어 둔 표를 본다.
    taskOf: (commandId) => robotSession().commands[commandId]?.taskId ?? null,
    // 이 판에서 본 방위들 — `door_turn` 이 어느 걸음이었는지 견주는 재료다.
    seenYawByIndex: new Map(Object.entries(robotSession().seenYaw).map(([k, v]) => [Number(k), v])),
    viewpointCount,
  });
  const frames = applyEffects(effects);
  for (const frame of frames) appendViewpoint(missionId, atSec, frame);
  // 이 봉투로 열에 넣은 프레임 수. **회전 프레임만 세면 안 된다** — 아래 판정 칠하기도
  // 프레임이고, 그것까지 세야 재생 머리가 그 뒤로 넘어간다.
  let appended = frames.length;

  /**
   * **로봇이 고른 칸이 초록이 된다** (260910 지적).
   *
   * 전에는 대본이 「index 2 가 문」이라고 정해 두고 로봇의 각도와 대조해 어긋남을 표시했다.
   * 그걸 뒤집었다 — **로봇이 문으로 판단해 몸을 돌린 그 방향이 답이다.** 어긋남을 보여 줄
   * 것이 아니라 로봇을 따라간다.
   *
   * 판정은 `door_turn` 이 올 때 한 번에 난다. 로봇은 도는 동안에는 「몇 번째를 보고 있다」만
   * 말하고 어디에 문이 있는지는 끝에 가서야 말하기 때문이다 — 그 전에 칸을 칠하면 화면이
   * 로봇보다 앞서 간다.
   */
  for (const effect of effects) {
    if (effect.kind !== 'door-turn') continue;
    if (effect.chosenIndex === null) continue;   // 어느 걸음인지 못 짚었으면 초록을 안 켠다
    for (let index = 0; index < viewpointCount; index += 1) {
      const chosen = index === effect.chosenIndex;
      const verdict = applyEffects([{
        kind: 'viewpoint',
        frame: {
          channel: 'detection',
          payload: {
            index,
            angleDegOf: undefined,
            angle_deg: seenYawOf(index),
            door: chosen,
            bbox: null,
            confidence: chosen ? 1 : 0,
            reason: chosen ? '로봇이 이 방향을 문으로 판단했습니다' : '',
          } as never,
        },
        warning: null,
      }]);
      for (const done of verdict) appendViewpoint(missionId, atSec, done);
      appended += verdict.length;
    }
  }

  // **머리도 같이 민다.** 회전 사건에는 태스크 상태 변화가 없어서 아래 사건 옮기기만으로는
  // 머리가 안 움직이고, 그러면 방금 넣은 프레임이 「아직 안 온 것」으로 걸러진다.
  //
  // 260910 — 여기서 `frames.length` 만 봤다가 실물에서 걸렸다. `door_turn` 은 회전 프레임을
  // 하나도 안 만들고(진행률과 door-turn 효과뿐이다) 판정 여덟 칸만 만든다. 그래서 머리가
  // 안 밀렸고, **여덟 칸이 「회전 중」에서 영영 안 넘어갔다.** 로봇은 다 돌고 문까지
  // 골랐는데 화면만 도는 중이었다. 넣은 것을 다 세어야 한다.
  if (appended > 0) advanceRobotHead(missionId, atSec);

  // **태스크 노드도 로봇이 민다** (260910 지적). 대본 타이머가 멈춰 있으므로 노드 상태가
  // 저절로 바뀌지 않는다 — 응답을 기록 열의 사건으로 옮겨야 화면이 따라온다.
  for (const event of traceEventsOf(effects, atSec)) receiveRobotProgress(missionId, event);
  return appended;
}

/**
 * 로봇의 응답 → 기록 열의 사건. **없는 사건을 만들지 않는다** — 태스크 상태가 실제로
 * 바뀐 것만 옮긴다.
 *
 * `seq` 는 사람 조작(1,000,000)·생성(2,000,000) 대역과 겹치지 않게 3,000,000 부터 센다.
 * 되감기가 열을 정렬할 때 로봇이 낸 것이 남의 대역에 끼면 순서가 뒤섞인다.
 */
let robotSeq = 3_000_000;

function traceEventsOf(effects: readonly LinkEffect[], atSec: number): ScenarioEvent[] {
  const events: ScenarioEvent[] = [];
  for (const effect of effects) {
    if (effect.kind === 'task-running') {
      events.push(event(effect.taskId, 'running', 'started', atSec));
    } else if (effect.kind === 'task-done') {
      events.push(event(effect.taskId, 'done', 'evaluated', atSec, effect.result));
    } else if (effect.kind === 'task-failed') {
      // 거절·실패 사유를 payload 에 그대로 싣는다 — 화면이 코드와 문구를 읽는다.
      events.push(event(effect.taskId, 'failed', 'failed', atSec, {
        ...(effect.code === null ? {} : { code: effect.code }),
        ...(effect.message === null ? {} : { message: effect.message }),
      }));
    }
  }
  return events;
}

function event(
  nodeId: string,
  status: ScenarioEvent['status'],
  kind: string,
  atSec: number,
  payload?: Record<string, unknown>,
): ScenarioEvent {
  robotSeq += 1;
  return {
    seq: robotSeq,
    atSec,
    nodeId,
    status,
    kind,
    // **로봇이 낸 것이다.** 사람도 대본도 아니다 — 열을 되짚을 때 그 사실이 남아야 한다.
    producedBy: 'backend',
    ...(payload === undefined ? {} : { payload }),
  } as ScenarioEvent;
}

/** 클라이언트를 화면 상태에 붙인다. 되돌려주는 함수를 부르면 끊긴다. */
export function bindRobot(
  client: PhysicalClient,
  missionId: string,
  headSec: () => number,
): () => void {
  return client.onMessage((message) => {
    receiveUplink(message, missionId, headSec());
  });
}

/** 그 걸음이 보고한 방위. 못 봤으면 0 — 표시용이고 칸을 고르는 데는 안 쓴다. */
function seenYawOf(index: number): number {
  return robotSession().seenYaw[index] ?? 0;
}


/**
 * **로봇 응답을 앱 수명 내내 받는다** (260910 실측으로 드러난 자리).
 *
 * 처음엔 이 배선이 `RobotPanel` 안에 있었다. 그 패널은 마일스톤 화면에만 있어서,
 * **로봇이 도는 동안 노드를 눌러 태스크 그래프로 들어가면 패널이 사라지고 구독이 끊겼다.**
 * 실물로 재보니 여덟 걸음은 다 들어왔는데 마지막 `door_turn` 하나가 통째로 버려져서,
 * 로봇은 문을 골라 돌아섰는데 화면은 여덟 칸이 「회전 중」인 채로 굳었다.
 *
 * 시연에서 노드를 눌러 보는 것은 당연한 동작이다. 그래서 `robotClient()` 가 연결 상태와
 * 장비 상태를 만들 때 잇는 것과 같은 이유로, 이 배선도 **안 사라지는 자리**에 둔다.
 *
 * 스캔 발행도 같이 옮겼다 — 승인 직후에 화면을 옮기면 명령이 아예 안 나갔다.
 */
export function useRobotUplink(missionId: string, params: Record<string, unknown> | null): void {
  useEffect(() => {
    const client = robotClient();
    return client.onMessage((message) => {
      // 시각은 **승인 뒤 몇 초째**다. 대본 시각이 아니다 — 화면이 로봇을 따라간다.
      receiveUplink(message, missionId, elapsedSec());
    });
  }, [missionId]);

  // **승인이 스캔을 쏜다.** 세션이 바뀔 때마다 조건을 다시 본다 — `shouldIssueScan()` 이
  // 한 번만 참이 되도록 스스로 빗장을 건다(`markScanIssued`).
  const session = useRobotSession();
  useEffect(() => {
    if (!shouldIssueScan()) return;
    void issueScan(robotClient(), params);
  }, [params, session.approved, session.scanIssued, session.connection.state]);
}
