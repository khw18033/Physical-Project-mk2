/**
 * src/sar/SarPassView.tsx (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **SAR 패스 노드.** 접힘 = 지금 상태 한 줄(몇 번째 패스 · 캡처 중인가 · 속도). 확대 = 계획 → 미리보기 →
 * 실행 → 진행 → 패스 기록.
 *
 * 화면은 **계획 · 명령 · 감시**만 한다. 비행과 CAP_ON 은 드론의 `sar_pass` 실행기가 맡는다 — 브라우저는 드론의
 * 파일을 만질 수 없고, 링크가 끊겨도 캡처는 드론 안에서 꺼져야 하기 때문이다.
 */

import { useMemo, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { telemetryValue, useDeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { SAR_FINISHED, isSarStale, useSarReports, type SarReport, type SarState } from '../shared/sarStatus.ts';
import {
  issueSarAbort, issueSarStart, sarLink, type SarIssueOutcome, type SarLink,
} from '../physical/sarCommands.ts';
import {
  SAR_RULES, alongCross, autoLeadInM, defaultDraft, endFrom, lineOf, planEstimate, planProblems, toLocal,
  toStartParams, type LatLon, type SarPlanDraft,
} from './plan.ts';
import { RTK_LABEL_KEY, rtkLevel } from './rtk.ts';
import { RtkBadge } from './RtkView.tsx';
import { useTick } from './useTick.ts';
import './sar.css';

const DRAFT_KEY = 'viz.sar.draft.v1';

function loadDraft(): SarPlanDraft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (raw !== null) return { ...defaultDraft(), ...JSON.parse(raw) as Partial<SarPlanDraft> };
  } catch { /* 저장소가 막혀 있으면 기본값 */ }
  return defaultDraft();
}

function saveDraft(d: SarPlanDraft): void {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* 이번 세션만 */ }
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits;
const fmt = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? '—' : v.toFixed(digits));

/** 이 노드가 보는 장비 — 명령을 받을 장비가 먼저, 없으면 SAR 보고를 보낸 장비. */
function focusDevice(link: SarLink, reports: Readonly<Record<string, SarReport>>): string | null {
  return link.deviceId ?? Object.keys(reports)[0] ?? null;
}

function useSarView() {
  useTick(1000);
  const reports = useSarReports();
  useDeviceTelemetry();
  const link = sarLink();
  const deviceId = focusDevice(link, reports);
  const report = deviceId === null ? null : reports[deviceId] ?? null;
  return { link, deviceId, report };
}

const STEPS: readonly SarState[] = ['preflight', 'transit', 'gap', 'accel', 'capture', 'decel'];

function stateKey(state: SarState): string {
  return `sar.state.${state}`;
}

// ── 접힘 ────────────────────────────────────────────────────────────────────

export function SarPassCard() {
  useLang();
  const { link, deviceId, report } = useSarView();
  if (report === null) {
    return <div className="sar-card">
      <p className="sar-empty">{t('sar.noReport')}</p>
      <small>{link.reason || (deviceId === null ? '' : t('sar.cardDevice', { id: deviceId }))}</small>
    </div>;
  }
  const stale = isSarStale(report);
  const target = report.plan?.speedMps ?? null;
  const speed = report.live?.groundSpeedMps ?? null;
  return <div className={`sar-card${stale ? ' is-stale' : ''}`}>
    <div className="sar-card__row">
      <b className={`sar-state sar-state--${report.state}`}>{t(stateKey(report.state))}</b>
      {report.passesTotal !== null && <span>{t('sar.passOf', { n: report.passNo, total: report.passesTotal })}</span>}
      <span className={`sar-cap ${report.capturing ? 'is-on' : ''}`}>{report.capturing ? t('sar.cap.on') : t('sar.cap.off')}</span>
    </div>
    <div className="sar-card__row">
      <span>{t('sar.speedVs', { v: fmt(speed), target: fmt(target) })}</span>
      <span>{t('sar.altNow', { m: fmt(report.live?.altRelM ?? null) })}</span>
      {report.live?.gpsFix && <RtkBadge level={rtkLevel(null, report.live.gpsFix)} />}
    </div>
    {report.error !== null && <p className="sar-bad">{report.error}</p>}
    {stale && <p className="sar-warn">{t('sar.stale', { sec: Math.round((Date.now() - report.receivedAtMs) / 1000) })}</p>}
  </div>;
}

