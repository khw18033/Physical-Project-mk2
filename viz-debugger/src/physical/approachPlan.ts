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
 * ## 로봇은 스캔 뒤 제자리에 서 있지 않다
 *
 * 탐지의 회전각(`robot_command.turn.deg`)은 **스캔을 시작한 방향 기준**이다. 그런데 로봇의
 * `scan_mission` 은 한 바퀴를 돈 뒤 `door_turn` 으로 **한 칸(-step_deg) 되돌아가 선다** — pi7 의
 * 고정 기하값이고 우리가 끌 수 없다(연동 가이드 §5-3). 그대로 보내면 한 칸만큼 틀린 쪽으로 돈다.
 *
 * 그래서 **로봇이 보고한 방위**로 보정한다. 같은 판의 값끼리만 견준다 — 절대 방위는 기준점이
 * 움직인다(§5-2).
 *
 *   출발 방위   마지막 복귀 회전의 yaw (한 바퀴 = 출발) → 없으면 첫 회전 yaw - 한 칸 → 없으면 T-A2 방위
 *   지금 방위   door_turn 의 yaw → 없으면 로봇 state 의 heading
 *   회전 방향   회전 걸음끼리의 yaw 차이로 잰다 (시계 회전에 yaw 가 느는지 주는지)
 *
 *   보낼 회전 = 탐지 회전(출발 기준) - 출발 뒤로 이미 돈 각도(시계 +)
 */

import { detectState } from '../detect/store.ts';
import { deviceState } from './deviceState.ts';
import { hardwareTarget } from './encode.ts';
import type { TaskCommand } from './missionLink.ts';
import { prepState } from './prepStage.ts';
import { STOP_ACTION as ARRIVAL_STOP, STOP_REASON as STOP_WHY, TEST_FORWARD_M } from './presets.ts';
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
 * **순수 계산.** 탐지 회전(출발 기준, 오른쪽 +)과 출발·지금 방위, yaw 가 시계 방향으로 느는지(+1)
 * 주는지(-1)로 지금 보내야 할 회전을 낸다.
 */
export function compensateTurn(detectionTurnDeg: number, startYawDeg: number, nowYawDeg: number, yawCwSign: 1 | -1): {
  turnedSinceStartCwDeg: number; turnDeg: number;
} {
  const turnedSinceStartCwDeg = wrapDeg((nowYawDeg - startYawDeg) * yawCwSign);
  return { turnedSinceStartCwDeg, turnDeg: wrapDeg(detectionTurnDeg - turnedSinceStartCwDeg) };
}

/** 회전 걸음들의 yaw 로 「시계 회전에 yaw 가 느는가」를 잰다. 못 재면 null. */
export function yawCwSignOf(seenYaw: Readonly<Record<number, number>>): 1 | -1 | null {
  const indices = Object.keys(seenYaw).map(Number).sort((a, b) => a - b);
  let sum = 0;
  let pairs = 0;
  for (let i = 1; i < indices.length; i += 1) {
    if (indices[i] !== indices[i - 1] + 1) continue;
    sum += wrapDeg(seenYaw[indices[i]] - seenYaw[indices[i - 1]]);
    pairs += 1;
  }
  if (pairs === 0 || sum === 0) return null;
  return sum > 0 ? 1 : -1;
}

/**
 * `robot_command` 가 없는 **옛 산출물**(260912 시료 · 「테스트」)의 회전각. 「왼쪽(반시계)으로 90.0도 회전」
 * 에서 방향과 각을 읽는다 — 오른쪽 +. 못 읽으면 null.
 */
export function turnFromInstruction(instruction: string | undefined): number | null {
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
    startYawDeg: number | null;
    startYawSource: string;
    nowYawDeg: number | null;
    nowYawSource: string;
    yawCwSign: 1 | -1 | null;
    /** 출발 뒤로 로봇이 이미 돈 각도(시계 +). 보정을 못 했으면 null. */
    turnedSinceStartCwDeg: number | null;
    /** 실제로 보낼 회전(오른쪽 +). */
    turnDeg: number;
    /** 경로가 낸 직진(m) · 실제로 보낼 직진(m, 「테스트」면 상한). */
    plannedForwardM: number;
    issuedForwardM: number;
    steps: readonly TaskCommand[];
    /** 보정을 못 한 사유 등 — 사람이 알아야 할 것. */
    notes: readonly string[];
  }
  | { ok: false; reason: string };

