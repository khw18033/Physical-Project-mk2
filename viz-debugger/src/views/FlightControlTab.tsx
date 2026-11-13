/**
 * src/views/FlightControlTab.tsx (261014 신설 — 드론 상세창 · 비행 제어 탭)
 *
 * **SSH 로 `test_sar_rtk.py` 를 띄우던 일을 화면에서.** 비행 설정을 미리 넣고 → dry-run 으로 점검하고 → 점검 목록을
 * 읽고 「yes」를 쳐서 비행을 시작한다. 비행 코드는 pi3 의 그 스크립트 그대로이고, 이 탭은 옵션을 넘기고
 * 출력을 보여 줄 뿐이다(`261014_드론비행실행기_요청_VZ.md`).
 *
 * 수동 제어 탭(로봇)과 모양을 맞췄지만 방식이 다르다 — 키를 누르는 동안 움직이는 것이 아니라, **경로 전체를 FC 에
 * 미션으로 올린 뒤** FC 가 혼자 난다. 그래서 이 탭에는 「누르는 동안」이 없고, 중단 · 비상 착륙만 언제든 나간다.
 *
 * ## 순서를 화면이 지킨다
 *
 *   1. 설정 — 범위는 스크립트 상수와 같다. 틀린 칸이 있으면 두 버튼 다 닫힌다.
 *   2. dry-run — 같은 설정의 dry-run 이 종료 코드 0 으로 끝나야 비행 버튼이 열린다(`dryRunPassed`).
 *   3. 비행 — 스크립트의 `confirm()` 점검 목록을 그대로 보여 주고, 「yes」를 쳐야 보낸다. 스크립트에는 `--yes` 로 간다.
 *
 * 설정은 장비마다 이 화면이 떠 있는 동안 기억한다 — 탭을 옮기거나 카드를 닫았다 열어도 그대로다.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { subscribeDeviceIdentity, deviceCandidates } from '../physical/deviceIdentity.ts';
import { isFcxStale, useFcxReports, type FcxReport } from '../shared/fcxStatus.ts';
import {
  ABORTS, argvPreview, EMERGENCY_MODES, estimateSec, FLIGHT_DEFAULTS, FLIGHT_LIMITS, PATTERNS, planProblems, relativeBearing,
  SCRIPT_PLAIN, SCRIPT_RTK, SIDES_OF, timeoutSec, withPattern, type EmergencyMode, type FlightPlan, type PlanProblem,
} from '../physical/flightPlan.ts';
import {
  isFlightRunStale, landingOf, lineTone, PHASES, readProgress, runOutcome, stripTime, useFlightRuns, type FlightProcess, type Landing, type Phase,
} from '../physical/flightRunFeed.ts';
import {
  dryRunPassed, dryRunPending, flightLink, issueFlightEmergency, issueFlightStart, issueFlightStop, scriptGuess, scriptOf,
  type FlightSupport, type ScriptGuess,
} from '../physical/flightRunCommands.ts';
import { NumberField } from './ManualControlTab.tsx';
import { useEverySec } from './ManualControlBadge.tsx';
import { ArmedButton, runSummary } from './FlightRunBadge.tsx';

// ── 장비별 설정 (화면이 떠 있는 동안) ──────────────────────────────────────

let plans: Readonly<Record<string, FlightPlan>> = {};
const planListeners = new Set<() => void>();

function planOf(deviceId: string): FlightPlan {
  return plans[deviceId] ?? FLIGHT_DEFAULTS;
}

function setPlan(deviceId: string, plan: FlightPlan): void {
  plans = { ...plans, [deviceId]: plan };
  for (const listener of planListeners) listener();
}

function usePlan(deviceId: string): FlightPlan {
  return useSyncExternalStore((listener) => {
    planListeners.add(listener);
    return () => { planListeners.delete(listener); };
  }, () => planOf(deviceId));
}

/** 장비 선언이 바뀌면 다시 그린다(버튼이 열리고 닫힌다). */
function useDeviceActions(deviceId: string): readonly string[] | null {
  return useSyncExternalStore(subscribeDeviceIdentity,
    () => deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null);
}

// ── 작은 조각 ───────────────────────────────────────────────────────────

