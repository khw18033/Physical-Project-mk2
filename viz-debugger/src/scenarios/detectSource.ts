/**
 * src/scenarios/detectSource.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S9)
 *
 * **탐지 방식 설정** — `legacy`(옛 `:8000` 탐지기) / `datastream`(data_stream 스캔 창구).
 *
 * 같은 문장(「문 쪽으로 가」)이 옛 편과 새 편에 다 맞으면 매처가 모호 거부한다(`matcher.ts`). 그래서 **설정에 맞는 편만
 * 매칭에 선다.** 편 파일의 `detectSource` 가 그 편의 방식이고, 없으면 탐지와 상관없는 편이라 늘 선다.
 *
 * ## 설정은 게이트웨이가 든다
 *
 * 매칭은 게이트웨이(`gateway/script-engine.ts`)와 브라우저가 **같은 `matcher.ts`** 로 한다. 브라우저 혼자 설정을 들면
 * 둘이 다른 편을 고른다. 그래서 게이트웨이 프로세스의 이 모듈 값이 원천이고(`/scan-detect-source`), 브라우저는 그것을 받아
 * 자기 쪽 이 모듈에 넣는다(`detectSourceSync.ts`). 게이트웨이가 없는 단독 빌드에서는 브라우저 값 하나뿐이다.
 *
 * 이 파일은 react 를 모른다 — 게이트웨이(Node)가 그대로 import 한다.
 */

import type { ScriptLibraryEntry } from './types.ts';

export type DetectSourceMode = 'legacy' | 'datastream';

export const DETECT_SOURCE_MODES: readonly DetectSourceMode[] = ['legacy', 'datastream'];

/** 처음 기본값 — 실물로 새 편 셋이 한 번씩 통과한 뒤 바꾼다(계획서 §7-4). */
export const DETECT_SOURCE_DEFAULT: DetectSourceMode = 'legacy';

let mode: DetectSourceMode = DETECT_SOURCE_DEFAULT;
const listeners = new Set<() => void>();

export function isDetectSourceMode(value: unknown): value is DetectSourceMode {
  return value === 'legacy' || value === 'datastream';
}

export function detectSource(): DetectSourceMode {
  return mode;
}

export function setDetectSource(next: DetectSourceMode): void {
  if (next === mode) return;
  mode = next;
  for (const listener of listeners) listener();
}

export function subscribeDetectSource(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 그 편의 탐지 방식. 탐지와 상관없는 편이면 null. */
export function entryDetectSource(entry: ScriptLibraryEntry): DetectSourceMode | null {
  const declared = entry.script?.detectSource;
  return isDetectSourceMode(declared) ? declared : null;
}

/** 이 설정에서 그 편이 매칭에 서는가. */
export function standsUnder(entry: ScriptLibraryEntry, under: DetectSourceMode = mode): boolean {
  const own = entryDetectSource(entry);
  return own === null || own === under;
}
