/**
 * src/dronedash/DroneDash.tsx (261002 신설 — 드론 파트 · 드론 상태판)
 *
 * **MicoConfigurator · QGC 의 상태 화면을 캔버스 노드 하나로.** 접힘 = 상태 줄 한 줄, 확대 = 상태 줄 ·
 * 자세계 · 나침반 · 지도 · 그래프 · GPS/RTK · 센서 건강 · 진동 · 배터리 셀 · 메시지 콘솔.
 *
 * 원천은 둘이다.
 *   ① FC 확장 텔레메트리(`fcx`, 5 Hz) — Pi 의 `fc_watch` 가 FC MAVLink 를 읽어 낸다. 전부 그릴 수 있다.
 *   ② 드론 에이전트의 `state`(1 Hz) — 자세 · GPS · 배터리 · 모드 정도. ①이 없을 때 이것으로 물러서고 그 사실을 적는다.
 * 없는 값은 「—」다. 지어 채우지 않는다.
 */

import { useMemo, useState, type ReactNode } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { telemetryValue, useDeviceTelemetry, isTelemetryStale } from '../shared/deviceTelemetry.ts';
import { isFcxStale, useFcxReports, type FcxReport, type FcxSample } from '../shared/fcxStatus.ts';
import { useSarReports } from '../shared/sarStatus.ts';
import { useRtcmReports } from '../shared/rtcmStatus.ts';
import { rtkLevel } from '../sar/rtk.ts';
import { RtkBadge, RtcmLine } from '../sar/RtkView.tsx';
import { useTick } from '../sar/useTick.ts';
import '../sar/sar.css';
import './dronedash.css';

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const fmt = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : v.toFixed(d));

type Level = 'good' | 'warn' | 'bad' | 'unknown';
const MARK: Record<Level, string> = { good: '✓', warn: '!', bad: '✕', unknown: '?' };

/** EKF 비율 판정 — QGC · MicoConfigurator 와 같은 기준(0.5 · 1.0). */
function ekfLevel(ratio: number | null): Level {
  if (ratio === null) return 'unknown';
  return ratio < 0.5 ? 'good' : ratio < 1 ? 'warn' : 'bad';
}

// ── 보는 장비와 값 모으기 ───────────────────────────────────────────────────

type View = {
  deviceId: string;
  fcx: FcxReport | null;
  extended: boolean;
  mode: string | null;
  armed: boolean | null;
  rollDeg: number | null;
  pitchDeg: number | null;
  yawDeg: number | null;
  lat: number | null;
  lon: number | null;
  altRelM: number | null;
  groundspeed: number | null;
  climb: number | null;
  fixType: number | null;
  fix: string | null;
  sats: number | null;
  batteryPct: number | null;
  batteryV: number | null;
  linkAgeS: number | null;
};

function useDroneViews(): View[] {
  const fcx = useFcxReports();
  const telemetry = useDeviceTelemetry();
  const ids = new Set<string>(Object.keys(fcx));
  for (const [id, report] of Object.entries(telemetry)) {
    if (report.values.attitude !== undefined || report.values.gps !== undefined || report.values.flight !== undefined) ids.add(id);
  }
  return [...ids].sort().map((id) => {
    const f = fcx[id] ?? null;
    const live = f !== null && !isFcxStale(f);
    const tv = (path: string) => telemetryValue(id, path);
    const st = telemetry[id];
    return {
      deviceId: id,
      fcx: f,
      extended: live,
      mode: (live ? f.mode : null) ?? (typeof tv('flight.mode') === 'string' ? tv('flight.mode') as string : null),
      armed: (live ? f.armed : null) ?? (typeof tv('flight.armed') === 'boolean' ? tv('flight.armed') as boolean : null),
      rollDeg: (live ? f.attitude?.rollDeg : null) ?? num(tv('attitude.roll_deg')),
      pitchDeg: (live ? f.attitude?.pitchDeg : null) ?? num(tv('attitude.pitch_deg')),
      yawDeg: (live ? f.attitude?.yawDeg : null) ?? num(tv('attitude.yaw_deg')),
      lat: (live ? f.position?.lat : null) ?? num(tv('gps.lat')),
      lon: (live ? f.position?.lon : null) ?? num(tv('gps.lon')),
      altRelM: (live ? f.position?.altRelM : null) ?? num(tv('altitude.relative_m')),
      groundspeed: live ? f.hud?.groundspeed ?? null : null,
      climb: live ? f.hud?.climb ?? null : null,
      fixType: (live ? f.gps?.fixType : null) ?? num(tv('gps.fix_type')),
      fix: (live ? f.gps?.fix : null) ?? (typeof tv('gps.fix') === 'string' ? tv('gps.fix') as string : null),
      sats: (live ? f.gps?.satellites : null) ?? num(tv('gps.satellites')),
      batteryPct: (live ? f.battery?.remainingPct : null) ?? num(tv('battery.remaining_pct')),
      batteryV: (live ? f.battery?.voltageV : null) ?? num(tv('battery.voltage_v')),
      linkAgeS: live ? f.link.heartbeatAgeS : st === undefined || isTelemetryStale(st) ? null : (Date.now() - st.receivedAtMs) / 1000,
    };
  });
}

