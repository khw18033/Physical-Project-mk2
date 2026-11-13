/**
 * src/views/SeqMissionPanel.tsx (261113 신설 — 드론 상세창 · 비행 제어 탭 · 복합 미션)
 *
 * **단계 목록을 한 미션으로 날린다** — 「5m 이륙 → 오른쪽 3m → 앞 1m → 착륙」. 비행 코드는 pi3 의 `mission_seq.py` 이고,
 * 이 화면은 단계를 넘기고 출력을 읽을 뿐이다(`MISSION_SEQ_요청_VZ.md`). 흐름은 요청 문서 §7 그대로다.
 *
 *   편집 → 미리보기 → dry-run → 계획 확인 → 비행 시작(「yes」) → 진행 표시 → 결과
 *
 *   - 미리보기는 드론 쪽 `seq_plan.py` 와 같은 식(`seqPlan.previewOf`)으로 그린 **기체 기준 평면도**다. 위가 이륙 직전 기수이고,
 *     회전 단계 뒤부터는 화살표가 돌아간 기수를 가리킨다 — 「돌고 나서 앞」 을 눈으로 확인하는 곳.
 *   - dry-run 이 끝나면 드론이 계산한 계획(`run.plan`)을 같은 그림에 겹치고, 단계 끝마다 화면 계산과 맞는지 표시한다.
 *   - 비행 버튼은 내 dry-run 이 종료 코드 0 이고 **그 `mission_key` 가 지금 편집기의 키와 같을 때만** 열린다(`seqGate`).
 *   - 진행 중에는 지금 단계를 강조하고, FC 실시간 위치(fcx)를 평면도에 겹친다.
 *
 * 편집 중인 미션은 장비마다 화면이 떠 있는 동안 기억한다.
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { useFcxReports, isFcxStale, type FcxReport } from '../shared/fcxStatus.ts';
import { isFlightRunStale, landingOf, runOutcome, useFlightRuns } from '../physical/flightRunFeed.ts';
import { EMERGENCY_MODES, type EmergencyMode } from '../physical/flightPlan.ts';
import { issueFlightEmergency } from '../physical/flightRunCommands.ts';
import {
  readSeqProgress, stepState, useMissionRuns, type MissionProcess, type SeqPlanReport, type SeqProgress,
} from '../physical/missionRunFeed.ts';
import { anyFlightRunning, issueSeqStart, issueSeqStop, seqGate, seqLink, type SeqGate } from '../physical/seqMissionCommands.ts';
import {
  LANDS, missionFingerprint, missionKey, MOVE_KINDS, newStep, previewOf, SEQ_ABORTS, SEQ_DEFAULTS, SEQ_LIMITS, SEQ_SCRIPT, seqProblems,
  STEP_KINDS, stepClass, withKind, type BodyPoint, type SeqMission, type SeqProblem, type SeqStep, type StepKind,
} from '../physical/seqPlan.ts';
import { NumberField } from './ManualControlTab.tsx';
import { useEverySec } from './ManualControlBadge.tsx';
import { ArmedButton, runSummary } from './FlightRunBadge.tsx';
import {
  fcLanding, fcxHeading, LandingNote, OptionalNumberField, Radio, RunLog, Steps, supportChip, useDeviceActions, VehicleFacts,
} from './FlightControlTab.tsx';

// ── 장비별 미션 (화면이 떠 있는 동안) ──────────────────────────────────────

let missions: Readonly<Record<string, SeqMission>> = {};
const missionListeners = new Set<() => void>();

function setMission(deviceId: string, mission: SeqMission): void {
  missions = { ...missions, [deviceId]: mission };
  for (const listener of missionListeners) listener();
}

function useMission(deviceId: string): SeqMission {
  return useSyncExternalStore((listener) => {
    missionListeners.add(listener);
    return () => { missionListeners.delete(listener); };
  }, () => missions[deviceId] ?? SEQ_DEFAULTS);
}

// ── 글자 ────────────────────────────────────────────────────────────────

const UNIT: Readonly<Record<ReturnType<typeof stepClass>, string>> = { move: 'm', rot: '°', hover: 's' };

/** `오른쪽 3m` · `시계 90°` · `대기 5s` (+ 속도 · 캡처). */
function stepLabel(step: SeqStep): string {
  const cls = stepClass(step.kind);
  const extra = [step.speedMps !== null ? `${step.speedMps}m/s` : '', step.capture ? t('seq.step.capShort') : ''].filter(Boolean).join(' · ');
  return `${t(`seq.kind.${step.kind}`)} ${step.value}${UNIT[cls]}${extra ? ` (${extra})` : ''}`;
}

