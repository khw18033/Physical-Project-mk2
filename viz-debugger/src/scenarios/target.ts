/**
 * src/scenarios/target.ts (260927 신설 — 장치 두 대 편 · 발화가 정하는 대상)
 *
 * **대본 문구의 빈칸(`@`)을 발화가 채운다.** 「장치 두 가지를 문까지 이동시켜」면 `@` 는 문이다.
 *
 * 이것도 LLM 이 아니다 — 대본이 적어 둔 정규식으로 문장에서 **한 조각을 잘라 올 뿐**이다.
 * 못 자르면 채우지 않는다. `@` 가 그대로 남는 것이 「아직 안 정해졌다」는 사실이고, 비슷한 낱말을
 * 지어 넣으면 사람이 말하지 않은 대상으로 장치가 간다.
 *
 * ## 왜 저장할 때가 아니라 그릴 때 채우나
 *
 * 대본의 한국어 문구는 **영어 사이드카의 키**다(`phrases.ts`). 「문 위치 추정」으로 바꿔 두면
 * 사이드카에 「@ 위치 추정」밖에 없으므로 영문 화면에서 못 찾는다. 그래서 임무 본문에는 `@` 를 둔 채로
 * 두고, **번역한 다음에** 채운다(`data/scenario.ts` 의 `displayMission`).
 *
 * React 도 저장소도 모르는 순수 함수만 둔다 — 게이트웨이·검사가 그대로 부른다.
 */

import type { ScriptTarget } from './types.ts';

/** 잘라 온 조각을 다듬는다. 따옴표·끝 조사 정도만 — 뜻을 바꾸는 손질은 하지 않는다. */
function tidy(raw: string): string {
  return raw.trim().replace(/^["'「『]+|["'」』]+$/g, '').trim();
}

/**
 * 문장에서 대상을 잘라 온다. **못 찾으면 null** — 채우지 않는다.
 *
 * 규칙 벌은 언어마다 따로다. 영어 화면이어도 한국어로 말할 수 있으므로(`matcher.ts` 와 같은 사정)
 * 영어 규칙이 안 맞으면 한국어 규칙으로 한 번 더 본다.
 */
export function extractTarget(sentence: string, spec: ScriptTarget | undefined, lang: 'ko' | 'en' = 'ko'): string | null {
  if (spec === undefined) return null;
  const sets = lang === 'en' ? [spec.patterns_en ?? [], spec.patterns] : [spec.patterns];
  for (const patterns of sets) {
    for (const source of patterns) {
      let found: RegExpMatchArray | null = null;
      try {
        found = sentence.match(new RegExp(source, 'i'));
      } catch {
        // 대본의 정규식이 깨졌으면 그 줄만 건너뛴다 — 발화 하나 때문에 화면이 멎으면 안 된다.
        continue;
      }
      const word = found?.[1] === undefined ? '' : tidy(found[1]);
      // 빈칸 그대로 말한 것(「@까지」)은 정한 것이 아니다.
      if (word === '' || word === spec.token) continue;
      return word;
    }
  }
  return null;
}

/** 문구 하나의 빈칸을 채운다. 대상이 없으면 **그대로** 돌려준다 — 같은 참조다. */
export function fillText(text: string, token: string, word: string | null): string {
  if (word === null || word === '' || !text.includes(token)) return text;
  return text.split(token).join(word);
}

/** 사건 한 건의 payload 에서 글자인 칸만 채운다. 숫자·식별자는 그대로 둔다. */
export function fillPayload(payload: unknown, token: string, word: string | null): unknown {
  if (word === null || payload === null || typeof payload !== 'object' || Array.isArray(payload)) return payload;
  const source = payload as Record<string, unknown>;
  let changed = false;
  const out: Record<string, unknown> = { ...source };
  for (const [key, value] of Object.entries(source)) {
    if (typeof value !== 'string' || !value.includes(token)) continue;
    out[key] = fillText(value, token, word);
    changed = true;
  }
  return changed ? out : payload;
}