// ── 확대 ────────────────────────────────────────────────────────────────────

export function SarPassZoom() {
  useLang();
  const { link, deviceId, report } = useSarView();
  const [draft, setDraftState] = useState<SarPlanDraft>(loadDraft);
  const [endMode, setEndMode] = useState<'heading' | 'point'>('heading');
  // 저장된 끝점에서 되짚으면 부동소수 꼬리(44.999999)가 붙는다 — 사람이 넣는 칸이라 다듬어 보인다.
  const [heading, setHeading] = useState<number>(() => (draft.start && draft.end ? round(lineOf(draft.start, draft.end).headingDeg, 1) : 0));
  const [length, setLength] = useState<number>(() => (draft.start && draft.end ? round(lineOf(draft.start, draft.end).lengthM, 1) : 80));
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'start' | 'abort' | null>(null);
  const [outcome, setOutcome] = useState<{ action: 'start' | 'abort'; result: SarIssueOutcome } | null>(null);

  const setDraft = (next: SarPlanDraft) => { setDraftState(next); saveDraft(next); setConfirmed(false); };
  const withEnd = (d: SarPlanDraft, h = heading, l = length): SarPlanDraft =>
    endMode === 'heading' && d.start !== null ? { ...d, end: endFrom(d.start, h, l) } : d;

  const here: LatLon | null = deviceId === null ? null : (() => {
    const lat = num(telemetryValue(deviceId, 'gps.lat'));
    const lon = num(telemetryValue(deviceId, 'gps.lon'));
    return lat === null || lon === null ? null : { lat, lon };
  })();
  const yaw = deviceId === null ? null : num(telemetryValue(deviceId, 'attitude.yaw_deg'));
  const rtk = deviceId === null ? 'unknown' as const
    : rtkLevel(telemetryValue(deviceId, 'gps.fix_type'), telemetryValue(deviceId, 'gps.fix'));

  const problems = planProblems(draft);
  const estimate = planEstimate(draft);
  const running = report !== null && !SAR_FINISHED.includes(report.state) && !isSarStale(report);
  const rtkBlocks = draft.requireRtk && rtk !== 'fixed';
  const canStart = problems.length === 0 && link.start === 'yes' && confirmed && !running && busy === null;

  async function start() {
    setBusy('start');
    try { setOutcome({ action: 'start', result: await issueSarStart(toStartParams(draft), link) }); }
    finally { setBusy(null); setConfirmed(false); }
  }
  async function abort() {
    setBusy('abort');
    try { setOutcome({ action: 'abort', result: await issueSarAbort(link) }); }
    finally { setBusy(null); }
  }

  const numberField = (labelKey: string, value: number, onChange: (v: number) => void, opts: { step?: number; min?: number; max?: number; unit?: string } = {}) =>
    <label className="sar-field">
      <span>{t(labelKey)}</span>
      <input type="number" value={Number.isFinite(value) ? value : ''} step={opts.step ?? 1} min={opts.min} max={opts.max}
        onChange={(e) => onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))} />
      {opts.unit && <small>{opts.unit}</small>}
    </label>;

  const coordField = (labelKey: string, p: LatLon | null, onChange: (p: LatLon | null) => void) =>
    <div className="sar-coord">
      <span>{t(labelKey)}</span>
      <input type="number" step={0.000001} placeholder="lat" value={p?.lat ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : { lat: Number(e.target.value), lon: p?.lon ?? 0 })} />
      <input type="number" step={0.000001} placeholder="lon" value={p?.lon ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : { lat: p?.lat ?? 0, lon: Number(e.target.value) })} />
    </div>;

  return <div className="sar-zoom">
    <p className="sar-lead">{t('sar.lead')}</p>

    {/* ① 계획 */}
    <section className="sar-section">
      <h3>{t('sar.plan.title')}</h3>
      <div className="sar-plan-grid">
        <div>
          {coordField('sar.plan.start', draft.start, (p) => setDraft(withEnd({ ...draft, start: p })))}
          <button type="button" disabled={here === null} onClick={() => here && setDraft(withEnd({ ...draft, start: here }))}>
            {t('sar.plan.useHere')}
          </button>
          <div className="sar-seg">
            <button type="button" className={endMode === 'heading' ? 'active' : ''} onClick={() => setEndMode('heading')}>{t('sar.plan.byHeading')}</button>
            <button type="button" className={endMode === 'point' ? 'active' : ''} onClick={() => setEndMode('point')}>{t('sar.plan.byPoint')}</button>
          </div>
          {endMode === 'heading' ? <>
            {numberField('sar.plan.heading', heading, (v) => { setHeading(v); setDraft(withEnd(draft, v, length)); }, { step: 1, min: 0, max: 359, unit: '°' })}
            <button type="button" disabled={yaw === null} onClick={() => {
              const h = Math.round((((yaw ?? 0) % 360) + 360) % 360);
              setHeading(h); setDraft(withEnd(draft, h, length));
            }}>{t('sar.plan.useYaw')}</button>
            {numberField('sar.plan.length', length, (v) => { setLength(v); setDraft(withEnd(draft, heading, v)); }, { step: 5, min: SAR_RULES.minLineM, unit: 'm' })}
          </> : coordField('sar.plan.end', draft.end, (p) => setDraft({ ...draft, end: p }))}
        </div>
        <div>
          {numberField('sar.plan.alt', draft.altM, (v) => setDraft({ ...draft, altM: v }), { step: 1, min: SAR_RULES.minAltM, max: SAR_RULES.maxAltM, unit: 'm' })}
          {numberField('sar.plan.speed', draft.speedMps, (v) => setDraft({ ...draft, speedMps: v }), { step: 0.5, min: SAR_RULES.minSpeed, max: SAR_RULES.maxSpeed, unit: 'm/s' })}
          {numberField('sar.plan.passes', draft.passes, (v) => setDraft({ ...draft, passes: v }), { step: 1, min: SAR_RULES.minPasses })}
          {numberField('sar.plan.gap', draft.gapS, (v) => setDraft({ ...draft, gapS: v }), { step: 1, min: SAR_RULES.minGapS, unit: 's' })}
          {numberField('sar.plan.leadIn', draft.leadInM, (v) => setDraft({ ...draft, leadInM: v }), { step: 1, min: 0, unit: 'm' })}
          <small className="sar-hint">{t('sar.plan.leadInAuto', { m: autoLeadInM(Number.isFinite(draft.speedMps) ? draft.speedMps : SAR_RULES.defaultSpeed).toFixed(1) })}</small>
          <label className="sar-check"><input type="checkbox" checked={draft.requireRtk} onChange={(e) => setDraft({ ...draft, requireRtk: e.target.checked })} />{t('sar.plan.requireRtk')}</label>
          <label className="sar-check"><input type="checkbox" checked={draft.rtlOnAbort} onChange={(e) => setDraft({ ...draft, rtlOnAbort: e.target.checked })} />{t('sar.plan.rtlOnAbort')}</label>
          <label className="sar-check"><input type="checkbox" checked={draft.rtlOnDone} onChange={(e) => setDraft({ ...draft, rtlOnDone: e.target.checked })} />{t('sar.plan.rtlOnDone')}</label>
        </div>
      </div>
      {problems.length > 0
        ? <ul className="sar-problems">{problems.map((p) => <li key={p.key}>{t(p.key, p.vars)}</li>)}</ul>
        : <p className="sar-ok">{t('sar.plan.ok')}</p>}
      {estimate !== null && <p className="sar-hint">
        {t('sar.plan.estimate', {
          m: estimate.lengthM.toFixed(1), deg: estimate.headingDeg.toFixed(0), lead: estimate.leadInM.toFixed(1),
          cap: estimate.captureS.toFixed(1), total: Math.ceil(estimate.totalMinS / 60),
        })}
      </p>}
    </section>

    {/* ② 미리보기 */}
    <section className="sar-section">
      <h3>{t('sar.preview.title')}</h3>
      <PassPreview draft={draft} here={here} live={report} />
    </section>

    {/* ③ 실행 */}
    <section className="sar-section">
      <h3>{t('sar.run.title')}</h3>
      <dl className="device-facts">
        <div><dt>{t('sar.run.device')}</dt><dd>{deviceId ?? t('sar.run.noDevice')}</dd></div>
        {link.client !== null && <div><dt>{t('sar.run.declared')}</dt><dd>{t(`sar.support.${link.start}`)} · sar_abort {t(`sar.support.${link.abort}`)}</dd></div>}
        <div><dt>{t('sar.run.rtk')}</dt><dd><RtkBadge level={rtk} />{rtkBlocks && <em className="sar-warn"> {t('sar.run.rtkBlocks', { level: t(RTK_LABEL_KEY[rtk]) })}</em>}</dd></div>
      </dl>
      {link.reason !== '' && <p className="sar-warn">{link.reason}</p>}
      {link.start !== 'yes' && link.reason === '' && <p className="sar-warn">{t('sar.link.notDeclared')}</p>}
      <label className="sar-check sar-confirm">
        <input type="checkbox" checked={confirmed} disabled={problems.length > 0 || running} onChange={(e) => setConfirmed(e.target.checked)} />
        {t('sar.run.confirm')}
      </label>
      <div className="sar-actions">
        <button type="button" className="sar-start" disabled={!canStart} onClick={() => void start()}>
          {busy === 'start' ? t('sar.run.sending') : t('sar.run.start')}
        </button>
        <button type="button" className="sar-abort" disabled={busy === 'abort'} onClick={() => void abort()}>
          {busy === 'abort' ? t('sar.run.sending') : t('sar.run.abort')}
        </button>
      </div>
      {outcome !== null && <p className={outcome.result.accepted === true ? 'sar-ok' : outcome.result.accepted === false || !outcome.result.sent ? 'sar-bad' : 'sar-warn'}>
        {t(outcome.action === 'start' ? 'sar.run.startResult' : 'sar.run.abortResult', { message: outcome.result.message })}
      </p>}
      {/* 장비를 골랐는데 선언이 없을 때만 — 브로커가 없어서 「없음」인 것과 가른다. */}
      {link.client !== null && link.abort === 'no' && <p className="sar-bad">{t('sar.cmd.abortUnsupported')}</p>}
    </section>

    {/* ④ 진행 */}
    <section className="sar-section">
      <h3>{t('sar.progress.title')}</h3>
      {report === null ? <p className="sar-empty">{t('sar.noReport')}</p> : <Progress report={report} />}
    </section>

    {/* ⑤ 패스 기록 */}
    <section className="sar-section">
      <h3>{t('sar.log.title')}</h3>
      {report === null || report.passes.length === 0
        ? <p className="sar-empty">{t('sar.log.empty')}</p>
        : <PassTable report={report} />}
      <p className="sar-hint">{t('sar.log.ulgHint')}</p>
    </section>
  </div>;
}