/** 비워 둘 수 있는 숫자 칸 — 비우면 `null`(스크립트 기본: 이륙 직전 기수). */
function OptionalNumberField({ value, min, max, step, placeholder, onCommit }: {
  value: number | null; min: number; max: number; step: number; placeholder: string; onCommit(value: number | null): void;
}) {
  useLang();
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parsed = Number(draft);
    if (draft.trim() === '') onCommit(null);
    else if (Number.isFinite(parsed)) onCommit(parsed);
    setDraft(null);
  };
  return <input type="number" min={min} max={max} step={step} placeholder={placeholder}
    value={draft ?? (value === null ? '' : String(value))}
    onChange={(event) => setDraft(event.target.value)}
    onBlur={commit}
    onKeyDown={(event) => { if (event.key === 'Enter') { commit(); event.currentTarget.blur(); } }} />;
}

function Radio<T extends string>({ items, value, label, name, onPick }: {
  items: readonly T[]; value: T; label: string; name(item: T): string; onPick(item: T): void;
}) {
  return <nav className="manual-presets" role="radiogroup" aria-label={label}>
    {items.map((item) => <button key={item} type="button" role="radio" aria-checked={value === item}
      onClick={(event) => { onPick(item); event.currentTarget.blur(); }}>{name(item)}</button>)}
  </nav>;
}

function problemText(problem: PlanProblem): string {
  const field = t(`flight.field.${problem.field}`);
  if (problem.kind === 'range') return t('flight.problem.range', { field, min: problem.min, max: problem.max });
  return t(`flight.problem.${problem.kind}`, { field });
}

function supportChip(actions: readonly string[] | null, action: string) {
  const support: FlightSupport = actions === null ? 'unknown' : actions.includes(action) ? 'yes' : 'no';
  return <span className={`manual-support manual-support--${support}`}>{action} · {t(`flight.support.${support}`)}</span>;
}

/** 기수 기준 경로 그림. 거리는 비례가 아니다 — 방향과 순서만 보인다. */
function RoutePreview({ plan }: { plan: FlightPlan }) {
  useLang();
  const bearing = relativeBearing(plan);
  const r = 46;
  const rad = bearing === null ? 0 : (bearing * Math.PI) / 180;
  const x = Math.sin(rad) * r;
  const y = -Math.cos(rad) * r;
  return <svg className="flight-route" viewBox="-70 -70 140 140" role="img" aria-label={t('flight.route.aria')}>
    <circle cx="0" cy="0" r="62" className="flight-route__ring" />
    {/* 기수 — 위가 앞이다. */}
    <path d="M0,-14 L7,4 L0,0 L-7,4 Z" className="flight-route__nose" />
    <text x="0" y="22" className="flight-route__label">L</text>
    {bearing === null
      ? <>
        <path d="M 0,-34 A 34 34 0 1 1 -24,-24" className="flight-route__path" markerEnd="url(#flight-arrow)" />
        <text x="0" y="-40" className="flight-route__label">360° × {plan.passes}</text>
      </>
      : <>
        <line x1={x * 0.2} y1={y * 0.2} x2={x} y2={y} className="flight-route__path" markerEnd="url(#flight-arrow)" />
        <text x={x * 1.22} y={y * 1.22 + 4} className="flight-route__label">X</text>
        <text x={x * 0.6 + (y === 0 ? 0 : 14)} y={y * 0.6 + (y === 0 ? -8 : 4)} className="flight-route__dist">{plan.lengthM}m</text>
      </>}
    <text x="0" y="36" className="flight-route__nose-label">{t('flight.route.nose')}</text>
    <defs>
      <marker id="flight-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 Z" className="flight-route__arrowhead" />
      </marker>
    </defs>
  </svg>;
}

function fcxHeading(fcx: FcxReport | undefined): number | null {
  const heading = fcx?.hud?.heading ?? fcx?.attitude?.yawDeg ?? null;
  return heading === null ? null : ((heading % 360) + 360) % 360;
}

