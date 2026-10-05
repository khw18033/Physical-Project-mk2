/**
 * src/physical/manualDispatch.ts (261005 신설 — 하드웨어 카드 · 로봇 수동 제어)
 *
 * **키를 받아 수동 제어 명령을 낸다.** 키 처리기는 앱에 **하나**이고 앱 수명과 같다 — 카드 창에
 * 붙이면 창을 닫는 순간 제어가 끊긴다. 카드를 닫고 카메라 화면을 보면서 몰 수 있어야 한다(지시 ④).
 *
 * ## 키가 명령이 되지 않는 때 (지시 ⑦)
 *
 *   꺼짐        그 장비의 수동 제어가 꺼져 있다 — 키를 아예 안 가로챈다
 *   입력 중     글 칸(input · textarea · select · contenteditable)에 포커스가 있다 — 키를 안 가로챈다
 *   자동 제어   임무가 그 장비를 몰고 있다(`autoDrivenDevices` · 옛 단일 로봇 임무)
 *   연결 없음   그 장비의 브로커 소켓이 열려 있지 않다
 *
 * 조합 키(Ctrl · Alt · ⌘)가 눌려 있으면 늘 통과시킨다 — Ctrl+C 가 로봇 명령이 되면 안 된다.
 * 명령이 될 키만 `preventDefault` 한다. 방향키가 페이지를 굴리지 않게 하되, 막힌 동안의 「입력 중」은
 * 건드리지 않는다 — 그건 글자를 치는 키다.
 *
 * ## 여러 대 (지시 ⑥)
 *
 * 켜진 장비마다 따로 푼다. 같은 키를 둘이 쓰면 **둘 다 움직인다** — 막지 않고 알림에서 경고한다
 * (261005 지시). 발행은 장비마다 그 장비의 브로커로 나간다(`clientForDevice`).
 *
 * ## 기록 — 추적기를 지난다
 *
 * 키 한 번 · 속도가 바뀐 순간 · 세운 순간은 `commandTracker.issue` 를 지난다(`inputMode: 'keyboard'`).
 * 사람이 누른 명령이라 `human` 기록이 맞다. **속도 모드의 유지 신호(200ms 마다 같은 값)는 추적기를 안 지난다**
 * — 이미 기록한 명령을 이어 보내는 것이고, 매번 적으면 실행 기록이 초당 다섯 줄씩 찬다. `ping` 이 추적기를
 * 안 지나는 것과 같은 자리다.
 *
 * ## 속도 모드에서 세우는 때
 *
 * 키를 다 뗐다 · 창이 포커스를 잃었다 · 탭이 숨었다 · 수동 제어를 껐다 · 글 칸에 들어갔다 · 연결이 끊겼다 →
 * 0 을 한 번 보낸다. **자동 제어가 시작됐을 때는 0 을 안 보낸다** — 임무가 낸 이동을 우리 0 이 세울 수 있다.
 * 유지 신호만 끊고, 장비가 `TELEOP_HOLD_MS` 뒤 스스로 수동 이동을 접는다.
 *
 * ## 장비의 거절을 알림에 올린다 (261005 — pi7 답신)
 *
 * 화면은 응답을 기다리지 않고 내지만, 거절은 늘 `Acceptance` 로 온다. 그것을 받아 알림 줄에 적는다 — 안 적으면
 * 「눌렀는데 안 움직인다」만 남는다. pi7 이 정한 사유 둘은 풀어 쓴다.
 *
 *   mission_in_progress      임무가 도는 중이다. teleop 은 0 이어도 거절된다 — 그래서 우리 0 이 임무를 못 세운다
 *   teleop_halted_by_abort   정지 직후다. 0 을 받거나 1초 동안 안 오면 다시 받는다 — 정지 뒤 키를 누른 채라 다시 걷는 것을 막는다
 *
 * teleop 이 거절되면 그 장비의 유지 신호를 끊는다. 누른 채로 계속 보내 봐야 다 거절이고, 다시 받게 하려면
 * 키를 다시 누르는 것이 사람의 뜻과 맞다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { commandTracker } from '../shared/commandCenter.ts';
import type { CommandAck, CommandRequest } from '../transport/index.ts';
import { deviceCandidates } from './deviceIdentity.ts';
import { declaredAction, type DeclaredAction, type PhysicalAction } from './encode.ts';
import {
  enabledManualDevices, isZero, keyCaptureActive, keyMeaning, manualConfig, manualEnabled, manualModeOf,
  motionSupport, stepCommand, subscribeManual, velocityOf, ZERO_VELOCITY,
  type KeyMeaning, type ManualMotion, type Velocity,
} from './manualControl.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { STOP_ACTION, STOP_REASON, TELEOP_ACTION, TELEOP_HOLD_MS, TELEOP_KEEPALIVE_MS } from './presets.ts';
import { clientForDevice } from './robotClient.ts';
import { runningTaskId } from './robotSession.ts';
import { autoDrivenDevices } from './taskRunner.ts';

/** `onMessage` 가 없는 소켓(검사의 흉내)은 거절을 못 듣는다 — 낼 수는 있다. */
type ClientLike = Pick<PhysicalClient, 'getStatus' | 'send'> & Partial<Pick<PhysicalClient, 'onMessage'>>;

