/**
 * src/sar/SarPassView.tsx (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **SAR 패스 노드.** 접힘 = 지금 상태 한 줄. 확대 = **처음 쓰는 사람도 따라 할 수 있는 여섯 단계**:
 *   ① 준비 점검(자동 ✓/✕) → ② 위성 지도에서 선 정하기 → ③ 비행 조건 → ④ 시작 → ⑤ 진행 → ⑥ 결과 · 데이터 저장
 * 맨 위 「지금 할 일」 한 줄이 다음에 무엇을 하면 되는지 말한다.
 *
 * 화면은 **계획 · 명령 · 감시 · 내려받기**만 한다. 비행과 CAP_ON 은 드론의 `sar_pass` 실행기가 맡는다 — 브라우저는
 * 드론의 파일을 만질 수 없고, 링크가 끊겨도 캡처는 드론 안에서 꺼져야 하기 때문이다.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { deviceTelemetry, isTelemetryStale, telemetryValue, useDeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { SAR_FINISHED, isSarStale, useSarReports, type SarReport, type SarState } from '../shared/sarStatus.ts';
import { isRtcmReportStale, useRtcmReports } from '../shared/rtcmStatus.ts';
import { useFcxReports } from '../shared/fcxStatus.ts';
import { connectionAddress, useConnections } from '../shared/connections.ts';
import { physicalWsUrls } from '../physical/PhysicalClient.ts';
import {
  issueSarAbort, issueSarStart, sarLink, type SarIssueOutcome, type SarLink,
} from '../physical/sarCommands.ts';
import {
  SAR_RULES, autoLeadInM, batteryBudget, defaultDraft, endFrom, lineOf, planEstimate, planProblems, toGlobal, toLocal, windEffect,
  toStartParams, type LatLon, type SarPlanDraft,
} from './plan.ts';
import { RTK_LABEL_KEY, rtkLevel } from './rtk.ts';
import { RtkBadge } from './RtkView.tsx';
import { useTick } from './useTick.ts';
import { SatMap, type Area, type Marker } from '../dronedash/SatMap.tsx';
import { checkReflector, defaultAntenna, radarJson, swathPolygon, type AntennaDraft } from './coverage.ts';
import { ANT_KEY, CR_KEY, liveBeam } from './liveBeam.ts';
import { PassInspector } from './PassInspector.tsx';
import { ComparePanel, ImageButton, ImagingStatus, SarImageView, type ImageSummary, type Imaging, type MirrorState } from './SarImageView.tsx';
import './sar.css';

const DRAFT_KEY = 'viz.sar.draft.v1';

function loadJson<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); if (raw !== null) return { ...fallback, ...JSON.parse(raw) } as T; } catch { /* */ }
  return fallback;
}
function loadList<T>(key: string): T[] {
  try { const raw = localStorage.getItem(key); if (raw !== null) { const v = JSON.parse(raw); if (Array.isArray(v)) return v as T[]; } } catch { /* */ }
  return [];
}
function saveJson(key: string, v: unknown): void { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* */ } }

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
const fmt = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? '—' : v.toFixed(digits));
const bytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} kB`);

/** 이 노드가 보는 장비 — 명령을 받을 장비가 먼저, 없으면 SAR 보고를 보낸 장비, 그것도 없으면 GPS 를 보고한 장비. */
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
const stateKey = (state: SarState) => `sar.state.${state}`;

type Level = 'good' | 'warn' | 'bad' | 'unknown';
const MARK: Record<Level, string> = { good: '✓', warn: '!', bad: '✕', unknown: '?' };

// ── 데이터 서버 (Pi 의 drone/sar_data) ──────────────────────────────────────

/** 연결 관리에 적은 주소, 없으면 드론 브로커 주소의 호스트 + :8765. */
export function dataServerUrl(): string {
  const set = connectionAddress('drone-data', 'http').trim();
  if (set !== '') return set.replace(/\/+$/, '');
  for (const ws of physicalWsUrls()) {
    try { return `http://${new URL(ws).hostname}:8765`; } catch { /* 다음 줄 */ }
  }
  return '';
}

type DataPass = {
  pass_no: number; valid: boolean | null; reasons: string[]; traj_csv: string | null; meta_json: string;
  radar_files: { name: string; size: number }[]; radar_bytes: number; eff_start_along_m: number | null; eff_end_along_m: number | null;
  image?: ImageSummary | null;
};
type DataFlight = { id: string; started_unix: number; passes: DataPass[]; valid_passes: number; size_bytes: number; ulogs?: { name: string; size: number }[] };

function useDataServer(enabled: boolean) {
  useConnections();
  const base = dataServerUrl();
  const [state, setState] = useState<{ ok: boolean | null; flights: DataFlight[]; error: string | null; freeBytes: number | null;
    imaging: Imaging; mirror: MirrorState }>(
    { ok: null, flights: [], error: null, freeBytes: null, imaging: null, mirror: null });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!enabled || base === '') return;
    let alive = true;
    const pull = async () => {
      try {
        const [h, f] = await Promise.all([
          fetch(`${base}/api/health`).then((r) => r.json() as Promise<{ disk_free_bytes?: number; imaging?: Imaging; mirror?: MirrorState }>),
          fetch(`${base}/api/flights`).then((r) => r.json() as Promise<DataFlight[]>),
        ]);
        if (alive) setState({ ok: true, flights: Array.isArray(f) ? f : [], error: null, freeBytes: num(h.disk_free_bytes),
          imaging: h.imaging ?? null, mirror: h.mirror ?? null });
      } catch (e) {
        if (alive) setState((s) => ({ ...s, ok: false, error: e instanceof Error ? e.message : String(e) }));
      }
    };
    void pull();
    const id = setInterval(() => void pull(), 10_000);
    return () => { alive = false; clearInterval(id); };
  }, [enabled, base, nonce]);
  return { base, ...state, refresh: () => setNonce((n) => n + 1) };
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
      {report.passesTotal !== null && <span>{t('sar.validOf', { n: report.validPasses ?? 0, total: report.passesTotal, try: report.passNo })}</span>}
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

// ── 확대: 여섯 단계 ─────────────────────────────────────────────────────────

