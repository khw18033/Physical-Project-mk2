/**
 * src/views/ArmControlTab.tsx (261117 신설 — 로봇팔 MT4 제어 탭)
 *
 * 하드웨어 카드 상세보기의 탭. 안에 갈래가 둘이다.
 *
 *   키보드 제어 (기본)   Go1 수동 제어처럼 키로 민다 — 앞뒤 · 좌우 · 상하 · 그리퍼 회전 · 여닫기 · 펌프 (`armKeys.ts`)
 *   경로 설계            값을 정해 놓고 보낸다 — 관절 조그 · 관절/직교 절대·상대 이동 · 끝단 도구
 *
 * 두 갈래 위에는 늘 같은 것이 선다 — 상태 · 지금 자세 · 원점 복귀 · 정지 · 재개 · 리셋.
 *
 * 지금 값(상태 · 관절 · 끝점)은 장비가 `state` 로 보낸 그대로다. 버튼은 상태를 보고 닫지만 **판정은 장비가 다시 한다** —
 * 상태를 모르면 열고, 거절은 사유를 그대로 적는다(`armControl.ts`).
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { useDeviceTelemetry } from '../shared/deviceTelemetry.ts';
import {
  armReady, armView, CART_AXES, issueArm, isAlarm, JOG_MAX_DEG, JOINTS, SPEED_MAX, useArmEvents,
  type ArmAction, type ArmView, type CartAxis,
} from '../physical/armControl.ts';
import {
  armKeyMeaning, ARM_MOTION_KEYS, ARM_MOTIONS, ARM_SPEED_RANGE, ARM_STOP_KEY, ARM_TOOL_KEYS, ARM_TOOLS, armKeyConfig, armKeysEnabled,
  keysSharedWithGo1, setArmKeyConfig, setArmKeysEnabled, STEP_DEG_RANGE, STEP_MM_RANGE, useArmKeysState,
  ARM_KEY_MODES, JOG_DEG_S_RANGE, JOG_MM_S_RANGE,
} from '../physical/armKeys.ts';
import { deviceCandidates, subscribeDeviceIdentity } from '../physical/deviceIdentity.ts';
import { keyLabel, useManualState } from '../physical/manualControl.ts';
import { isTypingTarget } from '../physical/manualDispatch.ts';
import { NumberField } from './ManualControlTab.tsx';

const ARM_PANES = ['keys', 'path'] as const;
type ArmPane = (typeof ARM_PANES)[number];

const fmt = (value: number | undefined, digits = 1) => (value === undefined ? '—' : value.toFixed(digits));

/** 빈 칸은 「안 보낸다」이다. 숫자가 아니면 `NaN` — 보내기 전에 걸러낸다. */
function parseField(text: string): number | null {
  if (text.trim() === '') return null;
  return Number(text);
}

type Send = (action: ArmAction, parameters?: Record<string, number>) => Promise<void>;

