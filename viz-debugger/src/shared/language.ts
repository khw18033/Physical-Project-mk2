/**
 * src/shared/language.ts (260916 — 영문화 1단계 §1)
 *
 * **화면 언어의 런타임 원천.** `connections.ts` 와 **같은 꼴**이다 — 셋째 패턴이 아니다
 * (`useSyncExternalStore` · `localStorage` · `subscribe` · 저장소가 막혀도 도는 `try/catch`).
 *
 * ## 결정 순서
 *
 * ```
 * ?lang=   >   localStorage   >   navigator.language   >   'ko'
 * ```
 *
 * **URL 이 맨 위인 것이 요점이다.** 링크 하나로 영문 화면을 그대로 건넬 수 있어야 한다 —
 * 「일반적인 웹사이트처럼」이라는 요청의 실질이 이것이고, 라우터를 안 넣고도 되는 이유다
 * (`/ko`·`/en` 경로 분리는 `standalone.html` 전달본에서 아예 동작하지 않는다).
 *
 * `?lang=` 으로 들어오면 **그 값을 `localStorage` 에도 적는다.** 주소창을 지우고 새로고침해도
 * 살아남아야 한다. 목록에 없는 값(`?lang=jp`)은 **던지지 않고** 다음 순서로 떨어진다.
 *
 * `navigator.language` 는 **브라우저에서만** 본다. Node 에도 `navigator` 가 있어서 검사
 * 스크립트가 기계 로캘을 따라가 버렸다 (260917 — `fromNavigator()` 주석). 검사 환경의
 * 기본값은 언제나 `'ko'` 이고, 영어를 재려면 검사가 `setLang('en')` 을 명시한다.
 *
 * ## 언어는 다른 상태를 건드리지 않는다
 *
 * `setLang()` 은 `renderMode` · 연결 주소 · 기록 열 중 **무엇도 못 바꾼다.** 언어는 표시층의
 * 설정이고 그 밖으로 새면 안 된다 — `verify:lang-switch` 가 이것을 검사한다.
 *
 * ## `<html lang>` 을 여기서 심는다
 *
 * `index.html` · `standalone.html` 은 한 줄짜리 조각이라 **`<html lang="ko">` 이 아예 없다.**
 * 그래서 전환할 때만 고치면 첫 화면이 `lang` 이 빈 채로 뜬다. 모듈이 실릴 때 한 번 심는다 —
 * 줄바꿈 규칙과 스크린리더가 이 값을 본다.
 */

import { useSyncExternalStore } from 'react';

export type Lang = 'ko' | 'en';

/** **언어 목록의 유일한 원천.** 전환 UI 는 이것을 그린다 — 손으로 둘을 적지 않는다. */
export const LANGS: readonly Lang[] = ['ko', 'en'];

/** 판(v1)을 붙여 둔다 — 모양이 바뀌면 옛 값을 조용히 버릴 수 있다 (`connections.ts` 와 같은 규칙). */
const STORAGE_KEY = 'viz.lang.v1';

function isLang(value: unknown): value is Lang {
  return typeof value === 'string' && (LANGS as readonly string[]).includes(value);
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // 사파리 비공개 창처럼 **접근 자체가 던지는** 경우가 있다 (`connections.ts:192-199`).
    return null;
  }
}

/** `?lang=` — 결정 순서의 맨 위. 없거나 목록 밖이면 `null` 이고 다음으로 떨어진다. */
function fromQuery(): Lang | null {
  try {
    if (typeof location === 'undefined') return null;
    const value = new URLSearchParams(location.search).get('lang');
    return isLang(value) ? value : null;
  } catch {
    return null;
  }
}

