/**
 * src/physical/armKeys.ts (261117 신설 — 로봇팔 MT4 키보드 제어)
 *
 * **키로 팔을 민다.** Go1 수동 제어(`manualDispatch.ts`)와 같은 자리에 같은 방식으로 건다 — 키 처리기는 앱에 하나이고
 * 앱 수명과 같다. 카드를 닫고 카메라를 보면서 몰 수 있어야 한다. 켜진 동안은 우측 상단 알림(`ArmKeysBadge`)이 그 사실을 말한다.
 *
 * ## 걷는 로봇과 다른 점 — 명령 하나가 동작 하나다
 *
 * 팔에는 속도 명령이 없고 물리 동작은 한 번에 하나다(`arm_node.py`). 그래서 키 한 번이 **상대 직교 이동 한 걸음**
 * (`move_cart relative=1`)이다. **누르고 있으면 걸음이 끝날 때마다 다음 걸음을 낸다** — 결과(`CommandResult`)가 오면
 * 그 키가 아직 눌려 있는지 보고 이어 낸다. 떼면 다음 걸음이 안 나간다(진행 중인 한 걸음은 끝까지 간다).
 *
 *   W / S   앞 / 뒤     x ±            Q / E   그리퍼 회전   4번 관절 ∓ / ± (jog_joint)
 *   A / D   왼 / 오     y ± / ∓        Z / X   그리퍼 열기 / 닫기
 *   R / F   위 / 아래   z ±            1 2 3   펌프 흡입 · 배출 · 끔
 *   H       원점 복귀 (home)
 *   Space   정지 (Go1 과 같은 키 — 언제나 나간다)
 *
 * ## 손목이 풀리지 않게 — 직교 이동에 `a: 0` 을 싣는다 (261117 실측)
 *
 * `move_cart` 에 `a` 를 안 실으면 노드가 손목(4번 관절)을 0° 로 되돌린다 — j4 10° 에서 x +5 를 내자 j4 가 0.02° 가 됐다.
 * 상대 이동에 `a: 0` 을 실으면 손목이 그대로다(10.02° → 10.05°). 노드 쪽 수정을 요청했고, 그 전까지는 늘 싣는다.
 *
 * 축의 방향은 MT4 의 기본 좌표다(x 팔 앞, y 왼쪽, z 위). 장비 쪽에서 다르면 이 표만 고친다.
 *
 * ## 키가 명령이 되지 않는 때 — Go1 과 같다
 *
 * 꺼짐 · 글 칸에 포커스 · 키 받아 적기 중(Go1 탭) · 조합 키(Ctrl · Alt · ⌘). 거절이 오면 누르고 있던 키를 놓은 것으로
 * 친다 — 누른 채로 계속 보내 봐야 다 거절이다.
 *
 * ## Go1 과 같은 키
 *
 * 둘 다 켜져 있으면 **둘 다 움직인다** — Go1 이 막지 않는 것과 같은 규칙이다. 탭과 알림이 경고한다.
 * 처리기는 `defaultPrevented` 를 보지 않는다 — Go1 처리기가 먼저 걸려 같은 키를 가로채므로, 보면 팔이 영영 못 받는다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { armBusy, isArmDevice, issueArm, noteArm, subscribeArmEvents, type ArmAction, type CartAxis } from './armControl.ts';
import { deviceCandidates } from './deviceIdentity.ts';
import { enabledManualDevices, keyCaptureActive, keyLabel, manualConfig, keyMeaning } from './manualControl.ts';
import { isTypingTarget } from './manualDispatch.ts';
import { clientForDevice } from './robotClient.ts';

export type ArmMotion = 'forward' | 'back' | 'left' | 'right' | 'up' | 'down' | 'rotLeft' | 'rotRight';
export type ArmTool = 'home' | 'gripOpen' | 'gripClose' | 'pumpSuck' | 'pumpBlow' | 'pumpOff';
export type ArmKeyMeaning = { kind: 'motion'; motion: ArmMotion } | { kind: 'tool'; tool: ArmTool } | { kind: 'stop' };

export const ARM_MOTIONS: readonly ArmMotion[] = ['forward', 'back', 'left', 'right', 'up', 'down', 'rotLeft', 'rotRight'];
export const ARM_TOOLS: readonly ArmTool[] = ['home', 'gripOpen', 'gripClose', 'pumpSuck', 'pumpBlow', 'pumpOff'];
export const ARM_STOP_KEY = 'Space';

/** 기본 키 — `KeyboardEvent.code`. */
export const ARM_MOTION_KEYS: Readonly<Record<ArmMotion, string>> = {
  forward: 'KeyW', back: 'KeyS', left: 'KeyA', right: 'KeyD', up: 'KeyR', down: 'KeyF', rotLeft: 'KeyQ', rotRight: 'KeyE',
};
export const ARM_TOOL_KEYS: Readonly<Record<ArmTool, string>> = {
  home: 'KeyH', gripOpen: 'KeyZ', gripClose: 'KeyX', pumpSuck: 'Digit1', pumpBlow: 'Digit2', pumpOff: 'Digit3',
};

