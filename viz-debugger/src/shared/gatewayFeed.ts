/**
 * src/shared/gatewayFeed.ts (261001 신설 — 백엔드 서버 연결 확인 · 서버 카드)
 *
 * **게이트웨이 소켓으로 무엇이 들어왔나.** 연결 관리의 「확인」과 하드웨어 패널의 서버 카드가 읽는다.
 *
 * 260929 실측 — 백엔드 `/state` 에 붙었고 서버도 「보냈다」고 했는데 **화면에는 아무것도 안 떴다.** 하드웨어 카드는
 * MQTT 로 붙은 장비만 그리게 되어 있었고(목 게이트웨이의 가짜 함대를 걷어내려던 가름 — `registry.ts`), 서버 연결을
 * 확인할 자리도 없어서 「연결은 되는데 화면만 빔」의 원인을 화면 안에서 가를 수 없었다.
 *
 * 받는 쪽(`tabs/data/index.ts`)이 밀어 넣고 그리는 쪽은 여기만 읽는다 — `connectedDevices.ts` 와 같은 모양이다
 * (그리는 쪽이 대시보드 저장소를 직접 읽으면 단독 빌드에 딸려 들어간다).
 *
 * ## 서버가 준 장비인지 어떻게 아나 — **봉투가 스스로 밝힌다**
 *
 * 백엔드 `/state` 는 원래 메시지를 `payload` 에 **통째로** 싣는다(`vz-media-interface.md` §15-1) — 공통 헤더
 * (`schema_version` · `source_id` · `node_id` · `zone_id`)가 그 안에 있다. 목 게이트웨이의 가짜 함대는 그 헤더가 없다.
 * 주소로 가르지 않는다(`deviceIdentity.ts` 와 같은 규칙).
 */

import { useSyncExternalStore } from 'react';

export type GatewaySocketState = 'connecting' | 'open' | 'reconnecting' | 'closed';

export type GatewayFeed = {
  socket: GatewaySocketState;
  /** 붙은 뒤 받은 봉투 수. 다시 붙으면 0 부터. */
  count: number;
  /** 마지막으로 받은 시각(ms). */
  lastAtMs: number | null;
  /** 서버가 밝힌 장비 — 개체 id → 마지막 수신(ms). 목 함대는 안 든다. */
  serverEntities: Readonly<Record<string, number>>;
};

const EMPTY: GatewayFeed = { socket: 'closed', count: 0, lastAtMs: null, serverEntities: {} };
let feed: GatewayFeed = EMPTY;
const listeners = new Set<() => void>();

function commit(next: GatewayFeed): void {
  feed = next;
  for (const listener of listeners) listener();
}

/** 이 본문이 공통 헤더를 실었는가 — 실물 장비(서버 경유)가 보낸 메시지다. */
export function selfIntroduced(body: unknown): boolean {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return false;
  const record = body as Record<string, unknown>;
  return typeof record.schema_version === 'string' && typeof record.source_id === 'string' && record.source_id !== '';
}

/** 봉투 한 건. 받는 쪽이 부른다. 1초 안에 같은 장비가 또 오면 다시 그리지 않는다(1Hz 상태). */
export function noteGatewayEnvelope(entity: string, body: unknown, nowMs = Date.now()): void {
  const server = selfIntroduced(body) && entity !== '';
  const previous = server ? feed.serverEntities[entity] : undefined;
  const quiet = feed.lastAtMs !== null && nowMs - feed.lastAtMs < 1000 && (!server || (previous !== undefined && nowMs - previous < 1000));
  const next: GatewayFeed = {
    ...feed,
    count: feed.count + 1,
    lastAtMs: nowMs,
    serverEntities: server ? { ...feed.serverEntities, [entity]: nowMs } : feed.serverEntities,
  };
  if (quiet) { feed = next; return; }
  commit(next);
}

/** 소켓 상태. 다시 붙으면(열림) 셈을 새로 시작한다. */
export function noteGatewaySocket(state: GatewaySocketState): void {
  if (state === feed.socket) return;
  commit(state === 'open' ? { ...feed, socket: state, count: 0 } : { ...feed, socket: state });
}

export function gatewayFeed(): GatewayFeed {
  return feed;
}

export function subscribeGatewayFeed(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useGatewayFeed(): GatewayFeed {
  return useSyncExternalStore(subscribeGatewayFeed, gatewayFeed, gatewayFeed);
}

/** 검사가 부른다. */
export function resetGatewayFeed(): void {
  commit(EMPTY);
}

/** 주소를 화면에 적을 때 토큰을 가린다 — 서버 로그와 같은 규칙(`token=***`). */
export function maskToken(url: string): string {
  return url.replace(/(token=)[^&\s]*/g, '$1***');
}
