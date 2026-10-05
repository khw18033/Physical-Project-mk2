/**
 * src/views/ManualControlTab.tsx (261005 신설 — 하드웨어 카드 · 로봇 수동 제어 탭)
 *
 * 카드 상세보기의 두 번째 탭. **켜고 끄기 · 기본 배치 · 키 달기 · 걸음 크기**를 여기서 한다.
 * 키를 받아 명령을 내는 것은 이 탭이 아니라 앱에 하나 걸린 처리기다(`manualDispatch.ts`) — 탭을 닫아도,
 * 카드를 닫아도 켜 둔 장비는 계속 키를 받는다.
 *
 * ## 키 달기
 *
 * 칸을 누르면 「키를 누르세요」가 되고, 그 사이의 키는 명령이 아니다(`setKeyCapture`). 받아 적는 처리기는
 * **창의 capture 단계**에 걸어 다른 처리기보다 먼저 받고 거기서 멈춘다 — Esc 로 받아 적기를 그만둘 때
 * 카드 창까지 같이 닫히면 안 된다.
 *
 * 다른 데 쓰는 키 · 이 장비의 다른 칸이 쓰는 키는 거절하고 이유를 적는다. 다른 장비와 겹치는 것은 막지 않는다
 * (함께 움직이되 경고 — 261005 지시).
 */

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { deviceCandidates, subscribeDeviceIdentity } from '../physical/deviceIdentity.ts';
import {
  bindKey, customized, extraActions, KEY_PRESETS, keyLabel, manualConfig, manualEnabled, manualModeOf, MOTIONS,
  motionSupport, resetSpeed, setKeyCapture, setManualEnabled, setPreset, setSpeed, setStep, sharedKeys, STEP_DEG_RANGE,
  STEP_M_RANGE, STEP_VX_RANGE, STOP_KEY, unbindKey, useManualState, type BindResult, type BindSlot,
} from '../physical/manualControl.ts';
import { TELEOP_LIMITS } from '../physical/presets.ts';
import { manualBlock, useManualEvents } from '../physical/manualDispatch.ts';
import { ManualEventLine, useEverySec } from './ManualControlBadge.tsx';

function useDeviceActions(deviceId: string): readonly string[] | null {
  return useSyncExternalStore(subscribeDeviceIdentity,
    () => deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null);
}

function slotName(slot: BindSlot): string {
  return slot.kind === 'motion' ? t(`manual.motion.${slot.motion}`) : slot.action;
}

function sameSlot(a: BindSlot | null, b: BindSlot): boolean {
  if (a === null || a.kind !== b.kind) return false;
  return a.kind === 'motion' ? b.kind === 'motion' && a.motion === b.motion : b.kind === 'extra' && a.action === b.action;
}

/**
 * **숫자 칸 — 칸을 떠나거나 Enter 를 칠 때 정한다.** 칠 때마다 정하면 「0.」을 치는 순간 0 이 되어 하한으로
 * 붙어 버린다. 범위는 저장소가 묶고, 칸은 묶인 값으로 다시 그린다.
 */
function NumberField({ value, min, max, step, onCommit }: {
  value: number; min: number; max: number; step: number; onCommit(value: number): void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parsed = Number(draft);
    if (draft.trim() !== '' && Number.isFinite(parsed)) onCommit(parsed);
    setDraft(null);
  };
  return <input type="number" min={min} max={max} step={step} value={draft ?? String(value)}
    onChange={(event) => setDraft(event.target.value)}
    onBlur={commit}
    onKeyDown={(event) => { if (event.key === 'Enter') { commit(); event.currentTarget.blur(); } }} />;
}