function problemText(problem: SeqProblem): string {
  switch (problem.kind) {
    case 'range': return t('flight.problem.range', { field: t(`seq.field.${problem.field}`), min: problem.min, max: problem.max });
    case 'count': return t('seq.problem.count', { min: problem.min, max: problem.max });
    case 'value': return t('seq.problem.value', { k: problem.k, kind: t(`seq.kind.${problem.step}`), min: problem.min, max: problem.max, unit: UNIT[stepClass(problem.step)] });
    case 'speed': return t('seq.problem.speed', { k: problem.k, min: problem.min, max: problem.max });
    case 'speedNotMove': return t('seq.problem.speedNotMove', { k: problem.k });
    case 'radius': return t('seq.problem.radius', { got: problem.got.toFixed(1), max: problem.max });
    case 'path': return t('seq.problem.path', { got: problem.got.toFixed(1), max: problem.max });
  }
}

const fmtM = (x: number) => (Math.abs(x) < 0.0005 ? '0' : x.toFixed(Math.abs(x) >= 100 ? 0 : 2).replace(/\.?0+$/, ''));

// ── 평면도 ──────────────────────────────────────────────────────────────

/** 지구 반지름(m) — 실시간 위치를 L 원점 북 · 동으로 바꿀 때만 쓴다(수십 m 범위라 평면 근사로 충분). */
const R_EARTH = 6_378_137;

function liveBody(fcx: FcxReport | undefined, plan: SeqPlanReport | null): (BodyPoint & { stale: boolean }) | null {
  const lat = fcx?.position?.lat ?? null;
  const lon = fcx?.position?.lon ?? null;
  if (fcx === undefined || plan?.L == null || plan.h0 === null || lat === null || lon === null) return null;
  const [lat0, lon0] = plan.L;
  const n = ((lat - lat0) * Math.PI / 180) * R_EARTH;
  const e = ((lon - lon0) * Math.PI / 180) * R_EARTH * Math.cos((lat0 * Math.PI) / 180);
  const h = (plan.h0 * Math.PI) / 180;
  const heading = fcxHeading(fcx);
  return {
    fwd: n * Math.cos(h) + e * Math.sin(h),
    right: -n * Math.sin(h) + e * Math.cos(h),
    yaw: heading === null ? 0 : heading - plan.h0,
    stale: isFcxStale(fcx),
  };
}

/** 드론 계획의 단계 끝이 화면 계산과 같은가(1 cm). 계획에 그 단계가 없으면 `null`. */
function planMatches(preview: BodyPoint[], plan: SeqPlanReport | null): (boolean | null)[] {
  return preview.map((point, index) => {
    const to = plan?.steps.find((step) => step.k === index + 1)?.to ?? null;
    if (to === null) return null;
    return Math.abs(to.fwd - point.fwd) < 0.01 && Math.abs(to.right - point.right) < 0.01;
  });
}

function Arrow({ x, y, yaw, size, className }: { x: number; y: number; yaw: number; size: number; className: string }) {
  return <path transform={`translate(${x} ${y}) rotate(${yaw})`} className={className}
    d={`M0,${-size} L${size * 0.55},${size * 0.5} L0,${size * 0.15} L${-size * 0.55},${size * 0.5} Z`} />;
}

/**
 * **기체 기준 평면도.** 위 = 이륙 직전 기수. 점마다 단계 번호와 그 단계 끝의 기수 화살표, 이륙 지점(L) · 착륙점 · 최대 거리 원.
 * `plan` 이 있으면 드론이 계산한 단계 끝을 속 빈 마름모로 겹치고, `live` 가 있으면 지금 위치 · 기수를 겹친다.
 */
