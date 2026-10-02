/**
 * src/physical/sarFeed.ts (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **드론의 SAR 패스 실행기가 보내는 상태 한 건을 뜯는다.** 토픽은 `{zone}/{type}/{id}/sar`(JSON,
 * retained)이고 보내는 쪽은 `drone/sar_pass/status.py` 다. 모양은 `drone/README.md` 「화면 ↔ 드론 규약」.
 *
 * 토픽 문자열은 이 디렉터리 밖에 적지 않는다(`verify:physical-port`). 화면은 `shared/sarStatus.ts`
 * 의 저장소만 읽는다.
 *
 * **모양이 틀리면 `null` 이다** — 지어 채우지 않는다. 숫자 칸이 비면 `null`(모름)이고 0 으로 바꾸지 않는다.
 */

import type { SarPassRecord, SarState, SarStatus } from '../shared/sarStatus.ts';

/** 구역의 모든 장비를 받는다 — 상태 토픽과 같은 규칙(`+`)이다. 드론 id 를 적지 않는다. */
export const SAR_TOPIC = 'zoneA/+/+/sar';

export function sarChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'sar';
}

const STATES: readonly SarState[] = [
  'idle', 'preflight', 'transit', 'gap', 'accel', 'capture', 'decel', 'returning', 'done', 'incomplete', 'aborted', 'failed',
];

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const obj = (v: unknown): Record<string, unknown> | null =>
  v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null;

function passRecord(raw: unknown): SarPassRecord | null {
  const r = obj(raw);
  const passNo = num(r?.pass_no);
  if (r === null || passNo === null) return null;
  return {
    passNo,
    startUnix: num(r.start_unix),
    endUnix: num(r.end_unix),
    durationS: num(r.duration_s),
    captured: r.captured === true,
    meanSpeedMps: num(r.mean_speed_mps),
    maxSpeedErrMps: num(r.max_speed_err_mps),
    maxCrossTrackM: num(r.max_cross_track_m),
    maxAltErrM: num(r.max_alt_err_m),
    maxHeadingErrDeg: num(r.max_heading_err_deg),
    alongAtStartM: num(r.along_at_start_m),
    fcStartUnix: num(r.fc_start_unix),
    fcEndUnix: num(r.fc_end_unix),
    worstFix: str(r.worst_fix),
    valid: typeof r.valid === 'boolean' ? r.valid : null,
    reasons: Array.isArray(r.reasons) ? r.reasons.filter((x): x is string => typeof x === 'string') : [],
    ackStartUnix: num(r.ack_start_unix),
    ackEndUnix: num(r.ack_end_unix),
    ackOnLatencyS: num(r.ack_on_latency_s),
    capLeadS: num(r.cap_lead_s),
    leadInM: num(r.lead_in_m),
    effStartAlongM: num(r.eff_start_along_m),
    effEndAlongM: num(r.eff_end_along_m),
    trajCsv: str(r.traj_csv),
    metaJson: str(r.meta_json),
    note: str(r.note),
  };
}

/** 한 건 → 화면이 읽는 모양. 장비 id 는 본문(`source_id`)이 먼저, 없으면 토픽의 세 번째 칸이다. */
export function parseSarStatus(body: Record<string, unknown>, topic = ''): SarStatus | null {
  const state = str(body.state);
  if (state === null || !STATES.includes(state as SarState)) return null;
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  if (deviceId === '') return null;
  const plan = obj(body.plan);
  const live = obj(body.live);
  return {
    deviceId,
    state: state as SarState,
    passNo: num(body.pass) ?? 0,
    passesTotal: num(body.passes_total),
    capturing: body.capturing === true,
    plan: plan === null ? null : {
      startLat: num(plan.start_lat), startLon: num(plan.start_lon),
      endLat: num(plan.end_lat), endLon: num(plan.end_lon),
      altM: num(plan.alt_m), speedMps: num(plan.speed_mps), passes: num(plan.passes), gapS: num(plan.gap_s),
      leadInM: num(plan.lead_in_m), lengthM: num(plan.length_m), headingDeg: num(plan.heading_deg),
      requireRtk: plan.require_rtk === true,
    },
    live: live === null ? null : {
      groundSpeedMps: num(live.ground_speed_mps),
      altRelM: num(live.alt_rel_m),
      yawDeg: num(live.yaw_deg),
      headingErrDeg: num(live.heading_err_deg),
      alongM: num(live.along_m),
      crossTrackM: num(live.cross_track_m),
      gpsFix: str(live.gps_fix),
      flightMode: str(live.flight_mode),
    },
    passes: Array.isArray(body.passes)
      ? body.passes.map(passRecord).filter((r): r is SarPassRecord => r !== null)
      : [],
    validPasses: num(body.valid_passes),
    maxAttempts: num(body.max_attempts),
    capAck: typeof body.cap_ack === 'boolean' ? body.cap_ack : null,
    ekf2HgtRef: num(body.ekf2_hgt_ref),
    battery: (() => {
      const b = obj(body.battery);
      const bp = num(b?.battery_pct); const need = num(b?.need_pct); const rate = num(b?.drain_pct_s);
      return bp === null || need === null || rate === null ? null : { batteryPct: bp, needPct: need, drainPctS: rate };
    })(),
    clockOffsetS: num(body.clock_offset_s),
    warnings: Array.isArray(body.warnings) ? body.warnings.map(str).filter((w): w is string => w !== null) : [],
    message: str(body.message),
    error: str(body.error),
    deviceTime: num(body.time),
    timestamp: str(body.timestamp),
  };
}
