/**
 * src/autodrive/presets.ts (260929 신설 — 장애물 탐지 영상 주소 고르기)
 *
 * **연결 관리의 「장애물 탐지 영상」 줄마다 고르는 칸.** 로봇 브로커(`physical/presets.ts`)와 같은 모양이다 —
 * 두 대상의 줄이 같은 꼴이어야 한 판에서 읽힌다(260929 지시 「로봇 쪽이랑 UI 구성을 맞추자」).
 *
 * 주소는 이 폴더 밖에 적지 않는다(`verify:autodrive-ai` — AI 서버 주소는 경계 안).
 */

export type AiPreset = {
  id: string;
  labelKey: string;
  /** 빈 문자열이면 아직 값이 없다 — 화면이 고를 수 없게 막는다. `manual` 만 예외다. */
  url: string;
  whyKey: string;
};

/** Go1 앞 카메라 AI 서버 (260915 사용자가 준 주소). */
export const AI_GO1_BASE = 'http://210.110.250.33:7864';
/** 드론 카메라 AI 서버 (260929 사용자가 준 주소). */
export const AI_DRONE_BASE = 'http://100.114.96.78:8891';

export const AI_PRESETS: readonly AiPreset[] = [
  { id: 'go1', labelKey: 'preset.ai.go1', url: AI_GO1_BASE, whyKey: 'preset.ai.go1.why' },
  { id: 'drone', labelKey: 'preset.ai.drone', url: AI_DRONE_BASE, whyKey: 'preset.ai.drone.why' },
  { id: 'manual', labelKey: 'preset.manual', url: '', whyKey: 'preset.manual.why' },
];

export function aiPresetReady(preset: AiPreset): boolean {
  return preset.id === 'manual' || preset.url.trim() !== '';
}