function SeqPreview({ mission, plan, live, activeStep }: {
  mission: SeqMission; plan: SeqPlanReport | null; live: (BodyPoint & { stale: boolean }) | null; activeStep: number | null;
}) {
  useLang();
  const preview = previewOf(mission);
  const vertices = [{ fwd: 0, right: 0, yaw: 0 }, ...preview.ends];
  const extentM = Math.max(2.5, ...vertices.map((p) => Math.max(Math.abs(p.fwd), Math.abs(p.right))),
    live === null ? 0 : Math.max(Math.abs(live.fwd), Math.abs(live.right))) * 1.25;
  const half = 100;
  const scale = (half - 14) / extentM;
  const X = (p: { right: number }) => p.right * scale;
  const Y = (p: { fwd: number }) => -p.fwd * scale;
  const ringR = mission.maxRadiusM * scale;
  // 같은 자리의 단계(회전 · 대기)는 번호를 묶어 하나로 쓴다. 화살표는 그 자리 마지막 단계의 기수.
  const groups: { fwd: number; right: number; yaw: number; ks: number[] }[] = [];
  preview.ends.forEach((point, index) => {
    const same = groups.find((g) => Math.abs(g.fwd - point.fwd) < 1e-6 && Math.abs(g.right - point.right) < 1e-6);
    if (same !== undefined) { same.ks.push(index + 1); same.yaw = point.yaw; } else groups.push({ ...point, ks: [index + 1] });
  });
  const atL = groups.find((g) => Math.abs(g.fwd) < 1e-6 && Math.abs(g.right) < 1e-6);
  const north = plan?.h0 ?? null;
  const grid = extentM > 20 ? 10 : extentM > 8 ? 5 : extentM > 3 ? 2 : 1;
  const gridLines: number[] = [];
  for (let v = grid; v * scale < half; v += grid) gridLines.push(v);
  return <svg className="seq-map" viewBox={`${-half} ${-half} ${half * 2} ${half * 2}`} role="img" aria-label={t('seq.preview.aria')}>
    {gridLines.flatMap((v) => [v, -v]).map((v) => <g key={v} className="seq-map__grid">
      <line x1={v * scale} y1={-half} x2={v * scale} y2={half} /><line x1={-half} y1={v * scale} x2={half} y2={v * scale} />
    </g>)}
    {ringR < half * 1.5
      ? <circle cx="0" cy="0" r={ringR} className="seq-map__ring" />
      : <text x={-half + 4} y={-half + 12} className="seq-map__scale">{t('seq.preview.ringOut', { m: mission.maxRadiusM })}</text>}
    <polyline className="seq-map__path" points={vertices.map((p) => `${X(p)},${Y(p)}`).join(' ')} />
    {mission.land === 'home' && <line className="seq-map__path seq-map__path--home" x1={X(vertices.at(-1)!)} y1={Y(vertices.at(-1)!)} x2="0" y2="0" />}
    {/* 이륙 지점 — 처음 기수 */}
    <Arrow x={0} y={0} yaw={atL?.yaw ?? 0} size={9} className="seq-map__nose" />
    <text x="0" y="20" className="seq-map__label">L{atL !== undefined ? ` · ${atL.ks.join('·')}` : ''}</text>
    {groups.filter((g) => g !== atL).map((g) => {
      const active = activeStep !== null && g.ks.includes(activeStep);
      return <g key={g.ks.join('-')} className={active ? 'seq-map__pt seq-map__pt--active' : 'seq-map__pt'}>
        <Arrow x={X(g)} y={Y(g)} yaw={g.yaw} size={7} className="seq-map__heading" />
        <text x={X(g) + 10} y={Y(g) - 8} className="seq-map__num">{g.ks.join('·')}</text>
      </g>;
    })}
    {/* 착륙점 */}
    <rect x={X(preview.land) - 5} y={Y(preview.land) - 5} width="10" height="10" className="seq-map__land" />
    {/* 드론이 계산한 단계 끝 */}
    {plan?.steps.map((step) => step.to === null ? null
      : <path key={step.k} transform={`translate(${step.to.right * scale} ${-step.to.fwd * scale})`} d="M0,-6 L6,0 L0,6 L-6,0 Z" className="seq-map__drone" />)}
    {live !== null && <Arrow x={X(live)} y={Y(live)} yaw={live.yaw} size={8} className={live.stale ? 'seq-map__live seq-map__live--stale' : 'seq-map__live'} />}
    {north !== null && <g transform={`translate(${half - 16} ${-half + 16}) rotate(${-north})`} className="seq-map__north">
      <path d="M0,-10 L4,4 L0,1 L-4,4 Z" /><text x="0" y="-13">N</text>
    </g>}
    <text x={-half + 4} y={half - 5} className="seq-map__scale">{t('seq.preview.grid', { m: grid })}</text>
  </svg>;
}

// ── 편집기 ──────────────────────────────────────────────────────────────

