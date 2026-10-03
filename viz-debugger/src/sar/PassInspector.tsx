// 패스 자세히 보기 — 궤적 CSV(50 Hz)로 「어디서 · 왜」 틀어졌는지 보고, 그 순간을 지도에서 다시 재생한다.
//
// 가로축은 모두 진행 거리(m, 캡처 구간 0~길이)이고 지표마다 작은 차트 하나(축 하나)다.
// 회색 띠 = 허용 범위(판정 기준), 연한 칸 = 레이더가 실제로 기록한 구간. 커서는 모든 차트 · 지도에서 같이 움직인다.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { SatMap, type Area, type TrackPoint } from '../dronedash/SatMap.tsx';
import { liveBeam, readAntenna, readReflectors, reflectorMarkers } from './liveBeam.ts';

type Row = {
  t: number; lat: number; lon: number; along: number; cross: number; speed: number; altRel: number;
  yaw: number; roll: number; pitch: number; vn: number; ve: number; cap: boolean; ack: boolean;
};
type Meta = {
  plan?: Record<string, number | string | boolean>;
  line?: { length_m: number; heading_deg: number };
  pass?: { pass_no: number; valid: boolean | null; reasons: string[] };
};

const numOr = (v: string | undefined, d = NaN) => (v === undefined || v === '' ? d : Number(v));
const wrap = (d: number) => ((d + 540) % 360) - 180;

export function parseTrajCsv(text: string): Row[] {
  const lines = text.trim().split(/\r?\n/);
  const head = lines.shift()?.split(',') ?? [];
  const ix = (k: string) => head.indexOf(k);
  const c = Object.fromEntries(['t_pi', 't_fc', 'lat', 'lon', 'along_m', 'cross_m', 'speed_avg', 'alt_rel_m', 'yaw_deg', 'roll_deg',
    'pitch_deg', 'vn', 've', 'cap_on', 'cap_ack'].map((k) => [k, ix(k)]));
  return lines.map((l) => {
    const f = l.split(',');
    const tf = numOr(f[c.t_fc!]);
    return {
      t: Number.isFinite(tf) ? tf : numOr(f[c.t_pi!]), lat: numOr(f[c.lat!]), lon: numOr(f[c.lon!]),
      along: numOr(f[c.along_m!]), cross: numOr(f[c.cross_m!]), speed: numOr(f[c.speed_avg!]), altRel: numOr(f[c.alt_rel_m!]),
      yaw: numOr(f[c.yaw_deg!], 0), roll: numOr(f[c.roll_deg!], 0), pitch: numOr(f[c.pitch_deg!], 0),
      vn: numOr(f[c.vn!], 0), ve: numOr(f[c.ve!], 0), cap: f[c.cap_on!] === '1', ack: f[c.cap_ack!] === '1',
    };
  }).filter((r) => Number.isFinite(r.t) && Number.isFinite(r.along));
}

/** 0.5 s 평균 속도 방향 − 선 방위 (드론 sar_pass.mission.course_error_deg 와 같은 정의). */
export function courseSeries(rows: readonly Row[], headingDeg: number, windowS = 0.5): (number | null)[] {
  const out: (number | null)[] = [];
  let j = 0; let sn = 0; let se = 0;
  for (let i = 0; i < rows.length; i++) {
    sn += rows[i]!.vn; se += rows[i]!.ve;
    while (rows[j]!.t < rows[i]!.t - windowS) { sn -= rows[j]!.vn; se -= rows[j]!.ve; j++; }
    const n = i - j + 1;
    out.push(rows[i]!.t - rows[0]!.t < 0.9 * windowS || Math.hypot(sn, se) / n < 0.5 ? null : wrap((Math.atan2(se, sn) * 180) / Math.PI - headingDeg));
  }
  return out;
}

function meanIn(rows: readonly Row[], length: number, f: (r: Row) => number): number {
  const v = rows.filter((r) => r.along >= 0 && r.along <= length).map(f);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0;
}

type Series = { key: string; unit: string; values: (number | null)[]; tol: number | null; center: number; digits: number };