export function ManualControlTab({ deviceId }: { deviceId: string }) {
  useLang();
  useManualState();
  useEverySec();
  const events = useManualEvents();
  const actions = useDeviceActions(deviceId);
  const config = manualConfig(deviceId);
  const enabled = manualEnabled(deviceId);
  const mode = manualModeOf(actions);
  const extras = extraActions(actions);
  const block = enabled ? manualBlock(deviceId) : null;
  const shared = [...sharedKeys()].filter(([, ids]) => ids.includes(deviceId));

  const [capturing, setCapturing] = useState<BindSlot | null>(null);
  const [bindNote, setBindNote] = useState<string>('');

  useEffect(() => {
    if (capturing === null) return;
    setKeyCapture(true);
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (event.key === 'Escape') { setCapturing(null); setBindNote(''); return; }
      const result: BindResult = bindKey(deviceId, capturing, event.code);
      if (result.ok) setBindNote('');
      else if (result.reason === 'reserved') setBindNote(t('manual.bind.reserved', { key: keyLabel(event.code) }));
      else setBindNote(t('manual.bind.taken', { key: keyLabel(event.code), slot: slotName(result.by) }));
      setCapturing(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      setKeyCapture(false);
    };
  }, [capturing, deviceId]);

  const pickPreset = (preset: (typeof KEY_PRESETS)[number]) => {
    if (preset === config.preset && !customized(config)) return;
    if (customized(config) && !window.confirm(t('manual.preset.confirm'))) return;
    setPreset(deviceId, preset);
  };

  const keyCell = (slot: BindSlot, code: string | null) => <>
    <td>
      <button type="button" className="manual-key" aria-pressed={sameSlot(capturing, slot)}
        onClick={() => setCapturing(sameSlot(capturing, slot) ? null : slot)}>
        {sameSlot(capturing, slot) ? t('manual.bind.press') : keyLabel(code)}
      </button>
    </td>
    <td>{code !== null && <button type="button" className="manual-unbind" onClick={() => unbindKey(deviceId, slot)}>{t('manual.bind.clear')}</button>}</td>
  </>;

  return <div className="manual-tab">
    <section className="manual-tab__head">
      {/* 체크박스가 아니라 버튼이다 — 포커스가 남은 체크박스는 「입력 중」으로 잡혀 키가 막히고, Space 를 먹는다. */}
      <button type="button" className={enabled ? 'manual-switch manual-switch--on' : 'manual-switch'} aria-pressed={enabled}
        onClick={(event) => { setManualEnabled(deviceId, !enabled); event.currentTarget.blur(); }}>
        {enabled ? t('manual.switch.on') : t('manual.switch.off')}
      </button>
      <div>
        <b>{t(mode === 'velocity' ? 'manual.mode.velocity' : 'manual.mode.step')}</b>
        <small>{t(mode === 'velocity' ? 'manual.mode.velocityWhy' : 'manual.mode.stepWhy')}</small>
      </div>
      {enabled && <p className={block === null ? 'manual-tab__state' : 'manual-tab__state manual-tab__state--blocked'}>
        {block === null ? t('manual.state.ready') : t(`manual.block.${block}`)}
      </p>}
    </section>

    {shared.length > 0 && <p className="manual-warn">{t('manual.shared', {
      keys: shared.map(([key, ids]) => `${keyLabel(key)} (${ids.join(', ')})`).join(' · '),
    })}</p>}

    <section className="manual-tab__section">
      <header><h3>{t('manual.preset.title')}</h3>
        <nav className="manual-presets" role="radiogroup" aria-label={t('manual.preset.title')}>
          {KEY_PRESETS.map((preset) => <button key={preset} type="button" role="radio" aria-checked={config.preset === preset && !customized(config)}
            onClick={(event) => { pickPreset(preset); event.currentTarget.blur(); }}>{t(`manual.preset.${preset}`)}</button>)}
        </nav>
      </header>
      <table className="manual-table">
        <thead><tr><th>{t('manual.col.motion')}</th><th>{t('manual.col.key')}</th><th /><th>{t('manual.col.support')}</th></tr></thead>
        <tbody>
          {MOTIONS.map((motion) => {
            const support = motionSupport(actions, motion);
            return <tr key={motion}>
              <td>{t(`manual.motion.${motion}`)}</td>
              {keyCell({ kind: 'motion', motion }, config.motionKeys[motion])}
              <td><span className={`manual-support manual-support--${support}`}>{t(`manual.support.${support}`)}</span></td>
            </tr>;
          })}
          <tr className="manual-table__stop">
            <td>{t('manual.stop')}</td>
            <td><span className="manual-key manual-key--fixed">{keyLabel(STOP_KEY)}</span></td>
            <td />
            <td><small>{t('manual.stopWhy')}</small></td>
          </tr>
        </tbody>
      </table>
      {bindNote !== '' && <p className="manual-warn">{bindNote}</p>}
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('manual.extra.title')}</h3></header>
      {actions === null
        ? <p className="manual-note">{t('manual.extra.unknown')}</p>
        : extras.length === 0
          ? <p className="manual-note">{t('manual.extra.none')}</p>
          : <table className="manual-table">
            <thead><tr><th>{t('manual.col.action')}</th><th>{t('manual.col.key')}</th><th /></tr></thead>
            <tbody>{extras.map((action) => <tr key={action}>
              <td><code>{action}</code></td>
              {keyCell({ kind: 'extra', action }, config.extraKeys[action] ?? null)}
            </tr>)}</tbody>
          </table>}
    </section>

    <section className="manual-tab__section">
      <header><h3>{t('manual.speed.title')}</h3>
        <button type="button" className="manual-unbind" onClick={(event) => { resetSpeed(deviceId); event.currentTarget.blur(); }}>{t('manual.speed.reset')}</button>
      </header>
      <div className="manual-steps">
        <label>{t('manual.speed.vx')}
          <NumberField value={config.speed.vx} min={TELEOP_LIMITS.vx.min} max={TELEOP_LIMITS.vx.max} step={0.05}
            onCommit={(value) => setSpeed(deviceId, { vx: value })} /> m/s
        </label>
        <label>{t('manual.speed.vy')}
          <NumberField value={config.speed.vy} min={TELEOP_LIMITS.vy.min} max={TELEOP_LIMITS.vy.max} step={0.05}
            onCommit={(value) => setSpeed(deviceId, { vy: value })} /> m/s
        </label>
        <label>{t('manual.speed.vyaw')}
          <NumberField value={config.speed.vyaw} min={TELEOP_LIMITS.vyaw.min} max={TELEOP_LIMITS.vyaw.max} step={0.1}
            onCommit={(value) => setSpeed(deviceId, { vyaw: value })} /> rad/s
        </label>
      </div>
      <p className="manual-note">{mode === 'velocity'
        ? t('manual.speed.whyVelocity', { vx: TELEOP_LIMITS.vx.max, vy: TELEOP_LIMITS.vy.max, vyaw: TELEOP_LIMITS.vyaw.max })
        : t('manual.speed.whyStep', { max: STEP_VX_RANGE.max })}</p>
    </section>

    {mode === 'step' && <section className="manual-tab__section">
      <header><h3>{t('manual.step.title')}</h3></header>
      <div className="manual-steps">
        <label>{t('manual.step.m')}
          <NumberField value={config.stepM} min={STEP_M_RANGE.min} max={STEP_M_RANGE.max} step={0.05}
            onCommit={(value) => setStep(deviceId, { stepM: value })} /> m
        </label>
        <label>{t('manual.step.deg')}
          <NumberField value={config.stepDeg} min={STEP_DEG_RANGE.min} max={STEP_DEG_RANGE.max} step={5}
            onCommit={(value) => setStep(deviceId, { stepDeg: value })} /> °
        </label>
      </div>
      <p className="manual-note">{t('manual.step.why')}</p>
    </section>}

    <p className="manual-note">{t('manual.rules')}</p>
    {events[deviceId] !== undefined && <p className="manual-tab__last"><ManualEventLine event={events[deviceId]} /></p>}
  </div>;
}
