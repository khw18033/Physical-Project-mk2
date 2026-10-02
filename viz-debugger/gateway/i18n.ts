/**
 * gateway/i18n.ts (260919 신설 — 영문화 5단계 §1)
 *
 * **말을 만든 쪽이 언어를 안다.**
 *
 * 4단계까지는 `src/` 만 옮겼다. 그런데 화면에 뜨는 한국어 중에는 **게이트웨이가 완성된
 * 문장으로 보내 준 것**이 있다 — 승인 팝업의 검증 문장(`대본 매칭 — 키워드 대조`),
 * 제어 패널의 대상 이름(`전 구역 운영자`), 명령 거절 사유. 화면은 그것을 그대로 그린다.
 * 260919 에 사람이 `?lang=en` 으로 보고 찾았다.
 *
 * 화면 쪽 사전(`src/i18n/`)으로는 못 옮긴다. 그 글자를 **우리가 만들지 않기 때문**이다 —
 * 실제 백엔드가 오면 그 자리는 백엔드가 말한다. 그래서 **게이트웨이가 자기 사전을 갖고,
 * 요청한 언어로 답한다.** 3단계에서 STT 에 `language` 를 실어 보낸 것과 같은 모양이다.
 *
 * ## 왜 표지(marker)인가 — 봉투는 **모두에게 하나**가 나간다
 *
 * `Hub.fanout()` 은 봉투 하나를 붙어 있는 모두에게 보낸다. 만드는 자리에서 글자로
 * 굳히면 **접속마다 다른 언어로 줄 수가 없다.** 그렇다고 값 만드는 함수 전부에 `lang`
 * 을 흘리면 열두 파일의 서명이 다 바뀐다.
 *
 * 그래서 만드는 자리는 **키와 값만** 담고(`say('plan.scriptMatch', { id })`), 글자로
 * 바꾸는 것은 **보낼 때 한 곳**에서 한다(`render(msg, lang)`). 받는 사람마다 그린다.
 *
 * ## 전선에 나가는 모양은 안 바뀐다
 *
 * 표지는 **게이트웨이 안에서만** 산다. `render()` 를 지나면 평범한 문자열이다.
 * 계약(payload 모양)은 한 글자도 안 바뀌고, 화면은 고칠 것이 없다.
 *
 * ## 서버 콘솔은 대상이 아니다
 *
 * `log('접속 c1')` 같은 줄은 화면에 안 뜬다. `src/` 의 DEV_ONLY 와 같은 기준이다 —
 * **「화면에 뜨는가」이지 「어디에 적히는가」가 아니다.**
 */

import { GW_KO } from './i18n.ko.ts';
import { GW_EN } from './i18n.en.ts';

export type GwLang = 'ko' | 'en';

export const GW_LANGS: readonly GwLang[] = ['ko', 'en'];

export function isGwLang(v: unknown): v is GwLang {
  return v === 'ko' || v === 'en';
}

/**
 * 치환값. **표지를 값으로 넣을 수 있다** — 문장 안에 다른 문장이 들어가는 자리가 있다
 * (`{action} 명령 접수` 의 `{action}` 이 그 자체로 옮겨야 하는 이름이다). 조각을 이어
 * 붙이는 대신 **한 문장에 한 키**를 지키려면 이 중첩이 필요하다.
 */
export type SayVar = string | number | Say;

/** 표지 — 「이 자리는 받는 사람의 언어로 그린다」. `sayJson()` 을 지나면 사라진다. */
export type Say = {
  readonly __say: string;
  readonly vars?: Readonly<Record<string, SayVar>>;
};

const MARK = '__say';

/** 표시 자리에 담는다. 글자가 아니라 **키와 값**이다. */
export function say(key: string, vars?: Record<string, SayVar>): Say {
  return vars === undefined ? { __say: key } : { __say: key, vars };
}

/**
 * **표시 자리.** 만들 때는 표지일 수 있고, 전선에 나갈 때는 반드시 글자다.
 *
 * 게이트웨이 안에서만 쓰는 타입이다 — `sayJson()` 을 지나면 전부 `string` 이라
 * 화면이 받는 모양은 한 글자도 안 바뀐다. 계약 타입(`src/transport/types.ts`)에는
 * 이 개념이 없어야 한다. 거기까지 넓히면 「글자인 줄 알았는데 아닌」 자리가 화면에 생긴다.
 */
export type Text = string | Say;

export function isSay(v: unknown): v is Say {
  return typeof v === 'object' && v !== null && typeof (v as Record<string, unknown>)[MARK] === 'string';
}

