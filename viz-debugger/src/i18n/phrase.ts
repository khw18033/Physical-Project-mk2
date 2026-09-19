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
import { getLang } from '../shared/language.ts';
import { isTranslated, serviceWords } from './serviceWords.ts';

/**
 * **남이 준 말.** 우리 사전에 없고, 그릴 때 그쪽 표로 옮긴다 (`serviceWords.ts`).
 * 못 옮기는 문장이면 한국어 그대로 나온다 — 지어내지 않는다.
 */
export type LogForeign = { foreign: string };

/**
 * **원문.** 옮겨서 그린 자리에 한해 원문을 나란히 남긴다. 안 옮겨졌으면(한국어 화면이거나
 * 모르는 문장이면) **빈 글자**라 줄에서 빠진다 — 한국어 화면에 같은 말이 두 번 뜨면 안 된다.
 *
 * 260919 사용자 결정 — 「화면이 영어라면 번역하고, 로그에 원문 한국어를 표시」.
 * 탐지 파트와 이야기할 때는 화면의 영어가 아니라 **서비스가 실제로 뱉은 글자**가 필요하다.
 */
export type LogOriginal = { original: string };

/** 치환값. **값 자리에 또 다른 문구**가 올 수 있다 — 「경로 실패 — {reason}」의 `{reason}`. */
export type LogVar = string | number | LogPhrase | LogForeign | LogOriginal;

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

function isForeign(v: LogVar): v is LogForeign {
  return typeof v === 'object' && v !== null && typeof (v as LogForeign).foreign === 'string';
}

function isOriginal(v: LogVar): v is LogOriginal {
  return typeof v === 'object' && v !== null && typeof (v as LogOriginal).original === 'string';
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
  if (isForeign(v)) return serviceWords(v.foreign, getLang());
  // 옮겨진 자리에만 원문을 보탠다. 아니면 빈 글자라 줄에서 빠진다.
  if (isOriginal(v)) return isTranslated(v.original, getLang()) ? v.original : '';
  return isPhrase(v) ? sayText(v) : String(v);
}

/** 두 줄이 같은 말인가. **키와 값으로** 본다 — 글자로 비교하면 언어를 바꾼 뒤 또 쌓인다. */
export function sameSay(a: LogSay | undefined, b: LogSay | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}