/** 기체 상태 한 줄 — 스크립트가 다시 확인하므로 막지는 않고, 눈에 띄게만 한다. */
function VehicleFacts({ fcx }: { fcx: FcxReport | undefined }) {
  useLang();
  if (fcx === undefined) return <p className="manual-note">{t('flight.vehicle.none')}</p>;
  const stale = isFcxStale(fcx);
  const facts: { label: string; value: string; tone: 'ok' | 'warn' | 'bad' | '' }[] = [
    { label: t('flight.vehicle.armed'), value: fcx.armed === null ? '?' : fcx.armed ? t('flight.vehicle.armedYes') : t('flight.vehicle.armedNo'), tone: fcx.armed ? 'bad' : fcx.armed === false ? 'ok' : '' },
    { label: t('flight.vehicle.mode'), value: fcx.mode ?? '?', tone: '' },
    { label: t('flight.vehicle.landed'), value: fcx.landedState ?? '?', tone: '' },
    { label: t('flight.vehicle.gps'), value: fcx.gps === null ? '?' : `${fcx.gps.fix ?? '?'} · ${t('flight.vehicle.sats', { n: fcx.gps.satellites ?? '?' })}`, tone: fcx.gps?.fix?.includes('RTK_FIXED') ? 'ok' : fcx.gps?.fix?.includes('RTK') ? 'warn' : '' },
    { label: t('flight.vehicle.battery'), value: fcx.battery === null ? '?' : `${fcx.battery.remainingPct ?? '?'}% · ${fcx.battery.voltageV?.toFixed(1) ?? '?'}V`, tone: (fcx.battery?.remainingPct ?? 100) < 30 ? 'warn' : '' },
    { label: t('flight.vehicle.heading'), value: fcxHeading(fcx) === null ? '?' : `${fcxHeading(fcx)!.toFixed(0)}°`, tone: '' },
  ];
  return <>
    {stale && <p className="manual-warn">{t('flight.vehicle.stale', { sec: Math.round((Date.now() - fcx.receivedAtMs) / 1000) })}</p>}
    <dl className="flight-facts">
      {facts.map((fact) => <div key={fact.label} className={fact.tone === '' ? '' : `flight-facts--${fact.tone}`}>
        <dt>{fact.label}</dt><dd>{fact.value}</dd>
      </div>)}
    </dl>
    {fcx.armed === true && <p className="manual-warn">{t('flight.vehicle.armedWarn')}</p>}
  </>;
}

const DRY_STEPS: readonly Phase[] = ['starting', 'connecting', 'position', 'route', 'upload', 'verified', 'dryDone'];
const FLY_STEPS: readonly Phase[] = PHASES;

/**
 * 실행이 도는 동안의 FC 착지 값 — `[착륙감시]` 줄이 없는 스크립트에서도 착륙 상태를 가르게(261111). 낡은 fcx 는 안 쓴다.
 */
function fcLanding(fcx: FcxReport | undefined): { landedState: string | null; armed: boolean | null } | null {
  return fcx === undefined || isFcxStale(fcx) ? null : { landedState: fcx.landedState, armed: fcx.armed };
}

/**
 * **착륙 상태 알림** (261111). 스크립트가 `[확인] 착륙 완료` 를 못 찍어 실행이 안 끝날 때(11/9 실기 — `REPORT_착륙판정_261111.md`),
 * FC 가 말하는 것으로 지금 어떤지를 알린다. 제어는 하지 않는다 — 중단은 여전히 사람이 누르고, 누르면 스크립트가 abort 명령을 보낸다는
 * 것을 같이 적는다.
 */
function LandingNote({ process, landing, how, fromWatch }: { process: FlightProcess; landing: Landing; how: string; fromWatch: boolean }) {
  useLang();
  if (landing === 'none' || landing === 'confirmed' || process.state !== 'running') return null;
  const progress = readProgress(process.lines);
  const src = t(fromWatch ? 'flight.landing.src.watch' : 'flight.landing.src.fcx');
  return <div className={`flight-landing flight-landing--${landing}`} role="status">
    <b>{landing === 'missionDone'
      ? t('flight.landing.missionDone', { cur: progress.liveItem ?? '?', total: progress.itemsTotal ?? '?' })
      : t(`flight.landing.${landing}`, { src })}</b>
    <span>{t(landing === 'disarmed' ? 'flight.landing.stopAfter' : 'flight.landing.stopCaution', { how })}</span>
  </div>;
}