function fill(lang: GwLang, template: string, vars?: Readonly<Record<string, SayVar>>): string {
  if (vars === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const v = vars[name];
    if (v === undefined) return whole;
    // 값 자리에 들어온 표지도 **같은 언어로** 푼다.
    return isSay(v) ? gwT(lang, v.__say, v.vars) : String(v);
  });
}

/**
 * 표지 하나를 글자로. 영어가 없으면 **한국어로 떨어진다** — 부분 번역 상태에서도
 * 화면이 정상이어야 한다 (`src/i18n/dict.ts` 와 같은 규칙).
 */
export function gwT(lang: GwLang, key: string, vars?: Readonly<Record<string, SayVar>>): string {
  const hit = lang === 'en' ? GW_EN[key] : undefined;
  if (hit !== undefined) return fill(lang, hit, vars);
  const ko = GW_KO[key];
  if (ko !== undefined) return fill(lang, ko, vars);
  // 양쪽에 다 없다 — 키가 드러나는 편이 낫다. 조용히 빈칸이 되면 못 찾는다.
  return key;
}

/**
 * **보내는 모양 그대로 직렬화하면서** 표지를 글자로 바꾼다. 받는 사람마다 한 번씩 부른다.
 *
 * 처음에는 메시지를 통째로 훑어 새 객체를 만드는 `render()` 를 썼다가 **목 게이트웨이가
 * 멈췄다** — 영상이 15fps 로 흐르는 동안 봉투마다 깊은 순회를 도니 이벤트 루프가 막혔고,
 * `verify:one-gateway` 가 「끊고 다시 붙기 시간 초과」로 그것을 잡았다.
 *
 * `JSON.stringify` 는 **어차피 전부 한 번 훑는다.** 그 순회에 얹으면 추가 비용이 사실상
 * 없고 복사도 안 생긴다. 표지가 없는 봉투(대부분)는 예전과 똑같은 일만 한다.
 */
export function sayJson(value: unknown, lang: GwLang, space?: number): string {
  return JSON.stringify(value, (_key, v: unknown) => (isSay(v) ? gwT(lang, v.__say, v.vars) : v), space);
}

/**
 * 같은 일을 **객체로** 한다 — 전선에 안 나가고 검사가 들여다볼 때 쓴다.
 *
 * 표지가 없으면 **원래 객체를 그대로 돌려준다** — 새로 만들지 않는다.
 */
export function render<T>(value: T, lang: GwLang): T {
  return walk(value, lang) as T;
}

function walk(value: unknown, lang: GwLang): unknown {
  if (isSay(value)) return gwT(lang, value.__say, value.vars);
  if (Array.isArray(value)) {
    let changed = false;
    const out = value.map((v) => {
      const next = walk(v, lang);
      if (next !== v) changed = true;
      return next;
    });
    return changed ? out : value;
  }
  if (typeof value === 'object' && value !== null) {
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const next = walk(v, lang);
      if (next !== v) changed = true;
      out[k] = next;
    }
    return changed ? out : value;
  }
  return value;
}

/** 주소의 `?lang=` 을 읽는다. 없거나 모르는 값이면 `ko` — 지금까지와 같은 화면이다. */
export function langOf(url: string | undefined): GwLang {
  if (url === undefined) return 'ko';
  const q = url.indexOf('?');
  if (q === -1) return 'ko';
  const value = new URLSearchParams(url.slice(q + 1)).get('lang');
  return isGwLang(value) ? value : 'ko';
}

/**
 * **원천이 두 벌을 들고 있는 자리**를 영어로 고른다 — 레지스트리의
 * `display_name`/`display_name_en`, `aliases`/`aliases_en`.
 *
 * 사전을 타지 않는다. 그 글자는 우리가 짓는 것이 아니라 **데이터가 이미 가진 것**이고,
 * 사전에 또 적으면 갈라질 자리가 하나 더 생긴다.
 *
 * 규칙 하나뿐이다 — `X_en` 이 있고 비어 있지 않으면 `X` 자리에 넣고 `X_en` 은 지운다.
 * 없으면 한국어가 그대로 남는다(부분 번역 상태에서도 화면은 정상이어야 한다).
 */
export function inEnglish<T>(value: T): T {
  return pickEn(value) as T;
}

function usable(v: unknown): boolean {
  if (typeof v === 'string') return v.trim() !== '';
  return Array.isArray(v) && v.length > 0;
}

function pickEn(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(pickEn);
  if (value === null || typeof value !== 'object') return value;
  const out: Record<string, unknown> = {};
  const box = value as Record<string, unknown>;
  for (const [k, v] of Object.entries(box)) {
    if (k.endsWith('_en')) continue;                  // 아래에서 본체 자리에 넣는다
    const en = box[`${k}_en`];
    out[k] = en !== undefined && usable(en) ? pickEn(en) : pickEn(v);
  }
  return out;
}
