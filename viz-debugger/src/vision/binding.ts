/**
 * src/vision/binding.ts (261001 신설 — 객체 탐지 추론 스트림 · 장비와 포트 맞추기)
 *
 * **이 장비의 추론 스트림은 어느 포트인가.** 서버는 포트 하나가 소스 하나다(10003 robot1 …). 그런데 robot1 이
 * 어느 로봇인지는 서버 실행 인자(`--robot1 <IP>`)가 정하고, 현장에서 바뀐다. 그래서 표로 박지 않는다.
 *
 * ## 정하는 순서
 *
 *   1. 사람이 고른 것 — 하드웨어 카드 상세(더블클릭)에서 고른다. 「연결 안 함」도 고름이다
 *   2. **주소가 같은 것** — 서버 `/health` 의 상태 문장에 그 소스가 붙는 파이 주소가 나온다
 *      (`받는 중 mqtt://100.72.109.9:1883`). 장비가 붙어 있는 브로커 주소와 같으면 그 포트다.
 *      짐작이 아니라 같은 주소를 맞대 보는 것이다. 둘 이상이 같으면 **고르지 않는다** — 사람에게 넘긴다
 *   3. 없으면 없다. 아무 포트나 붙이면 다른 로봇의 영상을 이 로봇 것으로 읽는다
 *
 * 브로커가 호스트 이름(`.local`)이고 서버가 IP 로 붙어 있으면 2번이 못 맞춘다 — 그때는 1번이다.
 * `/state` 로만 오는 장비(브로커 없음)도 1번이다.
 *
 * 고름은 **장비 id 마다** 이 브라우저에 남는다(`viz.visionBinding.v1`). 연결 관리 설정에 넣지 않는 이유는
 * 노드 고름(`media/cameraChoice.ts`)과 같다 — 칸 하나 때문에 판을 올리면 저장된 설정이 버려진다.
 */

import { useSyncExternalStore } from 'react';
import { clientForDevice } from '../physical/robotClient.ts';
import type { VisionSourceState } from './store.ts';

const STORAGE_KEY = 'viz.visionBinding.v1';
/** 「연결 안 함」을 고른 표시. 주소가 될 수 없는 글자다. */
export const VISION_UNBOUND = '-';

function read(): Record<string, string> {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'string' && value !== '') out[id] = value;
    }
    return out;
  } catch {
    return {};
  }
}

let choices: Record<string, string> = read();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 사람이 고른 포트 · `VISION_UNBOUND` · 고르지 않았으면 null. */
export function visionBindingChoice(entityId: string): string | null {
  return choices[entityId] ?? null;
}

export function useVisionBindingChoice(entityId: string): string | null {
  return useSyncExternalStore(subscribe, () => visionBindingChoice(entityId), () => visionBindingChoice(entityId));
}

/** null 이면 고름을 지운다(자동으로). */
export function setVisionBinding(entityId: string, base: string | null): void {
  const next = { ...choices };
  if (base === null || base === '') delete next[entityId];
  else next[entityId] = base;
  choices = next;
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(choices));
  } catch {
    // 이번 세션에만 남는다.
  }
  for (const listener of listeners) listener();
}

/** 장비가 붙어 있는 브로커의 호스트. 브로커로 붙지 않은 장비면 null. */
export function deviceBrokerHost(entityId: string): string | null {
  const client = clientForDevice(entityId);
  if (client === null) return null;
  try {
    const host = new URL(client.address()).hostname;
    return host === '' ? null : host;
  } catch {
    return null;
  }
}

/** 이 호스트에 붙는 포트들 — **순수 함수**라 검사가 그대로 부른다. */
export function basesForHost(host: string | null, sources: Readonly<Record<string, VisionSourceState>>, bases: readonly string[]): string[] {
  if (host === null) return [];
  return bases.filter((base) => sources[base]?.health?.upstreamHosts.includes(host) === true);
}

export type VisionBinding = {
  base: string | null;
  how: 'chosen' | 'unbound' | 'matched' | 'ambiguous' | 'none';
  /** 주소가 같은 포트들 — `ambiguous` 면 둘 이상이다. */
  candidates: readonly string[];
};

/** 정하는 순서는 파일 머리. **순수 함수**다 — 호스트와 받은 값을 인자로 받는다. */
export function resolveVisionBinding(
  chosen: string | null,
  host: string | null,
  sources: Readonly<Record<string, VisionSourceState>>,
  bases: readonly string[],
): VisionBinding {
  const candidates = basesForHost(host, sources, bases);
  if (chosen === VISION_UNBOUND) return { base: null, how: 'unbound', candidates };
  if (chosen !== null) return { base: chosen, how: 'chosen', candidates };
  if (candidates.length === 1) return { base: candidates[0], how: 'matched', candidates };
  if (candidates.length > 1) return { base: null, how: 'ambiguous', candidates };
  return { base: null, how: 'none', candidates };
}