export function ArmControlTab({ deviceId }: { deviceId: string }) {
  useLang();
  useDeviceTelemetry();
  const events = useArmEvents();
  const view = armView(deviceId);
  const last = events[deviceId];

  const [pane, setPane] = useState<ArmPane>('keys');
  const [pending, setPending] = useState<ArmAction | null>(null);
  const [note, setNote] = useState('');

  const busy = pending !== null;
  const can = (action: ArmAction) => armReady(action, view) && (!busy || action === 'stop' || action === 'reset');

  const send: Send = async (action, parameters) => {
    if (action !== 'stop' && action !== 'reset') setPending(action);
    setNote('');
    try {
      const outcome = await issueArm(deviceId, action, parameters);
      if (!outcome.sent) setNote(outcome.message);
    } finally {
      if (action !== 'stop' && action !== 'reset') setPending(null);
    }
  };

  const reset = () => {
    if (!window.confirm(t('arm.reset.confirm'))) return;
    void send('reset');
  };

  const stateTone = view.armState === null ? 'unknown' : isAlarm(view.armState) || view.locked ? 'no' : view.armState === 'Idle' ? 'yes' : 'unknown';

  return <div className="manual-tab arm-tab">
    <section className="manual-tab__head">
      <div>
        <b>{t('arm.title')}</b>
        <small>{t('arm.why')}</small>
      </div>
      <span className={`manual-support manual-support--${stateTone}`}>{view.armState ?? t('arm.state.unknown')}</span>
      <span className={`manual-support manual-support--${view.homed === true ? 'yes' : view.homed === false ? 'no' : 'unknown'}`}>
        {t(view.homed === true ? 'arm.homed.yes' : view.homed === false ? 'arm.homed.no' : 'arm.homed.unknown')}
      </span>
      {view.serialOk === false && <span className="manual-support manual-support--no">{t('arm.serial.lost')}</span>}
    </section>

    {view.locked && <p className="manual-warn">{t('arm.locked', { reason: view.lockReason ?? '—' })}</p>}
    {view.homed === false && <p className="manual-warn">{t('arm.needHome')}</p>}

    <section className="manual-tab__section">
      <div className="arm-buttons">
        {/* blur — 누른 버튼에 포커스가 남으면 Space(정지 키)가 그 버튼을 다시 누른다. */}
        <button type="button" className="arm-btn" disabled={!can('home')} onClick={(event) => { event.currentTarget.blur(); void send('home'); }}>{t('arm.btn.home')}</button>
        <button type="button" className="arm-btn arm-btn--stop" disabled={!can('stop')} onClick={(event) => { event.currentTarget.blur(); void send('stop'); }}>{t('arm.btn.stop')}</button>
        <button type="button" className="arm-btn" disabled={!can('resume')} onClick={(event) => { event.currentTarget.blur(); void send('resume'); }}>{t('arm.btn.resume')}</button>
        <button type="button" className="arm-btn arm-btn--danger" disabled={!can('reset')} onClick={(event) => { event.currentTarget.blur(); reset(); }}>{t('arm.btn.reset')}</button>
      </div>
      <p className="manual-note">{t('arm.basic.why')}</p>
      <table className="manual-table arm-table">
        <thead><tr>{JOINTS.map((j) => <th key={j}>j{j} (°)</th>)}{CART_AXES.map((axis) => <th key={axis}>{axis} (mm)</th>)}</tr></thead>
        <tbody><tr>
          {JOINTS.map((j) => <td key={j}>{fmt(view.joints?.[`j${j}`])}</td>)}
          {CART_AXES.map((axis) => <td key={axis}>{fmt(view.tcp?.[axis])}</td>)}
        </tr></tbody>
      </table>
      {view.joints === null && <p className="manual-note">{t('arm.now.none')}</p>}
    </section>

    <nav className="manual-presets arm-panes" role="tablist" aria-label={t('arm.title')}>
      {ARM_PANES.map((item) => <button key={item} type="button" role="tab" aria-checked={pane === item} aria-selected={pane === item}
        onClick={(event) => { setPane(item); event.currentTarget.blur(); }}>{t(`arm.pane.${item}`)}</button>)}
    </nav>

    {pane === 'keys' ? <ArmKeysPane deviceId={deviceId} /> : <ArmPathPane view={view} can={can} send={send} setNote={setNote} />}

    {note !== '' && <p className="manual-warn">{note}</p>}
    {busy && <p className="manual-note">{t('arm.pending', { action: pending })}</p>}
    {last !== undefined && <p className={`manual-tab__last arm-last arm-last--${last.tone}`}>
      {new Date(last.atMs).toLocaleTimeString()} · {last.line}
      {last.result !== null && Object.keys(last.result).length > 0 && <><br />{Object.entries(last.result).map(([key, value]) => `${key}=${Number.isInteger(value) ? value : value.toFixed(2)}`).join('  ')}</>}
    </p>}
  </div>;
}

// ── 키보드 제어 ─────────────────────────────────────────────────────────