/**
 * 걸음 하나 — 어느 쪽으로. 이동은 직교 상대 이동(mm), **회전은 4번 관절 조그(도)** — 펌웨어가 직교 `a` 축에 답하지 않는다
 * (261117 실측 · `armControl.ts` 의 `CART_AXES`). MT4 의 4번 관절이 손목(그리퍼) 회전이다.
 */
const MOTION_AXIS: Readonly<Record<ArmMotion, { axis: CartAxis | 'j4'; sign: 1 | -1 }>> = {
  forward: { axis: 'x', sign: 1 }, back: { axis: 'x', sign: -1 },
  left: { axis: 'y', sign: 1 }, right: { axis: 'y', sign: -1 },
  up: { axis: 'z', sign: 1 }, down: { axis: 'z', sign: -1 },
  rotLeft: { axis: 'j4', sign: -1 }, rotRight: { axis: 'j4', sign: 1 },
};

/** 그리퍼 모드 1 · 2 가 열기 · 닫기다(`arm_node.py` 의 `gripper mode`). 장비에서 반대면 여기만 바꾼다. */
const TOOL_COMMAND: Readonly<Record<ArmTool, { action: ArmAction; mode: number | null }>> = {
  home: { action: 'home', mode: null },
  gripOpen: { action: 'gripper', mode: 1 }, gripClose: { action: 'gripper', mode: 2 },
  pumpSuck: { action: 'pump', mode: 1 }, pumpBlow: { action: 'pump', mode: 2 }, pumpOff: { action: 'pump', mode: 0 },
};

export const STEP_MM_RANGE = { min: 1, max: 50 } as const;
export const STEP_DEG_RANGE = { min: 1, max: 90 } as const;
export const ARM_SPEED_RANGE = { min: 1, max: 2000 } as const;

/**
 * **두 방식** (261117 — 사람이 고른다).
 *
 *   step   걸음 — 키 한 번이 상대 이동 한 걸음, 누르고 있으면 걸음이 끝날 때마다 다음 걸음. 지금 노드로 된다.
 *          걸음 사이에 가속 · 감속 · 멈춤(≈0.65초)이 낀다 — 노드가 물리 동작을 하나씩만 받기 때문이다.
 *   jog    연속 — 누르는 동안 속도 명령(`jog`)을 200ms 마다 이어 보내고, 떼면 0 을 보낸다. Go1 teleop 과 같은 모양.
 *          **노드에 `jog` 가 있어야 한다** (pi6 에 요청 · 261117). 없으면 노드가 거절하고 그 사유가 그대로 뜬다.
 */
export type ArmKeyMode = 'step' | 'jog';
export const ARM_KEY_MODES: readonly ArmKeyMode[] = ['step', 'jog'];

export type ArmKeyConfig = {
  mode: ArmKeyMode;
  stepMm: number;
  stepDeg: number;
  /** 걸음 방식의 속도. 비우면(`null`) 장비 기본. */
  speed: number | null;
  /** 연속 방식 — 직교 이동 속도(mm/s) · 손목 회전 속도(deg/s). */
  jogMmS: number;
  jogDegS: number;
};

const DEFAULT_CONFIG: ArmKeyConfig = { mode: 'step', stepMm: 10, stepDeg: 10, speed: null, jogMmS: 20, jogDegS: 20 };

export const JOG_MM_S_RANGE = { min: 1, max: 100 } as const;
export const JOG_DEG_S_RANGE = { min: 1, max: 90 } as const;
/** 연속 방식 규약 (pi6 요청 문서와 같은 값) — 유지 신호 간격 · 노드가 스스로 세우기까지. Go1 teleop 과 같다. */
export const JOG_KEEPALIVE_MS = 200;
export const JOG_HOLD_MS = 600;

// ── 상태 ────────────────────────────────────────────────────────────────

