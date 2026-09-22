/**
 * src/shared/deviceTelemetry.ts (260922 신설 — 드론 카드 안을 채운다)
 *
 * **장비가 보고한 상태 항목.** 카드와 상세 보기가 그릴 줄들이다.
 *
 * `connectedDevices.ts` 가 「지금 값이 흐르는가」를 들고 있고, 이 파일은 **그 값이 무엇이었나**를
 * 들고 있다. 둘을 한 저장소에 합치지 않는 이유는 수명이 다르기 때문이다 — 카드가 떠 있어야
 * 하는 조건(30초 창)과, 마지막으로 본 값을 얼마나 오래 적어 둘 것인가는 같은 물음이 아니다.
 *
 * ## 왜 또 `shared/` 인가 — `tabs/` 를 못 부르기 때문이다
 *
 * 드론 상태는 백엔드 `/state` 로 온다(`verify:drone-via-state` — 경로가 둘이면 「어느 쪽이
 * 진짜냐」가 생긴다). 그런데 그것을 그릴 `DeviceFacts`·`HardwareLink` 는 단독 빌드에도 들어
 * 있고, 단독 빌드는 `tabs/` 를 끌어오면 안 된다(`verify:standalone` — 측정축 D 가 오염된다).
 *
 * 그래서 방향을 뒤집는다. **받는 쪽이 여기에 밀어 넣고, 그리는 쪽은 여기만 읽는다.**
 * `connectedDevices.ts` 와 같은 모양이고 같은 이유다.
 *
 * ## 줄에 글자를 담지 않는다 — **사전 키**다
 *
 * 칸 이름을 글자로 담으면 **밀어 넣은 순간의 언어로 굳는다.** 언어를 바꿔도 이 판만 옛
 * 언어로 남는다(`CONNECTION_TARGETS` 가 `labelKey` 를 든 것과 같은 이유 — 260918).
 *
 * 값은 다르다. `AUTO.LOITER`·`ON_GROUND`·`3D` 는 **장비가 보낸 규약 문자열**이고 번역하지
 * 않는다 — 번역하면 계약 문서와 화면을 대조할 수 없다. 참/거짓처럼 낱말이어야 하는 것만
 * `valueKey` 로 키를 준다.
 *
 * ## 안 온 것은 줄을 안 만든다
 *
 * 채우는 쪽(`stateRows.ts`)이 `null` 인 필드를 아예 안 담는다. FC 링크가 없으면 계약상
 * `battery`·`flight`·`gps`·`attitude`·`altitude` 가 전부 `null` 이고(계약 §7-1), 그때 빈 줄
 * 스무 개를 그리는 것보다 **`fc_link ✕` 한 줄이 이유를 말하는 편**이 낫다.
 */

import { useSyncExternalStore } from 'react';

/** 화면에 그릴 줄 하나. **글자가 아니라 키다**(위 주석). */
export type TelemetryRow = {
  /**
   * 칸 이름의 **사전 키**. 표에 없는 이름(장비가 새로 보내기 시작한 필드)이면 `null` 이고
   * `rawLabel` 을 쓴다 — 없는 키를 지어 넣으면 화면에 키 문자열이 그대로 뜬다.
   */
  labelKey: string | null;
  /** 사전에 없는 이름을 **그대로**. 번역할 수 없는 것을 번역된 척하지 않는다. */
  rawLabel?: string;
  /**
   * 값. 장비가 보낸 규약 문자열이거나 숫자+단위다. **번역하지 않는다.**
   * `valueKey` 가 있으면 그쪽이 이긴다.
   */
  value: string;
  /** 값도 낱말이어야 할 때(참/거짓)의 **사전 키**. */
  valueKey?: string;
  /**
   * 이 표본의 나이(초). 계약이 묶음마다 `age_s` 를 준다(§7-1).
   * **`null` 은 모른다**이고, 화면은 낡았을 때만 적는다 — 매 줄에 「0.2초 전」을 달면 읽을 수 없다.
   */
  ageS: number | null;
  /** 값을 그대로 믿으면 안 되는 줄. 화면이 그 사실을 적는다(계약이 의심한 값). */
  noteKey?: string;
  /** 카드 한 줄에도 나오는가. 상세 보기는 전부 그리고, 카드는 이것만 그린다. */
  onCard?: boolean;
};

export type DeviceTelemetry = {
  entityId: string;
  rows: readonly TelemetryRow[];
  /** 장비가 찍은 시각. **우리 시계가 아니다.** */
  timestamp: string | null;
  /** 우리가 받은 시각(ms). 신선도는 이것으로 잰다. */
  receivedAtMs: number;
  /** 무엇이 왜 보냈는가 — 계약 §7-1 의 `reason`. 그대로 적는다. */
  reason: string | null;
};

let devices: Readonly<Record<string, DeviceTelemetry>> = {};
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * 상태 보고 한 건이 들어왔다. **받는 쪽이 부른다** — 그리는 쪽은 이 함수를 모른다.
 *
 * **줄이 없으면 안 담는다.** 뜯을 것이 하나도 없는 채널(heartbeat 등)까지 담으면 마지막
 * 값이 빈 줄로 덮여, 방금까지 보이던 배터리가 이유 없이 사라진다.
 */
export function noteDeviceTelemetry(
  entityId: string,
  rows: readonly TelemetryRow[],
  meta: { timestamp?: string | null; reason?: string | null; atMs?: number } = {},
): void {
  if (entityId === '' || rows.length === 0) return;
  devices = {
    ...devices,
    [entityId]: {
      entityId,
      rows,
      timestamp: meta.timestamp ?? null,
      reason: meta.reason ?? null,
      receivedAtMs: meta.atMs ?? Date.now(),
    },
  };
  notify();
}

/** 한 장비의 마지막 보고. 없으면 `null` — 지어내지 않는다. */
export function deviceTelemetry(entityId: string): DeviceTelemetry | null {
  return devices[entityId] ?? null;
}

/**
 * **이 보고가 낡았는가.** 계약의 `state` 가 1Hz, `status` 가 10초다(§7-1·§7-2).
 * 그 셋배가 30초이고, 「붙어 있다」를 보는 창(`connectedDevices`)과 같은 값이다 — 두 판정이
 * 갈리면 카드는 떠 있는데 값만 낡은 상태가 설명 없이 생긴다.
 */
export const TELEMETRY_STALE_MS = 30_000;

export function isTelemetryStale(report: DeviceTelemetry, nowMs = Date.now()): boolean {
  return nowMs - report.receivedAtMs > TELEMETRY_STALE_MS;
}

export function subscribeDeviceTelemetry(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 그리는 쪽이 구독한다. 보고가 들어오면 다시 그린다. */
export function useDeviceTelemetry(): Readonly<Record<string, DeviceTelemetry>> {
  return useSyncExternalStore(subscribeDeviceTelemetry, snapshot, snapshot);
}

function snapshot(): Readonly<Record<string, DeviceTelemetry>> {
  return devices;
}

/** 검사와 화면 전환이 쓴다. 저장소를 비운다. */
export function resetDeviceTelemetry(): void {
  devices = {};
  notify();
}
