/**
 * src/detect/detectBridge.ts (260912 신설)
 *
 * **탐지 결과 → 여덟 칸.** `physical/robotBridge.ts` 와 같은 자리·같은 모양이다.
 *
 * 여덟 칸을 채우는 길은 이미 있다(`viewpoint/fill.ts`). 로봇 연동에서 쓰고 있고, 그 열은
 * 프레임이 **대본에서 왔는지 로봇에서 왔는지 탐지에서 왔는지 모른다**(260909 §6 의 규칙).
 * 그래서 여기가 하는 일은 모양을 맞춰 넣는 것뿐이다.
 *
 * ## 무작위로 뽑던 자리가 여기로 바뀐다
 *
 * 탐지가 없는 동안 화면은 여덟 중 하나를 **무작위로** 뽑아 초록을 켰다. 임시였고 화면에
 * 「임시」라고 적어 두었다. 이제 그 자리에 진짜가 들어온다 — **화면 코드는 안 바뀐다.**
 */

import { appendViewpoint } from '../viewpoint/store.ts';
import { liveFrame } from '../viewpoint/source.ts';
import { boxOf, chosenFrame, indexOfRotation, reasonOf } from './parse.ts';
import { detectState } from './store.ts';
import type { DetectFrame } from './types.ts';

/** 그 각도의 점수. 근거가 아직 안 왔으면 0 — 없는 점수를 지어내지 않는다. */
function scoreOf(frame: DetectFrame): number {
  return detectState().evidence[frame.frame]?.final_score ?? 0;
}

/**
 * 지금까지 받은 결과로 **초록이 될 칸**을 고른다.
 *
 * 찾은 것 중 점수가 가장 높은 하나다. 하나도 못 찾았으면 null 이고, 그때는 **임의로 한
 * 방향을 고르지 않는다** — 「문을 찾지 못함」에서 멈추는 것이 맞다.
 */
export function chosenIndex(stepDeg: number, count: number): number | null {
  const best = chosenFrame(detectState().frames, scoreOf);
  if (best === null) return null;
  return indexOfRotation(best.rotation_deg, stepDeg, count);
}

/** 아직 아무 각도도 안 봤는가. 화면이 「탐지 대기」와 「문 없음」을 가르는 재료다. */
export function hasResults(): boolean {
  return detectState().frames.length > 0;
}

/**
 * 받은 결과를 여덟 칸에 얹는다. 넣은 프레임 수를 돌려준다.
 *
 * **초록은 하나다.** 둘 이상에서 `found` 가 오는 것은 가정이 아니라 측정값이다 — 받은
 * 시료에서 270도와 315도가 둘 다 찾혔고 점수 차이가 0.0016 이었다. 나머지도 찾혔다는
 * 사실은 칸을 열면 보이게 남긴다(근거에 그대로 있다).
 */
export function applyDetection(missionId: string, atSec: number, stepDeg: number, count: number): number {
  const { frames } = detectState();
  if (frames.length === 0) return 0;
  const winner = chosenIndex(stepDeg, count);
  let put = 0;
  for (const result of frames) {
    const index = indexOfRotation(result.rotation_deg, stepDeg, count);
    if (index === null) continue;   // 범위 밖 각도는 버린다 — 없는 칸을 만들지 않는다
    const evidence = detectState().evidence[result.frame] ?? null;
    const frame = liveFrame({
      channel: 'detection',
      payload: {
        index,
        // **스캔 시작이 0도다** (260912 결정). 로봇의 yaw 를 여기 넣지 않는다.
        angle_deg: result.rotation_deg,
        // 찾았어도 초록은 하나다. 나머지는 「문 없음」이 아니라 **안 고른 것**이고,
        // 그 구별은 근거에 남는다.
        door: index === winner,
        bbox: boxOf(evidence?.box_xyxy),
        confidence: evidence?.final_score ?? 0,
        reason: reasonOf(evidence, result.found, index === winner),
      },
    });
    if (frame === null) continue;
    if (appendViewpoint(missionId, atSec, frame)) put += 1;
  }
  return put;
}