function Steps({ process, landing }: { process: FlightProcess; landing: Landing }) {
  useLang();
  const progress = readProgress(process.lines);
  // `test_sar.py`(RTK 없는 판)는 RTK 대기 단계를 지나지 않는다.
  const steps = (process.dryRun === true ? DRY_STEPS : FLY_STEPS).filter((step) => step !== 'rtk' || process.script !== SCRIPT_PLAIN);
  const at = steps.indexOf(progress.phase);
  const outcome = runOutcome(process);
  return <div className="flight-steps">
    {steps.map((step, index) => {
      const done = index < at || (index === at && outcome === 'ok');
      const active = index === at && outcome === 'running';
      const failed = index === at && (outcome === 'failed' || outcome === 'badArgs' || outcome === 'killed');
      // 스크립트는 착륙을 못 찍었지만 FC 는 땅 위라고 한다 — 착륙 칸을 점선으로 「FC 기준」 표시.
      const fc = step === 'landed' && progress.phase === 'mission' && (landing === 'onGround' || landing === 'disarmed');
      if (fc) return <span key={step} className="step-fc" title={t('flight.landing.short.' + landing)}>{t('flight.phase.landedFc')}</span>;
      return <span key={step} className={failed ? 'step-failed' : done ? 'step-done' : active ? 'step-active' : ''}>{t(`flight.phase.${step}`)}</span>;
    })}
  </div>;
}

/** 출력 원문. 맨 아래에 붙어 있으면 새 줄을 따라 내려가고, 위로 올려 읽는 중이면 그대로 둔다. */
function RunLog({ process }: { process: FlightProcess }) {
  useLang();
  const box = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);
  const last = process.lines.at(-1)?.seq ?? 0;
  useEffect(() => {
    const node = box.current;
    if (node !== null && stick.current) node.scrollTop = node.scrollHeight;
  }, [last, process.runId]);
  const shown = process.lines.slice(-400);
  return <div className="flight-log" ref={box} onScroll={(event) => {
    const node = event.currentTarget;
    stick.current = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
  }}>
    {shown.length === 0
      ? <p className="manual-note">{t('flight.log.empty')}</p>
      : shown.map((line) => <div key={line.seq} className={`flight-log__line flight-log__line--${lineTone(line.text) || 'plain'}`}>{stripTime(line.text)}</div>)}
  </div>;
}

/**
 * 이번에 실행기가 띄울 스크립트 (261022). RTK 보정이 FC 로 들어오면 `test_sar_rtk.py`, 아니면 `test_sar.py` —
 * 고르는 것은 실행기이고 여기는 지금 보이는 보정 상태로 미리 알린다(`scriptGuess`).
 */
function ScriptLine({ guess }: { guess: ScriptGuess }) {
  useLang();
  const tone = guess.corrections === null ? 'unknown' : guess.corrections ? 'yes' : 'warn';
  const key = guess.corrections === null ? 'flight.script.unknown' : guess.corrections ? 'flight.script.rtk' : 'flight.script.plain';
  return <p className={`flight-script flight-script--${tone}`}>
    <span className={`manual-support manual-support--${tone === 'warn' ? 'unknown' : tone}`}>{guess.script ?? `${SCRIPT_RTK} / ${SCRIPT_PLAIN}`}</span>
    {' '}{t(key)}
  </p>;
}

// ── 탭 ──────────────────────────────────────────────────────────────────