// ── 상태 줄 ────────────────────────────────────────────────────────────────

function Chip({ level, label, value, title }: { level: Level; label: string; value?: ReactNode; title?: string }) {
  return <span className={`dash-chip dash-chip--${level}`} title={title}>
    <i aria-hidden>{MARK[level]}</i><b>{label}</b>{value !== undefined && <span>{value}</span>}
  </span>;
}

function StatusBar({ v, compact }: { v: View; compact?: boolean }) {
  useLang();
  const rtcm = useRtcmReports()[v.deviceId];
  const f = v.extended ? v.fcx : null;
  const linkLevel: Level = v.linkAgeS === null ? 'bad' : v.linkAgeS < 2 ? 'good' : v.linkAgeS < 5 ? 'warn' : 'bad';
  const batLevel: Level = v.batteryPct === null ? 'unknown' : v.batteryPct > 30 ? 'good' : v.batteryPct > 15 ? 'warn' : 'bad';
  const level = rtkLevel(v.fixType, v.fix);
  return <div className={`dash-status${compact ? ' dash-status--compact' : ''}`}>
    <Chip level={linkLevel} label={t('dash.link')} value={v.linkAgeS === null ? t('dash.lost') : `${fmt(v.linkAgeS)}s${f?.link.msgsPerS ? ` · ${fmt(f.link.msgsPerS, 0)}/s` : ''}`} />
    <Chip level={v.mode === null ? 'unknown' : 'good'} label={t('dash.mode')} value={v.mode ?? '—'} />
    <Chip level={v.armed === null ? 'unknown' : v.armed ? 'warn' : 'good'} label={v.armed ? t('dash.armed') : t('dash.disarmed')} />
    <span className="dash-gps"><RtkBadge level={level} /><small>{t('dash.sats', { n: v.sats ?? '—' })}{f?.gps?.hdop !== null && f?.gps?.hdop !== undefined ? ` · HDOP ${fmt(f.gps.hdop, 2)}` : ''}</small></span>
    {!compact && f?.ekf && (['pos', 'vel', 'mag', 'ter', 'ver'] as const).map((k) =>
      <Chip key={k} level={ekfLevel(f.ekf![k])} label={k.toUpperCase()} title={t('dash.ekfTitle', { v: fmt(f.ekf![k], 2) })} />)}
    <Chip level={batLevel} label={t('dash.battery')} value={`${fmt(v.batteryV, 2)}V · ${v.batteryPct === null ? '—' : `${Math.round(v.batteryPct)}%`}`} />
    {!compact && f?.rc && <Chip level={f.rc.rssi === null ? 'unknown' : f.rc.rssi > 50 ? 'good' : f.rc.rssi > 20 ? 'warn' : 'bad'} label="RC" value={f.rc.rssi === null ? '—' : `${f.rc.rssi}%`} />}
    {!compact && <RtcmLine report={rtcm} />}
    {!compact && f?.clockOffsetS !== null && f?.clockOffsetS !== undefined &&
      <Chip level={Math.abs(f.clockOffsetS) <= 1 ? 'good' : 'bad'} label={t('dash.clock')} value={`${f.clockOffsetS >= 0 ? '+' : ''}${fmt(f.clockOffsetS, 2)}s`} />}
  </div>;
}

// ── 자세계 · 나침반 ─────────────────────────────────────────────────────────

