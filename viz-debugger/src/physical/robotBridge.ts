/**
 * src/physical/robotBridge.ts (260910 신설 — 화면 연결 §3)
 *
 * **uplink → 화면 상태.** `effectsOf()` 가 이미 내놓는 것을 잇기만 한다. 여기서 새로
 * 계산하지 않는다 — 계산이 두 곳에 있으면 하나만 고쳐지는 날이 온다.
 *
 * 뷰포인트 프레임은 1단계가 세운 열(`src/viewpoint/store.ts`)로 들어간다. 그 열은
 * 프레임이 로봇에서 왔는지 대본에서 왔는지 모른다 — 260909 §6 의 규칙 그대로다.
 */

import { appendViewpoint } from '../viewpoint/store.ts';
import { effectsOf, type LinkEffect } from './missionLink.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { advanceRobotHead, receiveRobotProgress } from '../data/scenario.ts';
import type { ScenarioEvent } from '../model/types.ts';
import { applyEffects, robotSession } from './robotSession.ts';
import type { UplinkMessage } from './uplink.ts';
import type { DoorDetectionFrame } from '../viewpoint/fill.ts';

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
  chosenAngleDeg: number | null,
  viewpointCount = 8,
  /** 그 인덱스의 문 판정 — 대본이 준다. 없으면 판정을 안 붙인다. */
  detectionFor?: (index: number) => DoorDetectionFrame | null,
): number {
  const effects = effectsOf(message, {
    // 어느 태스크의 응답인가 — 발행할 때 적어 둔 표를 본다.
    taskOf: (commandId) => robotSession().commands[commandId]?.taskId ?? null,
    chosenAngleDeg,
    viewpointCount,
  });
  const frames = applyEffects(effects);
  for (const frame of frames) appendViewpoint(missionId, atSec, frame);

  /**
   * **각도는 로봇, 문 유무는 대본** (2단계-A §6 그대로).
   *
   * 로봇은 「몇 번째 각도를 보고 있는가」만 말한다 — 거기 문이 있는지는 안 말한다.
   * 탐지 연동은 2단계-B 다. 그때까지는 대본이 그 답을 주되, **시각은 로봇을 따른다** —
   * 로봇이 3번째 각도에 닿았을 때 3번 칸의 판정이 뜬다.
   *
   * 대본의 시계로 흘리지 않는 이유가 이것이다. 그러면 로봇이 아직 두 번째를 보는 중에
   * 화면은 다섯 번째를 판정해 버린다.
   */
  if (detectionFor !== undefined) {
    for (const frame of frames) {
      if (frame.channel !== 'robot_state') continue;
      const verdict = detectionFor(frame.payload.rotation_index);
      if (verdict === null) continue;
      const applied = applyEffects([{ kind: 'viewpoint', frame: { channel: 'detection', payload: verdict }, warning: null }]);
      for (const done of applied) appendViewpoint(missionId, atSec, done);
    }
  }
  // **머리도 같이 민다.** 회전 사건에는 태스크 상태 변화가 없어서 아래 사건 옮기기만으로는
  // 머리가 안 움직이고, 그러면 방금 넣은 프레임이 「아직 안 온 것」으로 걸러진다.
  if (frames.length > 0) advanceRobotHead(missionId, atSec);

  // **태스크 노드도 로봇이 민다** (260910 지적). 대본 타이머가 멈춰 있으므로 노드 상태가
  // 저절로 바뀌지 않는다 — 응답을 기록 열의 사건으로 옮겨야 화면이 따라온다.
  for (const event of traceEventsOf(effects, atSec)) receiveRobotProgress(missionId, event);
  return frames.length;
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
  chosenAngleDeg: () => number | null,
): () => void {
  return client.onMessage((message) => {
    receiveUplink(message, missionId, headSec(), chosenAngleDeg());
  });
}