type State = { enabled: ReadonlySet<string>; configs: Readonly<Record<string, ArmKeyConfig>> };
let state: State = { enabled: new Set(), configs: {} };
const listeners = new Set<() => void>();
function setState(next: State): void {
  state = next;
  for (const listener of listeners) listener();
}

export function useArmKeysState(): State {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    () => state, () => state,
  );
}

export function armKeysEnabled(deviceId: string): boolean {
  return state.enabled.has(deviceId);
}

export function enabledArmDevices(): readonly string[] {
  return [...state.enabled];
}

export function setArmKeysEnabled(deviceId: string, on: boolean): void {
  if (on === state.enabled.has(deviceId)) return;
  const enabled = new Set(state.enabled);
  if (on) enabled.add(deviceId);
  else { enabled.delete(deviceId); haltDevice(deviceId); }
  setState({ ...state, enabled });
}

export function armKeyConfig(deviceId: string): ArmKeyConfig {
  return state.configs[deviceId] ?? DEFAULT_CONFIG;
}

const clamp = (value: number, range: { min: number; max: number }) => Math.min(range.max, Math.max(range.min, value));

export function setArmKeyConfig(deviceId: string, patch: Partial<ArmKeyConfig>): void {
  const current = armKeyConfig(deviceId);
  const next: ArmKeyConfig = {
    mode: patch.mode ?? current.mode,
    stepMm: patch.stepMm === undefined ? current.stepMm : clamp(patch.stepMm, STEP_MM_RANGE),
    stepDeg: patch.stepDeg === undefined ? current.stepDeg : clamp(patch.stepDeg, STEP_DEG_RANGE),
    speed: patch.speed === undefined ? current.speed : patch.speed === null ? null : clamp(patch.speed, ARM_SPEED_RANGE),
    jogMmS: patch.jogMmS === undefined ? current.jogMmS : clamp(patch.jogMmS, JOG_MM_S_RANGE),
    jogDegS: patch.jogDegS === undefined ? current.jogDegS : clamp(patch.jogDegS, JOG_DEG_S_RANGE),
  };
  // 방식을 바꾸면 누르던 키 · 흐르던 연속 이동을 접는다 — 한 방식의 손이 다른 방식으로 넘어가면 안 된다.
  if (next.mode !== current.mode) haltDevice(deviceId);
  setState({ ...state, configs: { ...state.configs, [deviceId]: next } });
}

export function armKeyMeaning(code: string): ArmKeyMeaning | null {
  if (code === ARM_STOP_KEY) return { kind: 'stop' };
  const motion = ARM_MOTIONS.find((item) => ARM_MOTION_KEYS[item] === code);
  if (motion !== undefined) return { kind: 'motion', motion };
  const tool = ARM_TOOLS.find((item) => ARM_TOOL_KEYS[item] === code);
  if (tool !== undefined) return { kind: 'tool', tool };
  return null;
}

/** 걸음 하나의 명령. */
export function stepCommand(motion: ArmMotion, config: ArmKeyConfig): { action: ArmAction; parameters: Record<string, number> } {
  const { axis, sign } = MOTION_AXIS[motion];
  if (axis === 'j4') return { action: 'jog_joint', parameters: { joint: 4, delta_deg: sign * config.stepDeg } };
  // `a: 0` — 손목을 그대로 둔다(위 머리말). 빼면 노드가 손목을 0° 로 되돌린다.
  return { action: 'move_cart', parameters: { [axis]: sign * config.stepMm, a: 0, relative: 1, ...(config.speed === null ? {} : { speed: config.speed }) } };
}

export type JogVelocity = { vx: number; vy: number; vz: number; vj4: number };
export const ZERO_JOG: JogVelocity = { vx: 0, vy: 0, vz: 0, vj4: 0 };

/** 누르고 있는 키들의 합 — 앞+왼쪽을 같이 누르면 대각선이다. 반대 키를 같이 누르면 그 축은 0. */
export function jogVelocity(motions: readonly ArmMotion[], config: ArmKeyConfig): JogVelocity {
  const v = { ...ZERO_JOG };
  for (const motion of new Set(motions)) {
    const { axis, sign } = MOTION_AXIS[motion];
    if (axis === 'j4') v.vj4 += sign * config.jogDegS;
    else v[`v${axis}` as 'vx' | 'vy' | 'vz'] += sign * config.jogMmS;
  }
  return v;
}

const isZeroJog = (v: JogVelocity) => v.vx === 0 && v.vy === 0 && v.vz === 0 && v.vj4 === 0;
const jogParams = (v: JogVelocity): Record<string, number> => ({ ...v, hold_ms: JOG_HOLD_MS });

