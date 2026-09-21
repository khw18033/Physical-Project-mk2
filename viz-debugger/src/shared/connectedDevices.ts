/**
 * src/shared/connectedDevices.ts (260921 신설 — 드론 연결 · 하드웨어 카드)
 *
 * **지금 값이 흐르고 있는 장비 목록.** 임무가 무엇이든 상관없다.
 *
 * 하드웨어 카드는 지금까지 **대본의 배역**(`cast`)이었다. 그래서 대본에 안 적힌 장비는
 * 붙어 있어도 안 보였다 — 드론이 정확히 그 경우다. 의도는 원래 그게 아니었다:
 * **연결이 유지되는 장비는 다 뜨고, 그중 쓸 것만 끌어다 쓴다.**
 *
 * ## 왜 저장소를 따로 두나 — `tabs/` 를 못 부르기 때문이다
 *
 * 값은 두 길로 들어온다.
 *
 *   백엔드 `/state`   계약 봉투 — `tabs/data/` 가 받는다 (드론·앞으로의 Go1)
 *   MQTT 장비 상태    구역 상태 토픽 — `physical/deviceState.ts` 가 받는다 (지금의 Go1)
 *
 * **토픽 문자열은 여기 안 적는다.** 로봇을 아는 면은 `src/physical/` 하나여야 하고
 * (`verify:physical-port`), 주석이라도 적으면 그 규칙이 한 칸 느슨해진다.
 *
 * 카드를 그리는 쪽(`main.tsx`·`registry.ts`)이 앞엣것을 직접 읽으면 **단독 빌드에 대시보드
 * 데이터 계층이 딸려 들어간다** — `verify:standalone` 이 그것을 막는다(측정축 D 가 오염된다).
 *
 * 그래서 **방향을 뒤집는다.** 받는 쪽이 여기에 밀어 넣고, 그리는 쪽은 여기만 읽는다.
 * `registerConnectionDefault` 가 주소에 대해 하는 일과 같은 모양이다.
 *
 * 단독 빌드에서는 `tabs/` 가 없으므로 MQTT 쪽만 밀어 넣는다 — 그 빌드에 게이트웨이가
 * 없으니 그것이 맞는 결과다. 빈 목록이면 카드는 대본 배역만 그린다(전과 같다).
 *
 * ## 「연결됨」은 시간이 지나면 거짓이 된다
 *
 * 한 번 본 장비를 영영 목록에 두면 **꺼진 장비가 계속 떠 있다.** 무대에서 그 카드를 끌어다
 * 배정하면 아무 일도 안 일어나고, 왜인지 알 수 없다. 그래서 창을 둔다 — 창 밖의 장비는
 * 목록에서 빠진다. 값을 지어내 살려 두지 않는다.
 */

import { useSyncExternalStore } from 'react';

/**
 * 이 시간 동안 아무것도 안 오면 **연결이 유지되는 것으로 안 본다.**
 *
 * 가장 느린 것에 맞춘다: 드론 `status` 가 10초 주기이고(계약 §3-1) Go1 상태가 5초다.
 * 그 세 배가 30초다 — `STALE_AFTER_MS` 가 「주기의 세 배」로 잡힌 것과 같은 셈이다.
 * 짧게 잡으면 한 건 놓칠 때마다 카드가 사라졌다 나타난다.
 */
export const CONNECTED_WINDOW_MS = 30_000;

/** 어느 길로 들어왔는가. 화면이 「무엇을 보고 있는지」를 감추지 않는다. */
export type ConnectedSource = 'state' | 'mqtt';

export type ConnectedDevice = {
  entityId: string;
  source: ConnectedSource;
  lastSeenMs: number;
};

let devices: Readonly<Record<string, ConnectedDevice>> = {};
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * 값이 한 건 들어왔다. **받는 쪽이 부른다** — 그리는 쪽은 이 함수를 모른다.
 *
 * 같은 장비가 두 길로 들어오면 **나중 것이 이긴다.** Go1 이 `/state` 로 옮겨 가는 동안
 * 두 길이 겹치는 기간이 있고(지시 — 「Go1 도 나중엔 서버 연결로」), 그때 카드가 둘로
 * 갈라지면 안 된다. id 가 같으면 한 장비다.
 */
