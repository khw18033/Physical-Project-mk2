/**
 * src/physical/navControl.ts (260915 신설 — 자율주행 편 · 머리줄 조작 셋)
 *
 * **자율주행 편에서 정지 · 일시정지 · 재시작이 하는 일.** 머리줄 버튼(`StopButton.tsx`)이 지금 임무가
 * 중계 편(`driver: 'relay'`)이면 이쪽을 부른다.
 *
 * ## 로봇에는 아무것도 보내지 않는다 — 보낼 길이 없다
 *
 * 자율주행 편의 로봇(pi1)은 유니티가 몬다. 화면은 pi1 중계를 **받기만** 하고, pi1 에는 화면의 정지를 받아
 * 로봇에 옮기는 창구가 없다. 그래서 여기서 할 수 있는 것은 **화면 쪽**뿐이다.
 *
 *   ■ 정지     화면을 잠그고 칠하기를 끝낸다. 임무 이력에 「정지」로 남는다. 다시 승인해야 한다
 *   ⏸ 일시정지 칠하기만 멈춘다. 그동안 온 사건은 칠하지 않는다
 *   ▶ 재시작   일시정지를 푼다
 *
 * **pi7(문 찾기 시연)으로 `abort` 를 보내지 않는다.** 전에는 이 편에서도 머리줄 정지가 pi7 로 나갔다 —
 * 시연 로봇이 붙어 있으면 **엉뚱한 로봇이 멈추고** 정작 움직이는 로봇은 그대로다.
 *
 * 멈추지 못했다는 사실은 크게 말한다(`published: false` → 잠금 띠의 붉은 문구 · 알림). 조용히 성공한 척하면
 * 누른 사람은 로봇이 섰다고 믿고 다가간다.
 */

import { t } from '../i18n/dict.ts';
import { noteIssue } from '../shared/notifications.ts';
import { lockPaused, lockStopped, releasePaused, type PauseState, type StopState } from './robotSession.ts';

/** 260918 — **사전 키**다. 모듈 최상위 상수라 여기서 t() 를 부르면 언어가 굳는다. */
export const RELAY_STOP_WORDS_KEY = 'relay.stopWords';
/** 260918 — **사전 키**다. */
export const RELAY_PAUSE_WORDS_KEY = 'relay.pauseWords';

export function stopRelayRun(): StopState {
  noteIssue('stop', 'robot', t('relay.stopPrefix', { words: t(RELAY_STOP_WORDS_KEY) }));
  return lockStopped(false, t(RELAY_STOP_WORDS_KEY));
}

export function pauseRelayRun(): PauseState {
  noteIssue('pause', 'robot', t('relay.pausePrefix', { words: t(RELAY_PAUSE_WORDS_KEY) }));
  return lockPaused(null, false, t(RELAY_PAUSE_WORDS_KEY));
}

export function resumeRelayRun(): void {
  releasePaused();
}