export type ManualBlock = 'typing' | 'auto' | 'offline';

/** 그 장비에 마지막으로 일어난 일 — 알림 줄이 적는다. */
export type ManualEvent =
  | { kind: 'sent'; action: string; parameters: Record<string, number>; atMs: number }
  | { kind: 'failed'; action: string; reason: string; atMs: number }
  | { kind: 'rejected'; action: string; code: string | null; message: string | null; atMs: number }
  | { kind: 'blocked'; block: ManualBlock | 'unsupported' | 'undeclared'; atMs: number };

// ── 바꿔 끼울 수 있는 것 — 검사가 소켓 · 포커스 · 임무를 흉내 낸다 ─────────────────────────

let lookup: (deviceId: string) => ClientLike | null = clientForDevice;
let typingProbe: () => boolean = () => (typeof document === 'undefined' ? false : isTypingTarget(document.activeElement));
let autoProbe: (deviceId: string) => boolean = (deviceId) => autoDrivenDevices().has(deviceId) || runningTaskId() !== null;

/** 검사용. 화면에서는 부르지 않는다. `null` 을 주면 원래 것으로 돌아간다. */
export function setManualProbes(probes: {
  client?: ((deviceId: string) => ClientLike | null) | null;
  typing?: (() => boolean) | null;
  auto?: ((deviceId: string) => boolean) | null;
}): void {
  if (probes.client !== undefined) lookup = probes.client ?? clientForDevice;
  if (probes.typing !== undefined) typingProbe = probes.typing ?? (() => (typeof document === 'undefined' ? false : isTypingTarget(document.activeElement)));
  if (probes.auto !== undefined) autoProbe = probes.auto ?? ((deviceId) => autoDrivenDevices().has(deviceId) || runningTaskId() !== null);
}

/**
 * **글을 치는 자리인가.** 체크박스 · 버튼도 `input` 이지만 걸러 내지 않는다 — 슬라이더(`range`)는 방향키를,
 * 체크박스는 Space 를 먹는다. 포커스가 거기 있으면 사람은 그 칸을 만지는 중이다.
 */
export function isTypingTarget(element: { tagName?: string; isContentEditable?: boolean } | null): boolean {
  if (element === null || element === undefined) return false;
  const tag = (element.tagName ?? '').toUpperCase();
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable === true;
}

/**
 * 「임무가 그 장비를 모는가」. 판(`taskRunner`)은 장비를 안다. 옛 단일 로봇 임무(`robotSession`)는 명령에 장비가
 * 안 실려 있어 **어느 로봇인지 모른다** — 그 판이 명령을 내는 동안은 로봇 전부를 막는다. 엉뚱한 로봇을 풀어 두는
 * 것보다 하나를 더 막는 편이 낫다.
 */
