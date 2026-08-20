/**
 * src/data/hooks.ts
 *
 * React 바인딩. `useSyncExternalStore`만 쓰고 상태 관리 라이브러리는 도입하지 않는다.
 *
 * 여기서 리렌더가 결정되므로 규칙이 하나 있다 —
 * **store가 알릴 때만 리렌더한다.** store는 병합 창(100ms)에서만 알리므로,
 * 20Hz로 들어오는 값이 20Hz 리렌더가 되지 않는다.
 */

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { getTransport } from '../transport/index.ts';
import type { ConnectionStatus, RoleInfo } from '../transport/index.ts';
import { store } from './index.ts';
import { commandTracker, type TrackedCommand } from './commands.ts';
import type { EntityRecord } from './store.ts';
import { ZoneSummaryFeed, type ZoneSummary } from './summary.ts';

/** 구독 결과 전체. 병합 창이 닫힐 때만 새 스냅샷이 나온다. */
export function useEntities(): ReadonlyMap<string, EntityRecord> {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

/**
 * 발행한 명령의 단계 이력 (VZ-O-02).
 * store가 아니라 추적기를 보는 이유 — store는 채널별 **마지막 값**만 갖는다.
 * 명령 결과는 네 단계가 각각 의미를 갖는 이산 이벤트라 마지막 값만으로는 부족하다.
 */
export function useCommands(): readonly TrackedCommand[] {
  return useSyncExternalStore(commandTracker.subscribe, commandTracker.getSnapshot, commandTracker.getSnapshot);
}

export function useConnectionStatus(): ConnectionStatus {
  const transport = getTransport();
  const [status, setStatus] = useState<ConnectionStatus>(() => transport.getStatus());
  useEffect(() => transport.onStatus(setStatus), [transport]);
  return status;
}

/** VZ-C-04 — 역할과 그 적용 범위. scope는 현 단계 ['*'] 고정이지만 실제로 받아 온다. */
export function useRole(): RoleInfo | null {
  const transport = getTransport();
  const [role, setRole] = useState<RoleInfo | null>(null);
  const status = useConnectionStatus();
  useEffect(() => {
    if (status.state !== 'open') return;
    let alive = true;
    void transport.fetchRole().then((r) => {
      if (alive) setRole(r);
    });
    return () => {
      alive = false;
    };
  }, [transport, status.state]);
  return role;
}

/** 구역 요약 — 5초 주기(단, 오프라인 전이 시 즉시). */
export function useZoneSummary(zoneId: string | null): ZoneSummary {
  const feed = useMemo(() => new ZoneSummaryFeed(store, zoneId), [zoneId]);
  return useSyncExternalStore(feed.subscribe, feed.getSnapshot, feed.getSnapshot);
}

/**
 * 리렌더 실측 (검증 항목 2).
 * 렌더될 때마다 세고, 최근 1초 동안의 렌더 횟수를 돌려준다.
 * Profiler를 열지 않고도 "초당 10회를 넘지 않는가"를 화면에서 바로 볼 수 있어야 한다.
 */
export function useRenderRate(): { total: number; perSecond: number } {
  const marks = useRef<number[]>([]);
  const total = useRef(0);

  total.current += 1;
  const now = performance.now();
  marks.current.push(now);
  while (marks.current.length > 0 && now - marks.current[0] > 1000) marks.current.shift();

  return { total: total.current, perSecond: marks.current.length };
}