export function FlightControlTab({ deviceId }: { deviceId: string }) {
  useLang();
  useEverySec();
  const actions = useDeviceActions(deviceId);
  const plan = usePlan(deviceId);
  const update = (patch: Partial<FlightPlan>) => setPlan(deviceId, { ...plan, ...patch });
  const runs = useFlightRuns();
  const entry = runs[deviceId];
  const fcx = useFcxReports()[deviceId];
  const link = flightLink(deviceId);
  const problems = planProblems(plan);
  const run = entry?.run ?? null;
  const running = run?.state === 'running';
  const passed = dryRunPassed(deviceId, plan, entry);
  const pending = dryRunPending(deviceId, plan, entry);
  const moving = plan.pattern !== 'rotate';
  const guess = scriptGuess(deviceId);
  // dry-run 을 한 스크립트와 지금 날 스크립트가 다르면(그 사이 보정이 켜지거나 꺼졌다) 그 dry-run 은 이 비행의 점검이 아니다.
  const dryScript = passed ? scriptOf(run) : null;
  const scriptChanged = passed && guess.script !== null && dryScript !== guess.script;
  const gateOpen = passed && !scriptChanged;

  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [emergencyMode, setEmergencyMode] = useState<EmergencyMode>('land');

  // 설정을 바꾸면 확인 창을 닫는다 — 읽고 동의한 내용과 보낼 내용이 달라지면 안 된다.
  const signatureKey = JSON.stringify(plan);
  useEffect(() => { setConfirming(false); setTyped(''); }, [signatureKey]);

  const startBlock: string | null = link.start !== 'yes'
    ? (link.reason || (link.start === 'unknown' ? t('flight.link.unknown') : t('flight.link.notDeclared')))
    : problems.length > 0 ? t('flight.block.problems')
      : running ? t('flight.block.running')
        : null;

  const send = async (dryRun: boolean) => {
    setBusy(true);
    setNote('');
    const outcome = await issueFlightStart(link, plan, { dryRun, confirmed: !dryRun && typed.trim().toLowerCase() === 'yes' });
    setNote(outcome.message);
    setBusy(false);
    if (!dryRun) { setConfirming(false); setTyped(''); }
  };

  const heading = fcxHeading(fcx);
  const lineBearing = plan.headingDeg ?? heading;
  const relative = relativeBearing(plan);
  const est = estimateSec(plan);
  const sideName = moving ? t(`flight.side.${plan.side}`) : '';

  return <div className="manual-tab flight-tab">
    <section className="manual-tab__head">
      <div>
        <b>{t('flight.head.title')}</b>
        <small>{t('flight.head.why')}</small>
      </div>
      <div className="flight-support">
        {supportChip(actions, 'rtk_test_start')}
        {supportChip(actions, 'rtk_test_stop')}
        {supportChip(actions, 'rtk_test_emergency')}
      </div>
    </section>
    {link.start !== 'yes' && <p className="manual-warn">{link.reason || t('flight.link.needRunner')}</p>}

    <div className="flight-grid">
      <section className="manual-tab__section">
        <header><h3>{t('flight.plan.title')}</h3>
          <button type="button" className="manual-unbind" disabled={running}
            onClick={(event) => { setPlan(deviceId, FLIGHT_DEFAULTS); event.currentTarget.blur(); }}>{t('flight.plan.reset')}</button>
        </header>
        <fieldset className="flight-fields" disabled={running}>
          <div className="flight-row"><span>{t('flight.field.pattern')}</span>
            <Radio items={PATTERNS} value={plan.pattern} label={t('flight.field.pattern')} name={(item) => t(`flight.pattern.${item}`)}
              onPick={(item) => setPlan(deviceId, withPattern(plan, item))} />
          </div>
          {moving && <div className="flight-row"><span>{t('flight.field.side')}</span>
            <Radio items={SIDES_OF[plan.pattern as 'fb' | 'lr']} value={plan.side} label={t('flight.field.side')} name={(item) => t(`flight.side.${item}`)}
              onPick={(item) => update({ side: item })} />
          </div>}
          <div className="manual-steps">
            <label>{t('flight.field.altitudeM')}
              <NumberField value={plan.altitudeM} {...FLIGHT_LIMITS.altitudeM} step={0.5} onCommit={(value) => update({ altitudeM: value })} /> m
            </label>
            {moving && <label>{t('flight.field.lengthM')}
              <NumberField value={plan.lengthM} {...FLIGHT_LIMITS.lengthM} step={1} onCommit={(value) => update({ lengthM: value })} /> m
            </label>}
            {moving && <label>{t('flight.field.speedMps')}
              <NumberField value={plan.speedMps} {...FLIGHT_LIMITS.speedMps} step={0.1} onCommit={(value) => update({ speedMps: value })} /> m/s
            </label>}
            <label>{t(moving ? 'flight.field.passes' : 'flight.field.turns')}
              <NumberField value={plan.passes} {...FLIGHT_LIMITS.passes} step={1} onCommit={(value) => update({ passes: value })} /> {t('flight.unit.times')}
            </label>
          </div>
          <details className="flight-advanced">
            <summary>{t('flight.advanced.title')}</summary>
            <div className="manual-steps">
              <label>{t('flight.field.gapS')}
                <NumberField value={plan.gapS} {...FLIGHT_LIMITS.gapS} step={1} onCommit={(value) => update({ gapS: value })} /> s
              </label>
              <label>{t('flight.field.headingDeg')}
                <OptionalNumberField value={plan.headingDeg} {...FLIGHT_LIMITS.headingDeg} step={1} placeholder={t('flight.field.headingAuto')}
                  onCommit={(value) => update({ headingDeg: value })} /> °
              </label>
              <label>{t('flight.field.acceptRadiusM')}
                <NumberField value={plan.acceptRadiusM} {...FLIGHT_LIMITS.acceptRadiusM} step={0.1} onCommit={(value) => update({ acceptRadiusM: value })} /> m
              </label>
              <label>{t('flight.field.alignHoldS')}
                <NumberField value={plan.alignHoldS} {...FLIGHT_LIMITS.alignHoldS} step={1} onCommit={(value) => update({ alignHoldS: value })} /> s
              </label>
              <label>{t('flight.field.settleS')}
                <NumberField value={plan.settleS} {...FLIGHT_LIMITS.settleS} step={1} onCommit={(value) => update({ settleS: value })} /> s
              </label>
              <label>{t('flight.field.rtkMinS')}
                <NumberField value={plan.rtkMinS} {...FLIGHT_LIMITS.rtkMinS} step={5} onCommit={(value) => update({ rtkMinS: value })} /> s
              </label>
              <label>{t('flight.field.rtkTimeoutS')}
                <NumberField value={plan.rtkTimeoutS} {...FLIGHT_LIMITS.rtkTimeoutS} step={10} onCommit={(value) => update({ rtkTimeoutS: value })} /> s
              </label>
            </div>
            {guess.corrections !== true && <p className="manual-note">{t('flight.field.rtkUnused', { script: SCRIPT_PLAIN })}</p>}
            <div className="flight-row"><span>{t('flight.field.abort')}</span>
              <Radio items={ABORTS} value={plan.abort} label={t('flight.field.abort')} name={(item) => t(`flight.abort.${item}`)}
                onPick={(item) => update({ abort: item })} />
            </div>
            <p className="manual-note">{t('flight.advanced.why')}</p>
          </details>
        </fieldset>
        {problems.length > 0 && <ul className="flight-problems">{problems.map((problem, index) => <li key={index}>{problemText(problem)}</li>)}</ul>}
      </section>

      <section className="manual-tab__section flight-preview">
        <header><h3>{t('flight.route.title')}</h3></header>
        <RoutePreview plan={plan} />
        <p className="flight-sequence">{moving
          ? t('flight.route.seqLine', { alt: plan.altitudeM, side: sideName, len: plan.lengthM, n: plan.passes })
          : t('flight.route.seqRotate', { alt: plan.altitudeM, n: plan.passes })}</p>
        <dl className="flight-facts">
          <div><dt>{t('flight.route.estimate')}</dt><dd>{t('flight.route.minutes', { min: (est / 60).toFixed(1) })}</dd></div>
          <div><dt>{t('flight.route.timeout')}</dt><dd>{t('flight.route.minutes', { min: (timeoutSec(plan) / 60).toFixed(1) })}</dd></div>
          <div><dt>{t('flight.route.heading')}</dt><dd>{plan.headingDeg !== null
            ? `${plan.headingDeg}°`
            : heading === null ? t('flight.route.headingAuto') : t('flight.route.headingNow', { deg: heading.toFixed(0) })}</dd></div>
          {relative !== null && lineBearing !== null && <div><dt>{t('flight.route.bearing')}</dt><dd>{((lineBearing + relative) % 360).toFixed(0)}°</dd></div>}
        </dl>
        {plan.headingDeg === null && <p className="manual-note">{t('flight.route.headingWhy')}</p>}
        <details className="flight-advanced">
          <summary>{t('flight.route.argv')}</summary>
          <code className="flight-argv">{guess.script ?? SCRIPT_RTK} {argvPreview(plan, false, guess.script ?? SCRIPT_RTK).join(' ')}</code>
          {guess.script === null && <p className="manual-note">{t('flight.route.argvUnknown', { script: SCRIPT_PLAIN })}</p>}
        </details>
      </section>
    </div>

    <section className="manual-tab__section">
      <header><h3>{t('flight.vehicle.title')}</h3></header>
      <VehicleFacts fcx={fcx} />
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('flight.run.title')}</h3></header>
      <ScriptLine guess={guess} />
      <div className="flight-actions">
        <button type="button" className="manual-switch" disabled={busy || startBlock !== null}
          onClick={(event) => { event.currentTarget.blur(); void send(true); }}>{t('flight.btn.dry')}</button>
        <button type="button" className="manual-switch flight-go" disabled={busy || startBlock !== null || !gateOpen || confirming}
          onClick={(event) => { event.currentTarget.blur(); setConfirming(true); }}>{t('flight.btn.fly')}</button>
        <span className="flight-actions__state">{startBlock ?? (scriptChanged
          ? t('flight.gate.scriptChanged', { was: dryScript ?? '?', now: guess.script ?? '?' })
          : passed ? t('flight.gate.passed', { script: dryScript ?? '?' }) : pending ? t('flight.gate.pending') : t('flight.gate.needDry'))}</span>
      </div>

      {confirming && <div className="flight-confirm" role="alertdialog" aria-label={t('flight.confirm.title')}>
        <b>{moving
          ? t('flight.confirm.headLine', { alt: plan.altitudeM, len: plan.lengthM, n: plan.passes })
          : t('flight.confirm.headRotate', { alt: plan.altitudeM, n: plan.passes })}</b>
        <ul>
          {moving && <li>{t('flight.confirm.direction', { pattern: t(`flight.pattern.${plan.pattern}`), side: sideName })}</li>}
          <li>{moving ? t('flight.confirm.spaceLine', { side: sideName, len: plan.lengthM, alt: plan.altitudeM }) : t('flight.confirm.spaceRotate', { alt: plan.altitudeM })}</li>
          <li>{t('flight.confirm.people')}</li>
          <li>{t('flight.confirm.rc')}</li>
          <li>{t('flight.confirm.battery')}</li>
          <li>{t('flight.confirm.cansar')}</li>
          <li>{moving
            ? t('flight.confirm.orderLine', { alt: plan.altitudeM, len: plan.lengthM, n: plan.passes })
            : t('flight.confirm.orderRotate', { alt: plan.altitudeM, n: plan.passes })}</li>
          <li>{moving
            ? t('flight.confirm.timingLine', { speed: plan.speedMps, gap: plan.gapS, min: (est / 60).toFixed(1) })
            : t('flight.confirm.timingRotate', { gap: plan.gapS, min: (est / 60).toFixed(1) })}</li>
          <li>{t(guess.corrections === null ? 'flight.confirm.scriptUnknown' : guess.corrections ? 'flight.confirm.scriptRtk' : 'flight.confirm.scriptPlain',
            { script: guess.script ?? dryScript ?? '?', min: plan.rtkMinS })}</li>
          <li>{t('flight.confirm.mission')}</li>
          <li>{t(plan.abort === 'rtl' ? 'flight.confirm.abortRtl' : 'flight.confirm.abort', { how: t(`flight.abort.${plan.abort}`) })}</li>
        </ul>
        <label className="flight-confirm__yes">{t('flight.confirm.type')}
          <input value={typed} autoFocus onChange={(event) => setTyped(event.target.value)} placeholder="yes"
            onKeyDown={(event) => { if (event.key === 'Enter' && typed.trim().toLowerCase() === 'yes' && !busy) void send(false); }} />
        </label>
        <div className="flight-actions">
          <button type="button" className="manual-switch flight-go" disabled={busy || typed.trim().toLowerCase() !== 'yes' || startBlock !== null || !gateOpen}
            onClick={(event) => { event.currentTarget.blur(); void send(false); }}>{t('flight.confirm.send')}</button>
          <button type="button" className="manual-unbind" onClick={() => { setConfirming(false); setTyped(''); }}>{t('flight.confirm.cancel')}</button>
        </div>
      </div>}

      <div className="flight-actions flight-actions--stop">
        <ArmedButton className="manual-switch" label={t('flight.btn.stopLong', { how: t(`flight.abort.${plan.abort}`) })} armedLabel={t('flight.btn.again')}
          disabled={!running || link.stop === 'no'}
          onFire={() => { void issueFlightStop(link).then((outcome) => setNote(outcome.message)); }} />
        <span className="flight-emergency">
          <Radio items={EMERGENCY_MODES} value={emergencyMode} label={t('flight.emergency.title')} name={(item) => t(`flight.emergency.${item}`)}
            onPick={(item: EmergencyMode) => setEmergencyMode(item)} />
          <ArmedButton className="manual-switch flight-danger" label={t('flight.btn.emergency')} armedLabel={t('flight.btn.again')}
            disabled={link.emergency === 'no'}
            onFire={() => { void issueFlightEmergency(link, emergencyMode).then((outcome) => setNote(outcome.message)); }} />
        </span>
      </div>
      <p className="manual-note">{t('flight.run.stopWhy')}</p>
      {note !== '' && <p className="manual-tab__last">{note}</p>}
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('flight.progress.title')}</h3>
        {run !== null && <small className="flight-run-id">{runSummary(run)} · {scriptOf(run)} · {run.runId}</small>}
        {entry !== undefined && running && isFlightRunStale(entry) && <span className="manual-support manual-support--unknown">{t('flight.progress.stale', { sec: Math.round((Date.now() - entry.receivedAtMs) / 1000) })}</span>}
      </header>
      {run === null
        ? <p className="manual-note">{t('flight.progress.none')}</p>
        : <>
          <Steps process={run} landing={landingOf(readProgress(run.lines), fcLanding(fcx))} />
          <LandingNote process={run} landing={landingOf(readProgress(run.lines), fcLanding(fcx))} how={t(`flight.abort.${plan.abort}`)}
            fromWatch={readProgress(run.lines).landWatch.seen} />
          <ProgressFacts process={run} plan={plan} />
          <RunLog process={run} />
        </>}
      {entry?.emergency != null && <>
        <h4 className="flight-subhead">{t('flight.emergency.last', { mode: entry.emergency.mode ?? '?' })} · {t(`flight.outcome.${runOutcome(entry.emergency)}`, { code: entry.emergency.exitCode ?? '?' })}</h4>
        <RunLog process={entry.emergency} />
      </>}
    </section>
  </div>;
}