/**
 * **Go1 수동 제어와 겹치는 키** — 켜진 Go1 이 같은 키를 쓰면 함께 움직인다. 정지(Space)는 뺀다 — 같이 서는 것이 맞다.
 */
export function keysSharedWithGo1(): readonly { key: string; devices: readonly string[] }[] {
  const go1 = enabledManualDevices();
  if (go1.length === 0) return [];
  const codes = [...Object.values(ARM_MOTION_KEYS), ...Object.values(ARM_TOOL_KEYS)];
  const out: { key: string; devices: string[] }[] = [];
  for (const code of codes) {
    const devices = go1.filter((deviceId) => keyMeaning(manualConfig(deviceId), code) !== null);
    if (devices.length > 0) out.push({ key: keyLabel(code), devices });
  }
  return out;
}

// ── 바꿔 끼울 수 있는 것 — 검사가 보내기를 흉내 낸다(`manualDispatch.setManualProbes` 와 같은 자리) ──

let issue: typeof issueArm = issueArm;
/**
 * 연속 방식의 유지 신호 — **추적기를 안 지난다.** 같은 값을 200ms 마다 이어 보내는 것이라 매번 적으면 실행 기록이
 * 초당 다섯 줄씩 찬다(Go1 teleop 유지 신호와 같은 자리 · `manualDispatch.ts`). 값이 바뀐 순간은 `issue` 로 추적기를 지난다.
 * 거절이 오면 `onReject` 를 부른다.
 */
type KeepaliveSender = (deviceId: string, parameters: Record<string, number>, onReject: (reason: string) => void) => void;

const sendKeepalive: KeepaliveSender = (deviceId, parameters, onReject) => {
  const client = clientForDevice(deviceId);
  if (client === null || client.getStatus().state !== 'open') { onReject(t('arm.link.noBroker')); return; }
  const outcome = client.send('jog', parameters);
  if (!outcome.sent) { onReject(outcome.reason ?? t('robot.notSent')); return; }
  const off = client.onMessage((message) => {
    if (message.commandId !== outcome.commandId || message.kind !== 'acceptance') return;
    off();
    clearTimeout(timer);
    if (!message.accepted) onReject([message.code, message.message].filter((value) => value).join(' ') || t('robot.noReason'));
  });
  const timer = setTimeout(off, 3000);
};
let keepalive: KeepaliveSender = sendKeepalive;

/** 검사용. 화면에서는 부르지 않는다. `null` 이면 원래 것으로. */
export function setArmKeysIssuer(next: typeof issueArm | null, nextKeepalive: KeepaliveSender | null = null): void {
  issue = next ?? issueArm;
  keepalive = nextKeepalive ?? sendKeepalive;
}

// ── 키 → 명령 ───────────────────────────────────────────────────────────

/** 장비마다 지금 누르고 있는 이동 키(누른 순서). 걸음 방식은 마지막 것이 다음 걸음이고, 연속 방식은 전부의 합이다. */
const held = new Map<string, ArmMotion[]>();
/** 거절 · 못 냄으로 놓친 키 — 키 반복으로는 다시 안 잡는다. 떼었다 다시 눌러야 다시 나간다(Go1 teleop 거절과 같은 규칙). */
const dropped = new Map<string, Set<ArmMotion>>();

function hold(deviceId: string, motion: ArmMotion): void {
  const list = (held.get(deviceId) ?? []).filter((item) => item !== motion);
  list.push(motion);
  held.set(deviceId, list);
}

function release(deviceId: string, motion: ArmMotion): void {
  const list = (held.get(deviceId) ?? []).filter((item) => item !== motion);
  if (list.length === 0) held.delete(deviceId); else held.set(deviceId, list);
}

/** 누르던 키를 놓친 것으로 — 거절이 왔다. 키 반복으로 다시 잡지 않는다. */
function drop(deviceId: string): void {
  dropped.set(deviceId, new Set([...(dropped.get(deviceId) ?? []), ...(held.get(deviceId) ?? [])]));
  held.delete(deviceId);
}

// ── 걸음 방식 ───────────────────────────────────────────────────────────

/**
 * 보내는 중(수락을 기다리는 중)인 장비. `armBusy` 는 보낸 뒤에야 서므로 그 사이 키 반복(초당 30번)이 같은 걸음을
 * 겹쳐 내지 않게 따로 막는다.
 */
