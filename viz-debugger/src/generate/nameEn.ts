/**
 * src/generate/nameEn.ts (261123 신설 — 스캔 탐지를 data_stream 으로)
 *
 * **발화의 @(한국어 물체 이름) → 영어 이름 하나.** data_stream `targeted` 가 대상 이름을 모델 문구로 그대로 쓰므로
 * @ 편(`MSN-261123-03`)은 영어로 보낸다(결정 10). 옮기는 것은 생성 서비스(gen-lab `/generate/name_en`)의 LLM 이다.
 *
 * 생성 주소를 아는 면은 `src/generate/` 하나여야 한다(`verify:gen-port`) — 그래서 여기 둔다. 실패하면 지어내지 않고
 * 사유를 돌려준다. 부르는 쪽(스캔 실행기)은 그때 `prepare` 를 보내지 않고 멈춘다.
 */

import { generateBaseUrl } from './LlmClient.ts';

export type NameEnAnswer = { ok: true; nameEn: string; model: string | null } | { ok: false; reason: string };

/** 이미 영어(ASCII 낱말)면 그대로 — 영어 화면에서 「to the chair」로 말한 경우다. */
const ENGLISH = /^[a-z]+( [a-z]+){0,3}$/;

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