/** 지금 누르면 나갈 계획. 경로가 없거나 명령이 범위 밖이면 사유를 돌려준다 — **대신할 거리를 지어내지 않는다.** */
export function planApproach(stepDeg = 45): ApproachPlan {
  const detect = detectState();
  if (detect.pathFailure !== null) return { ok: false, reason: `경로 산출 실패 — ${detect.pathFailure}` };
  const path = detect.path;
  if (path === null) return { ok: false, reason: '경로가 아직 없습니다 — 「2D 맵 기반 경로 산출」이 끝나야 이동합니다' };
  const command = path.robot_command;
  const detectionTurnDeg = command?.turn.deg ?? path.turn_deg ?? turnFromInstruction(path.turn_instruction);
  const plannedForwardM = command?.move_forward.distance_m ?? path.forward_distance_m ?? path.forward_distance_cm / 100;
  if (detectionTurnDeg === null || !Number.isFinite(detectionTurnDeg)) return { ok: false, reason: '경로에 회전각이 없습니다' };
  if (!Number.isFinite(plannedForwardM)) return { ok: false, reason: '경로에 직진 거리가 없습니다' };
  if (command !== undefined && !command.distance_m_in_range) {
    return { ok: false, reason: command.warning ?? `직진 ${plannedForwardM.toFixed(2)}m 가 로봇이 받는 범위 밖입니다` };
  }

  const session = robotSession();
  const notes: string[] = [];
  const yawCwSign = yawCwSignOf(session.seenYaw);

  let startYawDeg: number | null = null;
  let startYawSource = '없음';
  if (session.scanReturnYaw !== null) {
    startYawDeg = session.scanReturnYaw;
    startYawSource = '마지막 복귀 회전의 yaw (한 바퀴 = 출발 방향)';
  } else if (session.seenYaw[1] !== undefined && yawCwSign !== null) {
    startYawDeg = session.seenYaw[1] - yawCwSign * stepDeg;
    startYawSource = `첫 회전 yaw ${session.seenYaw[1]}° 에서 한 칸(${stepDeg}°) 되돌림`;
  } else if (prepState().pose.value !== null) {
    startYawDeg = prepState().pose.value!.headingDeg;
    startYawSource = 'T-A2 가 잡은 출발 방위 (로봇 state)';
  }

  let nowYawDeg: number | null = null;
  let nowYawSource = '없음';
  if (session.doorTurn?.yawDeg !== null && session.doorTurn?.yawDeg !== undefined) {
    nowYawDeg = session.doorTurn.yawDeg;
    nowYawSource = 'door_turn 의 yaw (스캔 끝 방위)';
  } else {
    const heading = deviceState(hardwareTarget('robot-01'))?.position?.headingDeg;
    if (heading !== undefined) { nowYawDeg = heading; nowYawSource = '로봇 state 의 지금 방위'; }
  }

  let turnDeg = detectionTurnDeg;
  let turnedSinceStartCwDeg: number | null = null;
  if (startYawDeg !== null && nowYawDeg !== null) {
    const sign = yawCwSign ?? 1;
    if (yawCwSign === null) notes.push('회전 방향을 잴 걸음이 없어 yaw 가 시계 방향으로 는다고 봤습니다(실측 로봇과 같은 방향)');
    const compensated = compensateTurn(detectionTurnDeg, startYawDeg, nowYawDeg, sign);
    turnDeg = compensated.turnDeg;
    turnedSinceStartCwDeg = compensated.turnedSinceStartCwDeg;
  } else {
    notes.push('출발·지금 방위를 다 몰라 탐지 회전각을 보정 없이 보냅니다 — 로봇이 스캔 뒤 틀어져 있으면 그만큼 어긋납니다');
  }

  // 「테스트」가 켜져 있으면 직진에 상한을 건다 — 실험실에서 6m 를 걸을 자리가 없다(presets.ts).
  const issuedForwardM = detect.testMode ? Math.min(plannedForwardM, TEST_FORWARD_M) : plannedForwardM;
  if (issuedForwardM > FORWARD_MAX_M) return { ok: false, reason: `직진 ${issuedForwardM.toFixed(2)}m 가 ${FORWARD_MAX_M}m 를 넘습니다` };

  const steps: TaskCommand[] = [];
  if (Math.abs(turnDeg) >= TURN_MIN_DEG) {
    steps.push({ taskId: 'T-B2', action: 'turn', parameters: { deg: Number(turnDeg.toFixed(1)) } });
  } else {
    notes.push(`보낼 회전 ${turnDeg.toFixed(1)}° 가 ${TURN_MIN_DEG}° 미만이라 돌지 않습니다 — 이미 문 쪽을 보고 있습니다`);
  }
  if (issuedForwardM >= FORWARD_MIN_M) {
    steps.push({ taskId: 'T-B2', action: 'move_forward', parameters: { distance_m: Number(issuedForwardM.toFixed(3)) } });
  }
  if (steps.length === 0) return { ok: false, reason: '낼 명령이 없습니다 — 회전도 직진도 규약 최소값 미만입니다' };
  // 도착 정지 — `T-B3`「문과 가까워지면 정지」는 순서도의 걸음이다. 화면을 잠그는 비상 정지가 아니다.
  steps.push({ taskId: 'T-B3', action: ARRIVAL_STOP, parameters: { reason: STOP_WHY.screen } });

  return {
    ok: true, detectionTurnDeg, startYawDeg, startYawSource, nowYawDeg, nowYawSource, yawCwSign,
    turnedSinceStartCwDeg, turnDeg, plannedForwardM, issuedForwardM, steps, notes,
  };
}