function Chart({ s, xs, cursor, onCursor, capture, length, xMin, xMax }: {
  s: Series; xs: readonly number[]; cursor: number; onCursor: (i: number) => void;
  capture: [number, number] | null; length: number; xMin: number; xMax: number;
}) {
  useLang();
  const W = 640; const H = 92; const L = 46; const R = 8; const T = 8; const B = 18;
  // 세로 범위는 판정 구간(0~길이)의 값으로만 — 가속 · 감속 중 값까지 넣으면 판정 구간이 납작해진다. 넘는 선은 잘린다
  const vals = s.values.filter((v, i): v is number => v !== null && Number.isFinite(v) && xs[i]! >= 0 && xs[i]! <= length);
  const span = Math.max(...vals.map((v) => Math.abs(v - s.center)), (s.tol ?? 0) * 1.3, 1e-6) * 1.1;
  const y0 = s.center - span; const y1 = s.center + span;
  const X = (x: number) => L + ((x - xMin) / (xMax - xMin || 1)) * (W - L - R);
  const Y = (y: number) => T + (1 - (y - y0) / (y1 - y0 || 1)) * (H - T - B);
  const segs: string[] = []; let cur = '';
  s.values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v) || xs[i]! < xMin || xs[i]! > xMax) { if (cur) segs.push(cur); cur = ''; return; }
    cur += `${cur ? 'L' : 'M'}${X(xs[i]!).toFixed(1)},${Y(v).toFixed(1)}`;
  });
  if (cur) segs.push(cur);
  const over = s.tol === null ? [] : s.values.map((v, i) => (v !== null && Math.abs(v - s.center) > s.tol! && xs[i]! >= 0 && xs[i]! <= length ? i : -1)).filter((i) => i >= 0);
  const cv = s.values[cursor];
  const pick = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = xMin + ((e.clientX - r.left) / r.width * W - L) / (W - L - R) * (xMax - xMin);
    let best = 0; let bd = Infinity;
    xs.forEach((v, i) => { const d = Math.abs(v - x); if (d < bd) { bd = d; best = i; } });
    onCursor(best);
  };
  return <div className="pi-chart">
    <div className="pi-chart-head"><b>{t(s.key)}</b>
      <span className={cv !== null && cv !== undefined && s.tol !== null && Math.abs(cv - s.center) > s.tol ? 'sar-bad' : ''}>
        {cv === null || cv === undefined ? '—' : cv.toFixed(s.digits)} {s.unit}</span>
      {s.tol !== null && <small>{t('pi.tol', { v: s.tol.toFixed(s.digits), u: s.unit })}</small>}
      {over.length > 0 && <small className="sar-bad">{t('pi.over', { n: over.length })}</small>}
    </div>
    <svg viewBox={`0 0 ${W} ${H}`} className="pi-svg" onPointerMove={pick} onPointerDown={pick} role="img" aria-label={t(s.key)}>
      {capture && <rect x={X(capture[0])} y={T} width={Math.max(0, X(capture[1]) - X(capture[0]))} height={H - T - B} className="pi-cap" />}
      {s.tol !== null && <rect x={L} y={Y(s.center + s.tol)} width={W - L - R} height={Math.max(0, Y(s.center - s.tol) - Y(s.center + s.tol))} className="pi-tol" />}
      <line x1={L} x2={W - R} y1={Y(s.center)} y2={Y(s.center)} className="pi-zero" />
      {[0, length].map((x) => <line key={x} x1={X(x)} x2={X(x)} y1={T} y2={H - B} className="pi-edge" />)}
      <clipPath id={`pi-clip-${s.key}`}><rect x={L} y={T} width={W - L - R} height={H - T - B} /></clipPath>
      <g clipPath={`url(#pi-clip-${s.key})`}>{segs.map((d, i) => <path key={i} d={d} className="pi-line" />)}</g>
      {over.filter((_, k) => k % 3 === 0).map((i) => <circle key={i} cx={X(xs[i]!)} cy={Y(s.values[i]!)} r={2.5} className="pi-over" />)}
      <line x1={X(xs[cursor] ?? 0)} x2={X(xs[cursor] ?? 0)} y1={T} y2={H - B} className="pi-cursor" />
      <text x={L - 4} y={Y(y1) + 8} className="pi-ax" textAnchor="end">{(y1).toFixed(s.digits)}</text>
      <text x={L - 4} y={Y(y0)} className="pi-ax" textAnchor="end">{(y0).toFixed(s.digits)}</text>
      <text x={X(0)} y={H - 4} className="pi-ax" textAnchor="middle">0</text>
      <text x={X(length)} y={H - 4} className="pi-ax" textAnchor="middle">{length.toFixed(0)} m</text>
    </svg>
  </div>;
}

