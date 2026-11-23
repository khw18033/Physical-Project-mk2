/**
 * src/physical/scanApproach.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S6)
 *
 * **data_stream 결과(`best`) → 로봇에 보낼 이동 명령.** 경로는 가시화가 계산한다(결정 2).
 * 옛 `approachPlan.ts` 는 탐지기가 낸 경로 문장(「왼쪽으로 78.7도」)을 읽는다. 여기는 **부호 있는 방위를 숫자로** 받는다.
 * 하한(회전 5° · 직진 0.05 m · 직진 상한 10 m)과 속도 · 도착 정지는 옛 것과 같다.
 *
 * ```
 * turn_deg  = best.bearing_deg − 회전 오차
 * forward_m = best.distance_m − 정지 거리(params.stop_distance_max_m)
 * ```
 *
 * 회전 오차: `turn` 을 여러 번 나눠 돌았으므로 시작 방향과 어긋날 수 있다. 장치가 방위를 주면(시작 · 끝 둘 다)
 * `끝 − 시작` 을 회전 방향(오른쪽 +)으로 바꿔 뺀다. 못 주면 0 이고 그 사실을 적는다.
 *
 * **순수 함수다.** 실패 · 메모는 사전 키와 값으로 돌려주고 글로 푸는 것은 부르는 쪽이 한다.
 */

import { FORWARD_MAX_M, FORWARD_MIN_M, TURN_MIN_DEG, wrapDeg } from './approachPlan.ts';
import { APPROACH_VX, STOP_ACTION, STOP_REASON, TEST_FORWARD_M } from './presets.ts';
import type { TaskCommand } from './missionLink.ts';
import type { ScanBest } from '../detect/scan/types.ts';

/**
 * 장치가 보고한 방위가 `turn` 의 오른쪽 + 와 같은 방향으로 늘면 1, 반대면 −1.
 * 가짜 장치(`fakeDevice.ts`)는 `turn +45` 에 heading 이 +45 된다 — 1 이다. **실물 GO1 은 시험에서 확인한다.**
 */
export const HEADING_TURN_SIGN = 1;

export type ScanPlanKey = { key: string; vars?: Record<string, string | number> };

export type ScanApproachPlan =
  | {
    ok: true;
    bearingDeg: number;
    /** 뺀 회전 오차(오른쪽 +). 보정이 없으면 null. */
    driftDeg: number | null;
    turnDeg: number;
    plannedForwardM: number;
    issuedForwardM: number;
    forwardVx: number;
    steps: readonly TaskCommand[];
    notes: readonly ScanPlanKey[];
  }
  | { ok: false; reason: ScanPlanKey };

export type ScanPlanInput = {
  best: ScanBest | null;
  stopDistanceM: number;
  headingStartDeg: number | null;
  headingEndDeg: number | null;
  /** 「테스트」면 직진에 상한(`TEST_FORWARD_M`)을 건다 — 옛 계획과 같다. */
  testMode: boolean;
};

/** 시작 · 끝 방위 → 회전 오차(오른쪽 +). 하나라도 없으면 null. */
export function scanDrift(headingStartDeg: number | null, headingEndDeg: number | null): number | null {
  if (headingStartDeg === null || headingEndDeg === null) return null;
  if (!Number.isFinite(headingStartDeg) || !Number.isFinite(headingEndDeg)) return null;
  return wrapDeg((headingEndDeg - headingStartDeg) * HEADING_TURN_SIGN);
}

export function planScanApproach(input: ScanPlanInput): ScanApproachPlan {
  const { best } = input;
  if (best === null) return { ok: false, reason: { key: 'sd.plan.notFound' } };
  if (!best.distance_valid) return { ok: false, reason: { key: 'sd.plan.distanceInvalid', vars: { note: best.distance_note ?? '' } } };
  if (best.distance_m === null || !Number.isFinite(best.distance_m)) return { ok: false, reason: { key: 'sd.plan.noDistance' } };
  if (!Number.isFinite(best.bearing_deg)) return { ok: false, reason: { key: 'sd.plan.noBearing' } };

  const notes: ScanPlanKey[] = [];
  const driftDeg = scanDrift(input.headingStartDeg, input.headingEndDeg);
  if (driftDeg === null) notes.push({ key: 'sd.plan.noDrift' });
  const raw = best.bearing_deg - (driftDeg ?? 0);
  const turnDeg = raw > 180 || raw <= -180 ? wrapDeg(raw) : raw;

  const plannedForwardM = best.distance_m - input.stopDistanceM;
  if (plannedForwardM < FORWARD_MIN_M) {
    return { ok: false, reason: { key: 'sd.plan.alreadyClose', vars: { m: best.distance_m.toFixed(2), stop: input.stopDistanceM } } };
  }
  const issuedForwardM = input.testMode ? Math.min(plannedForwardM, TEST_FORWARD_M) : plannedForwardM;
  if (issuedForwardM > FORWARD_MAX_M) {
    return { ok: false, reason: { key: 'sd.plan.tooFar', vars: { m: issuedForwardM.toFixed(2), max: FORWARD_MAX_M } } };
  }
  if (best.provisional) notes.push({ key: 'sd.plan.provisional' });

  const steps: TaskCommand[] = [];
  if (Math.abs(turnDeg) >= TURN_MIN_DEG) {
    steps.push({ taskId: 'T-B2', action: 'turn', parameters: { deg: Number(turnDeg.toFixed(1)) } });
  } else {
    notes.push({ key: 'sd.plan.turnTooSmall', vars: { deg: turnDeg.toFixed(1), min: TURN_MIN_DEG } });
  }
  steps.push({ taskId: 'T-B2', action: 'move_forward', parameters: { distance_m: Number(issuedForwardM.toFixed(3)), vx: APPROACH_VX } });
  steps.push({ taskId: 'T-B3', action: STOP_ACTION, parameters: { reason: STOP_REASON.screen } });

  return {
    ok: true, bearingDeg: best.bearing_deg, driftDeg, turnDeg, plannedForwardM, issuedForwardM,
    forwardVx: APPROACH_VX, steps, notes,
  };
}
