/**
 * src/physical/approachPlan.ts (260914 신설)
 *
 * **`T-B1`(2D 맵 기반 경로 산출)이 낸 경로 → 로봇에 실제로 보낼 명령.** 계산은 여기 하나다 —
 * 버튼 문구, 실제 발행, 액션 아이템의 설명이 모두 이 결과를 읽는다.
 *
 * ## 하드코딩을 걷어낸 자리 (260914 리허설)
 *
 * 전에는 경로가 없어도 로봇의 `door_turn` 만 오면 「경로대로 이동」이 열렸고, 누르면 대본의
 * `forward_distance_m`(4.2m) 로 직진했다 — **방향도 모른 채.** 이제 경로가 없으면 계획이 없다.
 *
 * ## 탐지 회전각을 그대로 보낸다 (260914 두 번째 수정)
 *
 * 탐지의 회전각(`robot_command.turn.deg`)은 **스캔을 시작한 방향 기준**이다. 한때 pi7 의
 * `scan_mission` 이 한 바퀴 뒤 `door_turn` 으로 한 칸(-45°) 되돌아 섰고, 그만큼을 로봇이 보고한
 * 방위로 빼서 보냈다. **pi7 에서 `door_turn` 을 걷어 냈다** — 로봇은 여덟째 회전으로 출발 방향에
 * 돌아와 선다. 그래서 보정 없이 탐지 회전각이 곧 보낼 회전각이다.
 *
 * 옛 pi7 이 아직 `door_turn` 을 보내면 그 사실만 적는다 — 보정하지 않으므로 그만큼 어긋난다.
 *
 * ## 직진 속도 (260914 — 시연 시간)
 *
 * `move_forward` 에 `vx` 를 싣는다. 안 실으면 로봇 기본값 0.15 m/s 이고, 규약 상한 0.30 m/s 가
 * 그 두 배다(연동 가이드 §4-2). **회전 속도는 규약에 파라미터가 없다** — pi7 쪽 설정이다.
 */

import { t } from '../i18n/dict.ts';
import { detectState } from '../detect/store.ts';
import type { TaskCommand } from './missionLink.ts';
import { APPROACH_VX, STOP_ACTION as ARRIVAL_STOP, STOP_REASON as STOP_WHY, TEST_FORWARD_M } from './presets.ts';
import { robotSession } from './robotSession.ts';

/** 로봇이 받는 회전·직진 범위 (연동 가이드 §4-2). */
const TURN_MIN_DEG = 5;
const FORWARD_MIN_M = 0.05;
const FORWARD_MAX_M = 10;

/** (-180, 180] 로 감는다. */
export function wrapDeg(deg: number): number {
  const r = ((deg % 360) + 360) % 360;
  return r > 180 ? r - 360 : r;
}

/**
 * `robot_command` 가 없는 **옛 산출물**(260912 시료 · 「테스트」)의 회전각. 「왼쪽(반시계)으로 90.0도 회전」
 * 에서 방향과 각을 읽는다 — 오른쪽 +. 못 읽으면 null.
 */
export function turnFromInstruction(instruction: string | undefined): number | null {
  // **이 한글은 옮기지 않는다** (260919 · 4단계). 화면에 뜨는 글자가 아니라 **탐지 서비스가
  // 보낸 한국어를 읽는 자리**다. 영어로 바꾸면 「왼쪽으로 78.7도」를 못 읽어 회전 방향이 뒤집힌다.
  const matched = /([\d.]+)\s*도/.exec(instruction ?? '');
  if (matched === null) return null;
  const deg = Number(matched[1]);
  if (!Number.isFinite(deg)) return null;
  return /왼쪽|반시계/.test(instruction ?? '') ? -deg : deg;
}

