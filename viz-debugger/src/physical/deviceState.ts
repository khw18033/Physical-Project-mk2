/**
 * src/physical/deviceState.ts (260910 신설 — 장비 상태 구독)
 *
 * **로봇이 스스로 말하는 상태.** 명령 응답(uplink)과 다른 축이다.
 *
 *   uplink        「내가 시킨 명령이 어떻게 됐나」  — terminal/<id>/uplink
 *   device state  「장비가 지금 어떤가」            — zoneA/<type>/<id>/{status,state,heartbeat}
 *
 * 8/31 결정(`VZ-D-07`)은 registry 장비의 실측값을 **지어내지 않는다**였다. 그건 값을 줄
 * 채널이 없었기 때문이고, 이제 있다. 지어내지 않고 **온 것만** 적는다 — 안 온 필드는
 * 여전히 `null` 이고 화면은 그것을 자리표시로 그린다.
 *
 * ## 세 층이 여기서 갈린다
 *
 *   status.status        online | offline   — 파이가 보는 장비의 생사. 끊기면 LWT 가 offline
 *   status.link          ok | …             — **로봇 ↔ 파이 내부 링크.** 로봇 자신의 생사
 *   status.device_status ok | degraded | fault
 *
 * `ping` 은 단말까지만 증명한다고 적어 둔 자리의 답이 `link` 다 — 이제 로봇 줄을 채울 수 있다.
 */

import { useSyncExternalStore } from 'react';

/** 우리가 읽는 만큼. 스키마 전체를 옮기지 않는다 — 안 쓰는 필드를 옮기면 낡는다. */
export type DeviceState = {
  /** 하드웨어의 장비 id (`go1-001`). 화면 id 로 바꾸는 것은 `encode.ts` 의 표가 한다. */
  entityId: string;
  entityType: string;
  /** 파이가 보는 생사. 끊기면 LWT 가 `offline` 을 대신 넣는다. */
  online: boolean | null;
  /** `ok` · `degraded` · `fault`. */
  health: string | null;
  /** **로봇 ↔ 파이 내부 링크.** 로봇 자신이 붙어 있는가. */
  link: string | null;
  mode: string | null;
  inMission: boolean | null;
  batteryPct: number | null;
  position: { x: number; y: number; headingDeg: number } | null;
  speedMps: number | null;
  firmware: string | null;
  /** 마지막으로 무엇이든 받은 시각(ms). 신선도 판정에 쓴다. */
  lastSeenMs: number;
  /** 장비가 찍은 시각 문자열. 우리 시계가 아니라 저쪽 시계다. */
  timestamp: string | null;
  /** 목 장비인가 (`go1-sim`). 화면이 진짜와 섞지 않게 표시한다. */
  simulated: boolean;
};

/** 토픽 하나를 뜯는다. 우리 것이 아니면 null — 남의 토픽을 지어 해석하지 않는다. */
export function parseTopic(topic: string): { zone: string; entityType: string; entityId: string; channel: string } | null {
  const parts = topic.split('/');
  if (parts.length !== 4) return null;
  const [zone, entityType, entityId, channel] = parts;
  if (!zone || !entityType || !entityId) return null;
  if (channel !== 'status' && channel !== 'state' && channel !== 'heartbeat') return null;
  return { zone, entityType, entityId, channel };
}

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);

/**
 * 한 건을 기존 상태에 얹는다. **없는 필드는 안 지운다** — `state` 는 `link` 를 안 싣고
 * `heartbeat` 는 아무것도 안 싣는다. 매번 덮어쓰면 값이 깜빡인다.
 */
export function applyDeviceMessage(
  previous: DeviceState | undefined,
  parsed: { entityType: string; entityId: string; channel: string },
  body: Record<string, unknown>,
  nowMs = Date.now(),
): DeviceState {
  const next: DeviceState = previous ?? {
    entityId: parsed.entityId,
    entityType: parsed.entityType,
    online: null, health: null, link: null, mode: null, inMission: null,
    batteryPct: null, position: null, speedMps: null, firmware: null,
    lastSeenMs: nowMs, timestamp: null, simulated: false,
  };
  const merged: DeviceState = { ...next, lastSeenMs: nowMs };
  merged.timestamp = str(body.timestamp) ?? merged.timestamp;
  if (body.simulated === true) merged.simulated = true;

  if (parsed.channel === 'status') {
    // 끊기면 LWT 가 offline 을 대신 넣는다 — 그 사실이 이 한 줄이다.
    if (typeof body.status === 'string') merged.online = body.status === 'online';
    merged.health = str(body.device_status) ?? merged.health;
    merged.link = str(body.link) ?? merged.link;
    merged.mode = str(body.robot_mode) ?? merged.mode;
    if (typeof body.in_mission === 'boolean') merged.inMission = body.in_mission;
    merged.batteryPct = num(body.battery_pct) ?? merged.batteryPct;
    const registration = body.registration as Record<string, unknown> | undefined;
    merged.firmware = str(registration?.fw_version) ?? merged.firmware;
  } else if (parsed.channel === 'state') {
    merged.batteryPct = num(body.battery_pct) ?? merged.batteryPct;
    merged.health = str(body.device_status) ?? merged.health;
    merged.mode = str(body.robot_mode) ?? merged.mode;
    merged.speedMps = num(body.speed_mps) ?? merged.speedMps;
    const position = body.position as Record<string, unknown> | undefined;
    if (position !== undefined) {
      const x = num(position.x);
      const y = num(position.y);
      const headingDeg = num(position.heading_deg);
      if (x !== null && y !== null) merged.position = { x, y, headingDeg: headingDeg ?? 0 };
    }
  }
  // heartbeat 는 `lastSeenMs` 만 민다 — 살아 있다는 것 말고는 아무것도 안 말한다.
  return merged;
}

/** 이 값이 낡았는가. 상태는 5초 주기라 그 세 배를 넘으면 못 믿는다. */
export const STALE_AFTER_MS = 15_000;

export function isStale(device: DeviceState, nowMs = Date.now()): boolean {
  return nowMs - device.lastSeenMs > STALE_AFTER_MS;
}

// ── 열 ───────────────────────────────────────────────────────────────────────

let devices: Readonly<Record<string, DeviceState>> = {};
const listeners = new Set<() => void>();

export function deviceStates(): Readonly<Record<string, DeviceState>> {
  return devices;
}

export function deviceState(entityId: string): DeviceState | null {
  return devices[entityId] ?? null;
}

export function receiveDeviceMessage(topic: string, body: Record<string, unknown>): boolean {
  const parsed = parseTopic(topic);
  if (parsed === null) return false;
  devices = { ...devices, [parsed.entityId]: applyDeviceMessage(devices[parsed.entityId], parsed, body) };
  for (const listener of listeners) listener();
  return true;
}

export function subscribeDevices(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useDeviceStates(): Readonly<Record<string, DeviceState>> {
  return useSyncExternalStore(subscribeDevices, deviceStates, deviceStates);
}

export function resetDevices(): void {
  devices = {};
  for (const listener of listeners) listener();
}
