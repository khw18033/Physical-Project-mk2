/**
 * src/vision/nodeChoice.ts (261001 신설 — 객체 탐지 추론 스트림)
 *
 * **추론 영상 노드 한 장이 고른 것** — 포트 · 모델(여럿) · 원본을 같이 볼지. 노드마다 따로다 — 같은 노드를 여러 장
 * 놓고 확대에서 각자 고른다(카메라 노드 · 탐지 영상 노드와 같은 규칙).
 *
 *   포트   고르지 않았으면 연결한 태스크의 장비에 묶인 포트(`binding.ts`), 그것도 없으면 연결 관리 목록의 첫 줄
 *   모델   고르지 않았으면 **지금 결과가 오는 모델 전부** — 여러 모델이 돌면 처음부터 나란히 보인다
 *   원본   기본은 끔. 켜면 원본 실시간 영상이 한 칸 더 선다(결과보다 앞선다는 것을 그 칸이 적는다)
 *
 * 하드웨어 카드 상세도 같은 저장소를 쓴다 — 키가 `hw:<장비 id>` 다.
 */

import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'viz.visionNode.v1';

export type VisionNodeChoice = {
  base?: string;
  models?: readonly string[];
  raw?: boolean;
};

function clean(value: unknown): VisionNodeChoice | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  const out: VisionNodeChoice = {};
  if (typeof v.base === 'string' && v.base !== '') out.base = v.base;
  if (Array.isArray(v.models)) out.models = v.models.filter((m): m is string => typeof m === 'string' && m !== '');
  if (typeof v.raw === 'boolean') out.raw = v.raw;
  return out;
}

function read(): Record<string, VisionNodeChoice> {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, VisionNodeChoice> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      const choice = clean(value);
      if (choice !== null) out[id] = choice;
    }
    return out;
  } catch {
    return {};
  }
}

const NONE: VisionNodeChoice = {};
let choices: Record<string, VisionNodeChoice> = read();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function visionNodeChoice(nodeId: string): VisionNodeChoice {
  return choices[nodeId] ?? NONE;
}

export function useVisionNodeChoice(nodeId: string): VisionNodeChoice {
  return useSyncExternalStore(subscribe, () => visionNodeChoice(nodeId), () => visionNodeChoice(nodeId));
}

/** 칸을 덮어쓴다. `undefined` 를 준 칸은 지운다(기본으로). */
export function setVisionNodeChoice(nodeId: string, patch: Partial<Record<keyof VisionNodeChoice, unknown>>): void {
  const merged: Record<string, unknown> = { ...visionNodeChoice(nodeId) };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete merged[key];
    else merged[key] = value;
  }
  const next = { ...choices };
  const cleaned = clean(merged) ?? {};
  if (Object.keys(cleaned).length === 0) delete next[nodeId];
  else next[nodeId] = cleaned;
  choices = next;
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(choices));
  } catch {
    // 이번 세션에만 남는다.
  }
  for (const listener of listeners) listener();
}