/** `WAYPOINT 패스 1 L→X      36.0000400, 127.0000400  고도 5m …` → `WAYPOINT 패스 1 L→X` — 좌표 · 수치는 출력 칸에 그대로 있다. */
function itemName(text: string): string {
  return text.split(/\s{2,}/).slice(0, 2).join(' ').replace(/\s+-?\d+\.\d{4,}.*$/, '');
}

function ProgressFacts({ process, plan }: { process: FlightProcess; plan: FlightPlan }) {
  useLang();
  const progress = readProgress(process.lines);
  const passes = process.dryRun === true ? null : plan.passes;
  return <>
    <dl className="flight-facts">
      <div><dt>{t('flight.progress.itemLabel')}</dt><dd>{progress.itemCur !== null
        ? `${t('flight.progress.item', { cur: progress.itemCur, total: progress.itemsTotal ?? '?' })}${progress.itemText !== null ? ` · ${itemName(progress.itemText)}` : ''}`
        : progress.itemsTotal !== null ? t('flight.progress.items', { total: progress.itemsTotal }) : '—'}</dd></div>
      {passes !== null && <div><dt>{t('flight.progress.passLabel')}</dt><dd>{progress.capturing !== null
        ? t('flight.progress.capturing', { n: progress.capturing })
        : t('flight.progress.passes', { done: progress.passesDone, n: passes })}</dd></div>}
      {progress.live !== null && <div className="flight-facts__wide"><dt>{t('flight.progress.live')}</dt><dd>{progress.live}</dd></div>}
      {progress.warnings > 0 && <div className="flight-facts--warn"><dt>{t('flight.progress.warnings')}</dt><dd>{progress.warnings}</dd></div>}
    </dl>
    {progress.problems.length > 0 && <ul className="flight-problems">{progress.problems.slice(-3).map((line, index) => <li key={index}>{line}</li>)}</ul>}
  </>;
}