export function noteConnectedEntity(entityId: string, source: ConnectedSource, nowMs = Date.now()): void {
  if (entityId === '') return;
  const previous = devices[entityId];
  // 같은 길로 1초 안에 또 오면 다시 그리지 않는다 — 1Hz 상태에 매번 리렌더를 걸 이유가 없다.
  if (previous !== undefined && previous.source === source && nowMs - previous.lastSeenMs < 1_000) {
    devices = { ...devices, [entityId]: { ...previous, lastSeenMs: nowMs } };
    return;
  }
  devices = { ...devices, [entityId]: { entityId, source, lastSeenMs: nowMs } };
  notify();
}

/** 지금 연결이 유지되는 장비들. **창 밖은 빠진다.** */
export function connectedDevices(nowMs = Date.now()): readonly ConnectedDevice[] {
  return Object.values(devices)
    .filter((device) => nowMs - device.lastSeenMs <= CONNECTED_WINDOW_MS)
    .sort((a, b) => a.entityId.localeCompare(b.entityId));
}

/** 한 장비. 창 밖이면 `null` — 「아까 봤다」를 「지금 붙어 있다」로 적지 않는다. */
export function connectedDevice(entityId: string, nowMs = Date.now()): ConnectedDevice | null {
  const found = devices[entityId];
  if (found === undefined) return null;
  return nowMs - found.lastSeenMs <= CONNECTED_WINDOW_MS ? found : null;
}

export function subscribeConnectedDevices(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/**
 * **창이 닫히는 것은 값이 안 올 때 일어난다** — 그때는 아무도 이 저장소를 안 건드리므로
 * 구독자가 저절로 깨지 않는다. 그래서 화면이 주기로 다시 그리게 깨워 준다.
 *
 * 창(30초)의 1/6 이면 카드가 사라지는 시점이 최대 5초 늦는다. 그 정도면 무대에서 문제가
 * 안 되고, 1초마다 전부 다시 그리는 것보다 훨씬 싸다.
 */
const SWEEP_MS = 5_000;
let sweep: ReturnType<typeof setInterval> | null = null;

export function startConnectedSweep(): () => void {
  if (sweep !== null) return () => undefined;
  sweep = setInterval(() => {
    const now = Date.now();
    // 창 밖으로 나간 것이 **생겼을 때만** 다시 그린다.
    const expired = Object.values(devices).some((d) => now - d.lastSeenMs > CONNECTED_WINDOW_MS);
    if (expired) notify();
  }, SWEEP_MS);
  return () => { if (sweep !== null) { clearInterval(sweep); sweep = null; } };
}

export function useConnectedDevices(): readonly ConnectedDevice[] {
  // `getSnapshot` 은 **같은 참조**를 돌려줘야 한다 — 매번 새 배열을 만들면 무한히 다시 그린다.
  return useSyncExternalStore(subscribeConnectedDevices, snapshot, snapshot);
}

let cached: readonly ConnectedDevice[] = [];
let cachedAtMs = 0;
/** 창 판정이 시간에 달렸으므로 캐시를 짧게 둔다 — 같은 틱 안에서는 같은 참조다. */
function snapshot(): readonly ConnectedDevice[] {
  const now = Date.now();
  if (now - cachedAtMs < 500) return cached;
  const next = connectedDevices(now);
  // 내용이 같으면 **참조를 안 바꾼다.**
  if (next.length === cached.length && next.every((d, i) => d.entityId === cached[i]?.entityId)) {
    cachedAtMs = now;
    return cached;
  }
  cached = next;
  cachedAtMs = now;
  return cached;
}

/** 검사와 화면 전환이 쓴다. 저장소를 비운다. */
export function resetConnectedDevices(): void {
  devices = {};
  cached = [];
  cachedAtMs = 0;
  notify();
}