function Step({ n, title, help, level, open, children }: {
  n: number; title: string; help: string; level: Level | 'now' | 'todo'; open?: boolean; children: ReactNode;
}) {
  return <details className={`sar-guide-step sar-guide-step--${level}`} open={open}>
    <summary>
      <span className="sar-guide-n">{level === 'good' ? '✓' : n}</span>
      <b>{title}</b>
      <small>{help}</small>
    </summary>
    <div className="sar-guide-body">{children}</div>
  </details>;
}

type CheckItem = { key: string; level: Level; label: string; detail: string; fix?: string };

function CheckList({ items }: { items: readonly CheckItem[] }) {
  return <ul className="sar-checklist">
    {items.map((c) => <li key={c.key} className={`sar-check-item sar-check-item--${c.level}`}>
      <i aria-hidden>{MARK[c.level]}</i>
      <div><b>{c.label}</b><span>{c.detail}</span>{c.fix && c.level !== 'good' && <em>{c.fix}</em>}</div>
    </li>)}
  </ul>;
}

export function SarPassZoom() {
  useLang();
  const { link, deviceId, report } = useSarView();
  const rtcm = useRtcmReports();
  const fcx = useFcxReports();
  const [draft, setDraftState] = useState<SarPlanDraft>(loadDraft);
  const [pickNext, setPickNext] = useState<'start' | 'end'>(() => (loadDraft().start === null ? 'start' : 'end'));
  const [mapMode, setMapMode] = useState<'line' | 'reflector'>('line');
  const [reflectors, setReflectorsState] = useState<LatLon[]>(() => loadList<LatLon>(CR_KEY));
  const [antenna, setAntennaState] = useState<AntennaDraft>(() => loadJson(ANT_KEY, defaultAntenna()));
  const setReflectors = (v: LatLon[]) => { setReflectorsState(v); saveJson(CR_KEY, v); };
  const setAntenna = (v: AntennaDraft) => { setAntennaState(v); saveJson(ANT_KEY, v); };
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'start' | 'abort' | null>(null);
  const [outcome, setOutcome] = useState<{ action: 'start' | 'abort'; result: SarIssueOutcome } | null>(null);
  const data = useDataServer(true);

  const setDraft = (next: SarPlanDraft) => { setDraftState(next); saveDraft(next); setConfirmed(false); };

  const here: LatLon | null = deviceId === null ? null : (() => {
    const lat = num(telemetryValue(deviceId, 'gps.lat'));
    const lon = num(telemetryValue(deviceId, 'gps.lon'));
    return lat === null || lon === null ? null : { lat, lon };
  })();
  const yaw = deviceId === null ? null : num(telemetryValue(deviceId, 'attitude.yaw_deg'));
  const rtk = deviceId === null ? 'unknown' as const
    : rtkLevel(telemetryValue(deviceId, 'gps.fix_type'), telemetryValue(deviceId, 'gps.fix'));
  const tel = deviceId === null ? null : deviceTelemetry(deviceId);
  const rtcmReport = deviceId === null ? undefined : rtcm[deviceId];
  const fcxReport = deviceId === null ? undefined : fcx[deviceId];
  const clock = report?.clockOffsetS ?? fcxReport?.clockOffsetS ?? null;

  const problems = planProblems(draft);
  const estimate = planEstimate(draft);
  const running = report !== null && !SAR_FINISHED.includes(report.state) && !isSarStale(report);
  const finished = report !== null && SAR_FINISHED.includes(report.state) && report.state !== 'idle';

  // ① 준비 점검
  const checks: CheckItem[] = [
    { key: 'broker', level: link.client !== null ? 'good' : 'bad', label: t('sar.check.broker'),
      detail: link.client !== null ? t('sar.check.brokerOk', { id: deviceId ?? '—' }) : (link.reason || t('sar.link.noDevice')),
      fix: t('sar.check.brokerFix') },
    { key: 'state', level: tel !== null && !isTelemetryStale(tel) ? 'good' : 'bad', label: t('sar.check.state'),
      detail: tel === null ? t('sar.check.stateNone') : isTelemetryStale(tel) ? t('sar.check.stateStale') : t('sar.check.stateOk'),
      fix: t('sar.check.stateFix') },
    { key: 'rtk', level: rtk === 'fixed' ? 'good' : rtk === 'float' ? 'warn' : draft.requireRtk ? 'bad' : 'warn', label: t('sar.check.rtk'),
      detail: t(RTK_LABEL_KEY[rtk]), fix: t('sar.check.rtkFix') },
    { key: 'rtcm', level: rtcmReport === undefined || isRtcmReportStale(rtcmReport) ? 'warn' : rtcmReport.receiving ? 'good' : 'bad',
      label: t('sar.check.rtcm'),
      detail: rtcmReport === undefined || isRtcmReportStale(rtcmReport) ? t('rtcm.unknown')
        : rtcmReport.receiving ? t('rtcm.on', { fps: (rtcmReport.framesPerS ?? 0).toFixed(1), age: (rtcmReport.ageS ?? 0).toFixed(1) })
          : t('rtcm.off', { age: (rtcmReport.ageS ?? 0).toFixed(0) }),
      fix: t('sar.check.rtcmFix') },
    { key: 'cmd', level: link.start === 'yes' ? 'good' : link.start === 'unknown' ? 'warn' : 'bad', label: t('sar.check.cmd'),
      detail: t(`sar.support.${link.start}`), fix: t('sar.check.cmdFix') },
    { key: 'clock', level: clock === null ? 'warn' : Math.abs(clock) <= 1 ? 'good' : 'bad', label: t('sar.check.clock'),
      detail: clock === null ? t('sar.live.clockUnknown') : `${clock >= 0 ? '+' : ''}${clock.toFixed(3)} s`, fix: t('sar.check.clockFix') },
    { key: 'radar', level: report === null ? 'unknown' : report.capAck === null ? 'warn' : 'good', label: t('sar.check.radar'),
      detail: report === null ? t('sar.check.radarUnknown') : report.capAck === null ? t('sar.check.radarNone') : t('sar.check.radarOk'),
      fix: t('sar.check.radarFix') },
    { key: 'data', level: data.ok === true ? 'good' : data.base === '' ? 'warn' : data.ok === false ? 'warn' : 'unknown', label: t('sar.check.data'),
      detail: data.ok === true ? t('sar.check.dataOk', { url: data.base, free: data.freeBytes === null ? '—' : bytes(data.freeBytes) })
        : data.base === '' ? t('sar.check.dataNoUrl') : t('sar.check.dataFail', { url: data.base }),
      fix: t('sar.check.dataFix') },
  ];
  const blocking = checks.filter((c) => c.level === 'bad');
  const step1: Level = blocking.length > 0 ? 'bad' : checks.some((c) => c.level === 'warn') ? 'warn' : 'good';
  const step2: Level = draft.start === null || draft.end === null ? 'unknown' : problems.some((p) => p.key === 'sar.rule.line' || p.key === 'sar.rule.noLine') ? 'bad' : 'good';
  const step3: Level = problems.length > 0 ? 'bad' : 'good';
  const canStart = problems.length === 0 && link.start === 'yes' && confirmed && !running && busy === null;

  // 지금 할 일 — 위에서부터 처음 막힌 것
  const next = running ? t('sar.next.running')
    : blocking.length > 0 ? t('sar.next.fixCheck', { what: blocking[0]!.label })
      : draft.start === null ? t('sar.next.pickStart')
        : draft.end === null ? t('sar.next.pickEnd')
          : problems.length > 0 ? t('sar.next.fixPlan', { what: t(problems[0]!.key, problems[0]!.vars) })
            : !confirmed ? t('sar.next.confirm')
              : finished ? t('sar.next.download') : t('sar.next.start');

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

  function pick(p: LatLon) {
    if (mapMode === 'reflector') { setReflectors([...reflectors, p]); return; }
    if (pickNext === 'start') {
      setDraft({ ...draft, start: p, end: draft.end });
      setPickNext('end');
    } else {
      setDraft({ ...draft, end: p });
      setPickNext('start');
    }
  }

  const numberField = (labelKey: string, value: number, onChange: (v: number) => void, opts: { step?: number; min?: number; max?: number; unit?: string; hintKey?: string } = {}) =>
    <label className="sar-field" title={opts.hintKey ? t(opts.hintKey) : undefined}>
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

  const line = draft.start && draft.end ? lineOf(draft.start, draft.end) : null;
  const lead = Math.max(draft.leadInM, autoLeadInM(Number.isFinite(draft.speedMps) ? draft.speedMps : SAR_RULES.defaultSpeed));
  const leadIn = draft.start && draft.end && line && line.lengthM > 0 ? (() => {
    const { n, e } = toLocal(draft.start!, draft.end!);
    return toGlobal(draft.start!, (-n / line.lengthM) * lead, (-e / line.lengthM) * lead);
  })() : null;
  const markers: Marker[] = [];
  const home = fcxReport?.home;
  if (home?.lat != null && home.lon != null) markers.push({ lat: home.lat, lon: home.lon, kind: 'home' });
  if (rtcmReport?.base?.lat != null && rtcmReport.base.lon != null) markers.push({ lat: rtcmReport.base.lat, lon: rtcmReport.base.lon, kind: 'base', label: t('map.base') });
  if (draft.start && !draft.end) markers.push({ ...draft.start, kind: 'pick', label: t('map.capStart') });
  const crChecks = reflectors.map((cr) => (draft.start && draft.end && Number.isFinite(draft.altM)
    ? checkReflector(antenna, draft.start, draft.end, draft.altM, cr) : null));
  // 비행 중이면 지금 빔 자국을 그리고, 빔 안에 든 리플렉터는 빛난다
  const beam = liveBeam(antenna, {
    at: here, altM: num(deviceId === null ? null : telemetryValue(deviceId, 'altitude.relative_m')), yawDeg: yaw,
    pitchDeg: num(deviceId === null ? null : telemetryValue(deviceId, 'attitude.pitch_deg')),
    rollDeg: num(deviceId === null ? null : telemetryValue(deviceId, 'attitude.roll_deg')),
  }, reflectors);
  reflectors.forEach((cr, i) => markers.push({ ...cr, kind: 'reflector', label: `CR${i + 1}`, lit: beam.lit.has(i),
    ...(crChecks[i] ? { tone: crChecks[i]!.ok ? 'good' as const : 'bad' as const } : {}) }));
  const swath = draft.start && draft.end && Number.isFinite(draft.altM) ? swathPolygon(antenna, draft.start, draft.end, draft.altM) : null;
  const areas: Area[] = [...(swath ? [{ points: swath, kind: 'swath' as const }] : []), ...(beam.area ? [beam.area] : [])];
  const crCsv = ['name,lat,lon,ok,ground_range_m,along_m,slant_m,aperture_pct',
    ...reflectors.map((cr, i) => [`CR${i + 1}`, cr.lat.toFixed(8), cr.lon.toFixed(8), crChecks[i]?.ok ?? '',
      crChecks[i]?.groundRangeM.toFixed(2) ?? '', crChecks[i]?.alongM.toFixed(2) ?? '', crChecks[i]?.slantRangeM.toFixed(2) ?? '',
      crChecks[i] ? Math.round(crChecks[i]!.apertureFraction * 100) : ''].join(','))].join('\n');
  const antField = (labelKey: string, key: keyof AntennaDraft, step: number, unit: string) =>
    <label className="sar-field"><span>{t(labelKey)}</span>
      <input type="number" step={step} value={(antenna[key] as number | null) ?? ''}
        onChange={(e) => setAntenna({ ...antenna, [key]: e.target.value === '' ? null : Number(e.target.value) })} />
      <small>{unit}</small></label>;

  return <div className="sar-zoom sar-guide">
    <p className="sar-lead">{t('sar.lead')}</p>
    <div className={`sar-next${running ? ' is-running' : ''}`}><b>{t('sar.next.title')}</b><span>{next}</span></div>

    <Step n={1} title={t('sar.step.check')} help={t('sar.step.checkHelp')} level={step1} open={step1 !== 'good'}>
      <CheckList items={checks} />
    </Step>

    <Step n={2} title={t('sar.step.line')} help={t('sar.step.lineHelp')} level={step2 === 'unknown' ? 'now' : step2} open>
      <div className="satmap-seg sar-mapmode" role="group">
        <button type="button" className={mapMode === 'line' ? 'on' : ''} onClick={() => setMapMode('line')}>{t('cr.mode.line')}</button>
        <button type="button" className={mapMode === 'reflector' ? 'on' : ''} onClick={() => setMapMode('reflector')}>{t('cr.mode.reflector')}</button>
      </div>
      <SatMap
        drone={here} droneYaw={yaw}
        sarLine={draft.start && draft.end ? { start: draft.start, end: draft.end, leadIn } : null}
        capturing={report?.capturing}
        markers={markers}
        areas={areas}
        onPick={pick}
        pickHint={mapMode === 'reflector' ? t('cr.pick') : pickNext === 'start' ? t('sar.pick.start') : t('sar.pick.end')}
        height={360}
      />
      <div className="sar-line-tools">
        <button type="button" disabled={here === null} onClick={() => { if (here) { setDraft({ ...draft, start: here }); setPickNext('end'); } }}>{t('sar.plan.useHere')}</button>
        <button type="button" disabled={!draft.start || !draft.end} onClick={() => setDraft({ ...draft, start: draft.end, end: draft.start })}>{t('sar.plan.reverse')}</button>
        <button type="button" disabled={!draft.start || !draft.end || !line} onClick={() => line && draft.start && setDraft({ ...draft, end: endFrom(draft.start, line.headingDeg, 80) })}>{t('sar.plan.len80')}</button>
        <button type="button" disabled={!draft.start || yaw === null} onClick={() => draft.start && setDraft({ ...draft, end: endFrom(draft.start, ((yaw ?? 0) + 360) % 360, line?.lengthM ?? 80) })}>{t('sar.plan.useYaw')}</button>
        <button type="button" onClick={() => { setDraft({ ...draft, start: null, end: null }); setPickNext('start'); }}>{t('sar.plan.clear')}</button>
      </div>
      {line && <p className={step2 === 'bad' ? 'sar-bad' : 'sar-ok'}>{t('sar.plan.lineInfo', { m: line.lengthM.toFixed(1), deg: line.headingDeg.toFixed(0), lead: lead.toFixed(0) })}</p>}
      <div className="sar-cr">
        <div className="sar-cr-head"><b>{t('cr.title')}</b><small>{t('cr.help')}</small></div>
        {reflectors.length === 0 ? <p className="sar-hint">{t('cr.none')}</p> : <table className="sar-table"><tbody>
          {reflectors.map((cr, i) => { const c = crChecks[i]; return <tr key={i} className={c && !c.ok ? 'is-missed' : ''}>
            <td><b>CR{i + 1}</b><small>{cr.lat.toFixed(7)}, {cr.lon.toFixed(7)}</small></td>
            <td>{c === null ? '—' : c.ok ? <span className="sar-ok">✓ {t('cr.seen')}</span> : <span className="sar-bad">✕ {t('cr.notSeen')}</span>}</td>
            <td>{c === null ? t('cr.needLine') : t('cr.detail', { g: c.groundRangeM.toFixed(1), a: c.alongM.toFixed(1), r: c.slantRangeM.toFixed(1), ap: c.apertureM.toFixed(1), pct: Math.round(c.apertureFraction * 100) })}
              {c?.why.map((w) => <small key={w.key} className="sar-bad">{t(w.key, w.vars)}</small>)}</td>
            <td><button type="button" onClick={() => setReflectors(reflectors.filter((_, j) => j !== i))}>{t('cr.remove')}</button></td>
          </tr>; })}
        </tbody></table>}
        <div className="sar-line-tools">
          <button type="button" disabled={reflectors.length === 0} onClick={() => setReflectors([])}>{t('cr.clear')}</button>
          <a className="sar-btn" download="reflectors.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(crCsv)}`}>{t('cr.csv')}</a>
          <a className="sar-btn" download="radar.json" href={`data:application/json;charset=utf-8,${encodeURIComponent(radarJson(antenna))}`}>{t('cr.radarJson')}</a>
        </div>
        <p className="sar-hint">{t('cr.tip')}</p>
        <details className="sar-more"><summary>{t('cr.antenna')}</summary>
          <p className="sar-hint">{t('cr.antennaHelp')}</p>
          <div className="sar-seg sar-mapmode" role="group">
            {(['right', 'left'] as const).map((sd) => <button key={sd} type="button" className={antenna.side === sd ? 'active' : ''}
              onClick={() => setAntenna({ ...antenna, side: sd })}>{t(`cr.side.${sd}`)}</button>)}
          </div>
          <div className="sar-plan-grid"><div>
            {antField('cr.depression', 'depressionDeg', 1, '°')}
            {antField('cr.elBw', 'elBeamwidthDeg', 1, '°')}
            {antField('cr.azBw', 'azBeamwidthDeg', 1, '°')}
          </div><div>
            {antField('cr.rangeMin', 'rangeMinM', 1, 'm')}
            {antField('cr.rangeMax', 'rangeMaxM', 1, 'm')}
            {antField('cr.wavelength', 'wavelengthM', 0.0001, 'm')}
            {antField('cr.bandwidth', 'bandwidthHz', 1e6, 'Hz')}
            {antField('cr.prf', 'prfHz', 10, 'Hz')}
          </div></div>
        </details>
        <details className="sar-more"><summary>{t('cr.lever')}</summary>
          <p className="sar-hint">{t('cr.leverHelp')}</p>
          <div className="sar-plan-grid"><div>
            <b>{t('cr.lever.ant')}</b>
            {antField('cr.lever.fwd', 'antFwdM', 0.005, 'm')}
            {antField('cr.lever.right', 'antRightM', 0.005, 'm')}
            {antField('cr.lever.down', 'antDownM', 0.005, 'm')}
          </div><div>
            <b>{t('cr.lever.gnss')}</b>
            {antField('cr.lever.fwd', 'gnssFwdM', 0.005, 'm')}
            {antField('cr.lever.right', 'gnssRightM', 0.005, 'm')}
            {antField('cr.lever.down', 'gnssDownM', 0.005, 'm')}
          </div></div>
          <p className="sar-hint">{t('cr.leverPx4')}</p>
        </details>
      </div>
      <details className="sar-more"><summary>{t('sar.plan.byNumbers')}</summary>
        {coordField('sar.plan.start', draft.start, (p) => setDraft({ ...draft, start: p }))}
        {coordField('sar.plan.end', draft.end, (p) => setDraft({ ...draft, end: p }))}
      </details>
    </Step>

    <Step n={3} title={t('sar.step.cond')} help={t('sar.step.condHelp')} level={step3} open={step3 !== 'good'}>
      <div className="sar-plan-grid">
        <div>
          {numberField('sar.plan.alt', draft.altM, (v) => setDraft({ ...draft, altM: v }), { step: 1, min: SAR_RULES.minAltM, max: SAR_RULES.maxAltM, unit: 'm' })}
          {numberField('sar.plan.speed', draft.speedMps, (v) => setDraft({ ...draft, speedMps: v }), { step: 0.5, min: SAR_RULES.minSpeed, max: SAR_RULES.maxSpeed, unit: 'm/s' })}
          {numberField('sar.plan.passes', draft.passes, (v) => setDraft({ ...draft, passes: v }), { step: 1, min: SAR_RULES.minPasses, hintKey: 'sar.plan.passesHint' })}
          {numberField('sar.plan.gap', draft.gapS, (v) => setDraft({ ...draft, gapS: v }), { step: 1, min: SAR_RULES.minGapS, unit: 's' })}
        </div>
        <div>
          <label className="sar-check"><input type="checkbox" checked={draft.requireRtk} onChange={(e) => setDraft({ ...draft, requireRtk: e.target.checked })} />{t('sar.plan.requireRtk')}</label>
          <label className="sar-check"><input type="checkbox" checked={draft.rtlOnAbort} onChange={(e) => setDraft({ ...draft, rtlOnAbort: e.target.checked })} />{t('sar.plan.rtlOnAbort')}</label>
          <label className="sar-check"><input type="checkbox" checked={draft.rtlOnDone} onChange={(e) => setDraft({ ...draft, rtlOnDone: e.target.checked })} />{t('sar.plan.rtlOnDone')}</label>
        </div>
      </div>
      <PlanBudget draft={draft} wind={fcxReport?.wind ?? null} antenna={antenna} />
      <details className="sar-more"><summary>{t('sar.plan.advanced')}</summary>
        <p className="sar-hint">{t('sar.plan.advancedHelp')}</p>
        <div className="sar-plan-grid">
          <div>
            {numberField('sar.plan.leadIn', draft.leadInM, (v) => setDraft({ ...draft, leadInM: v }), { step: 1, min: 0, unit: 'm' })}
            <small className="sar-hint">{t('sar.plan.leadInAuto', { m: autoLeadInM(Number.isFinite(draft.speedMps) ? draft.speedMps : SAR_RULES.defaultSpeed).toFixed(1) })}</small>
            {numberField('sar.plan.extraPasses', draft.extraPasses, (v) => setDraft({ ...draft, extraPasses: v }), { step: 1, min: 0, max: 10 })}
            {numberField('sar.plan.minBattery', draft.minBatteryPct, (v) => setDraft({ ...draft, minBatteryPct: v }), { step: 5, min: 10, max: 80, unit: '%', hintKey: 'sar.plan.minBatteryHint' })}
          </div>
          <div>
            {numberField('sar.plan.qCross', draft.qCrossM, (v) => setDraft({ ...draft, qCrossM: v }), { step: 0.1, min: 0.1, unit: 'm' })}
            {numberField('sar.plan.qSpeed', draft.qSpeedMps, (v) => setDraft({ ...draft, qSpeedMps: v }), { step: 0.05, min: 0.05, unit: 'm/s' })}
            {numberField('sar.plan.qAlt', draft.qAltM, (v) => setDraft({ ...draft, qAltM: v }), { step: 0.1, min: 0.1, unit: 'm' })}
            {numberField('sar.plan.qHeading', draft.qHeadingDeg, (v) => setDraft({ ...draft, qHeadingDeg: v }), { step: 0.5, min: 0.5, unit: '°' })}
            {numberField('sar.plan.qCourse', draft.qCourseDeg, (v) => setDraft({ ...draft, qCourseDeg: v }), { step: 0.5, min: 1, unit: '°', hintKey: 'sar.plan.qCourseHint' })}
            {numberField('sar.plan.qEdge', draft.qEdgeM, (v) => setDraft({ ...draft, qEdgeM: v }), { step: 0.5, min: 0, unit: 'm' })}
          </div>
        </div>
      </details>
      {problems.length > 0
        ? <ul className="sar-problems">{problems.map((p) => <li key={p.key}>{t(p.key, p.vars)}</li>)}</ul>
        : <p className="sar-ok">{t('sar.plan.ok')}</p>}
      {estimate !== null && <p className="sar-hint">
        {t('sar.plan.estimate', { m: estimate.lengthM.toFixed(1), deg: estimate.headingDeg.toFixed(0), lead: estimate.leadInM.toFixed(1),
          cap: estimate.captureS.toFixed(1), total: Math.ceil(estimate.totalMinS / 60) })}
      </p>}
    </Step>

    <Step n={4} title={t('sar.step.run')} help={t('sar.step.runHelp')} level={running ? 'good' : canStart ? 'now' : 'todo'} open>
      <dl className="device-facts">
        <div><dt>{t('sar.run.device')}</dt><dd>{deviceId ?? t('sar.run.noDevice')}</dd></div>
        {link.client !== null && <div><dt>{t('sar.run.declared')}</dt><dd>{t(`sar.support.${link.start}`)} · sar_abort {t(`sar.support.${link.abort}`)}</dd></div>}
        <div><dt>{t('sar.run.rtk')}</dt><dd><RtkBadge level={rtk} />{draft.requireRtk && rtk !== 'fixed' && <em className="sar-warn"> {t('sar.run.rtkBlocks', { level: t(RTK_LABEL_KEY[rtk]) })}</em>}</dd></div>
      </dl>
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
      {link.start !== 'yes' && <p className="sar-hint">{t('sar.run.sshHint')}</p>}
      {outcome !== null && <p className={outcome.result.accepted === true ? 'sar-ok' : outcome.result.accepted === false || !outcome.result.sent ? 'sar-bad' : 'sar-warn'}>
        {t(outcome.action === 'start' ? 'sar.run.startResult' : 'sar.run.abortResult', { message: outcome.result.message })}
      </p>}
      {link.client !== null && link.abort === 'no' && <p className="sar-bad">{t('sar.cmd.abortUnsupported')}</p>}
    </Step>

    <Step n={5} title={t('sar.step.progress')} help={t('sar.step.progressHelp')} level={running ? 'now' : report ? 'good' : 'todo'} open={running}>
      {report === null ? <p className="sar-empty">{t('sar.noReport')}</p> : <Progress report={report} />}
    </Step>

    <Step n={6} title={t('sar.step.result')} help={t('sar.step.resultHelp')} level={finished ? 'now' : 'todo'} open={finished || data.flights.length > 0}>
      {report !== null && report.passes.length > 0 && <PassTable report={report} />}
      <DataPanel data={data} reflectors={reflectors} />
    </Step>
  </div>;
}