function Attitude({ roll, pitch }: { roll: number | null; pitch: number | null }) {
  useLang();
  const r = roll ?? 0;
  const p = pitch ?? 0;
  const S = 200;
  const PX = 3;   // 1° = 3px
  const known = roll !== null && pitch !== null;
  const ladder = [-30, -20, -10, 10, 20, 30];
  return <figure className="dash-att">
    <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={t('dash.attitude')}>
      <defs><clipPath id="dash-att-clip"><circle cx={S / 2} cy={S / 2} r={S / 2 - 4} /></clipPath></defs>
      <g clipPath="url(#dash-att-clip)">
        <g transform={`rotate(${-r} ${S / 2} ${S / 2}) translate(0 ${p * PX})`} opacity={known ? 1 : 0.35}>
          <rect x={-S} y={-S * 2 + S / 2} width={S * 3} height={S * 2} className="dash-att-sky" />
          <rect x={-S} y={S / 2} width={S * 3} height={S * 2} className="dash-att-ground" />
          <line x1={-S} y1={S / 2} x2={S * 2} y2={S / 2} className="dash-att-horizon" />
          {ladder.map((d) => <g key={d}>
            <line x1={S / 2 - (Math.abs(d) % 20 === 0 ? 28 : 16)} x2={S / 2 + (Math.abs(d) % 20 === 0 ? 28 : 16)} y1={S / 2 - d * PX} y2={S / 2 - d * PX} className="dash-att-ladder" />
            <text x={S / 2 + 34} y={S / 2 - d * PX + 4} className="dash-att-ladder-text">{d}</text>
          </g>)}
        </g>
      </g>
      {/* 롤 눈금 · 고정 비행기 표시 */}
      {[-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60].map((d) => {
        const a = ((d - 90) * Math.PI) / 180;
        const r1 = S / 2 - 6;
        const r2 = d % 30 === 0 ? r1 - 12 : r1 - 7;
        return <line key={d} x1={S / 2 + r1 * Math.cos(a)} y1={S / 2 + r1 * Math.sin(a)} x2={S / 2 + r2 * Math.cos(a)} y2={S / 2 + r2 * Math.sin(a)} className="dash-att-tick" />;
      })}
      <polygon points={`${S / 2},${16} ${S / 2 - 6},${28} ${S / 2 + 6},${28}`} className="dash-att-pointer" transform={`rotate(${-r} ${S / 2} ${S / 2})`} />
      <path d={`M ${S / 2 - 46} ${S / 2} h 30 l 8 8 l 8 -8 h 30`} className="dash-att-aircraft" />
      <circle cx={S / 2} cy={S / 2} r={3} className="dash-att-dot" />
      <circle cx={S / 2} cy={S / 2} r={S / 2 - 4} className="dash-att-rim" />
    </svg>
    <figcaption>{t('dash.rollPitch', { r: fmt(roll), p: fmt(pitch) })}</figcaption>
  </figure>;
}

function Compass({ yaw, homeBearing }: { yaw: number | null; homeBearing: number | null }) {
  useLang();
  const S = 200;
  const y = yaw ?? 0;
  const marks = Array.from({ length: 36 }, (_, i) => i * 10);
  const label: Record<number, string> = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' };
  return <figure className="dash-att">
    <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={t('dash.heading')}>
      <circle cx={S / 2} cy={S / 2} r={S / 2 - 4} className="dash-cmp-face" />
      <g transform={`rotate(${-y} ${S / 2} ${S / 2})`} opacity={yaw === null ? 0.35 : 1}>
        {marks.map((d) => {
          const a = ((d - 90) * Math.PI) / 180;
          const r1 = S / 2 - 8;
          const r2 = d % 30 === 0 ? r1 - 12 : r1 - 6;
          return <g key={d}>
            <line x1={S / 2 + r1 * Math.cos(a)} y1={S / 2 + r1 * Math.sin(a)} x2={S / 2 + r2 * Math.cos(a)} y2={S / 2 + r2 * Math.sin(a)} className="dash-att-tick" />
            {label[d] !== undefined && <text x={S / 2 + (r1 - 26) * Math.cos(a)} y={S / 2 + (r1 - 26) * Math.sin(a) + 5} textAnchor="middle" className={`dash-cmp-card${d === 0 ? ' is-n' : ''}`}>{label[d]}</text>}
          </g>;
        })}
        {homeBearing !== null && (() => {
          const a = ((homeBearing - 90) * Math.PI) / 180;
          return <text x={S / 2 + (S / 2 - 50) * Math.cos(a)} y={S / 2 + (S / 2 - 50) * Math.sin(a) + 5} textAnchor="middle" className="dash-cmp-home">H</text>;
        })()}
      </g>
      <polygon points={`${S / 2},${30} ${S / 2 - 9},${S / 2 + 6} ${S / 2},${S / 2 - 4} ${S / 2 + 9},${S / 2 + 6}`} className="dash-cmp-needle" />
      <text x={S / 2} y={S / 2 + 40} textAnchor="middle" className="dash-cmp-value">{yaw === null ? '—' : `${Math.round(y)}°`}</text>
    </svg>
    <figcaption>{t('dash.headingCaption')}</figcaption>
  </figure>;
}

