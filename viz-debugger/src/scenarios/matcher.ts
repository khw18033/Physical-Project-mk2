/**
 * src/scenarios/matcher.ts
 *
 * 문장 → 대본 매칭. **이것은 LLM이 아니다 — 키워드 대조다.**
 *
 * 게이트웨이(`gateway/script-engine.ts`) · 브라우저(발화 패널 배지·단독 빌드 재생기) ·
 * 검증(`scripts/verify-script-library.mjs`)이 **전부 이 파일 하나**를 import 한다.
 * 매칭 규칙이 두 벌이면 게이트웨이와 화면이 다른 대본을 고르는 날이 온다.
 *
 * 규칙:
 *   - must: 바깥 배열 AND · 안쪽 배열 OR (동의어·오인식 변형)
 *   - any : 비어 있지 않으면 하나는 맞아야 한다
 *   - not : 하나라도 들어 있으면 맞지 않는다 (260915 — 이웃 편의 문장을 스스로 내어 준다)
 *   - 정규화: 공백 제거 · 소문자 — 이 한 줄이 대본 파일 match.normalize 문구의 실체다
 *   - **맞는 대본이 없으면 없다고 한다.** 둘 이상 맞아도 고르지 않는다(모호 = 거부).
 *     비슷한 것을 억지로 고르면 「대본 조회」가 LLM 흉내가 된다.
 */

import { getLang } from '../shared/language.ts';
import { matchEnOf } from './phrases.ts';
import { t } from '../i18n/dict.ts';
import type { ScriptLibraryEntry, ScriptMatch } from './types.ts';

export function normalize(text: string): string {
  return String(text).replace(/\s+/g, '').toLowerCase();
}

/** 문장이 규칙 하나에 맞는가. */
export function matchesRule(sentence: string, match: ScriptMatch | undefined): boolean {
  if (!match || !Array.isArray(match.must) || match.must.length === 0) return false;
  const text = normalize(sentence);
  if (Array.isArray(match.not) && match.not.some((word) => text.includes(normalize(word)))) return false;
  const mustOk = match.must.every(
    (group) => Array.isArray(group) && group.some((word) => text.includes(normalize(word))),
  );
  if (!mustOk) return false;
  if (Array.isArray(match.any) && match.any.length > 0) {
    return match.any.some((word) => text.includes(normalize(word)));
  }
  return true;
}

/** 문장에 맞은 must·any 키워드 — 화면이 「어느 키워드가 맞아서 골라졌는지」를 보여줄 재료. */
export function matchedKeywords(sentence: string, match: ScriptMatch): string[] {
  const text = normalize(sentence);
  const hits: string[] = [];
  for (const group of match.must) {
    const hit = group.find((word) => text.includes(normalize(word)));
    if (hit !== undefined) hits.push(hit);
  }
  for (const word of match.any ?? []) {
    if (text.includes(normalize(word))) hits.push(word);
  }
  return hits;
}

export type MatchOutcome =
  | { kind: 'matched'; entry: ScriptLibraryEntry; keywords: string[] }
  | { kind: 'none'; reason: string }
  | { kind: 'ambiguous'; candidates: string[]; reason: string };

/**
 * 라이브러리 전체 대조. 정확히 하나면 그 하나, 없거나 둘 이상이면 고르지 않는다.
 * 거부 사유 문구까지 여기서 만든다 — 게이트웨이와 화면이 같은 말을 해야 한다.
 */
/**
 * **영어 화면에서는 영어 규칙을 먼저 본다** (260918 — 3단계).
 *
 * 규칙은 한국어 키워드 대조다. 영어로 말하면 한국어 규칙에는 하나도 안 맞고, 「맞는 대본이
 * 없다」로 끝난다. 그래서 편마다 `MSN-*.en.json` 에 `match_en` 을 두고 영어 화면에서 그것을
 * 먼저 쓴다.
 *
 * **안 맞으면 한국어 규칙으로 한 번 더 본다.** 화면은 영어인데 발표자는 한국어로 말하는 —
 * 실제로 그렇게 할 — 경우가 있고, 그때 못 고르면 시연이 선다.
 *
 * `ko` 에서는 한국어 규칙 하나뿐이다. 한국어 화면의 동작이 한 줄도 달라지지 않는다.
 */
function ruleSets(entry: ScriptLibraryEntry): readonly (ScriptMatch | undefined)[] {
  if (getLang() !== 'en') return [entry.match];
  const en = matchEnOf(entry.missionId);
  return en === null ? [entry.match] : [en, entry.match];
}

export function matchLibrary(sentence: string, library: readonly ScriptLibraryEntry[]): MatchOutcome {
  // 규칙 벌 차례대로 — 영어로 하나가 맞으면 한국어 규칙은 안 본다.
  const passes = getLang() === 'en' ? [0, 1] : [0];
  let hits: readonly ScriptLibraryEntry[] = [];
  let used = new Map<string, ScriptMatch>();
  for (const pass of passes) {
    const found: ScriptLibraryEntry[] = [];
    const rules = new Map<string, ScriptMatch>();
    for (const entry of library) {
      const rule = ruleSets(entry)[pass];
      if (rule === undefined) continue;
      if (matchesRule(sentence, rule)) { found.push(entry); rules.set(entry.missionId, rule); }
    }
    if (found.length > 0) { hits = found; used = rules; break; }
  }
  if (hits.length === 1) {
    // 맞은 키워드는 **실제로 쓴 규칙**에서 뽑는다 — 영어로 맞았는데 한국어 키워드를 적으면
    // 화면이 「왜 이 대본인가」에 거짓말을 한다.
    return { kind: 'matched', entry: hits[0], keywords: matchedKeywords(sentence, used.get(hits[0].missionId) ?? hits[0].match) };
  }
  if (hits.length === 0) {
    return { kind: 'none', reason: t('match.none') };
  }
  return {
    kind: 'ambiguous',
    candidates: hits.map((entry) => entry.missionId),
    reason: t('match.ambiguous', { ids: hits.map((entry) => entry.missionId).join(', ') }),
  };
}
