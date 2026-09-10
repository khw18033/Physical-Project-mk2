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
import { effectsOf } from './missionLink.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { applyEffects, robotSession } from './robotSession.ts';
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
  chosenAngleDeg: number | null,
  viewpointCount = 8,
): number {
  const effects = effectsOf(message, {
    // 어느 태스크의 응답인가 — 발행할 때 적어 둔 표를 본다.
    taskOf: (commandId) => robotSession().commands[commandId]?.taskId ?? null,
    chosenAngleDeg,
    viewpointCount,
  });
  const frames = applyEffects(effects);
  for (const frame of frames) appendViewpoint(missionId, atSec, frame);
  return frames.length;
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
