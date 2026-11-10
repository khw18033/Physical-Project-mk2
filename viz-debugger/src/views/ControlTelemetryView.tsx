/**
 * src/views/ControlTelemetryView.tsx (261111 신설 — 조작 기록 2차)
 *
 * **조작 판의 텔레메트리 표본을 판 전체 구간으로 그린다.** 실시간 상태 그래프와 같은 그래프 칸(`dronedash/Trend.tsx`)을
 * 쓰되, 창은 「최근 2분」이 아니라 판의 시작 ~ 끝이고, 점선은 이 판에서 명령을 낸 순간이다 — 「이 명령 뒤에 속도가
 * 올랐다 · 배터리가 떨어졌다」를 한 화면에서 잇는다. 위치가 있으면 이동 경로도 그린다.
 *
 * 표본의 빈칸(null)은 「그때 안 왔다」이다. 점을 만들지 않으므로 선이 끊기고 회색으로 비워진다 — 지어 잇지 않는다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import type { ControlEvent, ControlProgress, ControlRecordSummary } from '../record/controlRecorder.ts';
import type { MetricPoint, StatePoint } from '../shared/metricHistory.ts';
import { GraphGrid, GraphStat } from '../dronedash/Trend.tsx';
import '../dronedash/dronedash.css';

type Telemetry = NonNullable<ControlProgress['telemetry']>;

const clockWords = (ms: number) => new Date(ms).toLocaleTimeString([], { hour12: false });

/** 숫자 칸 — 단위 · 자릿수 · 세로축 최소 폭 · 계단인가. 이 차례로 그린다. */
const LINES: ReadonlyArray<{ key: string; unit: string; digits: number; minSpan: number; stair?: boolean }> = [
  { key: 'batteryPct', unit: '%', digits: 0, minSpan: 5, stair: true },
  { key: 'voltageV', unit: 'V', digits: 2, minSpan: 0.2 },
  { key: 'speedMps', unit: 'm/s', digits: 2, minSpan: 0.5 },
  { key: 'altM', unit: 'm', digits: 1, minSpan: 2 },
  { key: 'headingDeg', unit: '°', digits: 0, minSpan: 20 },
  { key: 'rxAgeS', unit: 's', digits: 1, minSpan: 2 },
];
/** 낱말 칸 — 참/거짓은 사전으로, 나머지는 장비가 보낸 규약 문자열 그대로. */
const LANES = ['mode', 'armed', 'gpsFix', 'link'] as const;

function columnOf(telemetry: Telemetry, key: string): number {
  return telemetry.columns.indexOf(key);
}

function numbers(telemetry: Telemetry, key: string): MetricPoint[] {
  const index = columnOf(telemetry, key);
  if (index < 0) return [];
  return telemetry.rows.flatMap((row) => (typeof row[index] === 'number' ? [{ atMs: row[0] as number, v: row[index] as number }] : []));
}

function words(telemetry: Telemetry, key: string): StatePoint[] {
  const index = columnOf(telemetry, key);
  if (index < 0) return [];
  return telemetry.rows.flatMap((row) => (typeof row[index] === 'string' ? [{ atMs: row[0] as number, code: row[index] as string }] : []));
}