export function manualBlock(deviceId: string): ManualBlock | null {
  if (typingProbe()) return 'typing';
  if (autoProbe(deviceId)) return 'auto';
  const client = lookup(deviceId);
  if (client === null || client.getStatus().state !== 'open') return 'offline';
  return null;
}

function factsOf(deviceId: string): readonly string[] | null {
  return deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null;
}

// ── 일어난 일 ─────────────────────────────────────────────────────────────────

let events: Readonly<Record<string, ManualEvent>> = {};
const eventListeners = new Set<() => void>();

function note(deviceId: string, event: ManualEvent): void {
  events = { ...events, [deviceId]: event };
  for (const listener of eventListeners) listener();
}

export function manualEvents(): Readonly<Record<string, ManualEvent>> {
  return events;
}

export function useManualEvents(): Readonly<Record<string, ManualEvent>> {
  return useSyncExternalStore((listener) => {
    eventListeners.add(listener);
    return () => eventListeners.delete(listener);
  }, () => events);
}

// ── 장비의 거절 ───────────────────────────────────────────────────────────────

/** 우리가 낸 수동 명령 — 거절이 오면 어느 장비 · 어느 동작인지 찾는다. 오래된 것은 버린다. */
const pending = new Map<string, { deviceId: string; action: string; atMs: number }>();
const PENDING_KEEP_MS = 5000;
const listening = new WeakSet<object>();

function watch(client: ClientLike, deviceId: string, action: string, commandId: string): void {
  const now = Date.now();
  for (const [id, sent] of pending) if (now - sent.atMs > PENDING_KEEP_MS) pending.delete(id);
  pending.set(commandId, { deviceId, action, atMs: now });
  if (client.onMessage === undefined || listening.has(client)) return;
  listening.add(client);
  // 소켓 하나에 한 번 건다. 소켓은 앱 수명과 같다(`syncRobotClients`).
  client.onMessage((message) => {
    if (message.kind !== 'acceptance' || message.accepted) return;
    const sent = pending.get(message.commandId);
    if (sent === undefined) return;
    pending.delete(message.commandId);
    note(sent.deviceId, { kind: 'rejected', action: sent.action, code: message.code, message: message.message, atMs: Date.now() });
    if (sent.action === TELEOP_ACTION) halt(sent.deviceId, false);
  });
}

// ── 내기 ─────────────────────────────────────────────────────────────────────

/**
 * 추적기를 지나 한 건. 대상은 장비가 밝힌 id 이고, 실제 발행 대상은 `PhysicalClient.send` 가 그 소켓의 장비로
 * 다시 정한다. 추적기는 `publish` 를 기다림 없이 바로 부르므로 **누른 순서대로 나간다** — 속도 0 이 앞 명령보다
 * 먼저 나가는 일이 없다.
 */
function issue(deviceId: string, client: ClientLike, action: PhysicalAction | DeclaredAction, parameters: Record<string, number>): void {
  void commandTracker.issue(
    deviceId,
    { action, label: action, targetPct: 0, irreversible: false, resultingState: '' },
    {
      params: { ...parameters },
      inputMode: 'keyboard',
      publish: async (request: CommandRequest): Promise<CommandAck> => {
        const outcome = client.send(action, parameters);
        if (outcome.sent) watch(client, deviceId, action, outcome.commandId);
        note(deviceId, outcome.sent
          ? { kind: 'sent', action, parameters, atMs: Date.now() }
          : { kind: 'failed', action, reason: outcome.reason ?? t('robot.notSent'), atMs: Date.now() });
        return {
          clientRequestId: request.client_request_id,
          commandId: outcome.sent ? outcome.commandId : null,
          accepted: outcome.sent,
          reasonCode: outcome.sent ? null : 'physical_not_connected',
          message: outcome.sent ? t('robot.published') : (outcome.reason ?? t('robot.notSent')),
        };
      },
    },
  );
}

// ── 속도 모드 ─────────────────────────────────────────────────────────────────

