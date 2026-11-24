/**
 * src/physical/missionRobot.ts (261124 신설 — 로봇 둘을 붙인 채 박스 탐지를 돌리면 명령과 영상이 갈라지던 것)
 *
 * **이 임무를 모는 로봇은 누구인가.** 한 판 안에서 회전 · 방위 · 추론 포트 · 접근 이동이 **같은 답**을 봐야 한다.
 *
 * ## 갈라지던 모양 (261124 실측 — Go1 · EP 동시 연결)
 *
 *   회전   `robotClient()` = 연결 관리 첫 줄 → EP 가 돌았다
 *   영상   `hardwareTarget('robot-01')` → 로봇이 둘이면 장비 판정이 `null` 이라 옛 표 `go1-001` 로 물러섬 →
 *          Go1 의 추론 포트로 스캔했다(가만히 있는 Go1 의 그림)
 *   배정   카드를 끌어 놓은 것은 `main.tsx` 컴포넌트 상태라 그림(대상 칸)만 바뀌었다
 *
 * ## 정하는 순서
 *
 *   1. **끌어 놓은 장비** — 마일스톤 배정(`data/assignments.ts`)과 자리(`data/slots.ts`)에 앉은 장비 가운데
 *      그 action 을 받을 수 있는 살아 있는 것이 정확히 하나면 그것. 둘이면 고르지 않는다.
 *      끌어 놓은 로봇이 붙어 있지 않으면 **다른 로봇으로 물러서지 않는다** — 사람이 고른 것을 조용히 바꾸지 않는다.
 *   2. 끌어 놓은 것이 없으면 **받을 수 있는 로봇이 하나뿐일 때만** 그것.
 *   3. 둘 이상이면 고르지 않고 사유(「카드를 끌어 놓으세요」)를 돌려준다. 하나도 없으면 `none` — 부르는 쪽이
 *      옛 길(첫 줄 · 옛 표)로 가서 「안 붙었다」를 그쪽이 말하게 둔다.
 *
 * 판정은 장비 후보(`deviceIdentity.ts`)만 본다 — 준비 단계(방위)와 실행기가 따로 불러도 같은 답이 나온다.
 * 소켓은 부르는 쪽이 `clientForDevice` 로 찾는다(이 파일이 `robotClient.ts` 를 import 하면 고리가 생긴다).
 */

import { t } from '../i18n/dict.ts';
import { assignedDeviceIds } from '../data/assignments.ts';
import { slotBindings } from '../data/slots.ts';
import { deviceCandidates, liveDevicesFor } from './deviceIdentity.ts';
import { hardwareIdOf } from './encode.ts';

export type MissionRobotPick =
  | { ok: true; deviceId: string; how: 'assigned' | 'only' }
  | { ok: false; how: 'none' | 'many' | 'manyAssigned' | 'assignedAway'; reason: string };

/** 끌어 놓은 장비 — 마일스톤 배정과 자리 둘 다. */
function assigned(): readonly string[] {
  return [...new Set([...assignedDeviceIds(), ...Object.values(slotBindings())])];
}

export function pickMissionRobot(action: string): MissionRobotPick {
  const robots = liveDevicesFor(action).map((c) => c.deviceId);
  const chosen = assigned();
  if (chosen.length > 0) {
    const hits = robots.filter((id) => chosen.includes(id));
    if (hits.length === 1) return { ok: true, deviceId: hits[0], how: 'assigned' };
    if (hits.length > 1) return { ok: false, how: 'manyAssigned', reason: t('mr.manyAssigned', { list: hits.join(' · ') }) };
    // 끌어 놓은 것 가운데 로봇으로 아는 것이 있는데 지금 받을 수 없다 — 다른 로봇으로 물러서지 않는다.
    const away = deviceCandidates().find((c) => chosen.includes(c.deviceId) && c.kind !== 'sensor'
      && (c.actions !== null ? c.actions.includes(action) : c.kind === 'robot'));
    if (away !== undefined) return { ok: false, how: 'assignedAway', reason: t('mr.assignedAway', { device: away.deviceId }) };
    // 끌어 놓은 것이 로봇이 아니다(고정 카메라 등) — 아래 규칙대로.
  }
  if (robots.length === 1) return { ok: true, deviceId: robots[0], how: 'only' };
  if (robots.length === 0) return { ok: false, how: 'none', reason: t('mr.none') };
  return { ok: false, how: 'many', reason: t('mr.many', { list: robots.join(' · ') }) };
}

/**
 * **AI 계획에 적힌 장비 가운데, 실제로 움직일 장비가 아닌 것** (261124 — 경고만, 실행은 그대로).
 *
 * 생성기는 붙은 장비를 모르고 장비표(`equipment.json`)의 이름(`robot-01` · `robot-02` …)으로 적는다. 실제로 움직이는 것은
 * 끌어 놓은 카드 · 하나뿐인 로봇이다. 둘이 같은 이름이거나 이어진 이름(`robot-01 → go1-001`, `encode.ts`)이면 맞다고 본다.
 * 그 밖은 전부 「다르다」 — 이어진 표가 없는 이름(`robot-02` 등)도 실제 장비를 가리킨다고 말할 수 없으므로 알린다.
 */
export function planTargetsAway(planTargets: readonly (string | null | undefined)[], deviceId: string): string[] {
  const away: string[] = [];
  for (const target of planTargets) {
    if (target === null || target === undefined || target === '' || away.includes(target)) continue;
    if (target === deviceId || hardwareIdOf(target) === deviceId) continue;
    away.push(target);
  }
  return away;
}

/**
 * **한 판 동안 고정한 로봇** — 판 도중 사람이 카드를 다시 끌어도 돌던 판의 명령이 다른 로봇으로 가지 않게.
 * 스캔 실행기가 판을 열 때 박고, 접근 이동(`scanApproachRun.ts`)이 그것을 쓴다.
 */
let pinned: { runKey: number; deviceId: string } | null = null;

export function pinMissionRobot(runKey: number, deviceId: string | null): void {
  pinned = deviceId === null ? null : { runKey, deviceId };
}

export function pinnedMissionRobot(): { runKey: number; deviceId: string } | null {
  return pinned;
}
