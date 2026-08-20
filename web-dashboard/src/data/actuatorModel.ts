/**
 * src/data/actuatorModel.ts
 *
 * 액추에이터 **도메인 어휘** (VZ-U-01).
 *
 * 수문·펌프는 대기 / 동작 중 / 완료 / 오류 / 확인 불가라는 자기만의 상태를 갖는다.
 * 이건 표준 3층(device_status·availability·deployment)과 **별개**이며, 공통 컴포넌트가
 * 하드코딩해서는 안 된다 — 그래서 statusModel.ts가 아니라 여기에 따로 둔다.
 *
 * 두 어휘는 같은 카드에 나란히 표시된다. 3층은 "이 장비의 소식을 듣고 있는가"를 말하고,
 * 도메인 어휘는 "이 장비가 지금 무엇을 하고 있는가"를 말한다. 겹치지 않는다.
 */

import type { ActuatorState, CommandResult } from '../transport/index.ts';

export type ActuatorPhase = ActuatorState['phase'];

export const ACTUATOR_PHASE_LABEL: Record<ActuatorPhase, string> = {
  idle: '대기',
  moving: '동작 중',
  completed: '완료',
  error: '오류',
  unverified: '확인 불가',
};

/**
 * REQ-903 — 본 레이어는 명령 결과를 **진행중 / 확정 / 실패** 3상태로만 표시한다.
 * 액션별 판정 규칙을 프런트가 떠안지 않는다. 확정 판정은 백엔드가 승격한 값을 따른다.
 */
export type CommandDisplay = 'in_progress' | 'confirmed' | 'failed';

export const COMMAND_DISPLAY_LABEL: Record<CommandDisplay, string> = {
  in_progress: '진행중',
  confirmed: '확정',
  failed: '실패',
};

export function deriveCommandDisplay(result: CommandResult | null): CommandDisplay | null {
  if (result === null) return null;
  switch (result.status) {
    case 'accepted':
      return 'in_progress';
    case 'completed':
      return 'confirmed';
    case 'rejected':
    case 'timeout':
    case 'failed':
      return 'failed';
    default:
      return null;
  }
}

export function describeActuator(state: ActuatorState | null): string {
  if (state === null) return '상태 미수신';
  if (state.control_locked) return state.lock_reason ?? '제어 잠금';
  if (state.phase === 'moving' && state.progress_pct !== null) {
    return '진행 ' + state.progress_pct.toFixed(0) + '% · 개도 ' + (state.position_pct ?? 0).toFixed(0) + '%';
  }
  return '개도 ' + (state.position_pct ?? 0).toFixed(0) + '%';
}
