/**
 * src/detect/useDetect.tsx (260912 신설)
 *
 * **탐지를 앱 수명 내내 받는다.** `useRobotUplink` 과 같은 자리·같은 이유다 —
 * 마일스톤 화면에만 있는 부품에 두면 노드를 눌러 그래프로 들어가는 순간 끊긴다.
 * 로봇 연동에서 실제로 그래서 마지막 응답 하나를 통째로 잃었다.
 *
 * ## 언제 묻는가
 *
 * **상대가 있을 때만** 묻는다 — 「테스트」가 켜져 있거나 주소가 들어 있을 때. 아무것도
 * 없는데 1.5초마다 실패하는 요청을 던지면 콘솔이 빨갛게 차고, 진짜 문제가 그 안에 묻힌다.
 *
 * 여덟을 다 보기 전에는 짧게, 다 보고 나면 길게 묻는다.
 */

import { useEffect } from 'react';
import { advanceRobotHead } from '../data/scenario.ts';
import { elapsedSec } from '../physical/robotSession.ts';
import { applyDetection } from './detectBridge.ts';
import { detectBaseUrl } from './DetectClient.ts';
import { startDetectPolling } from './poll.ts';
import { detectState, subscribeDetect, useDetect } from './store.ts';

export function useDetectUplink(missionId: string, params: Record<string, unknown> | null): void {
  const state = useDetect();
  const stepDeg = typeof params?.viewpoint_step_deg === 'number' ? params.viewpoint_step_deg : 45;
  const count = typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8;
  const base = detectBaseUrl();

  // 상대가 있을 때만 묻는다. 주소가 바뀌거나 테스트를 켜면 그때 다시 선다.
  useEffect(() => {
    if (!state.testMode && base.trim() === '') return;
    return startDetectPolling(() => detectState().frames.length < count);
  }, [state.testMode, base, count]);

  /**
   * 받은 것을 여덟 칸에 얹는다. **머리도 같이 민다** — 안 그러면 방금 넣은 프레임이
   * 「아직 안 온 것」으로 걸러진다(로봇 연동에서 그대로 겪은 자리다).
   */
  useEffect(() => subscribeDetect(() => {
    const at = elapsedSec();
    if (applyDetection(missionId, at, stepDeg, count) > 0) advanceRobotHead(missionId, at);
  }), [missionId, stepDeg, count]);
}