const held = new Map<string, Set<ManualMotion>>();
const lastVelocity = new Map<string, Velocity>();
let keepalive: ReturnType<typeof setInterval> | null = null;

function teleopParams(velocity: Velocity): Record<string, number> {
  return { vx: velocity.vx, vy: velocity.vy, vyaw: velocity.vyaw, hold_ms: TELEOP_HOLD_MS };
}

function applyVelocity(deviceId: string, client: ClientLike): void {
  const next = velocityOf(held.get(deviceId) ?? [], manualConfig(deviceId).speed);
  const previous = lastVelocity.get(deviceId) ?? ZERO_VELOCITY;
  if (next.vx === previous.vx && next.vy === previous.vy && next.vyaw === previous.vyaw) return;
  issue(deviceId, client, TELEOP_ACTION, teleopParams(next));
  if (isZero(next)) lastVelocity.delete(deviceId);
  else lastVelocity.set(deviceId, next);
  syncKeepalive();
}

/** 세운다. `sendZero` 가 거짓이면 유지 신호만 끊는다(자동 제어가 넘겨받았을 때). */
function halt(deviceId: string, sendZero: boolean): void {
  held.delete(deviceId);
  if (!lastVelocity.has(deviceId)) return;
  lastVelocity.delete(deviceId);
  const client = lookup(deviceId);
  if (sendZero && client !== null && client.getStatus().state === 'open') issue(deviceId, client, TELEOP_ACTION, teleopParams(ZERO_VELOCITY));
  syncKeepalive();
}

/** 움직이는 장비 전부를 세운다 — 창이 포커스를 잃었다 · 탭이 숨었다 · 키를 받아 적기 시작했다. */
export function haltAllManual(): void {
  for (const deviceId of [...held.keys(), ...lastVelocity.keys()]) halt(deviceId, true);
}

function syncKeepalive(): void {
  if (lastVelocity.size > 0 && keepalive === null) keepalive = setInterval(keepaliveTick, TELEOP_KEEPALIVE_MS);
  if (lastVelocity.size === 0 && keepalive !== null) {
    clearInterval(keepalive);
    keepalive = null;
  }
}

/** 유지 신호 한 번. 그 사이 막혔으면 세운다. 검사가 시계 없이 부를 수 있게 내보낸다. */
export function keepaliveTick(): void {
  for (const [deviceId, velocity] of [...lastVelocity]) {
    if (!manualEnabled(deviceId)) { halt(deviceId, true); continue; }
    const block = manualBlock(deviceId);
    if (block !== null) {
      note(deviceId, { kind: 'blocked', block, atMs: Date.now() });
      halt(deviceId, block !== 'auto');
      continue;
    }
    const client = lookup(deviceId);
    /**
     * **누른 채로 탭에서 속도를 바꿨으면** 새 값으로 — 바뀐 순간이라 추적기를 지난다(`applyVelocity`).
     * 같으면 그대로 유지 신호다.
     */
    const wanted = velocityOf(held.get(deviceId) ?? [], manualConfig(deviceId).speed);
    if (client !== null && (wanted.vx !== velocity.vx || wanted.vy !== velocity.vy || wanted.vyaw !== velocity.vyaw)) {
      applyVelocity(deviceId, client);
      continue;
    }
    const outcome = client?.send(TELEOP_ACTION, teleopParams(velocity));
    if (client !== null && client !== undefined && outcome?.sent === true) watch(client, deviceId, TELEOP_ACTION, outcome.commandId);
  }
}

// ── 키 ───────────────────────────────────────────────────────────────────────

export type KeyInput = {
  code: string;
  repeat: boolean;
  /** Ctrl · Alt · ⌘ 중 하나라도. Shift 는 안 친다 — 키 자리(`code`)는 Shift 와 무관하다. */
  modified: boolean;
};

/**
 * 키를 눌렀다. **가로챘으면 참**이다 — 부르는 쪽이 `preventDefault` 한다.
 * 막힌 장비의 키도 가로챈다(입력 중만 빼고) — 몰려던 키가 화면을 굴리면 안 된다.
 */
