/**
 * src/physical/radarFeed.ts (261003 신설 — 드론 파트 · 레이더 상태)
 *
 * **레이더(cansar)가 내는 상태 한 건을 뜯는다.** 토픽은 `{zone}/{type}/{id}/radar`(JSON, retained, 1 Hz).
 * 규약: `viz-debugger/drone/RADAR_INTERFACE.md` 5 절 · 보내는 쪽 `drone/sar_pass/radar_status.py`.
 * 모양이 틀리면 `null`, 숫자가 없으면 `null`(모름) — `rtcmFeed.ts` 와 같은 규칙이다.
 */

import type { RadarState, RadarStatus } from '../shared/radarStatus.ts';

export const RADAR_TOPIC = 'zoneA/+/+/radar';

export function radarChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'radar';
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const STATES: readonly RadarState[] = ['idle', 'armed', 'recording', 'error'];

export function parseRadarStatus(body: Record<string, unknown>, topic = ''): RadarStatus | null {
  if (typeof body.schema_version !== 'string' || !body.schema_version.startsWith('radar-')) return null;
  const state = STATES.includes(body.state as RadarState) ? body.state as RadarState : null;
  if (state === null) return null;
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  if (deviceId === '') return null;
  const ts = body.time_source;
  return {
    deviceId,
    state,
    recording: body.recording === true,
    file: str(body.file),
    pulsesPerS: num(body.pulses_per_s),
    dropped: num(body.dropped),
    bufferPct: num(body.buffer_pct),
    tempC: num(body.temp_c),
    timeSource: ts === 'pps' || ts === 'ntp' || ts === 'none' ? ts : null,
    ppsLocked: typeof body.pps_locked === 'boolean' ? body.pps_locked : null,
    diskFreeGb: num(body.disk_free_gb),
    lastError: str(body.last_error),
    deviceTime: num(body.time),
  };
}