// ── 지도 · 궤적 ────────────────────────────────────────────────────────────

const TILE = 256;
function mercator(lat: number, lon: number, z: number): { x: number; y: number } {
  const s = TILE * 2 ** z;
  const sin = Math.sin((lat * Math.PI) / 180);
  return { x: ((lon + 180) / 360) * s, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s };
}
function metersPerPixel(lat: number, z: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** z;
}
function bearing(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const la1 = (a.lat * Math.PI) / 180;
  const la2 = (b.lat * Math.PI) / 180;
  const dl = ((b.lon - a.lon) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(la2);
  const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dl);
  return (((Math.atan2(y, x) * 180) / Math.PI) + 360) % 360;
}
function distanceM(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos((a.lat * Math.PI) / 180) * Math.cos((b.lat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const TILES_KEY = 'viz.dash.tiles.v1';

function TrackMap({ v }: { v: View }) {
  useLang();
  const sar = useSarReports()[v.deviceId];
  const [tiles, setTiles] = useState<boolean>(() => { try { return localStorage.getItem(TILES_KEY) === '1'; } catch { return false; } });
  const history = v.fcx?.history ?? [];
  const track = history.filter((s): s is FcxSample & { lat: number; lon: number } => s.lat !== null && s.lon !== null);
  const home = v.fcx?.home?.lat != null && v.fcx.home.lon != null ? { lat: v.fcx.home.lat, lon: v.fcx.home.lon } : null;
  const plan = sar?.plan;
  const line = plan?.startLat != null && plan.startLon != null && plan.endLat != null && plan.endLon != null
    ? [{ lat: plan.startLat, lon: plan.startLon }, { lat: plan.endLat, lon: plan.endLon }] : null;
  const here = v.lat !== null && v.lon !== null ? { lat: v.lat, lon: v.lon } : null;
  const pts = [...track, ...(home ? [home] : []), ...(line ?? []), ...(here ? [here] : [])];
  if (pts.length === 0) return <p className="sar-empty">{t('dash.noPosition')}</p>;

  const W = 560;
  const H = 360;
  const center = { lat: (Math.min(...pts.map((p) => p.lat)) + Math.max(...pts.map((p) => p.lat))) / 2, lon: (Math.min(...pts.map((p) => p.lon)) + Math.max(...pts.map((p) => p.lon))) / 2 };
  // 다 들어가는 가장 큰 줌 (최소 60 m 폭)
  let z = 20;
  for (; z > 3; z--) {
    const ps = pts.map((p) => mercator(p.lat, p.lon, z));
    const w = Math.max(...ps.map((p) => p.x)) - Math.min(...ps.map((p) => p.x));
    const h = Math.max(...ps.map((p) => p.y)) - Math.min(...ps.map((p) => p.y));
    if (w < W * 0.8 && h < H * 0.8 && metersPerPixel(center.lat, z) * W >= 60) break;
  }
  const c = mercator(center.lat, center.lon, z);
  const ox = c.x - W / 2;
  const oy = c.y - H / 2;
  const P = (p: { lat: number; lon: number }) => { const m = mercator(p.lat, p.lon, z); return { x: m.x - ox, y: m.y - oy }; };
  const mpp = metersPerPixel(center.lat, z);
  const scaleM = [5, 10, 20, 50, 100, 200, 500, 1000].find((m) => m / mpp > 70) ?? 1000;
  const tileList: { x: number; y: number }[] = [];
  if (tiles) {
    for (let tx = Math.floor(ox / TILE); tx <= Math.floor((ox + W) / TILE); tx++) {
      for (let ty = Math.floor(oy / TILE); ty <= Math.floor((oy + H) / TILE); ty++) tileList.push({ x: tx, y: ty });
    }
  }
  const d = here ? P(here) : null;
  const yaw = v.yawDeg ?? 0;
  return <figure className="dash-map">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t('dash.map')}>
      <rect width={W} height={H} className="dash-map-bg" />
      {tileList.map((tl) => <image key={`${tl.x}-${tl.y}`} href={`https://tile.openstreetmap.org/${z}/${tl.x}/${tl.y}.png`}
        x={tl.x * TILE - ox} y={tl.y * TILE - oy} width={TILE} height={TILE} opacity={0.85} />)}
      {!tiles && Array.from({ length: 12 }, (_, i) => <g key={i}>
        <line x1={(i * scaleM) / mpp} y1={0} x2={(i * scaleM) / mpp} y2={H} className="dash-map-grid" />
        <line x1={0} y1={(i * scaleM) / mpp} x2={W} y2={(i * scaleM) / mpp} className="dash-map-grid" />
      </g>)}
      {line && <line x1={P(line[0]!).x} y1={P(line[0]!).y} x2={P(line[1]!).x} y2={P(line[1]!).y} className={`dash-map-sar${sar?.capturing ? ' is-on' : ''}`} />}
      {track.length > 1 && <polyline points={track.map((s) => { const q = P(s); return `${q.x.toFixed(1)},${q.y.toFixed(1)}`; }).join(' ')} className="dash-map-track" />}
      {home && <g transform={`translate(${P(home).x} ${P(home).y})`}><circle r={9} className="dash-map-home" /><text y={4} textAnchor="middle" className="dash-map-home-text">H</text></g>}
      {d && <g transform={`translate(${d.x} ${d.y}) rotate(${yaw})`}>
        <polygon points="0,-13 9,10 0,5 -9,10" className="dash-map-drone" />
      </g>}
      <g transform={`translate(${W - 22},26)`}><polygon points="0,-12 5,4 0,0 -5,4" className="dash-map-north" /><text x={-4} y={16} className="dash-map-text">N</text></g>
      <g transform={`translate(12,${H - 12})`}><line x1={0} y1={0} x2={scaleM / mpp} y2={0} className="dash-map-scale" /><text x={0} y={-5} className="dash-map-text">{scaleM} m</text></g>
    </svg>
    <figcaption className="dash-map-caption">
      <label className="sar-check"><input type="checkbox" checked={tiles} onChange={(e) => {
        setTiles(e.target.checked); try { localStorage.setItem(TILES_KEY, e.target.checked ? '1' : '0'); } catch { /* */ }
      }} />{t('dash.tiles')}</label>
      {home && here && <span>{t('dash.homeDist', { m: fmt(distanceM(home, here), 1), deg: Math.round(bearing(here, home)) })}</span>}
      {here && <span>{here.lat.toFixed(7)}, {here.lon.toFixed(7)}</span>}
      {tiles && <small>© OpenStreetMap</small>}
    </figcaption>
  </figure>;
}

// ── 그래프 (한 장에 한 계열 · 십자선 툴팁) ──────────────────────────────────

const WINDOW_MS = 120_000;
const MIN_WINDOW_MS = 30_000;

function LineChart({ title, unit, samples, pick, digits = 1 }: {
  title: string; unit: string; samples: readonly FcxSample[]; pick: (s: FcxSample) => number | null; digits?: number;
}) {
  useLang();
  const now = Date.now();
  // 쌓인 만큼만 가로를 쓴다(30초~2분) — 막 붙었을 때 선이 오른쪽 끝에 몰리지 않게.
  const first = samples.find((s) => now - s.atMs <= WINDOW_MS)?.atMs ?? now;
  const span = Math.min(WINDOW_MS, Math.max(MIN_WINDOW_MS, now - first));
  const pts = samples.filter((s) => now - s.atMs <= span).map((s) => ({ t: s.atMs, v: pick(s) })).filter((p): p is { t: number; v: number } => p.v !== null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 260;
  const H = 110;
  const L = 34;
  const B = 18;
  if (pts.length < 2) return <figure className="dash-chart"><figcaption><b>{title}</b> <small>{unit}</small></figcaption><p className="sar-empty">{t('dash.noData')}</p></figure>;
  let lo = Math.min(...pts.map((p) => p.v));
  let hi = Math.max(...pts.map((p) => p.v));
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.1;
  lo -= pad; hi += pad;
  const x = (tt: number) => L + ((tt - (now - span)) / span) * (W - L - 6);
  const y = (vv: number) => 6 + (1 - (vv - lo) / (hi - lo)) * (H - B - 6);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const area = `${path} L${x(pts.at(-1)!.t).toFixed(1)},${H - B} L${x(pts[0]!.t).toFixed(1)},${H - B} Z`;
  const last = pts.at(-1)!;
  const h = hover === null ? null : pts.reduce((best, p) => (Math.abs(x(p.t) - hover) < Math.abs(x(best.t) - hover) ? p : best), pts[0]!);
  return <figure className="dash-chart">
    <figcaption><b>{title}</b> <small>{unit}</small><span className="dash-chart-now">{last.v.toFixed(digits)}</span></figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} onPointerMove={(e) => {
      const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
      setHover(((e.clientX - r.left) / r.width) * W);
    }} onPointerLeave={() => setHover(null)} role="img" aria-label={title}>
      {[lo + pad, (lo + hi) / 2, hi - pad].map((g) => <g key={g}>
        <line x1={L} x2={W - 6} y1={y(g)} y2={y(g)} className="dash-chart-grid" />
        <text x={L - 4} y={y(g) + 3} textAnchor="end" className="dash-chart-axis">{g.toFixed(digits)}</text>
      </g>)}
      <text x={L} y={H - 4} className="dash-chart-axis">−{Math.round(span / 1000)}s</text>
      <text x={W - 6} y={H - 4} textAnchor="end" className="dash-chart-axis">{t('dash.now')}</text>
      <path d={area} className="dash-chart-area" />
      <path d={path} className="dash-chart-line" />
      <circle cx={x(last.t)} cy={y(last.v)} r={4} className="dash-chart-end" />
      {h && <g>
        <line x1={x(h.t)} x2={x(h.t)} y1={6} y2={H - B} className="dash-chart-cross" />
        <circle cx={x(h.t)} cy={y(h.v)} r={4} className="dash-chart-end" />
      </g>}
    </svg>
    {h && <div className="dash-chart-tip"><b>{h.v.toFixed(digits)} {unit}</b> <span>{t('dash.secAgo', { s: ((now - h.t) / 1000).toFixed(1) })}</span></div>}
  </figure>;
}

// ── 패널들 ─────────────────────────────────────────────────────────────────

function Panel({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  return <section className={`dash-panel${wide ? ' dash-panel--wide' : ''}`}><h4>{title}</h4>{children}</section>;
}

function Row({ k, v, level }: { k: string; v: ReactNode; level?: Level }) {
  return <div className="dash-row"><dt>{k}</dt><dd className={level ? `dash-v--${level}` : ''}>{v}</dd></div>;
}

function GpsPanel({ v }: { v: View }) {
  useLang();
  const f = v.extended ? v.fcx : null;
  const g = f?.gps;
  const rtk = f?.rtk;
  const home = f?.home;
  return <dl className="dash-rows">
    <Row k={t('dash.gps.fix')} v={<><RtkBadge level={rtkLevel(v.fixType, v.fix)} /> {v.fix ?? '—'}</>} />
    <Row k={t('dash.gps.sats')} v={v.sats ?? '—'} />
    <Row k="HDOP · VDOP" v={`${fmt(g?.hdop, 2)} · ${fmt(g?.vdop, 2)}`} level={g?.hdop == null ? undefined : g.hdop <= 1 ? 'good' : g.hdop <= 2 ? 'warn' : 'bad'} />
    <Row k={t('dash.gps.acc')} v={`${fmt(g?.hAccM, 3)} m · ${fmt(g?.vAccM, 3)} m`} />
    <Row k={t('dash.gps.baseline')} v={rtk ? `${fmt(rtk.baselineM, 1)} m · ±${rtk.accuracyMm ?? '—'} mm · IAR ${rtk.iarHypotheses ?? '—'}` : '—'} />
    <Row k={t('dash.gps.pos')} v={v.lat === null ? '—' : `${v.lat.toFixed(7)}, ${v.lon?.toFixed(7)}`} />
    <Row k={t('dash.gps.alt')} v={`${fmt(v.altRelM, 2)} m${f?.position?.altMslM != null ? ` · MSL ${fmt(f.position.altMslM, 1)} m` : ''}`} />
    <Row k={t('dash.gps.home')} v={home?.lat != null ? `${home.lat.toFixed(7)}, ${home.lon?.toFixed(7)}` : '—'} />
  </dl>;
}

function SensorsPanel({ v }: { v: View }) {
  useLang();
  const s = v.extended ? v.fcx?.sensors : null;
  if (!s || s.length === 0) return <p className="sar-empty">{t('dash.needFcx')}</p>;
  return <div className="dash-sensors">
    {s.map((x) => <Chip key={x.name} level={!x.enabled ? 'unknown' : x.healthy ? 'good' : 'bad'} label={x.name.replaceAll('_', ' ')} />)}
    <small className="sar-hint">{t('dash.load', { load: fmt(v.fcx?.loadPct, 0), drop: fmt(v.fcx?.dropRatePct, 1) })}</small>
  </div>;
}

function VibrationPanel({ v }: { v: View }) {
  useLang();
  const vib = v.extended ? v.fcx?.vibration : null;
  if (!vib) return <p className="sar-empty">{t('dash.needFcx')}</p>;
  // QGC 기준: 30 m/s² 넘으면 주의, 60 넘으면 위험
  const MAX = 90;
  return <div className="dash-bars">
    {(['x', 'y', 'z'] as const).map((k) => {
      const val = vib[k];
      const level: Level = val === null ? 'unknown' : val < 30 ? 'good' : val < 60 ? 'warn' : 'bad';
      return <div key={k} className="dash-bar">
        <span>{k.toUpperCase()}</span>
        <div className="dash-bar-track"><i className={`dash-bar-fill dash-bar-fill--${level}`} style={{ width: `${Math.min(100, ((val ?? 0) / MAX) * 100)}%` }} />
          <em style={{ left: `${(30 / MAX) * 100}%` }} /><em style={{ left: `${(60 / MAX) * 100}%` }} /></div>
        <b>{fmt(val, 1)}</b>
      </div>;
    })}
    <small className="sar-hint">{t('dash.vibHint', { c: vib.clipping.join(' / ') || '—' })}</small>
  </div>;
}

function BatteryPanel({ v }: { v: View }) {
  useLang();
  const b = v.extended ? v.fcx?.battery : null;
  return <>
    <dl className="dash-rows">
      <Row k={t('dash.bat.voltage')} v={`${fmt(v.batteryV, 2)} V`} />
      <Row k={t('dash.bat.remaining')} v={v.batteryPct === null ? '—' : `${Math.round(v.batteryPct)} %`} />
      <Row k={t('dash.bat.current')} v={`${fmt(b?.currentA, 1)} A · ${b?.consumedMah ?? '—'} mAh`} />
      <Row k={t('dash.bat.temp')} v={`${fmt(b?.temperatureC, 1)} °C`} />
    </dl>
    {b && b.cellsV.length > 0 && <div className="dash-bars">
      {b.cellsV.map((cv, i) => {
        const level: Level = cv >= 3.7 ? 'good' : cv >= 3.5 ? 'warn' : 'bad';
        return <div key={i} className="dash-bar"><span>{t('dash.bat.cell', { n: i + 1 })}</span>
          <div className="dash-bar-track"><i className={`dash-bar-fill dash-bar-fill--${level}`} style={{ width: `${Math.max(0, Math.min(100, ((cv - 3.3) / 0.9) * 100))}%` }} /></div>
          <b>{cv.toFixed(3)}</b></div>;
      })}
      <small className="sar-hint">{t('dash.bat.spread', { mv: Math.round((Math.max(...b.cellsV) - Math.min(...b.cellsV)) * 1000) })}</small>
    </div>}
  </>;
}

function ConsolePanel({ v }: { v: View }) {
  useLang();
  const [onlyWarn, setOnlyWarn] = useState(false);
  const fromFcx = v.fcx?.console ?? [];
  const fromState = (() => {
    const w = telemetryValue(v.deviceId, 'warnings');
    return Array.isArray(w) ? w.map((x) => x as Record<string, unknown>).filter((x) => typeof x.text === 'string')
      .map((x) => ({ t: 0, severity: String(x.severity ?? 'INFO'), level: 4, text: x.text as string })) : [];
  })();
  const lines = (fromFcx.length > 0 ? fromFcx : fromState).filter((l) => !onlyWarn || l.level <= 4);
  return <div className="dash-console">
    <label className="sar-check"><input type="checkbox" checked={onlyWarn} onChange={(e) => setOnlyWarn(e.target.checked)} />{t('dash.console.warnOnly')}</label>
    {lines.length === 0 ? <p className="sar-empty">{t('dash.console.empty')}</p> : <ol>
      {[...lines].reverse().map((l, i) => {
        const level: Level = l.level <= 3 ? 'bad' : l.level === 4 ? 'warn' : 'good';
        return <li key={`${l.t}-${i}`} className={`dash-console--${level}`}>
          <time>{l.t ? new Date(l.t * 1000).toLocaleTimeString(undefined, { hour12: false }) : ''}</time>
          <span className={`dash-sev dash-sev--${level}`}>{l.severity}</span>
          <span>{l.text}</span>
        </li>;
      })}
    </ol>}
  </div>;
}

// ── 노드 ───────────────────────────────────────────────────────────────────

export function DroneDashCard() {
  useLang();
  useTick(1000);
  const views = useDroneViews();
  if (views.length === 0) return <p className="sar-empty">{t('dash.noDevice')}</p>;
  return <div className="dash-card">
    {views.map((v) => <div key={v.deviceId}>
      <b>{v.deviceId}</b>{!v.extended && <small className="sar-hint"> · {t('dash.basicOnly')}</small>}
      <StatusBar v={v} compact />
      <div className="dash-card-numbers">
        <span>{t('dash.altShort')} <b>{fmt(v.altRelM)}</b> m</span>
        <span>{t('dash.speedShort')} <b>{fmt(v.groundspeed)}</b> m/s</span>
        <span>{t('dash.yawShort')} <b>{v.yawDeg === null ? '—' : Math.round(v.yawDeg)}</b>°</span>
      </div>
    </div>)}
  </div>;
}

export function DroneDashZoom() {
  useLang();
  useTick(500);
  const views = useDroneViews();
  const [pick, setPick] = useState<string | null>(null);
  const v = views.find((x) => x.deviceId === pick) ?? views[0];
  const homeBearing = useMemo(() => {
    const h = v?.fcx?.home;
    return v && h?.lat != null && h.lon != null && v.lat !== null && v.lon !== null ? bearing({ lat: v.lat, lon: v.lon }, { lat: h.lat, lon: h.lon }) : null;
  }, [v]);
  if (v === undefined) return <div className="sar-zoom"><p className="sar-empty">{t('dash.noDevice')}</p><p className="sar-hint">{t('dash.howTo')}</p></div>;
  const samples = v.fcx?.history ?? [];
  return <div className="sar-zoom dash-zoom">
    <div className="dash-head">
      {views.length > 1 ? <select value={v.deviceId} onChange={(e) => setPick(e.target.value)}>
        {views.map((x) => <option key={x.deviceId} value={x.deviceId}>{x.deviceId}</option>)}
      </select> : <h3>{v.deviceId}</h3>}
      <span className={v.extended ? 'sar-ok' : 'sar-warn'}>{v.extended ? t('dash.extended') : t('dash.basicOnly')}</span>
    </div>
    <StatusBar v={v} />
    {!v.extended && <p className="sar-hint">{t('dash.howTo')}</p>}
    <div className="dash-grid">
      <Panel title={t('dash.attitude')}><div className="dash-instruments"><Attitude roll={v.rollDeg} pitch={v.pitchDeg} /><Compass yaw={v.yawDeg} homeBearing={homeBearing} /></div></Panel>
      <Panel title={t('dash.map')}><TrackMap v={v} /></Panel>
      <Panel title={t('dash.charts')} wide>
        {v.extended ? <div className="dash-charts">
          <LineChart title={t('dash.chart.alt')} unit="m" samples={samples} pick={(s) => s.altRelM} />
          <LineChart title={t('dash.chart.speed')} unit="m/s" samples={samples} pick={(s) => s.groundspeed} digits={2} />
          <LineChart title={t('dash.chart.climb')} unit="m/s" samples={samples} pick={(s) => s.climb} digits={2} />
          <LineChart title={t('dash.chart.voltage')} unit="V" samples={samples} pick={(s) => s.voltageV} digits={2} />
        </div> : <p className="sar-empty">{t('dash.needFcx')}</p>}
      </Panel>
      <Panel title={t('dash.gps.title')}><GpsPanel v={v} /></Panel>
      <Panel title={t('dash.sensors')}><SensorsPanel v={v} /></Panel>
      <Panel title={t('dash.vibration')}><VibrationPanel v={v} /></Panel>
      <Panel title={t('dash.battery')}><BatteryPanel v={v} /></Panel>
      <Panel title={t('dash.console')} wide><ConsolePanel v={v} /></Panel>
    </div>
  </div>;
}
