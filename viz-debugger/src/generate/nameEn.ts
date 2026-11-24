/**
 * src/generate/nameEn.ts (261123 신설 — 스캔 탐지를 data_stream 으로)
 *
 * **발화의 @(한국어 물체 이름) → 영어 이름 하나.** data_stream `targeted` 가 대상 이름을 모델 문구로 그대로 쓰므로
 * @ 편(`MSN-261123-03`)은 영어로 보낸다(결정 10). 옮기는 것은 생성 서비스(gen-lab `/generate/name_en`)의 LLM 이다.
 *
 * 생성 주소를 아는 면은 `src/generate/` 하나여야 한다(`verify:gen-port`) — 그래서 여기 둔다. 실패하면 지어내지 않고
 * 사유를 돌려준다. 부르는 쪽(스캔 실행기)은 그때 `prepare` 를 보내지 않고 멈춘다.
 */

import { connectionAddress } from '../shared/connections.ts';

/**
 * 생성 서비스 주소. `LlmClient.ts` 의 `generateBaseUrl()` 과 같은 값이지만 그 파일을 import 하지 않는다 — 그 파일은 계약
 * (`../../../contracts/*.json`)을 끌어와, 스캔 화면(노드 상세 · 정지 버튼)을 묶을 때 `src/` 밖까지 딸려 온다. 기본값은 `LlmClient.ts` 가 심는다.
 */
const generateBaseUrl = (): string => connectionAddress('generate', 'base');

export type NameEnAnswer = { ok: true; nameEn: string; model: string | null } | { ok: false; reason: string };

/** 이미 영어(ASCII 낱말)면 그대로 — 영어 화면에서 「to the chair」로 말한 경우다. */
const ENGLISH = /^[a-z]+( [a-z]+){0,3}$/;

/** data_stream 에 보낼 수 있는 이름 — 소문자 영어 · 공백 · 하이픈만 (261124 · 요청 C). */
const SENDABLE = /^[a-z]+(?:[ -][a-z]+)*$/;
export const QUERY_MAX_CHARS = 40;

/**
 * **이 이름을 data_stream 에 보내도 되는가** (261124 — 요청 C). 번역 서비스가 깨진 이름을 돌려준 일이 있다:
 * 「사람」 → `celedar or person orhumanbeingorhumanh`, 「소화기」 → `ionalescrollingtext uebaa uebaa uebaa`.
 *
 * data_stream 이 정한 검사: 소문자 영어 · 공백 · 하이픈만, 40자 이하, `" or "` 없음. 여기에 **같은 낱말 되풀이**(`uebaa uebaa`)를
 * 하나 더 건다 — 위 두 번째 예는 앞의 셋을 다 통과한다. 어긋나면 사유 키를 돌려주고, 부르는 쪽은 그 이름을 보내지 않는다.
 */
export function sendableQuery(raw: string): { ok: true; query: string } | { ok: false; key: string; vars?: Record<string, string | number> } {
  const query = raw.trim().replace(/\s+/g, ' ');
  if (query === '') return { ok: false, key: 'sd.query.empty' };
  if (query.length > QUERY_MAX_CHARS) return { ok: false, key: 'sd.query.tooLong', vars: { n: query.length, max: QUERY_MAX_CHARS } };
  if (!SENDABLE.test(query)) return { ok: false, key: 'sd.query.chars' };
  if (` ${query} `.includes(' or ')) return { ok: false, key: 'sd.query.or' };
  const words = query.split(/[ -]/);
  if (new Set(words).size !== words.length) return { ok: false, key: 'sd.query.repeat' };
  return { ok: true, query };
}

export async function translateObjectName(textKo: string, timeoutMs = 20_000): Promise<NameEnAnswer> {
  const text = textKo.trim();
  const lowered = text.toLowerCase().replace(/\s+/g, ' ');
  if (ENGLISH.test(lowered)) return { ok: true, nameEn: lowered, model: null };
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const response = await fetch(`${generateBaseUrl().replace(/\/+$/, '')}/generate/name_en`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }), signal: abort.signal,
    });
    const body = await response.json().catch(() => null) as { name_en?: unknown; model?: unknown; error?: unknown } | null;
    if (!response.ok) return { ok: false, reason: `HTTP ${response.status}${typeof body?.error === 'string' ? ` ${body.error}` : ''}` };
    const name = typeof body?.name_en === 'string' ? body.name_en.trim().toLowerCase() : '';
    if (!ENGLISH.test(name)) return { ok: false, reason: `bad name ${JSON.stringify(body?.name_en ?? null)}` };
    return { ok: true, nameEn: name, model: typeof body?.model === 'string' ? body.model : null };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? (error.name === 'AbortError' ? `${timeoutMs}ms` : error.message) : String(error) };
  } finally {
    clearTimeout(timer);
  }
}