/** 이동 경로 — 위도 · 경도면 시작점 기준 미터로 펴고, 지도 좌표면 그대로. 북쪽(+y)이 위. 빈칸에서 선을 끊는다. */
function Track({ telemetry }: { telemetry: Telemetry }) {
  useLang();
  const geo = columnOf(telemetry, 'lat') >= 0 && columnOf(telemetry, 'lon') >= 0;
  const [kx, ky] = geo ? ['lon', 'lat'] : ['x', 'y'];
  const ix = columnOf(telemetry, kx);
  const iy = columnOf(telemetry, ky);
  if (ix < 0 || iy < 0) return null;
  const raw = telemetry.rows.map((row) => (typeof row[ix] === 'number' && typeof row[iy] === 'number' ? [row[ix] as number, row[iy] as number] as const : null));
  const first = raw.find((p) => p !== null);
  if (first === undefined || first === null) return null;
  const toMeters = (p: readonly [number, number]): [number, number] => geo
    ? [(p[0] - first[0]) * 111_320 * Math.cos((first[1] * Math.PI) / 180), (p[1] - first[1]) * 110_540]
    : [p[0], p[1]];
  const pts = raw.map((p) => (p === null ? null : toMeters(p)));
  const real = pts.filter((p): p is [number, number] => p !== null);
  const xs = real.map((p) => p[0]);
  const ys = real.map((p) => p[1]);
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1);
  const pad = span * 0.08;
  const minX = Math.min(...xs) - pad;
  const maxY = Math.max(...ys) + pad;
  const w = Math.max(...xs) - Math.min(...xs) + pad * 2;
  const h = Math.max(...ys) - Math.min(...ys) + pad * 2;
  let d = '';
  let pen = false;
  for (const p of pts) {
    if (p === null) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${(p[0] - minX).toFixed(3)},${(maxY - p[1]).toFixed(3)}`;
    pen = true;
  }
  const start = real[0]!;
  const end = real.at(-1)!;
  const r = span * 0.025;
  return <figure className="ctl-track">
    <figcaption>
      <b>{t('ctl.tel.track')}</b> <small>{t(geo ? 'ctl.tel.trackGeo' : 'ctl.tel.trackMap')} · {t('ctl.tel.trackSpan', { m: span.toFixed(1) })}</small>
      <span className="ctl-track__legend"><i className="is-start" />{t('ctl.tel.start')} <i className="is-end" />{t('ctl.tel.end')}</span>
    </figcaption>
    <svg viewBox={`0 0 ${w.toFixed(3)} ${h.toFixed(3)}`} role="img" aria-label={t('ctl.tel.track')}>
      <path className="ctl-track__line" d={d} vectorEffect="non-scaling-stroke" />
      <circle className="ctl-track__start" cx={start[0] - minX} cy={maxY - start[1]} r={r} />
      <circle className="ctl-track__end" cx={end[0] - minX} cy={maxY - end[1]} r={r} />
    </svg>
  </figure>;
}

export function ControlTelemetrySection({ summary, progress, events }: {
  summary: ControlRecordSummary; progress: ControlProgress; events: readonly ControlEvent[];
}) {
  useLang();
  const telemetry = progress.telemetry;
  if (telemetry === undefined || telemetry.rows.length === 0) {
    return <section className="ctl-telemetry"><h3>{t('ctl.tel.title')}</h3><p className="ctl-pad">{t('ctl.tel.none')}</p></section>;
  }
  const startMs = Date.parse(summary.startedAtIso);
  const lastRow = telemetry.rows.at(-1)![0] as number;
  const endMs = Math.max(summary.endedAtIso === null ? lastRow : Date.parse(summary.endedAtIso), lastRow, startMs + 10_000);
  const windowMs = endMs - startMs;
  // 유지 신호(teleop 반복)는 점선이 빽빽해져 아무것도 못 읽는다 — 사람이 낸 명령만.
  const marks = events.filter((e) => e.kind === 'commanded').map((e) => e.atMs);
  const s = summary.telemetry ?? null;
  const fmt = (v: number | undefined, digits: number) => (v === undefined ? '—' : v.toFixed(digits));
  return <section className="ctl-telemetry">
    <h3>{t('ctl.tel.title')}</h3>
    {s !== null && <p className="ctl-pad ctl-telemetry__summary">
      {t('ctl.tel.summary', { n: s.samples, start: s.batteryStart ?? '—', end: s.batteryEnd ?? '—', min: s.batteryMin ?? '—', age: s.maxRxAgeS ?? '—' })}
      {s.modes.length > 0 && <> · {t('ctl.tel.modes', { modes: s.modes.join(' → ') })}</>}
      {s.truncated && <> · <b>{t('ctl.tel.truncated')}</b></>}
    </p>}
    <p className="ctl-pad ctl-telemetry__hint">{t('ctl.tel.marks')}</p>
    <GraphGrid axis={[clockWords(startMs), clockWords(endMs)]}>
      {LINES.filter((spec) => columnOf(telemetry, spec.key) >= 0).map((spec) => {
        const points = numbers(telemetry, spec.key);
        const value = points.length === 0 ? '—'
          : `${fmt(points[0]?.v, spec.digits)} → ${fmt(points.at(-1)?.v, spec.digits)} ${spec.unit}`;
        return <GraphStat key={spec.key} now={endMs} windowMs={windowMs} marks={marks} live={false}
          level={points.length === 0 ? 'unknown' : 'good'} label={t(`ctl.tel.col.${spec.key}`)} value={value}
          title={points.length === 0 ? undefined : t('ctl.tel.range', { min: Math.min(...points.map((p) => p.v)).toFixed(spec.digits), max: Math.max(...points.map((p) => p.v)).toFixed(spec.digits), unit: spec.unit })}
          graph={{ kind: 'line', points, minSpan: spec.minSpan, stair: spec.stair }} />;
      })}
      {LANES.filter((key) => columnOf(telemetry, key) >= 0).map((key) => {
        const points = words(telemetry, key);
        const labelOf = (code: string) => (key === 'armed' ? t(code === 'true' ? 'dash.armed' : 'dash.disarmed') : code);
        return <GraphStat key={key} now={endMs} windowMs={windowMs} marks={marks} live={false}
          level={points.length === 0 ? 'unknown' : 'good'} label={t(`ctl.tel.col.${key}`)}
          value={points.length === 0 ? '—' : labelOf(points.at(-1)!.code)}
          graph={{ kind: 'lane', points, labelOf }} />;
      })}
    </GraphGrid>
    <Track telemetry={telemetry} />
  </section>;
}