function Progress({ report }: { report: SarReport }) {
  useLang();
  const stale = isSarStale(report);
  const live = report.live;
  const plan = report.plan;
  const along = live?.alongM ?? null;
  const lengthM = plan?.lengthM ?? null;
  const pct = along !== null && lengthM !== null && lengthM > 0 ? Math.max(0, Math.min(100, (along / lengthM) * 100)) : null;
  const speedErr = live?.groundSpeedMps !== null && live?.groundSpeedMps !== undefined && plan?.speedMps
    ? live.groundSpeedMps - plan.speedMps : null;
  return <div className={stale ? 'is-stale' : ''}>
    {stale && <p className="sar-warn">{t('sar.stale', { sec: Math.round((Date.now() - report.receivedAtMs) / 1000) })}</p>}
    <ol className="sar-steps">
      {STEPS.map((s) => <li key={s} className={s === report.state ? 'is-now' : ''}>{t(stateKey(s))}</li>)}
    </ol>
    <div className="sar-card__row">
      <b className={`sar-state sar-state--${report.state}`}>{t(stateKey(report.state))}</b>
      {report.passesTotal !== null && <span>{t('sar.passOf', { n: report.passNo, total: report.passesTotal })}</span>}
      <span className={`sar-cap ${report.capturing ? 'is-on' : ''}`}>{report.capturing ? t('sar.cap.on') : t('sar.cap.off')}</span>
    </div>
    {pct !== null && <div className="sar-bar" title={`${fmt(along)} / ${fmt(lengthM)} m`}><i style={{ width: `${pct}%` }} /></div>}
    <dl className="device-facts">
      <div><dt>{t('sar.live.speed')}</dt><dd className={speedErr !== null && Math.abs(speedErr) > 0.3 && report.state === 'capture' ? 'sar-bad' : ''}>
        {fmt(live?.groundSpeedMps)} m/s{plan?.speedMps ? ` / ${plan.speedMps} m/s` : ''}</dd></div>
      <div><dt>{t('sar.live.alt')}</dt><dd>{fmt(live?.altRelM)} m{plan?.altM ? ` / ${plan.altM} m` : ''}</dd></div>
      <div><dt>{t('sar.live.headingErr')}</dt><dd>{fmt(live?.headingErrDeg)}°</dd></div>
      <div><dt>{t('sar.live.cross')}</dt><dd>{fmt(live?.crossTrackM, 2)} m</dd></div>
      <div><dt>{t('sar.live.along')}</dt><dd>{fmt(along)} / {fmt(lengthM)} m</dd></div>
      <div><dt>{t('sar.live.mode')}</dt><dd>{live?.flightMode ?? '—'} · {live?.gpsFix ?? '—'}</dd></div>
      <div><dt>{t('sar.live.clock')}</dt>
        <dd className={report.clockOffsetS !== null && Math.abs(report.clockOffsetS) > 1 ? 'sar-bad' : ''}>
          {report.clockOffsetS === null ? t('sar.live.clockUnknown') : `${report.clockOffsetS >= 0 ? '+' : ''}${report.clockOffsetS.toFixed(3)} s`}
        </dd></div>
    </dl>
    {report.warnings.map((w) => <p key={w} className="sar-warn">{w}</p>)}
    {report.message !== null && <p className="sar-ok">{report.message}</p>}
    {report.error !== null && <p className="sar-bad">{report.error}</p>}
  </div>;
}