function fromStorage(): Lang | null {
  try {
    const value = storage()?.getItem(STORAGE_KEY) ?? null;
    return isLang(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * `navigator.language` 는 `'en-US'` 처럼 지역이 붙어 온다. **앞 두 글자만 본다.**
 *
 * ## 이 신호는 **브라우저에서만** 본다 (260917 — `verify:connection-panel` 회귀)
 *
 * 처음에는 `typeof navigator === 'undefined'` 만 봤다. **Node 21+ 에도 `navigator` 가 있다** —
 * `navigator.language` 가 `'en-US'` 로 온다. 그래서 검사 스크립트 안에서 `t()` 가 영어를
 * 돌려줬고, 한글 문구를 대조하던 `verify:connection-panel` 이 깨졌다.
 *
 * **그런데 그 깨짐이 로캘에 달려 있었다.** 한국어 윈도우에서는 `'ko-KR'` 이라 통과하고
 * 영어 로캘에서만 실패한다. 개수(2건)가 우연히 같아 보고서에서 「둘 다 기존」으로 넘어갔다.
 * **검사 결과가 기계마다 다른 것이 진짜 문제였다** — 2단계에서 문구 수백 개가 사전으로
 * 들어가면 한글을 대조하는 검사 7종이 전부 이 함정을 밟는다.
 *
 * 그래서 `navigator` 가 아니라 **브라우저인가**를 본다. Node 에는 `navigator` 는 있어도
 * `window` · `document` 는 없다. 검사 스크립트에서는 이 신호가 통째로 빠지고 기본값 `'ko'`
 * 가 되므로 **결과가 기계와 무관해진다.** 영어 경로를 재려면 검사가 `setLang('en')` 을
 * 명시적으로 부른다 — 환경이 정하게 두지 않는다.
 */
function fromNavigator(): Lang | null {
  try {
    // 브라우저 신호다. Node 의 `navigator` 를 브라우저로 착각하면 안 된다.
    if (typeof window === 'undefined' || typeof document === 'undefined') return null;
    if (typeof navigator === 'undefined') return null;
    const value = navigator.language?.slice(0, 2).toLowerCase();
    return isLang(value) ? value : null;
  } catch {
    return null;
  }
}

function persist(next: Lang): void {
  try {
    storage()?.setItem(STORAGE_KEY, next);
  } catch {
    // 저장이 막혀도 이번 세션에는 적용된다 — 여기서 던지면 앱이 안 뜬다.
  }
}

/** 문서의 `lang` 속성. 없는 환경(Node 검사)에서도 안 던진다. */
function applyDocumentLang(next: Lang): void {
  try {
    if (typeof document !== 'undefined') document.documentElement.lang = next;
  } catch {
    // 무시한다 — 표시 보조 속성이라 여기서 앱을 세울 이유가 없다.
  }
}

function decide(): Lang {
  const fromUrl = fromQuery();
  if (fromUrl !== null) {
    // **URL 로 들어온 값은 저장한다.** 주소창을 지우고 새로고침해도 살아남아야 한다.
    persist(fromUrl);
    return fromUrl;
  }
  return fromStorage() ?? fromNavigator() ?? 'ko';
}

let lang: Lang = decide();
const listeners = new Set<() => void>();

applyDocumentLang(lang);

export function getLang(): Lang {
  return lang;
}

/**
 * 언어를 바꾼다. **이 함수가 하는 일은 셋뿐이다** — 값·저장·`<html lang>`.
 * 렌더 모드도 연결 주소도 기록 열도 건드리지 않는다.
 *
 * 주소창의 `?lang=` 갱신은 여기가 아니라 전환 UI(`shell/LangSwitch.tsx`)가 한다 —
 * 저장소는 이력(history)을 모르는 편이 낫고, 검사(`verify:lang-switch`)가 이 함수를
 * 브라우저 없이 부를 수 있어야 하기 때문이다.
 */
export function setLang(next: Lang): void {
  if (!isLang(next) || lang === next) return;
  lang = next;
  persist(next);
  applyDocumentLang(next);
  for (const listener of listeners) listener();
}

export function subscribeLang(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useLang(): Lang {
  return useSyncExternalStore(subscribeLang, getLang, getLang);
}