function StepRow({ step, k, count, disabled, onChange, onMove, onCopy, onDelete, state }: {
  step: SeqStep; k: number; count: number; disabled: boolean;
  onChange(step: SeqStep): void; onMove(delta: -1 | 1): void; onCopy(): void; onDelete(): void;
  state: 'waiting' | 'active' | 'done' | null;
}) {
  useLang();
  const cls = stepClass(step.kind);
  const range = SEQ_LIMITS[cls];
  return <tr className={state === null ? '' : `seq-row--${state}`}>
    <td className="seq-steps__k">{k}</td>
    <td>
      <select value={step.kind} disabled={disabled} aria-label={t('seq.col.kind')}
        onChange={(event) => onChange(withKind(step, event.target.value as StepKind))}>
        {STEP_KINDS.map((kind) => <option key={kind} value={kind}>{t(`seq.kind.${kind}`)}</option>)}
      </select>
    </td>
    <td className="seq-steps__num">
      <NumberField value={step.value} min={range.min} max={range.max} step={cls === 'rot' ? 15 : cls === 'hover' ? 1 : 0.5}
        onCommit={(value) => onChange({ ...step, value })} /> {UNIT[cls]}
    </td>
    <td className="seq-steps__num">{cls === 'move'
      ? <><OptionalNumberField value={step.speedMps} {...SEQ_LIMITS.speedMps} step={0.1} placeholder={t('seq.step.speedDefault')}
        onCommit={(value) => onChange({ ...step, speedMps: value })} /> m/s</>
      : <span className="seq-steps__none">—</span>}</td>
    <td><input type="checkbox" checked={step.capture} disabled={disabled} aria-label={t('seq.col.capture')}
      onChange={(event) => onChange({ ...step, capture: event.target.checked })} /></td>
    <td className="seq-steps__tools">
      <button type="button" disabled={disabled || k === 1} title={t('seq.step.up')} onClick={() => onMove(-1)}>↑</button>
      <button type="button" disabled={disabled || k === count} title={t('seq.step.down')} onClick={() => onMove(1)}>↓</button>
      <button type="button" disabled={disabled || count >= SEQ_LIMITS.steps.max} title={t('seq.step.copy')} onClick={onCopy}>⧉</button>
      <button type="button" disabled={disabled || count <= 1} title={t('seq.step.delete')} onClick={onDelete}>✕</button>
    </td>
  </tr>;
}

// ── 진행 · 결과 ─────────────────────────────────────────────────────────

function StepProgress({ process, progress, mission }: { process: MissionProcess; progress: SeqProgress; mission: SeqMission }) {
  useLang();
  const plan = process.plan;
  // 실행의 단계는 드론 계획(라벨)이 정본이다. 계획 전이면 실행기가 띄운 정규형, 그것도 없으면 편집기.
  const rows = plan !== null && plan.steps.length > 0
    ? plan.steps.map((step) => ({ k: step.k, label: step.label || step.text, cap: step.cap }))
    : process.steps.length > 0
      ? process.steps.map((text, index) => ({ k: index + 1, label: text, cap: text.includes('+cap') }))
      : mission.steps.map((step, index) => ({ k: index + 1, label: stepLabel(step), cap: step.capture }));
  const dry = process.dryRun === true;
  return <table className="seq-progress">
    <thead><tr>
      <th>#</th><th>{t('seq.col.step')}</th><th>{t('seq.col.state')}</th><th>{t('seq.col.posErr')}</th><th>{t('seq.col.yawErr')}</th><th>{t('seq.col.dur')}</th>
    </tr></thead>
    <tbody>{rows.map((row) => {
      const state = dry ? 'waiting' : stepState(progress, row.k);
      const result = progress.results[row.k];
      const capturing = progress.capturingStep === row.k;
      const bad = (result?.posErrM ?? 0) > 1.5 || (result?.yawErrDeg ?? 0) > 15;
      return <tr key={row.k} className={`seq-row--${state}${bad ? ' seq-row--warn' : ''}`}>
        <td className="seq-steps__k">{row.k}</td>
        <td>{row.label}{row.cap && <span className={capturing ? 'seq-cap seq-cap--on' : 'seq-cap'}>{capturing ? t('seq.progress.capOn') : 'CAP'}</span>}</td>
        <td>{dry ? '—' : t(`seq.state.${state}`)}</td>
        <td>{result?.posErrM != null ? `${result.posErrM} m` : '—'}</td>
        <td>{result?.yawErrDeg != null ? `${result.yawErrDeg}°` : '—'}</td>
        <td>{result?.durS != null ? `${result.durS} s` : '—'}</td>
      </tr>;
    })}</tbody>
  </table>;
}

