/**
 * src/physical/fcxFeed.ts (261002 신설 — 드론 파트 · 드론 상태판)
 *
 * **Pi 의 FC 텔레메트리 수집기(`drone/fc_watch`)가 내는 보고 한 건을 뜯는다.** 토픽 `{zone}/{type}/{id}/fcx`
 * (JSON, 5 Hz, retained). 숫자가 아니면 `null`(모름) — 0 으로 바꾸지 않는다. 모양이 틀리면 묶음째 `null`.
 */

import type { Fcx, FcxConsoleLine, FcxSensor } from '../shared/fcxStatus.ts';

export const FCX_TOPIC = 'zoneA/+/+/fcx';

export function fcxChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'fcx';
}

type Obj = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);
const obj = (v: unknown): Obj | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Obj : null);

export function parseFcx(body: Obj, topic = ''): Fcx | null {
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  const link = obj(body.link);
  if (deviceId === '' || link === null) return null;
  const att = obj(body.attitude);
  const hud = obj(body.hud);
  const pos = obj(body.position);
  const home = obj(body.home);
  const gps = obj(body.gps);
  const rtk = obj(body.rtk);
  const bat = obj(body.battery);
  const ekf = obj(body.ekf);
  const vib = obj(body.vibration);
  const rc = obj(body.rc);
  const sensors: FcxSensor[] | null = Array.isArray(body.sensors)
    ? body.sensors.map(obj).filter((s): s is Obj => s !== null && typeof s.name === 'string')
      .map((s) => ({ name: s.name as string, enabled: s.enabled === true, healthy: s.healthy === true }))
    : null;
  const consoleLines: FcxConsoleLine[] = Array.isArray(body.console)
    ? body.console.map(obj).filter((c): c is Obj => c !== null && typeof c.text === 'string')
      .map((c) => ({ t: num(c.t) ?? 0, severity: str(c.severity) ?? '?', level: num(c.level) ?? 6, text: c.text as string }))
    : [];
  return {
    deviceId,
    link: { heartbeatAgeS: num(link.heartbeat_age_s), msgsPerS: num(link.msgs_per_s), fcSysid: num(link.fc_sysid) },
    armed: bool(body.armed),
    mode: str(body.mode),
    landedState: str(body.landed_state),
    attitude: att && { rollDeg: num(att.roll_deg), pitchDeg: num(att.pitch_deg), yawDeg: num(att.yaw_deg) },
    hud: hud && { groundspeed: num(hud.groundspeed), airspeed: num(hud.airspeed), climb: num(hud.climb), heading: num(hud.heading), throttle: num(hud.throttle) },
    position: pos && { lat: num(pos.lat), lon: num(pos.lon), altRelM: num(pos.alt_rel_m), altMslM: num(pos.alt_msl_m), vn: num(pos.vn), ve: num(pos.ve), vd: num(pos.vd) },
    home: home && { lat: num(home.lat), lon: num(home.lon), altMslM: num(home.alt_msl_m) },
    gps: gps && { fixType: num(gps.fix_type), fix: str(gps.fix), satellites: num(gps.satellites), hdop: num(gps.hdop), vdop: num(gps.vdop), hAccM: num(gps.h_acc_m), vAccM: num(gps.v_acc_m) },
    rtk: rtk && { baselineM: num(rtk.baseline_m), accuracyMm: num(rtk.accuracy_mm), iarHypotheses: num(rtk.iar_hypotheses), rtkRate: num(rtk.rtk_rate), nsats: num(rtk.nsats) },
    battery: bat && {
      voltageV: num(bat.voltage_v), currentA: num(bat.current_a), remainingPct: num(bat.remaining_pct),
      cellsV: Array.isArray(bat.cells_v) ? bat.cells_v.map(num).filter((v): v is number => v !== null) : [],
      temperatureC: num(bat.temperature_c), consumedMah: num(bat.consumed_mah),
    },
    sensors,
    loadPct: num(body.load_pct),
    dropRatePct: num(body.drop_rate_pct),
    ekf: ekf && { vel: num(ekf.vel), pos: num(ekf.pos), ver: num(ekf.ver), mag: num(ekf.mag), ter: num(ekf.ter), gpsGlitch: ekf.gps_glitch === true, accelError: ekf.accel_error === true },
    vibration: vib && { x: num(vib.x), y: num(vib.y), z: num(vib.z), clipping: Array.isArray(vib.clipping) ? vib.clipping.map((c) => num(c) ?? 0) : [] },
    rc: rc && { rssi: num(rc.rssi), channels: num(rc.channels) },
    companion: (() => {
      const c = obj(body.companion);
      if (!c) return null;
      const th = obj(c.throttled);
      const lv = c.level === 'ok' || c.level === 'warn' || c.level === 'bad' ? c.level : null;
      return { cpuTempC: num(c.cpu_temp_c), throttledNow: th?.now === true, throttledEver: th?.since_boot === true, undervolt: th?.undervolt === true,
        load1: num(c.load1), diskFreeGb: num(c.disk_free_gb), level: lv,
        eth: obj(c.eth) ? { up: obj(c.eth)!.up === true, speedMbps: num(obj(c.eth)!.speed_mbps), rxErrors: num(obj(c.eth)!.rx_errors) } : null,
        wifi: obj(c.wifi) ? { connected: obj(c.wifi)!.connected === true, freqMhz: num(obj(c.wifi)!.freq_mhz), signalDbm: num(obj(c.wifi)!.signal_dbm) } : null };
    })(),
    wind: obj(body.wind) && { speedMps: num(obj(body.wind)!.speed_mps), fromDeg: num(obj(body.wind)!.from_deg), varH: num(obj(body.wind)!.var_h) },
    clockOffsetS: num(body.clock_offset_s),
    console: consoleLines,
    deviceTime: num(body.time),
  };
}