const ENDURANCE_KEY = 'viz.sar.enduranceMin.v1';

/** 바람이 빔에 주는 영향 · 배터리 예산 — 계획을 바꾸면 바로 다시 계산한다. */
function PlanBudget({ draft, wind, antenna }: { draft: SarPlanDraft; wind: { speedMps: number | null; fromDeg: number | null } | null; antenna: AntennaDraft }) {
  useLang();
  const [endurance, setEndurance] = useState<number>(() => { try { return Number(localStorage.getItem(ENDURANCE_KEY)) || 18; } catch { return 18; } });
  const [manual, setManual] = useState<{ speedMps: number; fromDeg: number } | null>(null);
  const line = draft.start && draft.end ? lineOf(draft.start, draft.end) : null;
  const w = wind?.speedMps != null && wind.fromDeg != null ? { speedMps: wind.speedMps, fromDeg: wind.fromDeg } : manual;
  const fx = line && w ? windEffect(line.headingDeg, draft.speedMps, w, antenna.depressionDeg, antenna.elBeamwidthDeg, antenna.azBeamwidthDeg) : null;
  const bud = batteryBudget(draft, endurance);
  const f1 = (v: number) => v.toFixed(1);
  return <div className="sar-budget">
    <div className={`sar-budget-card is-${fx?.level ?? 'none'}`}>
      <div className="sar-budget-head">
        <b>{t('plan.wind.title')}</b>
        <small>{wind?.speedMps != null ? t('plan.wind.fromFc') : t('plan.wind.manual')}</small>
      </div>
      <div className="sar-budget-body">
        {line && <WindRose headingDeg={line.headingDeg} wind={w} side={antenna.side} />}
        <div>
          {w === null ? <p className="sar-hint">{t('plan.wind.none')}</p> : <>
            <p className="sar-budget-big">{f1(w.speedMps)} m/s <small>{t('plan.wind.from', { deg: Math.round(w.fromDeg) })}</small></p>
            {fx && <ul className="sar-budget-list">
              <li>{t(fx.headMps >= 0 ? 'plan.wind.compHead' : 'plan.wind.compTail', { v: f1(Math.abs(fx.headMps)), cross: f1(Math.abs(fx.crossMps)) })}</li>
              <li>{t('plan.wind.tilt', { roll: f1(fx.rollDeg), pitch: f1(fx.pitchDeg) })}</li>
              <li>{t(fx.squintDeg >= 0 ? 'plan.wind.beamBack' : 'plan.wind.beamFwd', { el: f1(Math.abs(fx.rollDeg)), sq: f1(Math.abs(fx.squintDeg)) })}</li>
            </ul>}
            {fx && fx.level !== 'ok' && <p className={fx.level === 'bad' ? 'sar-bad' : 'sar-warn'}>{t(`plan.wind.advice.${fx.level}`)}</p>}
          </>}
          {wind?.speedMps == null && <div className="sar-inline">
            <label>{t('plan.wind.speed')} <input type="number" step={0.5} min={0} value={manual?.speedMps ?? ''}
              onChange={(e) => setManual(e.target.value === '' ? null : { speedMps: Number(e.target.value), fromDeg: manual?.fromDeg ?? 0 })} /> m/s</label>
            <label>{t('plan.wind.dir')} <input type="number" step={10} min={0} max={359} value={manual?.fromDeg ?? ''}
              onChange={(e) => setManual({ speedMps: manual?.speedMps ?? 0, fromDeg: Number(e.target.value) || 0 })} />°</label>
          </div>}
        </div>
      </div>
    </div>
    <div className={`sar-budget-card is-${bud?.level ?? 'none'}`}>
      <div className="sar-budget-head"><b>{t('plan.batt.title')}</b>
        <label className="sar-inline">{t('plan.batt.endurance')} <input type="number" min={5} max={60} step={1} value={endurance}
          onChange={(e) => { const v = Number(e.target.value) || 18; setEndurance(v); try { localStorage.setItem(ENDURANCE_KEY, String(v)); } catch { /* */ } }} /> {t('plan.batt.min')}</label>
      </div>
      {bud === null ? <p className="sar-hint">{t('plan.batt.needLine')}</p> : <>
        <div className="sar-budget-bar" role="img" aria-label={t('plan.batt.title')}>
          <span className="pass" style={{ width: `${Math.min(100, (bud.passMin / Math.max(bud.usableMin, 0.1)) * 100)}%` }} />
          <span className="retry" style={{ width: `${Math.max(0, Math.min(100, ((bud.worstMin - bud.passMin) / Math.max(bud.usableMin, 0.1)) * 100))}%` }} />
        </div>
        <p className="sar-budget-big">{t('plan.batt.need', { pass: f1(bud.passMin), worst: f1(bud.worstMin), usable: f1(bud.usableMin) })}</p>
        {bud.level !== 'ok' && <p className={bud.level === 'bad' ? 'sar-bad' : 'sar-warn'}>{t(`plan.batt.advice.${bud.level}`)}</p>}
      </>}
    </div>
  </div>;
}

