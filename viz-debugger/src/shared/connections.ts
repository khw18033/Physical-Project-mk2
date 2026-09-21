/**
 * src/shared/connections.ts (260904 — `VZ-C-07` 연결 대상 설정 · 추가 개선 3)
 *
 * **접속 주소의 런타임 원천.** 지금까지 주소는 빌드 시점 환경변수였다.
 *
 * ```
 * transport/index.ts   VITE_GATEWAY_WS / VITE_GATEWAY_HTTP
 * stt/SttClient.ts     (STT 주소 — 그 파일 안에서만 읽는다)
 * ```
 *
 * 바꾸려면 다시 빌드해야 했다. 현장에서 게이트웨이·제어 노드 IP가 바뀔 때마다 빌드할 수는
 * 없다. 그래서 **환경변수를 기본값으로 두고 화면에서 덮어쓴다.**
 *
 * ## 지켜야 하는 것 넷 (지시서 §3)
 *
 * 1. **출입구는 여전히 하나다.** 이 모듈은 주소만 들고 있고 연결을 만들지 않는다.
 *    `getTransport()` 싱글턴은 그대로이고, 주소가 바뀌면 **끊고 다시 붙는다**(새 인스턴스를
 *    만들지 않는다 — 만들면 구독이 통째로 날아간다). 여기저기서 URL 을 읽게 하면
 *    `verify:one-gateway` 가 무너진다.
 * 2. **대상 목록이 한 곳에 있다.** 화면은 이 목록을 그린다 — 손으로 넷을 적지 않는다.
 * 3. **새로고침에 살아남는다.** `localStorage` 이고 **키는 앱 전역**이다(임무별이 아니다 —
 *    접속 주소는 임무의 성질이 아니라 이 설치본의 성질이다). 저장소가 막혔으면 `try/catch`
 *    로 기본값으로 조용히 진행한다.
 * 4. **되돌아올 길이 있다.** 틀린 주소를 넣으면 아무 데도 못 붙으므로 기본값 복원이 필요하다.
 *
 * ## 상단의 `conn` 배지와 섞지 않는다
 *
 * 배지는 **상태**(지금 붙어 있나)이고 이 모듈은 **설정**(어디에 붙을 것인가)이다.
 * 둘을 한 곳에 두면 「연결 안 됨」이 주소가 틀린 것인지 서버가 죽은 것인지 알 수 없어진다.
 *
 * ## STT·생성의 기본값은 여기서 읽지 않는다
 *
 * STT 주소를 아는 곳은 `src/stt/` 뿐이어야 하고(`verify:no-stt`), 생성 주소를 아는 곳은
 * `src/generate/` 뿐이어야 한다(`verify:gen-port`) — 면이 둘이 되면 안 된다.
 * 그래서 각자 자기 환경변수를 읽어 `registerConnectionDefault()` 로 **기본값만 심는다.**
 * 여기 적힌 값은 그 전에 화면이 그릴 대비값이다.
 */

import { useSyncExternalStore } from 'react';

export type ConnectionTargetId = 'gateway' | 'stt' | 'generate' | 'physical' | 'detect' | 'autodrive' | 'autodrive-ai' | 'capability' | 'control-node' | 'digital-twin';

/**
 * ## 260918 — 여기 담는 것은 **글자가 아니라 사전 키**다
 *
 * 2단계가 `ConnectionsPanel` 의 문구를 사전으로 옮겼는데, **그 판이 그리는 이름은 이 파일에
 * 있었다.** 그래서 영문 화면에서 판 제목은 영어인데 대상 이름 아홉이 한국어로 남았다 —
 * 사람이 화면을 보고 260917 에 찾아냈다(「연결 관리 판이 한국어로 보인다」).
 *
 * **여기서 `t()` 를 부를 수는 없다.** `CONNECTION_TARGETS` 는 모듈 최상위 상수라 `import`
 * 시점에 한 번 평가된다 — 그때 부른 `t()` 는 그 순간의 언어로 굳고 언어를 바꿔도 안 변한다
 * (1단계 보고서 §3 ①). 그래서 **키를 담고 읽는 자리에서 푼다.** 이름을 `…Key` 로 두는 것은
 * 다음 사람이 여기에 한글을 도로 적지 않게 하려는 것이다.
 */