const launching = new Set<string>();

function step(deviceId: string): void {
  const motion = held.get(deviceId)?.at(-1);
  if (motion === undefined || launching.has(deviceId) || armBusy(deviceId)) return;
  launching.add(deviceId);
  const command = stepCommand(motion, armKeyConfig(deviceId));
  void issue(deviceId, command.action, command.parameters).then((outcome) => {
    launching.delete(deviceId);
    // 못 냈거나 거절됐으면 누른 키를 놓은 것으로 — 계속 보내 봐야 다 거절이다.
    if (!outcome.sent || outcome.accepted === false) drop(deviceId);
    if (!outcome.sent) noteArm(deviceId, command.action, outcome.message, 'bad');
    // 수락보다 결과가 먼저 왔으면 그때의 알림은 여기서 막혔다 — 아직 누르고 있으면 다음 걸음.
    else if (state.enabled.has(deviceId) && armKeyConfig(deviceId).mode === 'step') step(deviceId);
  });
}

// ── 연속 방식 ───────────────────────────────────────────────────────────

/** 장비마다 마지막으로 낸 속도. 0 이 아닌 동안 유지 신호가 이 값을 이어 보낸다. 0 이면 지운다. */
const jogging = new Map<string, JogVelocity>();
let keepaliveTimer: ReturnType<typeof setInterval> | null = null;

function syncKeepalive(): void {
  if (jogging.size > 0 && keepaliveTimer === null) {
    keepaliveTimer = setInterval(() => {
      for (const [deviceId, velocity] of [...jogging]) {
        keepalive(deviceId, jogParams(velocity), (reason) => {
          if (!jogging.has(deviceId)) return;
          jogging.delete(deviceId);
          drop(deviceId);
          syncKeepalive();
          noteArm(deviceId, 'jog', t('arm.cmd.rejected', { action: 'jog', detail: reason }), 'bad');
        });
      }
    }, JOG_KEEPALIVE_MS);
  } else if (jogging.size === 0 && keepaliveTimer !== null) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}

/** 누르고 있는 키로 속도를 다시 정한다. 바뀌었을 때만 낸다 — 같은 값은 유지 신호가 잇는다. */
function applyJog(deviceId: string): void {
  const velocity = jogVelocity(held.get(deviceId) ?? [], armKeyConfig(deviceId));
  const previous = jogging.get(deviceId) ?? ZERO_JOG;
  if (JSON.stringify(velocity) === JSON.stringify(previous)) return;
  if (isZeroJog(velocity)) jogging.delete(deviceId); else jogging.set(deviceId, velocity);
  syncKeepalive();
  void issue(deviceId, 'jog', jogParams(velocity)).then((outcome) => {
    if (outcome.sent && outcome.accepted !== false) return;
    // 거절 · 못 냄 — 유지 신호를 끊고 누른 키를 놓친 것으로. 노드가 `jog` 를 모르면 여기로 온다.
    jogging.delete(deviceId);
    drop(deviceId);
    syncKeepalive();
    if (!outcome.sent) noteArm(deviceId, 'jog', outcome.message, 'bad');
  });
}

/** 그 장비의 손을 다 놓는다 — 연속 이동 중이었으면 0 을 한 번 보낸다. */
function haltDevice(deviceId: string): void {
  held.delete(deviceId);
  dropped.delete(deviceId);
  if (jogging.has(deviceId)) {
    jogging.delete(deviceId);
    syncKeepalive();
    void issue(deviceId, 'jog', jogParams(ZERO_JOG));
  }
}

// ── 키 ───────────────────────────────────────────────────────────────────

export type ArmKeyInput = { code: string; repeat: boolean; modified: boolean };

/** 키를 눌렀다. **가로챘으면 참** — 부르는 쪽이 `preventDefault` 한다. */
export function armKeyDown(input: ArmKeyInput, typing: boolean): boolean {
  if (state.enabled.size === 0 || input.modified || keyCaptureActive() || typing) return false;
  const meaning = armKeyMeaning(input.code);
  if (meaning === null) return false;
  for (const deviceId of state.enabled) {
    if (meaning.kind === 'stop') {
      // 연속 이동이면 유지 신호부터 끊는다(0 은 안 보낸다 — 바로 뒤의 stop 이 세운다).
      held.delete(deviceId);
      if (jogging.delete(deviceId)) syncKeepalive();
      if (!input.repeat) void issue(deviceId, 'stop');
      continue;
    }
    if (meaning.kind === 'motion') {
      if (input.repeat && dropped.get(deviceId)?.has(meaning.motion) === true) continue;
      dropped.get(deviceId)?.delete(meaning.motion);
      hold(deviceId, meaning.motion);
      if (armKeyConfig(deviceId).mode === 'jog') applyJog(deviceId); else step(deviceId);
      continue;
    }
    if (input.repeat) continue;
    if (armBusy(deviceId) || jogging.has(deviceId)) { noteArm(deviceId, TOOL_COMMAND[meaning.tool].action, t('arm.keys.busy'), 'warn'); continue; }
    const command = TOOL_COMMAND[meaning.tool];
    void issue(deviceId, command.action, command.mode === null ? undefined : { mode: command.mode });
  }
  return true;
}