/** 작은 바람 장미 — 선 방향(파랑) · 안테나 쪽(청록 점선) · 바람(주황, 불어 오는 쪽에서 화살). */
function WindRose({ headingDeg, wind, side }: { headingDeg: number; wind: { speedMps: number; fromDeg: number } | null; side: 'right' | 'left' }) {
  const R = 44;
  const pt = (deg: number, r: number) => ({ x: 50 + r * Math.sin((deg * Math.PI) / 180), y: 50 - r * Math.cos((deg * Math.PI) / 180) });
  const a = pt(headingDeg + 180, R - 6);
  const b = pt(headingDeg, R - 6);
  const ant = pt(headingDeg + (side === 'right' ? 90 : -90), R - 10);
  const wf = wind ? pt(wind.fromDeg, R) : null;
  const wt = wind ? pt(wind.fromDeg, 12) : null;
  return <svg viewBox="0 0 100 100" className="sar-rose" aria-hidden="true">
    <circle cx={50} cy={50} r={R} className="ring" />
    <text x={50} y={9} className="n">N</text>
    <line x1={50} y1={50} x2={ant.x} y2={ant.y} className="ant" />
    <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="line" markerEnd="url(#sarRoseArrow)" />
    {wf && wt && <line x1={wf.x} y1={wf.y} x2={wt.x} y2={wt.y} className="wind" markerEnd="url(#sarRoseWind)" />}
    <defs>
      <marker id="sarRoseArrow" viewBox="0 0 10 10" refX={8} refY={5} markerWidth={5} markerHeight={5} orient="auto"><path d="M0,0 L10,5 L0,10 z" className="line-head" /></marker>
      <marker id="sarRoseWind" viewBox="0 0 10 10" refX={8} refY={5} markerWidth={5} markerHeight={5} orient="auto"><path d="M0,0 L10,5 L0,10 z" className="wind-head" /></marker>
    </defs>
  </svg>;
}