export type ConnectionField = {
  key: string;
  /** 칸 이름의 **사전 키**. 글자가 아니다. */
  labelKey: string;
  /** 기본값. 환경변수가 있으면 그것이 이긴다(아래 `seed`). */
  fallback: string;
};

export type ConnectionTarget = {
  id: ConnectionTargetId;
  /** 대상 이름의 **사전 키**. 글자가 아니다. */
  labelKey: string;
  /**
   * 무엇을 위해 붙는가 — **사전 키**. 화면이 풀어서 적는다.
   *
   * **없어도 된다** (260913 지시). 늘 쓰는 대상(로봇·객체 탐지)은 매번 읽을 문장이 아니라
   * 빼 뒀다 — 자리가 그만큼 줄고, 주소 칸이 먼저 눈에 들어온다.
   */
  whatKey?: string;
  fields: readonly ConnectionField[];
  /**
   * 지금 **실제로 붙는가.** false 면 주소를 넣어도 붙을 곳이 없다 — 자리만 두고
   * 「연결 예정」으로 표시한다. 없는 것을 있는 척하지 않는다(다른 자리표시와 같은 규칙).
   */
  live: boolean;
  /** `live: false` 의 사유 — **사전 키**. 있는 것만 적는다. */
  pendingKey?: string;
};

/** **대상 목록의 유일한 원천.** 화면은 이것을 그린다. */
/**
 * **대상 목록의 유일한 원천.** 화면은 이것을 그린다.
 *
 * **순서가 화면의 순서다** (260912 지시). 지금 실제로 쓰는 둘 — 로봇과 객체 탐지 — 이
 * 맨 위다. 시연 직전에 확인해야 하는 것이 그 둘이고, 아래로 내려가면 스크롤한 만큼
 * 늦게 눈에 들어온다. 나머지는 쓰던 순서 그대로 뒤에 선다.
 */
