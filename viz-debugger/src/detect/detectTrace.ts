/**
 * src/detect/detectTrace.ts (260912 신설)
 *
 * **탐지가 아는 것을 태스크 노드에 옮긴다.**
 *
 * 여덟 칸은 이미 탐지가 채운다. 그런데 **태스크 노드는 그대로 대기였다** — 여덟 칸이 다
 * 차고 초록까지 떠도 「문이 있는 방향으로 판단」이 회색이라 마일스톤이 안 끝나고, 다음
 * 마일스톤으로도 안 넘어갔다.
 *
 * 로봇이 하던 일(`physical/robotBridge.ts` 의 `traceEventsOf`)과 같은 자리·같은 모양이다.
 * 다른 점은 **무엇을 근거로 끝났다고 하는가**뿐이다.
 *
 * ## 없는 것을 끝났다고 하지 않는다
 *
 * 각 태스크는 **그것이 실제로 아는 값이 왔을 때만** 끝난다.
 *
 *   T-A1 문 위치 확인      `localization_ok` — 도면상 위치가 잡혔다
 *   T-A2 로봇 위치·각도     같음 (받침대로 자세를 역산한 결과다)
 *   T-A3 한 바퀴 돈다       여덟 각도를 다 봤다
 *   T-A4-n 각도 탐색        그 각도의 결과가 왔다
 *   T-A5 방향 판단          여덟을 다 보고 하나를 골랐다 (못 고르면 **안 끝난다**)
 *   T-A6 근거 가시화        고른 각도의 근거가 왔다
 *   T-B1 경로 산출          경로가 왔다
 *
 * `T-B2`(이동)·`T-B3`(정지)·`T-C1`(종료)은 **여기서 안 만든다.** 로봇이 실제로 움직여야
 * 끝나는 것들이고, 탐지는 그것을 모른다.
 */

import { receiveRobotProgress } from '../data/scenario.ts';
import type { ScenarioEvent } from '../model/types.ts';
import { chosenFrame, indexOfRotation } from './parse.ts';
import { detectState } from './store.ts';
import type { DetectFrame } from './types.ts';

/**
 * `seq` 대역. 사람 조작(1,000,000)·생성(2,000,000)·로봇(3,000,000)과 겹치지 않게 4,000,000
 * 부터 센다. 되감기가 열을 정렬할 때 남의 대역에 끼면 순서가 뒤섞인다.
 */
let seq = 4_000_000;

/** 이미 낸 사건. 같은 태스크를 두 번 끝냈다고 하지 않는다. */
const emitted = new Set<string>();

export function resetDetectTrace(): void {
  emitted.clear();
}

function event(nodeId: string, status: 'running' | 'done', atSec: number): ScenarioEvent {
  seq += 1;
  return {
    seq,
    atSec,
    nodeId,
    status,
    kind: status === 'done' ? 'evaluated' : 'started',
    // **탐지가 낸 것이다.** 사람도 대본도 로봇도 아니다 — 열을 되짚을 때 그 사실이 남아야 한다.
    producedBy: 'backend',
  } as ScenarioEvent;
}

/** 한 번만 낸다. 이미 낸 것이면 아무 일도 안 한다. */
function emit(missionId: string, nodeId: string, status: 'running' | 'done', atSec: number): boolean {
  const key = `${nodeId}:${status}`;
  if (emitted.has(key)) return false;
  emitted.add(key);
  receiveRobotProgress(missionId, event(nodeId, status, atSec));
  return true;
}

const scoreOf = (frame: DetectFrame) => detectState().evidence[frame.frame]?.final_score ?? 0;

/**
 * 지금까지 받은 것으로 태스크 노드를 민다. 낸 사건 수를 돌려준다.
 *
 * 매번 전부 다시 훑는다 — 싸고, 무엇이 이미 났는지를 따로 들고 있지 않아도 된다.
 */
export function advanceDetectTasks(
  missionId: string, atSec: number, stepDeg: number, count: number,
): number {
  const state = detectState();
  if (state.frames.length === 0) return 0;
  let put = 0;

  // 자세가 잡혔다 — 도면상 목표 위치와 로봇 자세 둘 다 여기서 나온다.
  if (state.frames.length > 0) {
    put += emit(missionId, 'T-A1', 'done', atSec) ? 1 : 0;
    put += emit(missionId, 'T-A2', 'done', atSec) ? 1 : 0;
  }

  // 도는 중 → 다 돌았다.
  put += emit(missionId, 'T-A3', 'running', atSec) ? 1 : 0;
  const swept = state.frames.length >= count;
  if (swept) put += emit(missionId, 'T-A3', 'done', atSec) ? 1 : 0;

  // 각도 하나가 오면 그 칸의 태스크가 끝난다.
  for (const frame of state.frames) {
    const index = indexOfRotation(frame.rotation_deg, stepDeg, count);
    if (index === null) continue;
    put += emit(missionId, `T-A4-${index}`, 'done', atSec) ? 1 : 0;
  }

  // **다 보고 하나를 골랐을 때만** 판단이 끝난다. 못 고르면 안 끝난다 —
  // 「문을 찾지 못함」은 완료가 아니다.
  const chosen = swept ? chosenFrame(state.frames, scoreOf) : null;
  if (chosen !== null) {
    put += emit(missionId, 'T-A5', 'done', atSec) ? 1 : 0;
    // 근거는 그 각도의 근거가 실제로 왔을 때.
    if (state.evidence[chosen.frame] !== undefined) {
      put += emit(missionId, 'T-A6', 'done', atSec) ? 1 : 0;
    }
  }

  // 경로가 오면 산출이 끝난다. **이동은 여기서 안 낸다** — 로봇이 움직여야 끝난다.
  if (state.path !== null) put += emit(missionId, 'T-B1', 'done', atSec) ? 1 : 0;
  return put;
}
