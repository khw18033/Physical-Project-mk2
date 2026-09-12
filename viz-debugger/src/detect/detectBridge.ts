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
  // **여덟을 다 보기 전에는 안 고른다** (260912 지시).
  //
  // 세 각도만 보고 「여기가 제일 높다」고 초록을 켜면, 다섯째에서 더 높은 것이 나왔을 때
  // 초록이 옮겨 다닌다. 보는 사람은 화면이 흔들린다고 읽는다. 실제로 가장 높은 것은
  // **다 보고 나서야** 알 수 있다.
  if (!sweepDone(count)) return null;
  const best = chosenFrame(detectState().frames, scoreOf);
  if (best === null) return null;
  return indexOfRotation(best.rotation_deg, stepDeg, count);
}

/** 여덟을 다 봤는가. 판정도 근거도 경로도 이 뒤에 나온다. */
export function sweepDone(count: number): boolean {
  return detectState().frames.length >= count;
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
  const done = sweepDone(count);
  const winner = chosenIndex(stepDeg, count);
  let put = 0;
  for (const result of frames) {
    const index = indexOfRotation(result.rotation_deg, stepDeg, count);
    if (index === null) continue;   // 범위 밖 각도는 버린다 — 없는 칸을 만들지 않는다
    /**
     * **도는 동안에는 「문 없음」만 칠한다** (260912 지시).
     *
     * 찾은 각도는 아직 **판정이 안 난 것**이지 탈락이 아니다. 그런데 칸의 상태는
     * 초록(선정)과 탈락 둘뿐이라, 도중에 칠하면 둘 중 하나로 거짓을 말하게 된다.
     * 여덟을 다 보고 나서 한 번에 칠한다 — 그때 초록 하나와 「문 후보」가 갈린다.
     *
     * 못 찾은 각도는 도중에 칠해도 거짓이 아니다. 그래야 화면이 한 칸씩 지워지는 것이
     * 보이고, 발표자가 「지금 어디까지 봤나」를 안다.
     */
    if (!done && result.found) continue;
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
