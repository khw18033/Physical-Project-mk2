/**
 * src/physical/rtcmFeed.ts (261002 신설 — 드론 파트 · RTK 보정 전달)
 *
 * **Pi 의 보정 전달기(`drone/rtk_relay/fc_injector.py`)가 내는 상태 한 건을 뜯는다.** 토픽은
 * `{zone}/{type}/{id}/rtcm`(JSON, retained, 1초마다). 「보정이 FC 로 들어가고 있는가」를 화면이 가른다 —
 * fix 등급(`gps.fix_type`)만 보면 Float 로 떨어졌을 때 그것이 보정이 끊겨서인지 하늘이 나빠서인지 모른다.
 *
 * 모양이 틀리면 `null`, 숫자가 없으면 `null`(모름) — `sarFeed.ts` 와 같은 규칙이다.
 */

import type { RtcmStatus } from '../shared/rtcmStatus.ts';

export const RTCM_TOPIC = 'zoneA/+/+/rtcm';

export function rtcmChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'rtcm';
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);

export function parseRtcmStatus(body: Record<string, unknown>, topic = ''): RtcmStatus | null {
  if (typeof body.receiving !== 'boolean') return null;
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  if (deviceId === '') return null;
  const base = body.base !== null && typeof body.base === 'object' ? body.base as Record<string, unknown> : null;
  const types = body.types !== null && typeof body.types === 'object' && !Array.isArray(body.types)
    ? Object.keys(body.types as Record<string, unknown>).filter((k) => /^\d+$/.test(k))
    : [];
  return {
    deviceId,
    receiving: body.receiving,
    mode: body.mode === 'external' ? 'external' : 'relay',
    ageS: num(body.age_s),
    framesPerS: num(body.frames_per_s),
    rateBps: num(body.rate_bps),
    frames: num(body.frames),
    types,
    base: base === null ? null : {
      stationId: num(base.station_id), lat: num(base.lat), lon: num(base.lon), altM: num(base.alt_m),
    },
    sender: str(body.sender),
    injectedMessages: num(body.injected_messages),
    badCrc: num(body.bad_crc),
    timestamp: str(body.timestamp),
  };
}
