/**
 * src/stt/language.ts (260918 신설 — 영문화 3단계 §2-E)
 *
 * **인식 언어는 화면 언어와 별개다.**
 *
 * 화면을 영어로 두고 발표는 한국어로 하는 — 실제로 그렇게 할 — 경우가 있다. 화면 언어를
 * 그대로 STT 에 밀면 그때 한국어 발화를 영어로 디코딩하려 들고, 인식이 통째로 무너진다.
 * 그래서 **따로 고를 수 있게** 두고 기본은 「화면 언어 따름」으로 둔다.
 *
 * ## 세 값의 뜻
 *
 * ```
 *   'auto'  화면 언어를 따른다 (기본)
 *   'ko'    화면이 영어여도 한국어로 듣는다
 *   'en'    화면이 한국어여도 영어로 듣는다
 * ```
 *
 * ## 왜 `localStorage` 인가
 *
 * 이 설치본의 성질이지 임무의 성질이 아니다 — 접속 주소(`shared/connections.ts`)와 같은
 * 규칙이라 키도 앱 전역이다. 저장소가 막혀 있으면 조용히 기본값으로 진행한다.
 */

import { useSyncExternalStore } from 'react';
import { getLang, type Lang } from '../shared/language.ts';

export type SttLangChoice = 'auto' | Lang;

export const STT_LANG_CHOICES: readonly SttLangChoice[] = ['auto', 'ko', 'en'];

const STORAGE_KEY = 'viz.stt.language.v1';

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // 사파리 비공개 창처럼 **접근 자체가 던지는** 경우가 있다 (connections.ts 와 같다).
    return null;
  }
}

function read(): SttLangChoice {
  try {
    const raw = storage()?.getItem(STORAGE_KEY);
    return raw === 'ko' || raw === 'en' || raw === 'auto' ? raw : 'auto';
  } catch {
    return 'auto';
  }
}

let choice: SttLangChoice = read();
const listeners = new Set<() => void>();

export function getSttLangChoice(): SttLangChoice {
  return choice;
}

export function setSttLangChoice(next: SttLangChoice): void {
  if (choice === next) return;
  choice = next;
  try {
    storage()?.setItem(STORAGE_KEY, next);
  } catch {
    // 못 저장해도 이번 세션에는 적용된다. 화면이 그 사실을 따로 말하지는 않는다 —
    // 연결 주소와 달리 다시 고르는 값이 하나뿐이라 갇히지 않는다.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useSttLangChoice(): SttLangChoice {
  return useSyncExternalStore(subscribe, getSttLangChoice, getSttLangChoice);
}

/**
 * 실제로 STT 에 보낼 언어. `auto` 면 지금 화면 언어다.
 *
 * **부를 때마다 읽는다** — 모듈 최상위에 굳히면 언어를 바꿔도 안 따라온다
 * (`i18n` 1단계 보고서 §3 ①과 같은 함정).
 */
export function sttLanguage(): Lang {
  return choice === 'auto' ? getLang() : choice;
}