function Progress({ report }: { report: SarReport }) {
  useLang();
  const stale = isSarStale(report);
  const live = report.live;
  const plan = report.plan;
  const along = live?.alongM ?? null;
  const lengthM = plan?.lengthM ?? null;
  const pct = along !== null && lengthM !== null && lengthM > 0 ? Math.max(0, Math.min(100, (along / lengthM) * 100)) : null;
  const speedErr = live?.groundSpeedMps != null && plan?.speedMps ? live.groundSpeedMps - plan.speedMps : null;
  const last = report.passes.at(-1);
  return <div className={stale ? 'is-stale' : ''}>
    {stale && <p className="sar-warn">{t('sar.stale', { sec: Math.round((Date.now() - report.receivedAtMs) / 1000) })}</p>}
    <ol className="sar-steps">
      {STEPS.map((s) => <li key={s} className={s === report.state ? 'is-now' : ''}>{t(stateKey(s))}</li>)}
    </ol>
    <div className="sar-card__row">
      <b className={`sar-state sar-state--${report.state}`}>{t(stateKey(report.state))}</b>
      {report.passesTotal !== null && <span>{t('sar.validOf', { n: report.validPasses ?? 0, total: report.passesTotal, try: report.passNo })}</span>}
      <span className={`sar-cap ${report.capturing ? 'is-on' : ''}`}>{report.capturing ? t('sar.cap.on') : t('sar.cap.off')}</span>
      {report.capAck !== null && <span className={`sar-ack ${report.capAck ? 'is-on' : ''}`}>{report.capAck ? t('sar.ack.on') : t('sar.ack.off')}</span>}
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
      {report.battery && <div><dt>{t('sar.live.battery')}</dt><dd>{t('sar.live.batteryValue', { b: report.battery.batteryPct.toFixed(0), need: report.battery.needPct.toFixed(0), rate: (report.battery.drainPctS * 60).toFixed(1) })}</dd></div>}
      <div><dt>{t('sar.live.learned')}</dt><dd>{t('sar.live.learnedValue', { lead: fmt(last?.leadInM, 0), cap: fmt(last?.capLeadS, 2) })}</dd></div>
      <div><dt>{t('sar.live.clock')}</dt>
        <dd className={report.clockOffsetS !== null && Math.abs(report.clockOffsetS) > 1 ? 'sar-bad' : ''}>
          {report.clockOffsetS === null ? t('sar.live.clockUnknown') : `${report.clockOffsetS >= 0 ? '+' : ''}${report.clockOffsetS.toFixed(3)} s`}
        </dd></div>
    </dl>
    {report.warnings.map((w) => <p key={w} className="sar-warn">{w}</p>)}
    {report.message !== null && <p className={report.state === 'incomplete' ? 'sar-warn' : 'sar-ok'}>{report.message}</p>}
    {report.error !== null && <p className="sar-bad">{report.error}</p>}
  </div>;
}