function localTime(unix: number | null): string {
  if (unix === null) return '—';
  return new Date(unix * 1000).toLocaleTimeString(undefined, { hour12: false }) + `.${String(Math.round((unix % 1) * 1000)).padStart(3, '0')}`;
}

function PassTable({ report }: { report: SarReport }) {
  useLang();
  const csv = useMemo(() => {
    const head = 'pass,start_unix,end_unix,fc_start_unix,fc_end_unix,duration_s,captured,mean_speed_mps,max_speed_err_mps,max_cross_track_m,max_alt_err_m,max_heading_err_deg,worst_fix,note';
    const rows = report.passes.map((p) => [p.passNo, p.startUnix, p.endUnix, p.fcStartUnix, p.fcEndUnix, p.durationS, p.captured,
      p.meanSpeedMps, p.maxSpeedErrMps, p.maxCrossTrackM, p.maxAltErrM, p.maxHeadingErrDeg, p.worstFix,
      JSON.stringify(p.note ?? '')].map((v) => v ?? '').join(','));
    return [head, ...rows].join('\n');
  }, [report.passes]);
  return <>
    <table className="sar-table">
      <thead><tr>
        <th>{t('sar.log.pass')}</th><th>{t('sar.log.start')}</th><th>{t('sar.log.end')}</th><th>{t('sar.log.duration')}</th>
        <th>{t('sar.log.meanSpeed')}</th><th>{t('sar.log.maxErr')}</th><th>{t('sar.log.worstFix')}</th><th>{t('sar.log.note')}</th>
      </tr></thead>
      <tbody>{report.passes.map((p) => <tr key={p.passNo} className={p.captured ? '' : 'is-missed'}>
        <td>{p.passNo}</td>
        <td>{localTime(p.startUnix)}<small>{p.startUnix?.toFixed(3) ?? ''}</small>{p.fcStartUnix !== null && <small>FC {p.fcStartUnix.toFixed(3)}</small>}</td>
        <td>{localTime(p.endUnix)}<small>{p.endUnix?.toFixed(3) ?? ''}</small>{p.fcEndUnix !== null && <small>FC {p.fcEndUnix.toFixed(3)}</small>}</td>
        <td>{fmt(p.durationS)} s</td>
        <td>{fmt(p.meanSpeedMps, 2)} m/s</td>
        <td>{t('sar.log.maxErrValue', { v: fmt(p.maxSpeedErrMps, 2), x: fmt(p.maxCrossTrackM, 2), z: fmt(p.maxAltErrM, 2), h: fmt(p.maxHeadingErrDeg, 1) })}</td>
        <td className={p.worstFix !== null && p.worstFix !== 'RTK_FIXED' ? 'sar-bad' : ''}>{p.worstFix ?? '—'}</td>
        <td>{p.captured ? (p.note ?? '') : (p.note ?? t('sar.log.missed'))}</td>
      </tr>)}</tbody>
    </table>
    <a className="sar-download" download={`sar_passes_${report.deviceId}.csv`} href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`}>
      {t('sar.log.csv')}
    </a>
  </>;
}

/**
 * 위에서 본 그림. 캡처 구간(실선) · 앞뒤 가감속 구간(점선) · 진행 방향 · 지금 드론 위치.
 * 축척은 그림에 맞춘다 — 지도는 아니다(배경 지도 없이 상대 위치만).
 */
function PassPreview({ draft, here, live }: { draft: SarPlanDraft; here: LatLon | null; live: SarReport | null }) {
  useLang();
  if (draft.start === null || draft.end === null) return <p className="sar-empty">{t('sar.preview.noLine')}</p>;
  const start = draft.start;
  const end = draft.end;
  const { lengthM, headingDeg } = lineOf(start, end);
  if (!(lengthM > 0)) return <p className="sar-empty">{t('sar.preview.noLine')}</p>;
  const lead = Math.max(draft.leadInM, autoLeadInM(Number.isFinite(draft.speedMps) ? draft.speedMps : SAR_RULES.defaultSpeed));
  const rad = (headingDeg * Math.PI) / 180;
  const un = Math.cos(rad);
  const ue = Math.sin(rad);
  const pts = {
    leadIn: { n: -un * lead, e: -ue * lead },
    start: { n: 0, e: 0 },
    end: toLocal(start, end),
    leadOut: { n: un * (lengthM + lead), e: ue * (lengthM + lead) },
  };
  const drone = here === null ? null : toLocal(start, here);
  const all = [pts.leadIn, pts.leadOut, ...(drone ? [drone] : [])];
  const minE = Math.min(...all.map((p) => p.e)) - 10;
  const maxE = Math.max(...all.map((p) => p.e)) + 10;
  const minN = Math.min(...all.map((p) => p.n)) - 10;
  const maxN = Math.max(...all.map((p) => p.n)) + 10;
  const W = 520;
  const H = 300;
  const scale = Math.min(W / (maxE - minE), H / (maxN - minN));
  const x = (p: { e: number }) => (p.e - minE) * scale + (W - (maxE - minE) * scale) / 2;
  const y = (p: { n: number }) => H - ((p.n - minN) * scale + (H - (maxN - minN) * scale) / 2);
  // 진행 방향 삼각형 — 캡처 구간 가운데, 화면 좌표(아래가 +y)로 돌린다.
  const mid = { n: un * lengthM * 0.5, e: ue * lengthM * 0.5 };
  const arrow = 10;
  const [cx, cy, dx, dy] = [x(mid), y(mid), ue, -un];
  const arrowPoints = [
    [cx + dx * arrow, cy + dy * arrow],
    [cx - dx * arrow + dy * arrow * 0.7, cy - dy * arrow - dx * arrow * 0.7],
    [cx - dx * arrow - dy * arrow * 0.7, cy - dy * arrow + dx * arrow * 0.7],
  ].map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(' ');
  const offTrack = drone !== null ? alongCross(start, end, here!) : null;
  const scaleBar = [10, 20, 50, 100, 200].find((m) => m * scale > 60) ?? 200;
  const capturing = live?.capturing === true;
  return <figure className="sar-preview">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t('sar.preview.title')}>
      <line className="sar-pv-lead" x1={x(pts.leadIn)} y1={y(pts.leadIn)} x2={x(pts.start)} y2={y(pts.start)} />
      <line className="sar-pv-lead" x1={x(pts.end)} y1={y(pts.end)} x2={x(pts.leadOut)} y2={y(pts.leadOut)} />
      <line className={`sar-pv-cap${capturing ? ' is-on' : ''}`} x1={x(pts.start)} y1={y(pts.start)} x2={x(pts.end)} y2={y(pts.end)} />
      <polygon className="sar-pv-arrow" points={arrowPoints} />
      <circle className="sar-pv-pt" cx={x(pts.start)} cy={y(pts.start)} r={5} />
      <circle className="sar-pv-pt" cx={x(pts.end)} cy={y(pts.end)} r={5} />
      <circle className="sar-pv-lead-pt" cx={x(pts.leadIn)} cy={y(pts.leadIn)} r={4} />
      <text className="sar-pv-label" x={x(pts.start) + 8} y={y(pts.start) - 8}>{t('sar.preview.capStart')}</text>
      <text className="sar-pv-label" x={x(pts.end) + 8} y={y(pts.end) - 8}>{t('sar.preview.capEnd')}</text>
      <text className="sar-pv-label sar-pv-label--dim" x={x(pts.leadIn) + 8} y={y(pts.leadIn) + 16}>{t('sar.preview.leadIn')}</text>
      {drone !== null && <>
        <circle className="sar-pv-drone" cx={x(drone)} cy={y(drone)} r={7} />
        <text className="sar-pv-label" x={x(drone) + 10} y={y(drone) + 4}>{t('sar.preview.drone')}</text>
      </>}
      {/* 북 화살표 · 축척 */}
      <g transform={`translate(${W - 24},28)`}>
        <polygon className="sar-pv-north" points="0,-14 6,4 0,0 -6,4" />
        <text className="sar-pv-label" x={-4} y={18}>N</text>
      </g>
      <g transform={`translate(12,${H - 14})`}>
        <line className="sar-pv-scale" x1={0} y1={0} x2={scaleBar * scale} y2={0} />
        <text className="sar-pv-label" x={0} y={-5}>{scaleBar} m</text>
      </g>
    </svg>
    <figcaption className="sar-hint">
      {t('sar.preview.caption', { m: lengthM.toFixed(1), deg: headingDeg.toFixed(0), lead: lead.toFixed(1) })}
      {offTrack !== null && ` · ${t('sar.preview.droneOff', { along: offTrack.along.toFixed(1), cross: offTrack.cross.toFixed(1) })}`}
    </figcaption>
  </figure>;
}