export function manualKeyDown(input: KeyInput): boolean {
  if (keyCaptureActive() || input.modified) return false;
  let claimed = false;
  const typing = typingProbe();
  for (const deviceId of enabledManualDevices()) {
    const config = manualConfig(deviceId);
    const meaning = keyMeaning(config, input.code);
    if (meaning === null || typing) continue;
    claimed = true;
    if (input.repeat) continue;
    const block = manualBlock(deviceId);
    if (block !== null) { note(deviceId, { kind: 'blocked', block, atMs: Date.now() }); continue; }
    act(deviceId, meaning);
  }
  return claimed;
}

function act(deviceId: string, meaning: KeyMeaning): void {
  const client = lookup(deviceId);
  if (client === null) return;
  const actions = factsOf(deviceId);
  if (meaning.kind === 'stop') {
    halt(deviceId, false);
    issue(deviceId, client, STOP_ACTION, { reason: STOP_REASON.human });
    return;
  }
  if (meaning.kind === 'extra') {
    const action = declaredAction(actions, meaning.action);
    if (action === null) { note(deviceId, { kind: 'blocked', block: 'undeclared', atMs: Date.now() }); return; }
    issue(deviceId, client, action, {});
    return;
  }
  if (motionSupport(actions, meaning.motion) === 'no') {
    note(deviceId, { kind: 'blocked', block: 'unsupported', atMs: Date.now() });
    return;
  }
  if (manualModeOf(actions) === 'velocity') {
    const set = held.get(deviceId) ?? new Set<ManualMotion>();
    set.add(meaning.motion);
    held.set(deviceId, set);
    applyVelocity(deviceId, client);
    return;
  }
  const command = stepCommand(meaning.motion, manualConfig(deviceId));
  if (command !== null) issue(deviceId, client, command.action, command.parameters);
}

/** 키를 뗐다. 속도 모드의 그 동작을 뺀다 — 막혀 있어도 뺀다(떼는 것은 늘 세우는 쪽이다). */
export function manualKeyUp(code: string): void {
  for (const [deviceId, set] of [...held]) {
    const meaning = keyMeaning(manualConfig(deviceId), code);
    if (meaning?.kind !== 'motion' || !set.delete(meaning.motion)) continue;
    const client = lookup(deviceId);
    if (client === null) { halt(deviceId, false); continue; }
    applyVelocity(deviceId, client);
  }
}

/** 검사용. 화면에서는 부르지 않는다. */
export function resetManualDispatch(): void {
  held.clear();
  lastVelocity.clear();
  syncKeepalive();
  events = {};
  pending.clear();
  for (const listener of eventListeners) listener();
}

// ── 앱에 거는 것 ─────────────────────────────────────────────────────────────

let started = false;

/** 앱이 살아 있는 동안 한 번 건다(`startTaskRunner` 와 같은 자리). */
export function startManualDispatch(): () => void {
  if (started || typeof window === 'undefined') return () => undefined;
  started = true;
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing) return;
    const claimed = manualKeyDown({ code: event.code, repeat: event.repeat, modified: event.ctrlKey || event.altKey || event.metaKey });
    if (claimed) event.preventDefault();
  };
  const onKeyUp = (event: KeyboardEvent) => manualKeyUp(event.code);
  const onBlur = () => haltAllManual();
  const onVisibility = () => { if (document.visibilityState === 'hidden') haltAllManual(); };
  // 끈 장비 · 키를 받아 적기 시작한 순간에 세운다 — 다음 유지 신호(200ms)까지 기다리지 않는다.
  const offManual = subscribeManual(() => {
    if (keyCaptureActive()) haltAllManual();
    for (const deviceId of [...lastVelocity.keys()]) if (!manualEnabled(deviceId)) halt(deviceId, true);
  });
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', onBlur);
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    haltAllManual();
    offManual();
    window.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('keyup', onKeyUp);
    window.removeEventListener('blur', onBlur);
    document.removeEventListener('visibilitychange', onVisibility);
    started = false;
  };
}