function localTime(unix: number | null): string {
  if (unix === null) return '—';
  return new Date(unix * 1000).toLocaleTimeString(undefined, { hour12: false }) + `.${String(Math.round((unix % 1) * 1000)).padStart(3, '0')}`;
}

function PassTable({ report }: { report: SarReport }) {
  useLang();
  const length = report.plan?.lengthM ?? null;
  const csv = useMemo(() => {
    const head = 'pass,valid,reasons,start_unix,end_unix,fc_start_unix,fc_end_unix,ack_start_unix,ack_end_unix,ack_latency_s,eff_start_along_m,eff_end_along_m,mean_speed_mps,max_speed_err_mps,max_cross_track_m,max_alt_err_m,max_heading_err_deg,max_course_err_deg,worst_fix,traj_csv';
    const rows = report.passes.map((p) => [p.passNo, p.valid, JSON.stringify(p.reasons.join('; ')), p.startUnix, p.endUnix, p.fcStartUnix, p.fcEndUnix,
      p.ackStartUnix, p.ackEndUnix, p.ackOnLatencyS, p.effStartAlongM, p.effEndAlongM, p.meanSpeedMps, p.maxSpeedErrMps, p.maxCrossTrackM,
      p.maxAltErrM, p.maxHeadingErrDeg, p.maxCourseErrDeg, p.worstFix, p.trajCsv].map((v) => v ?? '').join(','));
    return [head, ...rows].join('\n');
  }, [report.passes]);
  return <>
    <table className="sar-table">
      <thead><tr>
        <th>{t('sar.log.pass')}</th><th>{t('sar.log.verdict')}</th><th>{t('sar.log.recorded')}</th><th>{t('sar.log.start')}</th>
        <th>{t('sar.log.radarLag')}</th><th>{t('sar.log.meanSpeed')}</th><th>{t('sar.log.maxErr')}</th><th>{t('sar.log.worstFix')}</th>
      </tr></thead>
      <tbody>{report.passes.map((p) => <tr key={p.passNo} className={p.valid === false ? 'is-missed' : ''}>
        <td>{p.passNo}</td>
        <td>{p.valid === null ? '…' : p.valid ? <span className="sar-ok">✓ {t('sar.log.valid')}</span>
          : <span className="sar-bad">✕ {t('sar.log.invalid')}<small>{p.reasons.join(' · ')}</small></span>}</td>
        <td>{p.effStartAlongM === null ? '—' : `${p.effStartAlongM.toFixed(1)} ~ ${fmt(p.effEndAlongM, 1)} m`}{length !== null && <small>{t('sar.log.target', { m: length.toFixed(0) })}</small>}</td>
        <td>{localTime(p.startUnix)}{p.fcStartUnix !== null && <small>FC {p.fcStartUnix.toFixed(3)}</small>}</td>
        <td>{p.ackOnLatencyS === null ? '—' : `${p.ackOnLatencyS.toFixed(2)} s`}{p.capLeadS ? <small>{t('sar.log.leadUsed', { s: p.capLeadS.toFixed(2) })}</small> : null}</td>
        <td>{fmt(p.meanSpeedMps, 2)} m/s</td>
        <td>{t('sar.log.maxErrValue', { v: fmt(p.maxSpeedErrMps, 2), x: fmt(p.maxCrossTrackM, 2), z: fmt(p.maxAltErrM, 2), h: fmt(p.maxHeadingErrDeg, 1), c: fmt(p.maxCourseErrDeg, 1) })}</td>
        <td className={p.worstFix !== null && p.worstFix !== 'RTK_FIXED' ? 'sar-bad' : ''}>{p.worstFix ?? '—'}</td>
      </tr>)}</tbody>
    </table>
    <a className="sar-download" download={`sar_passes_${report.deviceId}.csv`} href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`}>
      {t('sar.log.csv')}
    </a>
  </>;
}

/** ⑥ 비행 데이터 내려받기 — Pi 의 데이터 서버에서. 버튼 하나 = 파일 하나. */
function DataPanel({ data, reflectors }: { data: ReturnType<typeof useDataServer>; reflectors: readonly LatLon[] }) {
  useLang();
  const [open, setOpen] = useState<string | null>(null);
  const [view, setView] = useState<string | null>(null);
  const [inspect, setInspect] = useState<string | null>(null);
  if (data.base === '') return <p className="sar-hint">{t('sar.data.noUrl')}</p>;
  if (data.ok === false) return <div><p className="sar-warn">{t('sar.data.fail', { url: data.base, why: data.error ?? '' })}</p>
    <p className="sar-hint">{t('sar.data.howTo')}</p><button type="button" onClick={data.refresh}>{t('sar.data.retry')}</button></div>;
  if (data.ok === null) return <p className="sar-hint">{t('sar.data.loading')}</p>;
  if (data.flights.length === 0) return <p className="sar-hint">{t('sar.data.empty')}</p>;
  const url = (f: string, path: string) => `${data.base}/api/flights/${encodeURIComponent(f)}/${path}`;
  return <div className="sar-data">
    <div className="sar-data-head"><b>{t('sar.data.title')}</b><small>{data.base}</small><button type="button" onClick={data.refresh}>{t('sar.data.retry')}</button></div>
    {data.flights.map((f) => <div key={f.id} className="sar-flight">
      <div className="sar-flight-row" onClick={() => setOpen(open === f.id ? null : f.id)}>
        <b>{new Date(f.started_unix * 1000).toLocaleString(undefined, { hour12: false })}</b>
        <span>{t('sar.data.flightInfo', { n: f.passes.length, v: f.valid_passes, size: bytes(f.size_bytes) })}</span>
        <span className={f.ulogs && f.ulogs.length > 0 ? 'sar-ok' : 'sar-hint'} title={t('sar.data.ulogHint')}>
          {f.ulogs && f.ulogs.length > 0 ? t('sar.data.ulogYes', { size: bytes(f.ulogs.reduce((a, u) => a + u.size, 0)) }) : t('sar.data.ulogNo')}</span>
        <a className="sar-btn" href={url(f.id, 'report.html')} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{t('sar.data.report')}</a>
        <a className="sar-btn" href={url(f.id, 'bundle.zip?raw=0')} onClick={(e) => e.stopPropagation()}>{t('sar.data.positionAll')}</a>
        <a className="sar-btn sar-btn--main" href={url(f.id, 'bundle.zip')} onClick={(e) => e.stopPropagation()}>{t('sar.data.all')}</a>
      </div>
      {(open === f.id || data.flights.length === 1) && <div className="sar-passes">
        {f.passes.map((p) => {
          const key = `${f.id}:${p.pass_no}`;
          return <div key={p.pass_no} className={`sar-pass-card${p.valid === false ? ' is-missed' : p.valid ? ' is-valid' : ''}`}>
            <div className="sar-pass-main">
              <b className="sar-pass-no">{t('sar.data.pass', { n: p.pass_no })}</b>
              {p.valid ? <span className="sar-chip is-ok">✓ {t('sar.log.valid')}</span> : <span className="sar-chip is-bad">✕ {t('sar.log.invalid')}</span>}
              <span className="sar-pass-radar">{t('sar.data.radarFiles', { n: p.radar_files.length, size: bytes(p.radar_bytes) })}</span>
              {p.valid === false && p.reasons.length > 0 && <small className="sar-pass-why">{p.reasons.join(' · ')}</small>}
            </div>
            <div className="sar-pass-actions">
              {p.traj_csv && <button type="button" className={`sar-act${inspect === key ? ' is-on' : ''}`}
                onClick={() => setInspect(inspect === key ? null : key)}>{t('pi.open')}</button>}
              <ImageButton base={data.base} flight={f.id} pass={p.pass_no} summary={p.image ?? null} imaging={data.imaging}
                hasRaw={p.radar_files.length > 0} reflectors={reflectors}
                onOpen={() => { setView(key); data.refresh(); }} />
              <span className="sar-pass-dl">
                <a className="sar-btn sar-btn--main" href={url(f.id, `bundle.zip?pass=${p.pass_no}`)}>{t('sar.data.passZip')}</a>
                {p.traj_csv && <a className="sar-btn" href={url(f.id, `files/${encodeURIComponent(p.traj_csv)}`)}>{t('sar.data.trajCsv')}</a>}
                <a className="sar-btn" href={url(f.id, `files/${encodeURIComponent(p.meta_json)}`)}>{t('sar.data.meta')}</a>
              </span>
            </div>
            {inspect === key && p.traj_csv && <div className="sar-pass-open">
              <PassInspector base={data.base} flight={f.id} csvName={p.traj_csv} metaName={p.meta_json} />
            </div>}
            {view === key && <div className="sar-pass-open">
              <SarImageView base={data.base} flight={f.id} pass={p.pass_no} />
              <button type="button" onClick={() => setView(null)}>{t('img.close')}</button>
            </div>}
          </div>;
        })}
      </div>}
      {(open === f.id || data.flights.length === 1) && <ComparePanel base={data.base} flight={f.id}
        passes={[...f.passes.filter((p) => p.image?.full && p.valid), ...f.passes.filter((p) => p.image?.full && !p.valid)].map((p) => p.pass_no)} />}
    </div>)}
    <ImagingStatus imaging={data.imaging} mirror={data.mirror} />
  </div>;
}