function ArmKeysPane({ deviceId }: { deviceId: string }) {
  useLang();
  useArmKeysState();
  useManualState();
  const enabled = armKeysEnabled(deviceId);
  const config = armKeyConfig(deviceId);
  const shared = keysSharedWithGo1();
  /** 연속 방식을 노드가 받는가 — 선언 목록(Capability)으로만 안다. 못 받았으면 모른다(보내 보고 거절을 받는다). */
  const actions = useSyncExternalStore(subscribeDeviceIdentity,
    () => deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null);
  const jogDeclared = actions === null ? 'unknown' : actions.includes('jog') ? 'yes' : 'no';
  /**
   * **키가 무시된 이유를 말한다** (261117 — 「키를 눌러도 안 움직인다」). 꺼져 있거나 글 칸에 커서가 있으면 처리기는 키를
   * 조용히 흘려보낸다 — 그 사실이 화면에 없으면 사람은 팔이 고장 난 줄 안다. 이 탭이 떠 있는 동안만 본다.
   */
  const [ignored, setIgnored] = useState<'off' | 'typing' | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.altKey || event.metaKey || armKeyMeaning(event.code) === null) return;
      const typing = isTypingTarget(document.activeElement);
      setIgnored(!armKeysEnabled(deviceId) ? (typing ? null : 'off') : typing ? 'typing' : null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [deviceId]);

  return <>
    <section className="manual-tab__head">
      {/* 체크박스가 아니라 버튼이다 — Go1 탭과 같은 이유(포커스가 남은 체크박스는 Space 를 먹는다). */}
      <button type="button" className={enabled ? 'manual-switch manual-switch--on' : 'manual-switch'} aria-pressed={enabled}
        onClick={(event) => { setArmKeysEnabled(deviceId, !enabled); event.currentTarget.blur(); }}>
        {enabled ? t('arm.keys.on') : t('arm.keys.off')}
      </button>
      <div><small>{t('arm.keys.why')}</small></div>
    </section>

    {ignored !== null && <p className="manual-warn">{t(`arm.keys.ignored.${ignored}`)}</p>}

    {enabled && shared.length > 0 && <p className="manual-warn">{t('arm.keys.shared', {
      keys: shared.map((item) => `${item.key} (${item.devices.join(', ')})`).join(' · '),
    })}</p>}

    <section className="manual-tab__section">
      <header><h3>{t('arm.keys.title')}</h3></header>
      <div className="arm-keymap">
        <table className="manual-table">
          <thead><tr><th>{t('manual.col.motion')}</th><th>{t('manual.col.key')}</th></tr></thead>
          <tbody>
            {ARM_MOTIONS.map((motion) => <tr key={motion}>
              <td>{t(`arm.motion.${motion}`)}</td>
              <td><span className="manual-key manual-key--fixed">{keyLabel(ARM_MOTION_KEYS[motion])}</span></td>
            </tr>)}
          </tbody>
        </table>
        <table className="manual-table">
          <thead><tr><th>{t('manual.col.action')}</th><th>{t('manual.col.key')}</th></tr></thead>
          <tbody>
            {ARM_TOOLS.map((tool) => <tr key={tool}>
              <td>{t(`arm.tool.${tool}`)}</td>
              <td><span className="manual-key manual-key--fixed">{keyLabel(ARM_TOOL_KEYS[tool])}</span></td>
            </tr>)}
            <tr className="manual-table__stop">
              <td>{t('arm.btn.stop')}</td>
              <td><span className="manual-key manual-key--fixed">{keyLabel(ARM_STOP_KEY)}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('arm.keys.modeTitle')}</h3>
        <nav className="manual-presets" role="radiogroup" aria-label={t('arm.keys.modeTitle')}>
          {ARM_KEY_MODES.map((mode) => <button key={mode} type="button" role="radio" aria-checked={config.mode === mode}
            onClick={(event) => { setArmKeyConfig(deviceId, { mode }); event.currentTarget.blur(); }}>{t(`arm.keys.mode.${mode}`)}</button>)}
        </nav>
      </header>
      <p className="manual-note">{t(`arm.keys.mode.${config.mode}Why`)}</p>
      {config.mode === 'jog' && <p className={jogDeclared === 'yes' ? 'manual-note' : 'manual-warn'}>{t(`arm.keys.jog.${jogDeclared}`)}</p>}
    </section>

    {config.mode === 'jog' ? <section className="manual-tab__section">
      <header><h3>{t('arm.keys.jogTitle')}</h3></header>
      <div className="manual-steps">
        <label>{t('arm.keys.stepMm')}
          <NumberField value={config.jogMmS} min={JOG_MM_S_RANGE.min} max={JOG_MM_S_RANGE.max} step={5}
            onCommit={(value) => setArmKeyConfig(deviceId, { jogMmS: value })} /> mm/s
        </label>
        <label>{t('arm.keys.stepDeg')}
          <NumberField value={config.jogDegS} min={JOG_DEG_S_RANGE.min} max={JOG_DEG_S_RANGE.max} step={5}
            onCommit={(value) => setArmKeyConfig(deviceId, { jogDegS: value })} /> °/s
        </label>
      </div>
      <p className="manual-note">{t('arm.keys.jogWhy')}</p>
    </section> : <section className="manual-tab__section">
      <header><h3>{t('arm.keys.stepTitle')}</h3></header>
      <div className="manual-steps">
        <label>{t('arm.keys.stepMm')}
          <NumberField value={config.stepMm} min={STEP_MM_RANGE.min} max={STEP_MM_RANGE.max} step={1}
            onCommit={(value) => setArmKeyConfig(deviceId, { stepMm: value })} /> mm
        </label>
        <label>{t('arm.keys.stepDeg')}
          <NumberField value={config.stepDeg} min={STEP_DEG_RANGE.min} max={STEP_DEG_RANGE.max} step={1}
            onCommit={(value) => setArmKeyConfig(deviceId, { stepDeg: value })} /> °
        </label>
        <label>{t('arm.speed')}
          <SpeedField value={config.speed} onCommit={(value) => setArmKeyConfig(deviceId, { speed: value })} />
        </label>
      </div>
      <p className="manual-note">{t('arm.keys.stepWhy')}</p>
    </section>}
  </>;
}