/** dry-run 이 낸 계획 — 단계 끝 좌표와 화면 계산 대조. 지도에 그릴 정답 좌표(`lat` · `lon`)도 여기서 본다. */
function PlanCheck({ plan, mission }: { plan: SeqPlanReport; mission: SeqMission }) {
  useLang();
  const preview = previewOf(mission);
  const sameKey = plan.key === missionKey(mission);
  const matches = sameKey ? planMatches(preview.ends, plan) : [];
  const ll = (p: { lat: number | null; lon: number | null } | null) => (p?.lat != null && p.lon != null ? `${p.lat.toFixed(7)}, ${p.lon.toFixed(7)}` : '—');
  return <>
    <dl className="flight-facts">
      <div><dt>{t('seq.plan.h0')}</dt><dd>{plan.h0 !== null ? `${plan.h0.toFixed(1)}°` : '?'}</dd></div>
      <div><dt>{t('seq.plan.L')}</dt><dd>{plan.L !== null ? `${plan.L[0].toFixed(7)}, ${plan.L[1].toFixed(7)}` : '?'}</dd></div>
      <div><dt>{t('seq.plan.est')}</dt><dd>{plan.estS !== null ? t('flight.route.minutes', { min: (plan.estS / 60).toFixed(1) }) : '?'}</dd></div>
      <div><dt>{t('seq.plan.timeout')}</dt><dd>{plan.timeoutS !== null ? t('flight.route.minutes', { min: (plan.timeoutS / 60).toFixed(1) }) : '?'}</dd></div>
      <div><dt>{t('seq.plan.maxR')}</dt><dd>{plan.maxR ?? '?'} m</dd></div>
      <div><dt>{t('seq.plan.path')}</dt><dd>{plan.pathM ?? '?'} m · {t('seq.plan.items', { n: plan.nItems ?? '?' })}</dd></div>
    </dl>
    {!sameKey && <p className="manual-warn">{t('seq.plan.otherMission')}</p>}
    <table className="seq-progress">
      <thead><tr><th>#</th><th>{t('seq.col.step')}</th><th>{t('seq.col.end')}</th><th>{t('seq.col.yawEnd')}</th><th>{t('seq.col.latlon')}</th>{sameKey && <th>{t('seq.col.match')}</th>}</tr></thead>
      <tbody>
        {plan.steps.map((step, index) => <tr key={step.k} className={matches[index] === false ? 'seq-row--warn' : ''}>
          <td className="seq-steps__k">{step.k}</td>
          <td>{step.label || step.text}</td>
          <td>{step.to !== null ? t('seq.plan.fr', { fwd: fmtM(step.to.fwd), right: fmtM(step.to.right) }) : '—'}</td>
          <td>{step.yaw !== null ? `${step.yaw.toFixed(1)}°` : '—'}</td>
          <td className="seq-mono">{ll(step.to)}</td>
          {sameKey && <td>{matches[index] === null ? '—' : matches[index] ? '✔' : t('seq.plan.mismatch')}</td>}
        </tr>)}
        <tr>
          <td className="seq-steps__k">⬛</td><td>{t(`seq.land.${plan.land === 'home' ? 'home' : 'here'}`)}</td>
          <td>{plan.landPt !== null ? t('seq.plan.fr', { fwd: fmtM(plan.landPt.fwd), right: fmtM(plan.landPt.right) }) : '—'}</td>
          <td>—</td><td className="seq-mono">{ll(plan.landPt)}</td>{sameKey && <td />}
        </tr>
      </tbody>
    </table>
    {matches.includes(false) && <p className="manual-warn">{t('seq.plan.mismatchWhy')}</p>}
  </>;
}

function gateText(gate: SeqGate, other: 'flight' | 'mission' | null): string {
  if (other === 'flight') return t('seq.block.otherFlight');
  return t(`seq.gate.${gate}`);
}

// ── 패널 ────────────────────────────────────────────────────────────────

