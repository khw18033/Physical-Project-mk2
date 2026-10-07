/**
 * src/virtualmap/twinDevice.ts (261007 신설 — 3D 가상환경을 하드웨어 카드로)
 *
 * **3D 가상환경을 내보내는 PC 를 장비 하나로 본다.** 지금까지 3D 가상환경은 노드로만 볼 수 있었다. 고정 카메라와 같은
 * 취급이다(261007 지시) — 수동 제어 · 객체 탐지 없이 보기만 한다. 주소는 연결 관리의 「3D 가상환경」 칸(`virtual-3d.base`)이다.
 *
 * ## 「연결됨」은 그 주소가 답하는 것이다
 *
 * Unity 상공 카메라 서버면 `/status` 가 카메라 목록을 준다(`TopCamView.tsx`). 아니면(WebGL 페이지 등) 페이지가 답하기만
 * 하면 된다 — 다른 출처라 내용은 못 읽으므로 `no-cors` 로 닿는지만 본다. 답하면 연결 장비 저장소에 `twin` 길로 적고
 * (`noteConnectedEntity`), 하드웨어 카드는 그 저장소만 읽는다 — 고정 카메라와 같은 길이다. 주기와 창도 같다.
 *
 * ## 카드 이름은 그 PC 의 이름이다
 *
 * 브라우저는 상대 PC 이름을 모른다. 개발 서버가 이 PC 의 Tailscale 목록에서 그 주소의 기기 이름을 찾아 준다
 * (`scripts/video-records.mjs` 의 `host-name` — 261007 결정 (나)). 못 찾으면(Tailscale 이 없음 · 단독 빌드) 주소의 호스트를
 * 그대로 쓴다. 이름을 찾기 전에는 카드를 띄우지 않는다 — 주소로 떴다가 이름으로 바뀌면 카드가 둘로 갈라져 보인다.
 */

import { useSyncExternalStore } from 'react';
import { connectionAddress, subscribeConnections } from '../shared/connections.ts';
import { noteConnectedEntity } from '../shared/connectedDevices.ts';
import { topCamRoot } from './TopCamView.tsx';

export const TWIN_WATCH_MS = 10_000;
const PROBE_TIMEOUT_MS = 4_000;
const NAME_URL = '/video-records/host-name';

export type TwinFacts = {
  entityId: string;
  url: string;
  /** 이름을 어디서 얻었나 — Tailscale 에서 찾았나, 주소의 호스트를 그대로 썼나. */
  nameFrom: 'tailscale' | 'address';
  /** Unity 상공 카메라 서버인가(`/status` 가 답함), 그냥 웹 페이지인가. */
  kind: 'topcam' | 'page';
};

let facts: TwinFacts | null = null;
const listeners = new Set<() => void>();

function setFacts(next: TwinFacts | null): void {
  if (next?.entityId === facts?.entityId && next?.url === facts?.url && next?.kind === facts?.kind && next?.nameFrom === facts?.nameFrom) return;
  facts = next;
  for (const listener of listeners) listener();
}

/** 지금 3D 가상환경 장비 — 한 번도 안 닿았으면 null. */
export function twinFacts(): TwinFacts | null {
  return facts;
}

export function useTwinFacts(): TwinFacts | null {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; }, twinFacts, twinFacts);
}

/** 이 카드가 3D 가상환경 PC 인가. */
export function isTwinDevice(entityId: string): boolean {
  return facts !== null && facts.entityId === entityId;
}

function hostOf(url: string): string | null {
  try {
    const host = new URL(url).hostname;
    return host === '' ? null : host;
  } catch {
    return null;
  }
}

const names = new Map<string, { name: string; from: TwinFacts['nameFrom'] }>();

/** 그 호스트의 PC 이름. 한 번 찾은 것은 다시 묻지 않는다(주소가 바뀌면 새로 묻는다). */
async function nameOf(host: string): Promise<{ name: string; from: TwinFacts['nameFrom'] }> {
  const known = names.get(host);
  if (known !== undefined) return known;
  let found: { name: string; from: TwinFacts['nameFrom'] } = { name: host, from: 'address' };
  try {
    const response = await fetch(`${NAME_URL}?host=${encodeURIComponent(host)}`, { cache: 'no-store' });
    const body = response.ok ? await response.json() as { name?: unknown } : null;
    if (typeof body?.name === 'string' && body.name.trim() !== '') found = { name: body.name.trim(), from: 'tailscale' };
  } catch {
    // 창구가 없다(단독 빌드) — 주소를 이름으로 쓴다
  }
  // 창구가 답하지 않은 것은 기억하지 않는다 — 개발 서버가 늦게 뜨면 다음 주기에 다시 묻는다.
  if (found.from === 'tailscale') names.set(host, found);
  return found;
}

async function reach(url: string): Promise<TwinFacts['kind'] | null> {
  const timed = (input: string, init: RequestInit) => {
    const ctrl = new AbortController();
    const cut = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    return fetch(input, { ...init, signal: ctrl.signal, cache: 'no-store' }).finally(() => clearTimeout(cut));
  };
  try {
    const response = await timed(`${topCamRoot(url)}/status`, {});
    const body = response.ok ? await response.json() as { cameras?: unknown } : null;
    if (Array.isArray(body?.cameras)) return 'topcam';
  } catch {
    // 상공 카메라 서버가 아니다 — 페이지가 닿는지만 본다
  }
  try {
    await timed(url, { mode: 'no-cors' });
    return 'page';
  } catch {
    return null;
  }
}

async function probeOnce(): Promise<void> {
  const url = connectionAddress('virtual-3d', 'base').trim();
  const host = /^https?:\/\//i.test(url) ? hostOf(url) : null;
  if (host === null) { setFacts(null); return; }
  const kind = await reach(url);
  if (kind === null) return; // 안 닿으면 적지 않는다 — 창(30초)이 지나면 카드가 내려간다
  const { name, from } = await nameOf(host);
  // 기다리는 사이에 주소가 바뀌었으면 버린다
  if (connectionAddress('virtual-3d', 'base').trim() !== url) return;
  setFacts({ entityId: name, url, nameFrom: from, kind });
  noteConnectedEntity(name, 'twin');
}

/** **주기 감시.** 10초마다 한 번, 주소가 바뀌면 곧바로 한 번. 앞 요청이 안 끝났으면 거른다. */
export function startTwinWatch(intervalMs = TWIN_WATCH_MS): () => void {
  let busy = false;
  const tick = () => {
    if (busy) return;
    busy = true;
    void probeOnce().finally(() => { busy = false; });
  };
  let last = connectionAddress('virtual-3d', 'base');
  const unsubscribe = subscribeConnections(() => {
    const now = connectionAddress('virtual-3d', 'base');
    if (now === last) return;
    last = now;
    tick();
  });
  tick();
  const timer = setInterval(tick, intervalMs);
  return () => { clearInterval(timer); unsubscribe(); };
}