export type ApproachPlan =
  | {
    ok: true;
    /** 탐지가 낸 회전(출발 기준, 오른쪽 +). */
    detectionTurnDeg: number;
    /** 실제로 보낼 회전(오른쪽 +). 보정이 없으므로 탐지 회전을 감은 값이다. */
    turnDeg: number;
    /** 경로가 낸 직진(m) · 실제로 보낼 직진(m, 「테스트」면 상한). */
    plannedForwardM: number;
    issuedForwardM: number;
    /** 직진 속도(m/s). */
    forwardVx: number;
    steps: readonly TaskCommand[];
    /** 사람이 알아야 할 것 — 옛 pi7 의 `door_turn` 등. */
    notes: readonly string[];
  }
  | { ok: false; reason: string };

/** 지금 누르면 나갈 계획. 경로가 없거나 명령이 범위 밖이면 사유를 돌려준다 — **대신할 거리를 지어내지 않는다.** */
export function planApproach(): ApproachPlan {
  const detect = detectState();
  if (detect.pathFailure !== null) return { ok: false, reason: t('ap.pathFailed', { reason: detect.pathFailure }) };
  const path = detect.path;
  if (path === null) return { ok: false, reason: t('ap.1') };
  const command = path.robot_command;
  const detectionTurnDeg = command?.turn.deg ?? path.turn_deg ?? turnFromInstruction(path.turn_instruction);
  const plannedForwardM = command?.move_forward.distance_m ?? path.forward_distance_m ?? path.forward_distance_cm / 100;
  if (detectionTurnDeg === null || !Number.isFinite(detectionTurnDeg)) return { ok: false, reason: t('ap.2') };
  if (!Number.isFinite(plannedForwardM)) return { ok: false, reason: t('ap.3') };
  if (command !== undefined && !command.distance_m_in_range) {
    return { ok: false, reason: command.warning ?? t('ap.forwardOutOfRange', { m: plannedForwardM.toFixed(2) }) };
  }

  const notes: string[] = [];
  const doorTurn = robotSession().doorTurn;
  if (doorTurn !== null) {
    notes.push(t('ap.doorTurnNote', { yaw: doorTurn.yawDeg === null ? '' : ` (yaw ${doorTurn.yawDeg}°)` }));
  }

  // 범위 안이면 그대로 — 감는 계산이 -78.7 을 -78.69999… 로 바꾼다.
  const turnDeg = detectionTurnDeg > 180 || detectionTurnDeg <= -180 ? wrapDeg(detectionTurnDeg) : detectionTurnDeg;
  // 「테스트」가 켜져 있으면 직진에 상한을 건다 — 실험실에서 6m 를 걸을 자리가 없다(presets.ts).
  const issuedForwardM = detect.testMode ? Math.min(plannedForwardM, TEST_FORWARD_M) : plannedForwardM;
  if (issuedForwardM > FORWARD_MAX_M) return { ok: false, reason: t('ap.forwardTooFar', { m: issuedForwardM.toFixed(2), max: FORWARD_MAX_M }) };

  const steps: TaskCommand[] = [];
  if (Math.abs(turnDeg) >= TURN_MIN_DEG) {
    steps.push({ taskId: 'T-B2', action: 'turn', parameters: { deg: Number(turnDeg.toFixed(1)) } });
  } else {
    notes.push(t('ap.turnTooSmall', { deg: turnDeg.toFixed(1), min: TURN_MIN_DEG }));
  }
  if (issuedForwardM >= FORWARD_MIN_M) {
    steps.push({ taskId: 'T-B2', action: 'move_forward', parameters: { distance_m: Number(issuedForwardM.toFixed(3)), vx: APPROACH_VX } });
  }
  if (steps.length === 0) return { ok: false, reason: t('ap.4') };
  // 도착 정지 — `T-B3`「문과 가까워지면 정지」는 순서도의 걸음이다. 화면을 잠그는 비상 정지가 아니다.
  steps.push({ taskId: 'T-B3', action: ARRIVAL_STOP, parameters: { reason: STOP_WHY.screen } });

  return { ok: true, detectionTurnDeg, turnDeg, plannedForwardM, issuedForwardM, forwardVx: APPROACH_VX, steps, notes };
}
