/**
 * src/physical/manualControl.ts (261005 신설 — 하드웨어 카드 · 로봇 수동 제어)
 *
 * **장비마다 수동 제어를 켜 두었는가, 어느 키가 무엇인가.** 키를 받아 명령을 내는 것은
 * `manualDispatch.ts` 이고, 여기는 그 재료(상태 · 키 배치 · 판정)만 든다.
 *
 * ## 키와 action 사이에 「동작」이 있다
 *
 *     키 ──(키 배치)──▶ 동작(forward · back · left · right · rotLeft · rotRight · 추가 동작 · 정지)
 *                          │
 *                          ▼ 그 장비가 선언한 것으로 푼다
 *                 `teleop` 선언 → 속도 모드 · 아니면 스텝 모드(`move_forward` · `turn`)
 *
 * 키 배치는 장비와 무관하고, 동작을 무엇으로 바꾸는지는 장비가 정한다. 하드웨어가 속도 명령을
 * 열어 주는 날 키 설정은 한 줄도 안 바뀐다 — 푸는 쪽만 바뀐다.
 *
 * ## 스텝 모드는 임시다
 *
 * 지금 규약에는 뒤로 · 옆으로 · 누르는 동안 걷기가 없다(`stepScript.ts` §뒤로·옆으로는 안 만든다).
 * 그래서 W 한 번 = 한 걸음, Q · E 한 번 = 한 번 돌기이고, S · A · D 는 막혀 있다. 한 걸음 도중에 세울
 * 길이 정지 키(Space → `abort`)뿐이라 그것도 여기 있다. **속도 모드가 서면 정지 키와 걸음 크기는 뺀다**
 * (261005 지시 — 「최종적으로는 속도 모드로 쓸 것이기 때문에 일단 만들고 나중에 빼기」).
 *
 * ## 키는 `event.code` 로 적는다
 *
 * 글자(`event.key`)로 적으면 한글 입력기가 켜진 채로 W 를 눌렀을 때 `ㅈ` 이 와서 안 걷는다.
 * 자판 위치로 적으면 입력기 · Shift 와 무관하게 같은 키다.
 *
 * ## 켜짐은 저장하지 않는다
 *
 * 키 배치 · 걸음 크기는 브라우저에 남기지만 **켜짐은 남기지 않는다.** 새로고침하고 화면을 열자마자
 * 로봇이 키를 받으면 안 된다 — 켜는 것은 매번 사람이 한다(`humanAction.ts` 의 빗장과 같은 이유).
 */

import { useSyncExternalStore } from 'react';
import { FORWARD_MIN_M, TURN_MIN_DEG } from './stepScript.ts';
import { STOP_ACTION, TELEOP_ACTION, TELEOP_LIMITS, TELEOP_SPEED } from './presets.ts';
import type { PhysicalAction } from './encode.ts';

export const MOTIONS = ['forward', 'back', 'left', 'right', 'rotLeft', 'rotRight'] as const;
export type ManualMotion = (typeof MOTIONS)[number];

export type KeyPreset = 'wasd' | 'arrows';
export const KEY_PRESETS: readonly KeyPreset[] = ['wasd', 'arrows'];