export const CONNECTION_TARGETS: readonly ConnectionTarget[] = [
  {
    id: 'physical',
    labelKey: 'conn.target.physical',
    live: true,
    // **주소를 여기 적지 않는다.** stt·generate 는 대비값을 여기 두지만, 로봇은
    // 주소·토픽·장비 id 가 한 곳에만 있어야 한다는 제약이 더 세다(`verify:physical-port`) —
    // 브로커를 옮기거나 중앙 서버 경유로 바꿀 때 한쪽만 고쳐지면 화면이 「붙었다」고
    // 말하면서 아무것도 못 받는다. 기본값은 `src/physical/PhysicalClient.ts` 가 심는다.
    fields: [{ key: 'ws', labelKey: 'conn.field.ws', fallback: '' }],
  },
  {
    id: 'detect',
    labelKey: 'conn.target.detect',
    live: true,
    // 설명도 자리표시 문구도 없다 (260913 지시). 주소가 비었을 때 무엇을 할 수 있는지는
    // 아래 「상태」 줄이 그때그때 말한다 — 늘 떠 있는 문장이 아니라 그 상태의 사유다.
    //
    // **주소를 여기 적지 않는다** (260914). 로봇과 같다 — 기본값(Tailscale)은
    // `src/detect/DetectClient.ts` 가 `src/detect/presets.ts` 에서 꺼내 심는다.
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: '' }],
  },
  {
    // 260915 — 자율주행 편. 문 찾기 시연(`physical`, pi7)과 **기계도 브로커도 다르다.**
    // 주소는 여기 적지 않는다 — 기본값은 `src/physical/NavClient.ts` 가 심는다(로봇과 같은 규칙).
    id: 'autodrive',
    labelKey: 'conn.target.autodrive',
    whatKey: 'conn.target.autodrive.what',
    live: true,
    fields: [{ key: 'ws', labelKey: 'conn.field.ws', fallback: '' }],
  },
  {
    // 260915 — 자율주행 편의 AI 서버(로봇 앞 카메라). 문 찾기 시연의 객체 탐지(`detect`)와 **다른 서버**다.
    // 주소는 여기 적지 않는다 — 기본값은 `src/autodrive/aiClient.ts` 가 심는다.
    id: 'autodrive-ai',
    labelKey: 'conn.target.autodriveAi',
    whatKey: 'conn.target.autodriveAi.what',
    live: true,
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: '' }],
  },
  {
    // 260920 — 기능 상태 서비스(`perception-framework/tools/status_ui`). **실제 배치는 k3s 안이라
    // 주소를 우리가 미리 못 적는다** — 여기서 넣는다. 기본값(검토용 로컬)은
    // `src/capability/CapabilityClient.ts` 가 심는다(로봇·탐지와 같은 규칙).
    id: 'capability',
    labelKey: 'conn.target.capability',
    whatKey: 'conn.target.capability.what',
    live: true,
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: '' }],
  },
  {
    id: 'gateway',
    labelKey: 'conn.target.gateway',
    whatKey: 'conn.target.gateway.what',
    live: true,
    fields: [
      { key: 'ws', labelKey: 'conn.field.ws', fallback: 'ws://127.0.0.1:8790' },
      { key: 'http', labelKey: 'conn.field.http', fallback: 'http://127.0.0.1:8790' },
      /**
       * **구역 식별자.** 주소가 아닌 칸이 여기 있는 이유는, 이 값이 **붙는 게이트웨이를
       * 따라가야** 하기 때문이다 (260921).
       *
       * 목 게이트웨이(8790)는 `zone-503` 으로 발행하고 백엔드 `/state` 는 `zoneA` 로 발행한다.
       * 상수로 두면 한쪽에 붙을 때 반드시 다른 쪽이 **연결은 되고 화면만 비는** 상태가 된다 —
       * 구독 selector 의 `node` 축이 안 맞아 매칭이 0건이 되기 때문이고, 영상 쪽의
       * 「연결됨인데 영상만 안 옴」과 같은 종류의 진단하기 나쁜 실패다.
       *
       * 그래서 **주소와 한 묶음**으로 둔다. 주소를 바꾸는 사람이 구역도 같이 바꾼다.
       */
      { key: 'zone', labelKey: 'conn.field.zone', fallback: 'zone-503' },
    ],
  },
  {
    id: 'stt',
    labelKey: 'conn.target.stt',
    whatKey: 'conn.target.stt.what',
    live: true,
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: 'http://127.0.0.1:8801' }],
  },
  {
    id: 'generate',
    labelKey: 'conn.target.generate',
    whatKey: 'conn.target.generate.what',
    live: true,
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: 'http://127.0.0.1:8802' }],
  },
  {
    id: 'control-node',
    labelKey: 'conn.target.controlNode',
    whatKey: 'conn.target.controlNode.what',
    live: false,
    pendingKey: 'conn.target.controlNode.pending',
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: '' }],
  },
  {
    id: 'digital-twin',
    labelKey: 'conn.target.digitalTwin',
    whatKey: 'conn.target.digitalTwin.what',
    live: false,
    pendingKey: 'conn.target.digitalTwin.pending',
    fields: [{ key: 'base', labelKey: 'conn.field.base', fallback: '' }],
  },
];

/** `대상.칸` — 저장과 조회의 키. 화면도 이 함수로 키를 만든다. */
export function connectionKey(target: ConnectionTargetId, field: string): string {
  return `${target}.${field}`;
}

/**
 * 저장 칸. **앱 전역이다** — 임무별이 아니다. 판(v1)을 붙여 두어 모양이 바뀌면 옛 값을
 * 조용히 버릴 수 있게 한다(캔버스 구성과 같은 규칙).
 */
const STORAGE_KEY = 'viz.connections.v1';

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};

