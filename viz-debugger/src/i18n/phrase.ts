/**
 * src/i18n/phrase.ts (260919 신설 — 영문화 5단계 §3)
 *
 * **글자가 아니라 「무슨 말인지」를 담는다.**
 *
 * 열(로그·알림)에 문장을 쌓을 때 `t()` 로 그린 글자를 담으면, 그 줄은 **쌓인 순간의
 * 언어로 굳는다.** 나중에 언어를 바꿔도 안 따라오고, 기록으로 저장하면 영영 그 언어다.
 * 260919 에 사람이 「탐지 화면 로그는 '가까운 장애물 있음/없음' 부분만 한국어」로 본 것이
 * 그 자국이다.
 *
 * 그래서 **키와 값**을 담고 그릴 때 푼다. `t()` 를 부르는 시점이 「쌓을 때」에서
 * 「그릴 때」로 옮겨 가는 것이 전부다.
 *
 * ## 여기 있는 이유 — 경계
 *
 * 이 모양을 `detect/detectLog.ts` 에 두었더니 `verify:autodrive-ai` 가 잡았다:
 * **`src/autodrive/` 는 문 찾기 탐지(`src/detect/`)를 import 하지 않는다.** 두 판은 서로
 * 다른 실험이고, 한쪽이 다른 쪽을 끌어오기 시작하면 따로 돌릴 수 없게 된다.
 *
 * 말을 담는 방식은 탐지의 것도 자율주행의 것도 아니라 **표시층의 것**이다. 그래서 여기다.
 */

import { t } from './dict.ts';

/** 치환값. **값 자리에 또 다른 문구**가 올 수 있다 — 「경로 실패 — {reason}」의 `{reason}`. */
export type LogVar = string | number | LogPhrase;

export type LogPhrase = { key: string; vars?: Record<string, LogVar> };

/**
 * 한 자리에 담기는 것. **여럿이면 ` · ` 로 잇는다** — 상세 줄이 원래 그런 모양이다
 * (프레임 id · 점수 · 한 문장). 빈 조각은 빠진다.
 *
 * 조각마다 키이거나 값이다 — **문장을 토막 내는 것이 아니다.** 「12.3° · 문 있음」에서
 * 각 토막이 그 자체로 완결된 말이라 이을 수 있다.
 */
export type LogSay = LogPhrase | readonly LogVar[];

export function isPhrase(v: LogVar): v is LogPhrase {
  return typeof v === 'object' && v !== null && typeof (v as LogPhrase).key === 'string';
}

/** 담아 둔 말을 **지금 언어로**. 값 자리에 든 문구도 같이 푼다. */
export function sayText(p: LogSay): string {
  if (Array.isArray(p)) return p.map(one).filter((part) => part !== '').join(' · ');
  const phrase = p as LogPhrase;
  if (phrase.vars === undefined) return t(phrase.key);
  const flat: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(phrase.vars)) flat[k] = one(v);
  return t(phrase.key, flat);
}

function one(v: LogVar): string {
  return isPhrase(v) ? sayText(v) : String(v);
}

/** 두 줄이 같은 말인가. **키와 값으로** 본다 — 글자로 비교하면 언어를 바꾼 뒤 또 쌓인다. */
export function sameSay(a: LogSay | undefined, b: LogSay | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}