export function armKeyUp(code: string): void {
  const meaning = armKeyMeaning(code);
  if (meaning?.kind !== 'motion') return;
  for (const set of dropped.values()) set.delete(meaning.motion);
  for (const deviceId of [...held.keys()]) {
    release(deviceId, meaning.motion);
    // 연속 방식은 뗀 순간 속도를 다시 정한다 — 다 뗐으면 0.
    if (state.enabled.has(deviceId) && armKeyConfig(deviceId).mode === 'jog') applyJog(deviceId);
  }
}

/** 창이 포커스를 잃었다 · 탭이 숨었다 — 다 놓는다. 연속 이동은 0 을 보낸다(키를 뗀 소식을 못 받는다). */
function releaseAll(): void {
  for (const deviceId of new Set([...held.keys(), ...jogging.keys()])) haltDevice(deviceId);
  held.clear();
  dropped.clear();
}

/**
 * **상단 비상 정지 — 붙은 로봇팔 전부를 세운다** (261117).
 *
 * 상단 정지(`StopButton`)는 첫 번째 로봇 브로커 하나에 Go1 의 정지(`abort`)를 보낸다. 팔은 그 브로커에 없을 수 있고,
 * 있어도 `abort` 를 모른다(정지 이름이 `stop` 이다). 그래서 정지를 누르면 **그것과 별도로** 팔마다 `stop` 을 낸다.
 * 키보드 연속 이동은 먼저 끊는다 — 0 은 안 보낸다(바로 뒤의 stop 이 세운다).
 *
 * @returns `stop` 을 낸 팔 id.
 */
export function stopAllArms(): readonly string[] {
  // 꺼진 팔도 거르지 않는다 — 정지는 보내서 해로울 것이 없다(브로커가 없으면 `issueArm` 이 안 보내고 그렇게 적는다).
  const arms = deviceCandidates().filter((candidate) => isArmDevice(candidate.actions, candidate.deviceId));
  for (const { deviceId } of arms) {
    held.delete(deviceId);
    dropped.delete(deviceId);
    if (jogging.delete(deviceId)) syncKeepalive();
    void issue(deviceId, 'stop');
  }
  return arms.map((arm) => arm.deviceId);
}

/** 검사용. */
export function resetArmKeys(): void {
  held.clear();
  dropped.clear();
  launching.clear();
  jogging.clear();
  syncKeepalive();
  setState({ enabled: new Set(), configs: {} });
}

// ── 앱에 거는 것 ────────────────────────────────────────────────────────

let started = false;

/** 앱이 살아 있는 동안 한 번 건다(`startManualDispatch` 와 같은 자리). */
export function startArmKeys(): () => void {
  if (started || typeof window === 'undefined') return () => undefined;
  started = true;
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.isComposing) return;
    const claimed = armKeyDown(
      { code: event.code, repeat: event.repeat, modified: event.ctrlKey || event.altKey || event.metaKey },
      isTypingTarget(document.activeElement),
    );
    if (claimed) event.preventDefault();
  };
  const onKeyUp = (event: KeyboardEvent) => armKeyUp(event.code);
  const onVisibility = () => { if (document.visibilityState === 'hidden') releaseAll(); };
  // 걸음 방식 — 걸음이 끝나면 아직 눌린 키로 다음 걸음을 낸다.
  const offEvents = subscribeArmEvents(() => {
    for (const deviceId of [...held.keys()]) if (state.enabled.has(deviceId) && armKeyConfig(deviceId).mode === 'step') step(deviceId);
  });
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', releaseAll);
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    releaseAll();
    offEvents();
    window.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('keyup', onKeyUp);
    window.removeEventListener('blur', releaseAll);
    document.removeEventListener('visibilitychange', onVisibility);
    started = false;
  };
}