export const PRESET_KEYS: Record<KeyPreset, Readonly<Record<ManualMotion, string>>> = {
  wasd: { forward: 'KeyW', back: 'KeyS', left: 'KeyA', right: 'KeyD', rotLeft: 'KeyQ', rotRight: 'KeyE' },
  arrows: { forward: 'ArrowUp', back: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight', rotLeft: 'KeyZ', rotRight: 'KeyX' },
};

/** 정지 키 — 켜 둔 장비 전부에 `abort`. **스텝 모드용 임시 키다** (위 §스텝 모드는 임시다). */
export const STOP_KEY = 'Space';

/**
 * 다른 데 쓰는 키라 동작에 못 다는 것. Esc 는 창 닫기, Tab · Enter 는 화면 조작이고, 조합 키는
 * 단독으로 누를 일이 없다. Space 는 정지 키다.
 */
const RESERVED = new Set([
  'Escape', 'Tab', 'Enter', 'NumpadEnter', 'Backspace', 'CapsLock', STOP_KEY,
  'ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight', 'AltLeft', 'AltRight', 'MetaLeft', 'MetaRight',
  'ContextMenu', 'Lang1', 'Lang2', 'HangulMode', 'Hanja',
]);

/**
 * 추가 동작 칸에 안 띄우는 선언. 이동은 기본 칸이 맡고, 연결 확인 · 임무 · 정지는 수동 키로 낼 것이 아니다.
 * `sdk_auto` 는 `on` 값을 실어야 하는 설정이라 파라미터 없는 키 한 번으로는 못 낸다.
 */
const NOT_EXTRA = new Set<string>([
  'ping', 'diag', 'turn', 'move_forward', TELEOP_ACTION, 'scan_mission', 'scan_continue',
  STOP_ACTION, 'abort_mission', 'sar_start', 'sar_abort', 'sdk_auto',
]);

/** 걸음 크기의 범위. 아래는 규약 하한이고, 위는 「한 번 누른 것」으로 갈 만한 거리다. */
export const STEP_M_RANGE = { min: FORWARD_MIN_M, max: 1 } as const;
export const STEP_DEG_RANGE = { min: TURN_MIN_DEG, max: 90 } as const;
/** `move_forward` 의 `vx` 규약 범위(`stepScript.ts` §규약이 주는 한계). */
export const STEP_VX_RANGE = { min: 0.05, max: 0.3 } as const;
const DEFAULT_STEP_M = 0.3;
const DEFAULT_STEP_DEG = 15;

export type ManualConfig = {
  preset: KeyPreset;
  motionKeys: Readonly<Record<ManualMotion, string | null>>;
  /** 추가 동작(장비가 선언한 이름) → 키. 안 단 것은 칸이 없다. */
  extraKeys: Readonly<Record<string, string>>;
  stepM: number;
  stepDeg: number;
  /**
   * 키 하나가 내는 속도 (261005 — 탭에서 정한다). 속도 모드는 셋 다 쓰고, 스텝 모드는 `vx` 만 한 걸음의 속도로 쓴다 —
   * 그때는 `move_forward` 규약 범위(0.05~0.30)로 한 번 더 묶인다(`stepCommand`).
   */
  speed: Velocity;
};

type ManualState = Readonly<Record<string, { enabled: boolean; config: ManualConfig }>>;

function defaultConfig(preset: KeyPreset = 'wasd'): ManualConfig {
  return { preset, motionKeys: { ...PRESET_KEYS[preset] }, extraKeys: {}, stepM: DEFAULT_STEP_M, stepDeg: DEFAULT_STEP_DEG, speed: { ...TELEOP_SPEED } };
}

let state: ManualState = {};
let capturing = false;
const listeners = new Set<() => void>();

function commit(next: ManualState): void {
  state = next;
  for (const listener of listeners) listener();
}

// ── 브라우저 저장 — 편의값만. 못 읽고 못 써도 화면은 기본값으로 돈다. ───────────────────────

const STORAGE_PREFIX = 'vz.manual.';

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

function loadConfig(deviceId: string): ManualConfig {
  const base = defaultConfig();
  try {
    const raw = storage()?.getItem(STORAGE_PREFIX + deviceId) ?? null;
    if (raw === null) return base;
    const saved = JSON.parse(raw) as Partial<ManualConfig>;
    const preset = saved.preset === 'arrows' ? 'arrows' : 'wasd';
    const motionKeys = { ...PRESET_KEYS[preset] } as Record<ManualMotion, string | null>;
    for (const motion of MOTIONS) {
      const key = saved.motionKeys?.[motion];
      if (typeof key === 'string' || key === null) motionKeys[motion] = key;
    }
    const extraKeys: Record<string, string> = {};
    for (const [action, key] of Object.entries(saved.extraKeys ?? {})) if (typeof key === 'string') extraKeys[action] = key;
    return {
      preset, motionKeys, extraKeys,
      stepM: clamp(num(saved.stepM) ?? base.stepM, STEP_M_RANGE),
      stepDeg: clamp(num(saved.stepDeg) ?? base.stepDeg, STEP_DEG_RANGE),
      speed: {
        vx: clamp(num(saved.speed?.vx) ?? base.speed.vx, TELEOP_LIMITS.vx),
        vy: clamp(num(saved.speed?.vy) ?? base.speed.vy, TELEOP_LIMITS.vy),
        vyaw: clamp(num(saved.speed?.vyaw) ?? base.speed.vyaw, TELEOP_LIMITS.vyaw),
      },
    };
  } catch {
    return base;
  }
}

function saveConfig(deviceId: string, config: ManualConfig): void {
  try {
    storage()?.setItem(STORAGE_PREFIX + deviceId, JSON.stringify(config));
  } catch {
    // 저장이 막혀 있어도(사생활 창 · 막힌 사이트 데이터) 이번 화면에서는 그대로 쓴다.
  }
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clamp(value: number, range: { min: number; max: number }): number {
  return Math.min(range.max, Math.max(range.min, value));
}

/** 저장소에서 한 번 읽은 것. 그리기마다 다시 읽지 않는다. */
const loaded = new Map<string, ManualConfig>();

function entry(deviceId: string): { enabled: boolean; config: ManualConfig } {
  const known = state[deviceId];
  if (known !== undefined) return known;
  let config = loaded.get(deviceId);
  if (config === undefined) {
    config = loadConfig(deviceId);
    loaded.set(deviceId, config);
  }
  return { enabled: false, config };
}

function update(deviceId: string, change: (current: { enabled: boolean; config: ManualConfig }) => { enabled: boolean; config: ManualConfig }): void {
  const current = entry(deviceId);
  const next = change(current);
  if (next.config !== current.config) saveConfig(deviceId, next.config);
  commit({ ...state, [deviceId]: next });
}

// ── 읽기 ─────────────────────────────────────────────────────────────────────

export function manualConfig(deviceId: string): ManualConfig {
  return entry(deviceId).config;
}

export function manualEnabled(deviceId: string): boolean {
  return state[deviceId]?.enabled === true;
}

/** 지금 수동 제어가 켜진 장비. 켠 순서가 아니라 id 순이다 — 알림 줄이 출렁이지 않게. */
export function enabledManualDevices(): readonly string[] {
  return Object.keys(state).filter((id) => state[id].enabled).sort();
}

/** 이 키가 이 장비에서 무엇인가. 정지 키는 모든 장비 공통이다. */
export type KeyMeaning =
  | { kind: 'motion'; motion: ManualMotion }
  | { kind: 'extra'; action: string }
  | { kind: 'stop' };

export function keyMeaning(config: ManualConfig, code: string): KeyMeaning | null {
  if (code === STOP_KEY) return { kind: 'stop' };
  for (const motion of MOTIONS) if (config.motionKeys[motion] === code) return { kind: 'motion', motion };
  for (const [action, key] of Object.entries(config.extraKeys)) if (key === code) return { kind: 'extra', action };
  return null;
}

/** 기본 배치에서 손댔는가. 배치를 바꿀 때 「직접 바꾼 키가 지워진다」를 물을지 정한다. */
export function customized(config: ManualConfig): boolean {
  return MOTIONS.some((motion) => config.motionKeys[motion] !== PRESET_KEYS[config.preset][motion]);
}

/**
 * **같은 키를 둘 이상의 켜진 장비가 쓰는 곳** (261005 지시 — 함께 움직이되 경고).
 * 키 → 장비들. 정지 키는 일부러 공통이라 뺀다.
 */
export function sharedKeys(deviceIds: readonly string[] = enabledManualDevices()): ReadonlyMap<string, readonly string[]> {
  const users = new Map<string, string[]>();
  for (const deviceId of deviceIds) {
    const config = manualConfig(deviceId);
    const keys = new Set([...Object.values(config.motionKeys), ...Object.values(config.extraKeys)]);
    for (const key of keys) {
      if (key === null) continue;
      users.set(key, [...(users.get(key) ?? []), deviceId]);
    }
  }
  return new Map([...users].filter(([, ids]) => ids.length > 1));
}

// ── 쓰기 ─────────────────────────────────────────────────────────────────────

export function setManualEnabled(deviceId: string, enabled: boolean): void {
  update(deviceId, (current) => ({ ...current, enabled }));
}

/** 기본 배치를 바꾼다. 기본 칸은 그 배치로 다시 채우고, 새 배치와 겹치는 추가 동작 키는 뗀다. */
export function setPreset(deviceId: string, preset: KeyPreset): void {
  update(deviceId, (current) => {
    const motionKeys = { ...PRESET_KEYS[preset] };
    const taken = new Set(Object.values(motionKeys));
    const extraKeys = Object.fromEntries(Object.entries(current.config.extraKeys).filter(([, key]) => !taken.has(key)));
    return { ...current, config: { ...current.config, preset, motionKeys, extraKeys } };
  });
}

export type BindSlot = { kind: 'motion'; motion: ManualMotion } | { kind: 'extra'; action: string };
export type BindResult = { ok: true } | { ok: false; reason: 'reserved' } | { ok: false; reason: 'taken'; by: BindSlot };

/** 키를 단다. 다른 데 쓰는 키 · 이 장비의 다른 칸이 이미 쓰는 키는 거절한다(옮겨 달지 않는다). */
export function bindKey(deviceId: string, slot: BindSlot, code: string): BindResult {
  if (RESERVED.has(code)) return { ok: false, reason: 'reserved' };
  const config = manualConfig(deviceId);
  const meaning = keyMeaning(config, code);
  if (meaning !== null && meaning.kind !== 'stop' && !sameSlot(meaning, slot)) {
    return { ok: false, reason: 'taken', by: meaning };
  }
  update(deviceId, (current) => ({
    ...current,
    config: slot.kind === 'motion'
      ? { ...current.config, motionKeys: { ...current.config.motionKeys, [slot.motion]: code } }
      : { ...current.config, extraKeys: { ...current.config.extraKeys, [slot.action]: code } },
  }));
  return { ok: true };
}

/** 키를 뗀다. 기본 칸은 비우고(그 동작을 안 쓴다), 추가 동작은 칸에서 지운다. */
export function unbindKey(deviceId: string, slot: BindSlot): void {
  update(deviceId, (current) => {
    if (slot.kind === 'motion') {
      return { ...current, config: { ...current.config, motionKeys: { ...current.config.motionKeys, [slot.motion]: null } } };
    }
    const extraKeys = { ...current.config.extraKeys };
    delete extraKeys[slot.action];
    return { ...current, config: { ...current.config, extraKeys } };
  });
}

/** 걸음 크기 — 스텝 모드에서만 쓴다. 범위 밖은 범위 끝으로 붙인다. */
export function setStep(deviceId: string, change: { stepM?: number; stepDeg?: number }): void {
  update(deviceId, (current) => ({
    ...current,
    config: {
      ...current.config,
      stepM: change.stepM === undefined ? current.config.stepM : clamp(change.stepM, STEP_M_RANGE),
      stepDeg: change.stepDeg === undefined ? current.config.stepDeg : clamp(change.stepDeg, STEP_DEG_RANGE),
    },
  }));
}

/** 키 하나가 내는 속도. 범위 밖은 범위 끝으로 붙인다(`TELEOP_LIMITS` — pi7 상한). */
export function setSpeed(deviceId: string, change: Partial<Velocity>): void {
  update(deviceId, (current) => {
    const speed = { ...current.config.speed };
    for (const axis of ['vx', 'vy', 'vyaw'] as const) {
      const value = change[axis];
      if (value !== undefined && Number.isFinite(value)) speed[axis] = clamp(value, TELEOP_LIMITS[axis]);
    }
    return { ...current, config: { ...current.config, speed } };
  });
}

/** 속도를 기본값으로. */
export function resetSpeed(deviceId: string): void {
  update(deviceId, (current) => ({ ...current, config: { ...current.config, speed: { ...TELEOP_SPEED } } }));
}

function sameSlot(meaning: KeyMeaning, slot: BindSlot): boolean {
  if (meaning.kind === 'motion') return slot.kind === 'motion' && slot.motion === meaning.motion;
  if (meaning.kind === 'extra') return slot.kind === 'extra' && slot.action === meaning.action;
  return false;
}

/**
 * **키를 받아 적는 중** — 탭이 「키를 누르세요」를 띄운 동안. 그 사이의 키는 명령이 아니다.
 * 받는 쪽(`ManualControlTab`)이 켜고 끈다.
 */
export function setKeyCapture(on: boolean): void {
  if (capturing === on) return;
  capturing = on;
  for (const listener of listeners) listener();
}

export function keyCaptureActive(): boolean {
  return capturing;
}

export function subscribeManual(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 화면이 다시 그려질 때 쓰는 손잡이. 상태 전체를 하나로 보는 것이라 값 비교가 싸다. */
export function useManualState(): ManualState {
  return useSyncExternalStore(subscribeManual, () => state);
}

/** 검사용. 화면에서는 부르지 않는다. */
export function resetManualControl(): void {
  state = {};
  loaded.clear();
  capturing = false;
  for (const listener of listeners) listener();
}

// ── 판정 — 장비가 말한 것으로 ────────────────────────────────────────────────

/** 장비가 밝힌 것 중 판정에 쓰는 셋. `deviceCandidates()` 의 한 줄이 그대로 들어온다. */
export type ManualDeviceFacts = { kind: string | null; actions: readonly string[] | null };

/**
 * **수동 제어 탭을 띄울 장비인가** — 움직이는 장비 가운데 드론이 아닌 것.
 *
 * 드론 · 고정 카메라는 부르는 쪽이 이미 걸렀다고 받는다(`fixedCamera` · `drone`). 남은 것 중 장비가
 * `robot` 이라고 했거나, 걸을 수 있는 action 을 선언했으면 로봇이다. 아무 말도 못 들은 장비(대본의 배역)는 아니다.
 */
export function isManualRobot(facts: ManualDeviceFacts | null, flags: { drone: boolean; fixedCamera: boolean }): boolean {
  if (facts === null || flags.drone || flags.fixedCamera) return false;
  if (facts.kind === 'robot') return true;
  return facts.actions?.some((action) => action === 'move_forward' || action === 'turn' || action === TELEOP_ACTION) === true;
}

export type ManualMode = 'velocity' | 'step';

/** 속도 명령을 선언했으면 속도 모드. 아니면(목록을 못 받았어도) 스텝 모드다. */
export function manualModeOf(actions: readonly string[] | null): ManualMode {
  return actions?.includes(TELEOP_ACTION) === true ? 'velocity' : 'step';
}

export type Support = 'yes' | 'no' | 'unknown';

/**
 * 이 동작을 지금 이 장비에 낼 수 있는가.
 *
 * 스텝 모드의 뒤로 · 옆으로는 **언제나 아니다** — 낼 action 이 없다. 앞 · 돌기는 선언을 보고, 목록을 아직
 * 못 받았으면 `unknown` 이다(Capability 는 retained 가 아니라 늦게 붙은 화면은 못 받는 것이 정상이다).
 * 그때는 보내 보고 장비의 거절을 그대로 받는다.
 */
export function motionSupport(actions: readonly string[] | null, motion: ManualMotion): Support {
  if (manualModeOf(actions) === 'velocity') return 'yes';
  const needed = motion === 'forward' ? 'move_forward' : motion === 'rotLeft' || motion === 'rotRight' ? 'turn' : null;
  if (needed === null) return 'no';
  if (actions === null) return 'unknown';
  return actions.includes(needed) ? 'yes' : 'no';
}

/** 추가 동작 칸에 띄울 선언. 목록을 못 받았으면 빈 것이다. */
export function extraActions(actions: readonly string[] | null): readonly string[] {
  return (actions ?? []).filter((action) => !NOT_EXTRA.has(action));
}

/** 스텝 모드 — 동작 하나가 내는 명령. 못 내는 동작이면 `null`. `turn` 은 오른쪽이 + 다. */
export function stepCommand(motion: ManualMotion, config: ManualConfig): { action: PhysicalAction; parameters: Record<string, number> } | null {
  // 한 걸음의 속도는 탭의 `vx` — `move_forward` 규약 범위로 한 번 더 묶는다(속도 모드 상한 0.40 이 규약 0.30 보다 크다).
  if (motion === 'forward') return { action: 'move_forward', parameters: { distance_m: config.stepM, vx: clamp(config.speed.vx, STEP_VX_RANGE) } };
  if (motion === 'rotLeft') return { action: 'turn', parameters: { deg: -config.stepDeg } };
  if (motion === 'rotRight') return { action: 'turn', parameters: { deg: config.stepDeg } };
  return null;
}

export type Velocity = { vx: number; vy: number; vyaw: number };
export const ZERO_VELOCITY: Velocity = { vx: 0, vy: 0, vyaw: 0 };

/**
 * 속도 모드 — 누르고 있는 동작들의 합. 앞 · 뒤를 같이 누르면 서로 지워 0 이다.
 * 축은 `TELEOP_ACTION` 주석 그대로(앞 + · 왼쪽 + · 반시계 +).
 */
export function velocityOf(held: Iterable<ManualMotion>, speed: Velocity = TELEOP_SPEED): Velocity {
  const set = new Set(held);
  const axis = (plus: ManualMotion, minus: ManualMotion) => (set.has(plus) ? 1 : 0) - (set.has(minus) ? 1 : 0);
  return {
    vx: axis('forward', 'back') * speed.vx,
    vy: axis('left', 'right') * speed.vy,
    vyaw: axis('rotLeft', 'rotRight') * speed.vyaw,
  };
}

export function isZero(velocity: Velocity): boolean {
  return velocity.vx === 0 && velocity.vy === 0 && velocity.vyaw === 0;
}

/** 키 이름 — 화면에 적는 글자. `KeyW` → `W`, `ArrowUp` → `↑`. */
export function keyLabel(code: string | null): string {
  if (code === null) return '—';
  if (code.startsWith('Key')) return code.slice(3);
  if (code.startsWith('Digit')) return code.slice(5);
  if (code.startsWith('Numpad')) return 'Num ' + code.slice(6);
  const arrows: Record<string, string> = { ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→' };
  return arrows[code] ?? code;
}
