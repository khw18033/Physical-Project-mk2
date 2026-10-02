/**
 * src/i18n/dict.ts (260916 — 영문화 1단계 §2)
 *
 * **갈아끼울 통로 하나.** 이 단계의 산출물은 번역이 아니라 이 통로이고, 통로가 도는지는
 * 시범 키 다섯으로 증명한다.
 *
 * ## 지키는 것 셋
 *
 * **① 키는 `영역.항목` 이다.** 한국어 원문을 키로 쓰지 않는다.
 *
 * ```ts
 * t('stt.offline')                    // 좋다
 * t('STT 서비스에 닿지 않습니다')       // 나쁘다 — 원문을 한 글자 다듬으면 영어가 통째로 떨어진다
 * ```
 *
 * **② 누락은 한국어로 떨어진다.**
 *
 * ```
 * en 에 키가 없으면  →  ko 값을 돌려주고 콘솔에 한 줄
 * ko 에도 없으면    →  키 문자열을 돌려주고 콘솔에 경고
 * ```
 *
 * 빈 문자열을 그리지 않는다. **부분 번역 상태로도 화면이 정상이어야 한다** — 4단계까지
 * 1,249줄을 다 못 옮긴다는 전제로 설계한 것이다.
 *
 * 키 원문(`stt.offline`)이 화면에 뜨는 것은 **양쪽 사전에 다 없을 때뿐**이고, 그건 오타이거나
 * 아직 안 만든 키라 화면에 드러나는 편이 낫다. 조용히 비우면 어디가 빈지 아무도 모른다.
 *
 * **③ 치환은 자리표시로.** 문장을 쪼개 이어붙이지 않는다.
 *
 * ```ts
 * t('elapsed', { sec: 30 })
 * // ko: '경과 {sec}초'   en: '{sec}s elapsed'
 * ```
 *
 * 영어는 어순이 반대라 조각을 이어붙이는 순간 번역이 불가능해진다. `${}` 가 섞인 한글
 * 문자열이 이 저장소에 **164곳** 있고 2단계에서 전부 이 꼴로 옮긴다.
 *
 * 복수형(`Intl.PluralRules`)은 **안 넣는다.** 언어가 둘뿐이라 과하다.
 *
 * ## 모듈 최상위에서 부르지 마라
 *
 * `t()` 는 **부르는 순간의 언어**를 돌려준다. 최상위 `const` 에서 부르면 로드 시점에 한 번
 * 굳어 언어를 바꿔도 안 따라온다.
 *
 * ```ts
 * const LABEL = { business: t('plane.business') };   // 나쁘다 — 로드 때 굳는다
 * <b>{t('plane.' + plane)}</b>                       // 좋다 — 렌더마다 묻는다
 * ```
 *
 * 다시 그리게 하는 것은 `useLang()` 이다(`shared/language.ts`). 화면이 그 훅을 쓰고 있어야
 * 언어가 바뀔 때 `t()` 를 다시 부른다.
 */

import { en } from './en.ts';
import { ko } from './ko.ts';
import { getLang, type Lang } from '../shared/language.ts';

const DICTS = { ko, en } as const;

/**
 * 이미 알린 키. **같은 키는 한 번만 찍는다** — 렌더마다 찍으면 콘솔이 못 쓰게 되고,
 * 그러면 정작 봐야 할 한 줄이 묻힌다.
 */
const announced = new Set<string>();

function announce(key: string, message: string, level: 'log' | 'warn'): void {
  if (announced.has(key)) return;
  announced.add(key);
  console[level](message);
}

/** `{sec}` 같은 자리표시를 채운다. 값이 없는 자리표시는 **그대로 둔다** — 빈칸보다 낫다. */
function fill(template: string, vars?: Record<string, string | number>): string {
  if (vars === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole,
  );
}

/**
 * **언어를 받아서** 푼다 (260919 · 5단계).
 *
 * `t()` 는 지금 화면의 언어로 푸는데, 화면이 아닌 곳에서도 이 사전이 필요하다 —
 * 목 게이트웨이가 `scenarios/matcher.ts` 를 그대로 끌어 쓴다. 거기서는 `getLang()` 이
 * 언제나 `ko` 라(브라우저 전역이 없다) **3단계의 영어 조회 규칙이 아예 안 돌고 있었다.**
 * 거절 문구도 늘 한국어였다. 그래서 언어를 값으로 받는 자리를 따로 낸다.
 */
export function tIn(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const hit = DICTS[lang]?.[key];
  if (hit !== undefined) return fill(hit, vars);

  const korean = ko[key];
  if (korean !== undefined) {
    // 아직 안 옮긴 키. **정상 상태다** — 4단계까지 이 줄이 줄어드는 것이 진척이다.
    if (lang !== 'ko') announce(key, `[i18n] ${lang} 에 없어 한국어로 그립니다 — ${key}`, 'log');
    return fill(korean, vars);
  }

  // 양쪽에 다 없다. 오타이거나 아직 안 만든 키다 — 화면에 키가 드러나는 편이 낫다.
  announce(key, `[i18n] 어느 사전에도 없는 키입니다 — ${key}`, 'warn');
  return key;
}

/** 지금 **화면**의 언어로 푼다. 부르는 순간의 값을 줄 뿐 구독이 아니다 — `useLang()` 이 필요하다. */
export function t(key: string, vars?: Record<string, string | number>): string {
  return tIn(getLang(), key, vars);
}

/** 검사용. 사전을 직접 읽어야 하는 곳(`verify:lang-switch`)이 쓴다. */
export { ko, en };