/** 속도 — 비우면 장비 기본(`null`). */
function SpeedField({ value, onCommit }: { value: number | null; onCommit(value: number | null): void }) {
  useLang();
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parsed = Number(draft);
    if (draft.trim() === '') onCommit(null);
    else if (Number.isFinite(parsed)) onCommit(parsed);
    setDraft(null);
  };
  return <input type="number" min={ARM_SPEED_RANGE.min} max={ARM_SPEED_RANGE.max} step={50} placeholder={t('arm.speed.default')}
    value={draft ?? (value === null ? '' : String(value))}
    onChange={(event) => setDraft(event.target.value)} onBlur={commit}
    onKeyDown={(event) => { if (event.key === 'Enter') { commit(); event.currentTarget.blur(); } }} />;
}

// ── 경로 설계 ───────────────────────────────────────────────────────────

function ArmPathPane({ view, can, send, setNote }: {
  view: ArmView; can(action: ArmAction): boolean; send: Send; setNote(note: string): void;
}) {
  useLang();
  const [jogDeg, setJogDeg] = useState('5');
  const [speed, setSpeed] = useState('');
  const [joints, setJoints] = useState<Record<string, string>>({ j1: '', j2: '', j3: '', j4: '' });
  const [jointRel, setJointRel] = useState(false);
  const [cart, setCart] = useState<Record<CartAxis, string>>({ x: '', y: '', z: '' });
  const [cartRel, setCartRel] = useState(false);

  /** 속도 칸 — 비우면 안 싣는다. 범위 밖이면 사유를 적고 `undefined`(보내지 않음). */
  const speedParam = (): Record<string, number> | undefined => {
    const value = parseField(speed);
    if (value === null) return {};
    if (!Number.isFinite(value) || value <= 0 || value > SPEED_MAX) { setNote(t('arm.speed.bad', { max: SPEED_MAX })); return undefined; }
    return { speed: value };
  };

  const jog = (joint: number, sign: 1 | -1) => {
    const size = Number(jogDeg);
    if (!Number.isFinite(size) || size <= 0 || size > JOG_MAX_DEG) { setNote(t('arm.jog.bad', { max: JOG_MAX_DEG })); return; }
    void send('jog_joint', { joint, delta_deg: sign * size });
  };
  const moveJoint = () => {
    const extra = speedParam();
    if (extra === undefined) return;
    const params: Record<string, number> = {};
    for (const j of JOINTS) {
      const value = parseField(joints[`j${j}`]);
      if (value === null) continue;
      if (!Number.isFinite(value)) { setNote(t('arm.field.bad', { name: `j${j}` })); return; }
      params[`j${j}`] = value;
    }
    if (Object.keys(params).length === 0) { setNote(t('arm.field.empty')); return; }
    void send('move_joint', { ...params, relative: jointRel ? 1 : 0, ...extra });
  };
  const moveCart = () => {
    const extra = speedParam();
    if (extra === undefined) return;
    const params: Record<string, number> = {};
    for (const axis of CART_AXES) {
      const value = parseField(cart[axis]);
      if (value === null) continue;
      if (!Number.isFinite(value)) { setNote(t('arm.field.bad', { name: axis })); return; }
      params[axis] = value;
    }
    if (Object.keys(params).length === 0) { setNote(t('arm.field.empty')); return; }
    // 손목을 그대로 둔다 — `a` 를 빼면 노드가 손목을 0° 로 되돌린다(261117 실측 · `armKeys.ts`). 상대면 0, 절대면 지금 j4.
    const wrist = cartRel ? 0 : view.joints?.j4;
    void send('move_cart', { ...params, ...(wrist === undefined ? {} : { a: wrist }), relative: cartRel ? 1 : 0, ...extra });
  };
  /** 지금 자세를 칸에 옮긴다 — 한 관절만 고쳐 보내기 쉽게. */
  const fillJoints = () => {
    if (view.joints === null) return;
    setJoints(Object.fromEntries(JOINTS.map((j) => [`j${j}`, view.joints?.[`j${j}`] === undefined ? '' : String(view.joints[`j${j}`])])));
    setJointRel(false);
  };
  const fillCart = () => {
    if (view.tcp === null) return;
    setCart(Object.fromEntries(CART_AXES.map((axis) => [axis, view.tcp?.[axis] === undefined ? '' : String(view.tcp[axis])])) as Record<CartAxis, string>);
    setCartRel(false);
  };

  return <>
    <section className="manual-tab__section">
      <header><h3>{t('arm.jog.title')}</h3>
        <label className="arm-inline">{t('arm.jog.step')}
          <input type="number" min={0.1} max={JOG_MAX_DEG} step={1} value={jogDeg} onChange={(event) => setJogDeg(event.target.value)} /> °
        </label>
      </header>
      <div className="arm-jog">
        {JOINTS.map((j) => <div key={j} className="arm-jog__row">
          <b>j{j}</b>
          <button type="button" className="arm-btn" disabled={!can('jog_joint')} onClick={() => jog(j, -1)}>−</button>
          <button type="button" className="arm-btn" disabled={!can('jog_joint')} onClick={() => jog(j, 1)}>+</button>
          {view.jointRanges?.[`j${j}`] !== undefined && <small>{view.jointRanges[`j${j}`]![0]}° ~ {view.jointRanges[`j${j}`]![1]}°</small>}
        </div>)}
      </div>
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('arm.move.title')}</h3>
        <label className="arm-inline">{t('arm.speed')}
          <input type="number" min={1} max={SPEED_MAX} step={50} placeholder={t('arm.speed.default')} value={speed} onChange={(event) => setSpeed(event.target.value)} />
        </label>
      </header>
      <div className="arm-move">
        <div className="manual-steps">
          {JOINTS.map((j) => <label key={j}>j{j}
            <input type="number" step={1} value={joints[`j${j}`]} onChange={(event) => setJoints({ ...joints, [`j${j}`]: event.target.value })} /> °
          </label>)}
          <label><input type="checkbox" checked={jointRel} onChange={(event) => setJointRel(event.target.checked)} />{t('arm.relative')}</label>
          <button type="button" className="manual-unbind" disabled={view.joints === null} onClick={fillJoints}>{t('arm.fillNow')}</button>
          <button type="button" className="arm-btn" disabled={!can('move_joint')} onClick={moveJoint}>{t('arm.btn.moveJoint')}</button>
        </div>
        <div className="manual-steps">
          {CART_AXES.map((axis) => <label key={axis}>{axis}
            <input type="number" step={1} value={cart[axis]} onChange={(event) => setCart({ ...cart, [axis]: event.target.value })} /> mm
          </label>)}
          <label><input type="checkbox" checked={cartRel} onChange={(event) => setCartRel(event.target.checked)} />{t('arm.relative')}</label>
          <button type="button" className="manual-unbind" disabled={view.tcp === null} onClick={fillCart}>{t('arm.fillNow')}</button>
          <button type="button" className="arm-btn" disabled={!can('move_cart')} onClick={moveCart}>{t('arm.btn.moveCart')}</button>
        </div>
      </div>
      <p className="manual-note">{t('arm.move.why')}</p>
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('arm.tool.title')}</h3></header>
      <div className="arm-tools">
        <div className="arm-tools__row">
          <b>{t('arm.pump')}</b>
          {[0, 1, 2].map((mode) => <button key={mode} type="button" className="arm-btn" disabled={!can('pump')}
            onClick={() => void send('pump', { mode })}>{t(`arm.pump.${mode}`)}</button>)}
          {view.pumpPwm !== null && <small>pwm {view.pumpPwm}</small>}
        </div>
        <div className="arm-tools__row">
          <b>{t('arm.gripper')}</b>
          {[0, 1, 2].map((mode) => <button key={mode} type="button" className="arm-btn" disabled={!can('gripper')}
            onClick={() => void send('gripper', { mode })}>{t(`arm.gripper.${mode}`)}</button>)}
        </div>
      </div>
    </section>
  </>;
}