export function PassInspector({ base, flight, csvName, metaName }: { base: string; flight: string; csvName: string; metaName: string }) {
  useLang();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(2);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    const f = (n: string) => `${base}/api/flights/${encodeURIComponent(flight)}/files/${encodeURIComponent(n)}`;
    Promise.all([fetch(f(csvName)).then((r) => r.text()), fetch(f(metaName)).then((r) => r.json() as Promise<Meta>)])
      .then(([csv, m]) => { if (alive) { const rs = parseTrajCsv(csv); setRows(rs); setMeta(m); setCursor(Math.max(0, rs.findIndex((r) => r.cap))); } })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [base, flight, csvName, metaName]);

  // 재생 — 기록 시각 그대로(배속)
  useEffect(() => {
    if (!playing || rows === null) return;
    let last = performance.now();
    const step = (now: number) => {
      const dt = ((now - last) / 1000) * rate; last = now;
      setCursor((c) => {
        const target = rows[c]!.t + dt;
        let i = c;
        while (i < rows.length - 1 && rows[i + 1]!.t <= target) i++;
        if (i >= rows.length - 1) { setPlaying(false); return rows.length - 1; }
        return i === c ? Math.min(c + 1, rows.length - 1) : i;
      });
      timer.current = requestAnimationFrame(step);
    };
    timer.current = requestAnimationFrame(step);
    return () => { if (timer.current !== null) cancelAnimationFrame(timer.current); };
  }, [playing, rate, rows]);

  const derived = useMemo(() => {
    if (rows === null || meta === null) return null;
    const p = meta.plan ?? {};
    const heading = meta.line?.heading_deg ?? Number(p.heading_deg ?? 0);
    const length = meta.line?.length_m ?? 0;
    const speed = Number(p.speed_mps ?? 4); const alt = Number(p.alt_m ?? 20);
    const xs = rows.map((r) => r.along);
    const series: Series[] = [
      { key: 'pi.s.speed', unit: 'm/s', values: rows.map((r) => r.speed), tol: Number(p.q_speed_mps ?? 0.3), center: speed, digits: 2 },
      { key: 'pi.s.cross', unit: 'm', values: rows.map((r) => r.cross), tol: Number(p.q_cross_m ?? 1), center: 0, digits: 2 },
      { key: 'pi.s.alt', unit: 'm', values: rows.map((r) => r.altRel - alt), tol: Number(p.q_alt_m ?? 0.5), center: 0, digits: 2 },
      { key: 'pi.s.yaw', unit: '°', values: rows.map((r) => wrap(r.yaw - heading)), tol: Number(p.q_heading_deg ?? 3), center: 0, digits: 1 },
      { key: 'pi.s.course', unit: '°', values: courseSeries(rows, heading), tol: Number(p.q_course_deg ?? 10), center: 0, digits: 1 },
      // 기준이 없는 자세는 캡처 구간 평균을 가운데로 — 흔들림이 보이게
      { key: 'pi.s.roll', unit: '°', values: rows.map((r) => r.roll), tol: null, center: meanIn(rows, length, (r) => r.roll), digits: 1 },
      { key: 'pi.s.pitch', unit: '°', values: rows.map((r) => r.pitch), tol: null, center: meanIn(rows, length, (r) => r.pitch), digits: 1 },
    ];
    const capIdx = rows.map((r, i) => (r.ack || r.cap ? i : -1)).filter((i) => i >= 0);
    const capture: [number, number] | null = capIdx.length ? [xs[capIdx[0]!]!, xs[capIdx[capIdx.length - 1]!]!] : null;
    const track: TrackPoint[] = rows.filter((_, i) => i % 5 === 0).map((r) => ({ lat: r.lat, lon: r.lon, t: r.t * 1000, alt: r.altRel, speed: r.speed, capture: r.cap }));
    // 가로 범위: 캡처 구간 앞뒤 15 m — 이동 · 가속 구간 전체는 지도에서 본다
    return { heading, length, xs, series, capture, track, xMin: Math.max(Math.min(...xs), -15), xMax: Math.min(Math.max(...xs), length + 15) };
  }, [rows, meta]);

  if (err !== null) return <p className="sar-bad">{t('img.reqFail', { why: err })}</p>;
  if (rows === null || derived === null) return <p className="sar-hint">{t('sar.data.loading')}</p>;
  const r = rows[cursor]!;
  const antenna = readAntenna();
  const reflectors = readReflectors();
  const beam = liveBeam(antenna, { at: { lat: r.lat, lon: r.lon }, altM: r.altRel, yawDeg: r.yaw, pitchDeg: r.pitch, rollDeg: r.roll }, reflectors);
  const p = meta?.plan ?? {};
  const sarLine = p.start_lat != null ? { start: { lat: Number(p.start_lat), lon: Number(p.start_lon) }, end: { lat: Number(p.end_lat), lon: Number(p.end_lon) } } : null;
  const areas: Area[] = beam.area ? [beam.area] : [];
  const tRel = r.t - rows[0]!.t;
  return <div className="pi">
    <div className="pi-top">
      <div className="pi-map">
        <SatMap track={derived.track} drone={{ lat: r.lat, lon: r.lon }} droneYaw={r.yaw} sarLine={sarLine} capturing={r.cap}
          markers={reflectorMarkers(reflectors, beam.lit)} areas={areas} height={330} />
      </div>
      <div className="pi-now">
        <div className="pi-play">
          <button type="button" className="pi-main" onClick={() => { if (cursor >= rows.length - 1) setCursor(0); setPlaying(!playing); }}>
            {playing ? t('pi.pause') : t('pi.play')}</button>
          {[1, 2, 5].map((k) => <button key={k} type="button" className={rate === k ? 'active' : ''} onClick={() => setRate(k)}>{k}×</button>)}
        </div>
        <input type="range" min={0} max={rows.length - 1} value={cursor} onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }} className="pi-scrub" aria-label={t('pi.scrub')} />
        <dl className="pi-dl">
          <div><dt>{t('pi.time')}</dt><dd>{tRel.toFixed(2)} s</dd></div>
          <div><dt>{t('pi.along')}</dt><dd>{r.along.toFixed(1)} m</dd></div>
          <div><dt>{t('pi.phase')}</dt><dd className={r.ack || r.cap ? 'pi-rec' : ''}>{r.ack ? t('pi.rec.ack') : r.cap ? t('pi.rec.on') : t('pi.rec.off')}</dd></div>
          <div><dt>{t('pi.s.speed')}</dt><dd>{r.speed.toFixed(2)} m/s</dd></div>
          <div><dt>{t('pi.att')}</dt><dd>{t('pi.attVal', { r: r.roll.toFixed(1), p: r.pitch.toFixed(1), y: r.yaw.toFixed(1) })}</dd></div>
          <div><dt>{t('pi.beam')}</dt><dd>{beam.lit.size > 0 ? t('pi.beamLit', { list: [...beam.lit].map((i) => `CR${i + 1}`).join(', ') }) : t('pi.beamNone')}</dd></div>
        </dl>
        {meta?.pass && <p className={meta.pass.valid ? 'sar-ok' : 'sar-bad'}>
          {meta.pass.valid ? `✓ ${t('sar.log.valid')}` : `✕ ${t('sar.log.invalid')} — ${meta.pass.reasons.join(' · ')}`}</p>}
        <small className="sar-hint">{t('pi.legend')}</small>
      </div>
    </div>
    <div className="pi-charts">
      {derived.series.map((s) => <Chart key={s.key} s={s} xs={derived.xs} cursor={cursor} onCursor={(i) => { setPlaying(false); setCursor(i); }}
        capture={derived.capture} length={derived.length} xMin={derived.xMin} xMax={derived.xMax} />)}
    </div>
  </div>;
}