/** 기본값 — 환경변수가 있으면 그것이 이긴다. 사용자가 덮어쓰기 전까지 이 값이 쓰인다. */
const defaults = new Map<string, string>();
for (const target of CONNECTION_TARGETS) {
  for (const field of target.fields) defaults.set(connectionKey(target.id, field.key), field.fallback);
}
defaults.set('gateway.ws', env.VITE_GATEWAY_WS ?? defaults.get('gateway.ws')!);
defaults.set('gateway.http', env.VITE_GATEWAY_HTTP ?? defaults.get('gateway.http')!);

/**
 * 자기 환경변수를 읽는 모듈이 **기본값만** 심는다. 사용자가 덮어쓴 값은 건드리지 않는다.
 * `src/stt/` 가 이것을 쓴다 — STT 주소를 아는 면은 그쪽 하나여야 하기 때문이다.
 */
export function registerConnectionDefault(target: ConnectionTargetId, field: string, value: string): void {
  const key = connectionKey(target, field);
  if (defaults.get(key) === value) return;
  defaults.set(key, value);
  notify();
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // 사파리 비공개 창처럼 **접근 자체가 던지는** 경우가 있다.
    return null;
  }
}

function readOverrides(): Record<string, string> {
  try {
    const raw = storage()?.getItem(STORAGE_KEY) ?? null;
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const result: Record<string, string> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'string' && value.trim() !== '') result[key] = value.trim();
    }
    return result;
  } catch {
    // 판이 다르거나 깨졌으면 버린다. 기본값으로 조용히 진행한다 — 여기서 던지면 앱이 안 뜬다.
    return {};
  }
}

let overrides: Record<string, string> = readOverrides();
const listeners = new Set<() => void>();
/** `useSyncExternalStore` 는 같은 참조를 돌려받아야 다시 그리지 않는다. */
let snapshot: Readonly<Record<string, string>> = merged();

function merged(): Readonly<Record<string, string>> {
  const result: Record<string, string> = {};
  for (const [key, value] of defaults) result[key] = value;
  for (const [key, value] of Object.entries(overrides)) result[key] = value;
  return result;
}

function notify(): void {
  snapshot = merged();
  for (const listener of listeners) listener();
}

/** 이 설치본이 지금 쓰는 주소 전부. 기본값 위에 사용자 값이 얹힌 결과다. */
export function connectionAddresses(): Readonly<Record<string, string>> {
  return snapshot;
}

/** 한 칸. 없는 키면 빈 문자열이다 — 던지지 않는다. */
export function connectionAddress(target: ConnectionTargetId, field: string): string {
  return snapshot[connectionKey(target, field)] ?? '';
}

/** 사용자가 덮어쓴 것만. 화면이 「기본값과 다름」을 표시하는 데 쓴다. */
export function connectionOverrides(): Readonly<Record<string, string>> {
  return overrides;
}

/** 저장이 되는 창인가. 안 되면 화면이 그 사실을 숨기지 않는다. */
export function connectionsWritable(): boolean {
  return storage() !== null;
}

/**
 * 주소를 바꾼다. 기본값과 같은 칸은 저장하지 않는다 — 나중에 기본값이 바뀌면 따라가야 한다.
 * @returns 저장까지 됐는가. 저장소가 막혀 있으면 이번 세션에만 적용된다(false).
 */
export function saveConnections(next: Readonly<Record<string, string>>): boolean {
  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(next)) {
    const trimmed = value.trim();
    if (trimmed === '' || trimmed === defaults.get(key)) continue;
    cleaned[key] = trimmed;
  }
  overrides = cleaned;
  notify();
  try {
    const store = storage();
    if (store === null) return false;
    if (Object.keys(cleaned).length === 0) store.removeItem(STORAGE_KEY);
    else store.setItem(STORAGE_KEY, JSON.stringify(cleaned));
    return true;
  } catch {
    return false;
  }
}

/** **되돌아올 길.** 틀린 주소를 넣으면 아무 데도 못 붙는다 — 이 길이 없으면 갇힌다. */
export function resetConnections(): void {
  saveConnections({});
}

export function subscribeConnections(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useConnections(): Readonly<Record<string, string>> {
  return useSyncExternalStore(subscribeConnections, connectionAddresses, connectionAddresses);
}