export function SeqMissionPanel({ deviceId }: { deviceId: string }) {
  useLang();
  useEverySec();
  const actions = useDeviceActions(deviceId);
  const mission = useMission(deviceId);
  const update = (patch: Partial<SeqMission>) => setMission(deviceId, { ...mission, ...patch });
  const setSteps = (steps: SeqStep[]) => update({ steps });
  const entry = useMissionRuns()[deviceId];
  const flightEntry = useFlightRuns()[deviceId];
  const fcx = useFcxReports()[deviceId];
  const link = seqLink(deviceId);
  const problems = seqProblems(mission);
  const run = entry?.run ?? null;
  const running = run?.state === 'running';
  const other = anyFlightRunning(flightEntry, entry);
  const gate = seqGate(deviceId, mission, entry);
  const preview = previewOf(mission);

  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [emergencyMode, setEmergencyMode] = useState<EmergencyMode>('land');

  // 미션을 바꾸면 확인 창을 닫는다 — 읽고 동의한 내용과 보낼 내용이 달라지면 안 된다.
  const fingerprint = missionFingerprint(mission);
  useEffect(() => { setConfirming(false); setTyped(''); }, [fingerprint]);

  const startBlock: string | null = link.start !== 'yes'
    ? (link.reason || (link.start === 'unknown' ? t('flight.link.unknown') : t('seq.link.notDeclared')))
    : problems.length > 0 ? t('flight.block.problems')
      : other === 'mission' ? t('flight.block.running')
        : other === 'flight' ? t('seq.block.otherFlight')
          : null;
  const yes = typed.trim().toLowerCase() === 'yes';

  const send = async (dryRun: boolean) => {
    setBusy(true);
    setNote('');
    const outcome = await issueSeqStart(link, mission, { dryRun, confirmed: !dryRun && yes });
    setNote(outcome.message);
    setBusy(false);
    if (!dryRun) { setConfirming(false); setTyped(''); }
  };

  const progress = run !== null ? readSeqProgress(run.lines, run.plan) : null;
  // 평면도에 겹칠 드론 계획 — 지금 편집기와 같은 미션일 때만(다른 미션의 점을 섞어 그리지 않는다).
  const shownPlan = run?.plan != null && run.plan.key === missionKey(mission) ? run.plan : null;
  const live = running && run?.dryRun === false ? liveBody(fcx, run.plan) : null;
  const passedPlan = gate === 'passed' ? run?.plan ?? null : null;
  const landing = run !== null && progress !== null ? landingOf(progress, fcLanding(fcx)) : 'none';
  const abortName = t(`flight.abort.${mission.abort}`);

  return <div className="manual-tab flight-tab">
    <section className="manual-tab__head">
      <div>
        <b>{t('seq.head.title')}</b>
        <small>{t('seq.head.why')}</small>
      </div>
      <div className="flight-support">
        {supportChip(actions, 'seq_mission_start')}
        {supportChip(actions, 'seq_mission_stop')}
        {supportChip(actions, 'rtk_test_emergency')}
      </div>
    </section>

    <div className="flight-grid">
      <section className="manual-tab__section">
        <header><h3>{t('seq.edit.title')}</h3>
          <button type="button" className="manual-unbind" disabled={running}
            onClick={(event) => { setMission(deviceId, SEQ_DEFAULTS); event.currentTarget.blur(); }}>{t('flight.plan.reset')}</button>
        </header>
        <fieldset className="flight-fields" disabled={running}>
          <div className="manual-steps">
            <label>{t('seq.field.altitudeM')}
              <NumberField value={mission.altitudeM} {...SEQ_LIMITS.altitudeM} step={0.5} onCommit={(value) => update({ altitudeM: value })} /> m
            </label>
            <label>{t('seq.field.speedMps')}
              <NumberField value={mission.speedMps} {...SEQ_LIMITS.speedMps} step={0.1} onCommit={(value) => update({ speedMps: value })} /> m/s
            </label>
          </div>
          <div className="flight-row"><span>{t('seq.field.land')}</span>
            <Radio items={LANDS} value={mission.land} label={t('seq.field.land')} name={(item) => t(`seq.land.${item}`)} onPick={(item) => update({ land: item })} />
          </div>
          <table className="seq-steps">
            <thead><tr>
              <th>#</th><th>{t('seq.col.kind')}</th><th>{t('seq.col.value')}</th><th>{t('seq.col.speed')}</th><th>{t('seq.col.capture')}</th><th />
            </tr></thead>
            <tbody>{mission.steps.map((step, index) => <StepRow key={index} step={step} k={index + 1} count={mission.steps.length} disabled={running}
              state={running && run?.dryRun === false && progress !== null && shownPlan !== null ? stepState(progress, index + 1) : null}
              onChange={(next) => setSteps(mission.steps.map((s, i) => (i === index ? next : s)))}
              onMove={(delta) => {
                const steps = [...mission.steps];
                const [moved] = steps.splice(index, 1);
                steps.splice(index + delta, 0, moved!);
                setSteps(steps);
              }}
              onCopy={() => setSteps([...mission.steps.slice(0, index + 1), { ...step }, ...mission.steps.slice(index + 1)])}
              onDelete={() => setSteps(mission.steps.filter((_, i) => i !== index))} />)}
            </tbody>
          </table>
          <div className="seq-add">
            {STEP_KINDS.map((kind) => <button key={kind} type="button" disabled={mission.steps.length >= SEQ_LIMITS.steps.max}
              onClick={(event) => { setSteps([...mission.steps, newStep(kind)]); event.currentTarget.blur(); }}>+ {t(`seq.kind.${kind}`)}</button>)}
          </div>
          <p className="manual-note">{t('seq.edit.why', { moves: MOVE_KINDS.map((kind) => t(`seq.kind.${kind}`)).join(' · ') })}</p>
          <details className="flight-advanced">
            <summary>{t('flight.advanced.title')}</summary>
            <div className="manual-steps">
              <label>{t('seq.field.maxRadiusM')}
                <NumberField value={mission.maxRadiusM} {...SEQ_LIMITS.maxRadiusM} step={1} onCommit={(value) => update({ maxRadiusM: value })} /> m
              </label>
            </div>
            <div className="flight-row"><span>{t('flight.field.abort')}</span>
              <Radio items={SEQ_ABORTS} value={mission.abort} label={t('flight.field.abort')} name={(item) => t(`flight.abort.${item}`)}
                onPick={(item) => update({ abort: item })} />
            </div>
          </details>
        </fieldset>
        {problems.length > 0 && <ul className="flight-problems">{problems.map((problem, index) => <li key={index}>{problemText(problem)}</li>)}</ul>}
      </section>

      <section className="manual-tab__section flight-preview">
        <header><h3>{t('seq.preview.title')}</h3></header>
        <SeqPreview mission={mission} plan={shownPlan} live={live} activeStep={running ? progress?.stepCur ?? null : null} />
        <p className="seq-legend">{t('seq.preview.legend')}{shownPlan !== null && ` ${t('seq.preview.legendPlan')}`}{live !== null && ` ${t('seq.preview.legendLive')}`}</p>
        <p className="flight-sequence">{t('seq.preview.line', {
          alt: mission.altitudeM,
          steps: mission.steps.map(stepLabel).join(' → '),
          land: t(`seq.land.${mission.land}`),
        })}</p>
        <dl className="flight-facts">
          <div className={preview.maxR > mission.maxRadiusM ? 'flight-facts--bad' : ''}><dt>{t('seq.preview.maxR')}</dt><dd>{fmtM(preview.maxR)} / {mission.maxRadiusM} m</dd></div>
          <div className={preview.pathM > 300 ? 'flight-facts--bad' : ''}><dt>{t('seq.preview.path')}</dt><dd>{fmtM(preview.pathM)} / 300 m</dd></div>
          <div><dt>{t('seq.preview.land')}</dt><dd>{t('seq.plan.fr', { fwd: fmtM(preview.land.fwd), right: fmtM(preview.land.right) })}</dd></div>
          <div><dt>{t('seq.preview.est')}</dt><dd>{passedPlan?.estS != null
            ? t('flight.route.minutes', { min: (passedPlan.estS / 60).toFixed(1) })
            : t('seq.preview.estAfterDry')}</dd></div>
        </dl>
        <details className="flight-advanced">
          <summary>{t('seq.preview.key')}</summary>
          <code className="flight-argv">{missionKey(mission)}</code>
        </details>
      </section>
    </div>

    <section className="manual-tab__section">
      <header><h3>{t('flight.vehicle.title')}</h3></header>
      <VehicleFacts fcx={fcx} />
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('flight.run.title')}</h3></header>
      <p className="flight-script"><span className="manual-support manual-support--yes">{SEQ_SCRIPT}</span> {t('seq.run.script')}</p>
      <div className="flight-actions">
        <button type="button" className="manual-switch" disabled={busy || startBlock !== null}
          onClick={(event) => { event.currentTarget.blur(); void send(true); }}>{t('flight.btn.dry')}</button>
        <button type="button" className="manual-switch flight-go" disabled={busy || startBlock !== null || gate !== 'passed' || confirming}
          onClick={(event) => { event.currentTarget.blur(); setConfirming(true); }}>{t('flight.btn.fly')}</button>
        <span className="flight-actions__state">{startBlock ?? gateText(gate, other)}</span>
      </div>

      {confirming && <div className="flight-confirm" role="alertdialog" aria-label={t('flight.confirm.title')}>
        <b>{t('seq.confirm.head', { alt: mission.altitudeM, n: mission.steps.length, land: t(`seq.land.${mission.land}`) })}</b>
        <ol className="seq-confirm-steps">{mission.steps.map((step, index) => <li key={index}>{stepLabel(step)}</li>)}</ol>
        <ul>
          <li>{t('seq.confirm.space', { r: fmtM(preview.maxR), alt: mission.altitudeM })}</li>
          {mission.steps.some((step) => stepClass(step.kind) === 'rot') && <li>{t('seq.confirm.rot')}</li>}
          <li>{t('seq.confirm.sideways')}</li>
          <li>{t('flight.confirm.people')}</li>
          <li>{t('flight.confirm.rc')}</li>
          <li>{t('flight.confirm.battery')}</li>
          {mission.steps.some((step) => step.capture) && <li>{t('flight.confirm.cansar')}</li>}
          {passedPlan !== null && <li>{t('seq.confirm.timing', {
            min: ((passedPlan.estS ?? 0) / 60).toFixed(1), timeout: ((passedPlan.timeoutS ?? 0) / 60).toFixed(1), how: abortName,
          })}</li>}
          {passedPlan?.h0 != null && <li>{t('seq.confirm.heading', { deg: passedPlan.h0.toFixed(1) })}</li>}
          <li>{t('seq.confirm.mission')}</li>
          <li>{t(mission.abort === 'rtl' ? 'flight.confirm.abortRtl' : 'flight.confirm.abort', { how: abortName })}</li>
        </ul>
        <label className="flight-confirm__yes">{t('flight.confirm.type')}
          <input value={typed} autoFocus onChange={(event) => setTyped(event.target.value)} placeholder="yes"
            onKeyDown={(event) => { if (event.key === 'Enter' && yes && !busy && gate === 'passed' && startBlock === null) void send(false); }} />
        </label>
        <div className="flight-actions">
          <button type="button" className="manual-switch flight-go" disabled={busy || !yes || startBlock !== null || gate !== 'passed'}
            onClick={(event) => { event.currentTarget.blur(); void send(false); }}>{t('flight.confirm.send')}</button>
          <button type="button" className="manual-unbind" onClick={() => { setConfirming(false); setTyped(''); }}>{t('flight.confirm.cancel')}</button>
        </div>
      </div>}

      <div className="flight-actions flight-actions--stop">
        <ArmedButton className="manual-switch" label={t('flight.btn.stopLong', { how: abortName })} armedLabel={t('flight.btn.again')}
          disabled={!running || link.stop === 'no'}
          onFire={() => { void issueSeqStop(link).then((outcome) => setNote(outcome.message)); }} />
        <span className="flight-emergency">
          <Radio items={EMERGENCY_MODES} value={emergencyMode} label={t('flight.emergency.title')} name={(item) => t(`flight.emergency.${item}`)}
            onPick={(item: EmergencyMode) => setEmergencyMode(item)} />
          <ArmedButton className="manual-switch flight-danger" label={t('flight.btn.emergency')} armedLabel={t('flight.btn.again')}
            disabled={link.emergency === 'no'}
            onFire={() => { void issueFlightEmergency(link, emergencyMode).then((outcome) => setNote(outcome.message)); }} />
        </span>
      </div>
      <p className="manual-note">{t('seq.run.stopWhy')}</p>
      {note !== '' && <p className="manual-tab__last">{note}</p>}
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('flight.progress.title')}</h3>
        {run !== null && <small className="flight-run-id">{runSummary(run, progress)} · {run.script ?? SEQ_SCRIPT} · {run.runId}</small>}
        {entry !== undefined && running && isFlightRunStale({ ...entry, emergency: null }) && <span className="manual-support manual-support--unknown">{t('flight.progress.stale', { sec: Math.round((Date.now() - entry.receivedAtMs) / 1000) })}</span>}
      </header>
      {run === null || progress === null
        ? <p className="manual-note">{t('seq.progress.none')}</p>
        : <>
          <Steps process={run} landing={landing} />
          <LandingNote process={run} landing={landing} how={abortName} fromWatch={progress.landWatch.seen} />
          {run.plan !== null && run.dryRun === true && <PlanCheck plan={run.plan} mission={mission} />}
          {run.dryRun === true && run.plan === null && run.state === 'exited' && <p className="manual-note">{t('seq.plan.none')}</p>}
          {run.dryRun !== true && <StepProgress process={run} progress={progress} mission={mission} />}
          <dl className="flight-facts">
            {progress.live !== null && <div className="flight-facts__wide"><dt>{t('flight.progress.live')}</dt><dd>{progress.live}</dd></div>}
            {run.missionKey !== null && <div className="flight-facts__wide"><dt>{t('seq.progress.key')}</dt><dd>{run.missionKey}{run.missionHash !== null ? ` · ${run.missionHash}` : ''}</dd></div>}
            {run.argv.length > 0 && <div className="flight-facts__wide"><dt>{t('seq.progress.argv')}</dt><dd>{run.argv.join(' ')}</dd></div>}
            {run.rtk !== null && <div><dt>RTK</dt><dd>{run.rtk ? t('seq.progress.rtkOn') : t('seq.progress.rtkOff')}</dd></div>}
            {run.state === 'exited' && <div className={runOutcome(run) === 'ok' ? 'flight-facts--ok' : 'flight-facts--bad'}><dt>{t('seq.progress.exit')}</dt>
              <dd>{t(`flight.outcome.${runOutcome(run)}`, { code: run.exitCode ?? '?' })}</dd></div>}
          </dl>
          {progress.warningLines.length > 0 && <ul className="seq-warnings">{progress.warningLines.slice(-6).map((line, index) => <li key={index}>{line}</li>)}</ul>}
          {progress.problems.length > 0 && <ul className="flight-problems">{progress.problems.slice(-3).map((line, index) => <li key={index}>{line}</li>)}</ul>}
          <RunLog process={run} />
        </>}
    </section>
  </div>;
}
