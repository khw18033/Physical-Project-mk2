/**
 * src/physical/armControl.ts (261117 신설 — 로봇팔 MT4 제어 탭)
 *
 * **pi6 `pi/arm/arm_node.py` 가 받는 명령.** 규약의 정본은 그 파일 머리말이다(README 「로봇팔」 절에 요약).
 *
 *   home          원점복귀. Idle · Alarm 일 때
 *   move_joint    j1~j4(도) 중 하나 이상, relative(0/1), speed(≤2000). Idle 일 때. 범위 밖이면 OUT_OF_RANGE
 *   move_cart     x·y·z(mm), a(도) 중 하나 이상, relative, speed. Idle 일 때
 *   jog_joint     joint(1~4), delta_deg(0 제외, ±90). Idle 일 때
 *   pump          mode 0 끔 · 1 흡입 · 2 배출. Idle 일 때
 *   gripper       mode 0 · 1 · 2. Idle 일 때
 *   stop          언제나(잠금 중에도). 감속 정지 → Hold
 *   resume        Hold 일 때만
 *   reset         언제나. 즉시 정지, **위치를 잃어 다시 원점복귀가 필요**
 *
 * 물리 동작은 한 번에 하나다. 동작 중에 끼어드는 것은 `stop` · `reset` 뿐이다.
 *
 * ## 로봇팔인가 — 장비가 말한 것으로 (deviceIdentity §원칙 1)
 *
 * MT4 는 자기를 `actuator` 로 소개한다(`registration.entity_type`). 수문도 `actuator` 라 종류만으로는 못 가른다.
 * 그래서 **팔 동작을 선언했거나**(Capability) **상태 본문에 `arm_state` 를 싣는** 장비를 팔로 본다. Capability 는
 * retained 가 아니라 늦게 붙은 화면은 못 받는 것이 정상이고, `state` 는 5초마다 온다.
 *
 * ## 고르는 규칙 — 수동 제어 탭과 같다
 *
 * 선언 목록을 못 받았으면(`null`) **보내 보고 장비의 거절을 받는다** — 늘 못 받는 목록을 관문으로 두면 탭이 늘 잠긴다.
 * 선언했는데 그 이름이 없으면 안 보낸다. 정지 · 리셋은 늘 보낸다.
 *
 * ## 추적기를 지난다
 *
 * 다른 로봇 명령처럼 `commandTracker.issue` 를 지난다(`verify:single-egress` · `verify:command-through-tracker`).
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { commandTracker } from '../shared/commandCenter.ts';
import type { CommandAck, CommandRequest } from '../transport/index.ts';
import { telemetryValue } from '../shared/deviceTelemetry.ts';
import { deviceCandidates } from './deviceIdentity.ts';
import type { PhysicalAction } from './encode.ts';
import { recordHumanCommand } from './humanCommands.ts';
import { clientForDevice } from './robotClient.ts';
import { robotSession } from './robotSession.ts';
import type { UplinkMessage } from './uplink.ts';

export type ArmAction = Extract<PhysicalAction,
  'home' | 'move_joint' | 'move_cart' | 'jog_joint' | 'pump' | 'gripper' | 'stop' | 'resume' | 'reset' | 'jog'>;

/** 팔을 움직이는 명령. 화면 정지가 걸려 있으면 막는다. */
const MOTION: ReadonlySet<ArmAction> = new Set(['home', 'move_joint', 'move_cart', 'jog_joint', 'pump', 'gripper', 'resume']);
/** 언제나 보내는 것 — 못 멈추는 것보다 낫다. */
const ALWAYS: ReadonlySet<ArmAction> = new Set(['stop', 'reset']);

/** 규약 범위 (arm_node.py 머리말). */
export const JOG_MAX_DEG = 90;
export const SPEED_MAX = 2000;
export const JOINTS = [1, 2, 3, 4] as const;
/**
 * 직교 축. **`a`(손목 회전)는 뺐다** (261117 실측) — `move_cart a=5 relative=1` 이 수락된 뒤 `ABORTED · no_reply: M20G90G00A5`
 * 로 끝났다(펌웨어 MT4,20240820 이 A 축 직교 명령에 답하지 않는다). 손목 회전은 4번 관절(`jog_joint joint=4`)로 한다.
 * 끝점 상태도 `a` 가 아니라 `rx·ry·rz` 로 온다.
 */
export const CART_AXES = ['x', 'y', 'z'] as const;
export type CartAxis = (typeof CART_AXES)[number];

/** 이 장비가 로봇팔인가. 팔 동작을 선언했거나, 상태에 `arm_state` 를 싣는다. */
export function isArmDevice(actions: readonly string[] | null, deviceId: string): boolean {
  if (actions?.some((action) => action === 'jog_joint' || action === 'move_joint' || action === 'move_cart') === true) return true;
  return telemetryValue(deviceId, 'arm_state') !== undefined || telemetryValue(deviceId, 'arm_info') !== undefined;
}

// ── 지금 상태 (장비가 보낸 그대로) ──────────────────────────────────────

export type ArmView = {
  /** GRBL 상태 그대로 — `Idle` · `Alarm` · `Run` · `Hold:0` · `Home` … 못 받았으면 `null`. */
  armState: string | null;
  homed: boolean | null;
  joints: Partial<Record<`j${(typeof JOINTS)[number]}`, number>> | null;
  tcp: Partial<Record<CartAxis, number>> | null;
  pumpPwm: number | null;
  valvePwm: number | null;
  serialOk: boolean | null;
  locked: boolean;
  lockReason: string | null;
  jointRanges: Partial<Record<string, [number, number]>> | null;
};

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const bool = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);

function numbers<K extends string>(value: unknown, keys: readonly K[]): Partial<Record<K, number>> | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const out: Partial<Record<K, number>> = {};
  for (const key of keys) {
    const n = num((value as Record<string, unknown>)[key]);
    if (n !== null) out[key] = n;
  }
  return Object.keys(out).length > 0 ? out : null;
}

export function armView(deviceId: string): ArmView {
  const v = (path: string) => telemetryValue(deviceId, path);
  const ranges = v('joint_ranges_deg');
  return {
    armState: str(v('arm_state')),
    homed: bool(v('homed')),
    joints: numbers(v('joints_deg'), ['j1', 'j2', 'j3', 'j4'] as const),
    tcp: numbers(v('tcp'), CART_AXES),
    pumpPwm: num(v('pump_pwm')),
    valvePwm: num(v('valve_pwm')),
    serialOk: bool(v('serial_ok')),
    locked: v('control_locked') === true,
    lockReason: str(v('lock_reason')),
    jointRanges: ranges !== null && typeof ranges === 'object' && !Array.isArray(ranges) ? ranges as Record<string, [number, number]> : null,
  };
}

/** `Hold:0` 도 Hold 다. */
export const isIdle = (state: string | null) => state === 'Idle';
export const isHold = (state: string | null) => state !== null && state.startsWith('Hold');
export const isAlarm = (state: string | null) => state !== null && state.startsWith('Alarm');

/**
 * 지금 이 명령을 낼 만한가 — 화면이 버튼을 닫는 데 쓴다. **장비 판정을 대신하지 않는다**(장비가 다시 거른다).
 * 상태를 모르면(`null`) 연다 — 보내 보고 거절을 받는다.
 */
export function armReady(action: ArmAction, view: ArmView): boolean {
  if (ALWAYS.has(action)) return true;
  if (view.armState === null) return true;
  if (action === 'home') return isIdle(view.armState) || isAlarm(view.armState);
  if (action === 'resume') return isHold(view.armState);
  return isIdle(view.armState) && !view.locked;
}

// ── 보내기 ──────────────────────────────────────────────────────────────

export type ArmOutcome = {
  sent: boolean;
  commandId: string;
  /** 장비의 `Acceptance`. `null` 은 시한 안에 답이 없었다. */
  accepted: boolean | null;
  message: string;
};

/** 한 장비의 마지막 명령 — 탭을 옮겨도 남는다. */
export type ArmEvent = {
  action: ArmAction;
  commandId: string;
  atMs: number;
  /** 사람이 읽을 한 줄 — 수락 · 거절 · 진행 · 결과. */
  line: string;
  tone: 'ok' | 'warn' | 'bad' | 'info';
  /** `CommandResult.result` — j1~j4 · x·y·z · duration_s · mode · pwm · verified. */
  result: Readonly<Record<string, number>> | null;
  /**
   * **끝났나** — 결과 · 거절 · 무응답이 왔다. 키보드 제어가 이것을 보고 다음 걸음을 낸다(물리 동작은 한 번에 하나).
   * 정지 · 리셋은 수락되면 끝이다. 결과가 영영 안 오면 `BUSY_GIVE_UP_MS` 뒤 끝난 것으로 친다 — 키가 잠긴 채 남지 않게.
   */
  done: boolean;
};

let events: Readonly<Record<string, ArmEvent>> = {};
const listeners = new Set<() => void>();

function setEvent(deviceId: string, event: ArmEvent): void {
  events = { ...events, [deviceId]: event };
  for (const listener of listeners) listener();
}

/** 명령이 아닌 한 줄(막힘 등). 끝난 것으로 적는다. */
export function noteArm(deviceId: string, action: ArmAction, line: string, tone: ArmEvent['tone']): void {
  setEvent(deviceId, { action, commandId: '', atMs: Date.now(), line, tone, result: null, done: true });
}

/** 이 장비에 낸 팔 명령이 아직 안 끝났나. */
export function armBusy(deviceId: string): boolean {
  return events[deviceId]?.done === false;
}

export function subscribeArmEvents(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function patchEvent(deviceId: string, commandId: string, patch: Partial<ArmEvent>): void {
  const current = events[deviceId];
  if (current === undefined || current.commandId !== commandId) return;
  setEvent(deviceId, { ...current, ...patch });
}

export function useArmEvents(): Readonly<Record<string, ArmEvent>> {
  return useSyncExternalStore(subscribeArmEvents, () => events, () => events);
}

const ACCEPT_WAIT_MS = 4000;
/** 결과를 기다리는 한도 — 원점복귀가 가장 길다. */
const RESULT_WAIT_MS = 120_000;
/** 수락 뒤 결과가 이만큼 안 오면 끝난 것으로 친다 — 걸음 하나가 이보다 길지 않다. 원점복귀는 이보다 길 수 있으나 그동안 키는 장비가 거절한다(busy). */
const BUSY_GIVE_UP_MS = 20_000;

/** 알려진 거부 사유는 풀어 쓴다. `control_locked:<사유>` 처럼 꼬리가 붙는 것은 앞만 본다. */
// `UNIMPLEMENTED` — 노드에 없는 action(261117 실측: `jog` → `UNIMPLEMENTED · action not supported`).
const KNOWN_REJECTS = ['not_homed', 'on_hold', 'busy', 'control_locked', 'serial_lost', 'OUT_OF_RANGE', 'UNIMPLEMENTED'] as const;

function rejectText(code: string | null, message: string | null): string {
  for (const raw of [message, code]) {
    if (raw === null) continue;
    const head = raw.trim().split(':')[0];
    const known = KNOWN_REJECTS.find((name) => name === head);
    if (known !== undefined) return `${t(`arm.reject.${known}`)} (${raw.trim()})`;
  }
  return [code, message].filter((value) => value).join(' ') || t('robot.noReason');
}

/** 진행 detail — 단계 이름이거나 JSON(`{"phase":"moving","arm_state":"Run",…}`). */
function progressText(message: Extract<UplinkMessage, { kind: 'status' }>): string {
  try {
    const parsed: unknown = JSON.parse(message.raw);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const body = parsed as Record<string, unknown>;
      const parts = [str(body.phase), str(body.arm_state), num(body.elapsed_s) === null ? null : `${num(body.elapsed_s)!.toFixed(1)}s`];
      return parts.filter((part) => part !== null).join(' · ') || message.state;
    }
  } catch {
    // 단계 이름(executing · accepted_by_controller · state_changed)이다 — 그대로 적는다.
  }
  return message.raw || message.state;
}

const refuse = (message: string): ArmOutcome => ({ sent: false, commandId: '', accepted: null, message });

/**
 * 팔 명령 하나. 추적기를 지나 보내고 `Acceptance` 를 기다린다. 받았으면 진행 · 결과를 마지막 명령 칸에 이어 적는다.
 */
export async function issueArm(deviceId: string, action: ArmAction, parameters?: Record<string, number>): Promise<ArmOutcome> {
  const client = clientForDevice(deviceId);
  if (client === null || client.getStatus().state !== 'open') return refuse(t('arm.link.noBroker'));
  const actions = deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null;
  if (!ALWAYS.has(action) && actions !== null && !actions.includes(action)) return refuse(t('arm.cmd.notDeclared', { action }));
  // 연속 조그는 0(세우기)이 아니면 움직이는 명령이다. 0 은 언제나 낸다 — 세우는 쪽이다.
  const moving = MOTION.has(action) || (action === 'jog' && Object.entries(parameters ?? {}).some(([key, value]) => key !== 'hold_ms' && value !== 0));
  if (moving && robotSession().stopped !== null) return refuse(t('arm.cmd.screenStopped'));

  // 귀를 먼저 연다 — 빠른 응답을 놓치지 않게.
  const seen: UplinkMessage[] = [];
  let wake: (() => void) | null = null;
  let commandId = '';
  const off = client.onMessage((message) => {
    seen.push(message);
    wake?.();
    if (commandId === '' || message.commandId !== commandId) return;
    if (message.kind === 'status') patchEvent(deviceId, commandId, { line: t('arm.event.progress', { action, detail: progressText(message) }), tone: 'info' });
    if (message.kind === 'result') {
      // 종료 상태는 이름으로 온다 — `SUCCEEDED` · `ABORTED` … (`uplink.ts`)
      const ok = message.status === 'SUCCEEDED';
      const detail = message.code === null && message.message === null ? message.status : rejectText(message.code, message.message);
      patchEvent(deviceId, commandId, {
        line: ok ? t('arm.event.done', { action }) : t('arm.event.failed', { action, detail }),
        tone: ok ? 'ok' : 'bad',
        result: message.result,
        done: true,
      });
      stopListening();
    }
  });
  let listening = true;
  const stopListening = () => { if (listening) { listening = false; off(); } };

  try {
    await commandTracker.issue(
      deviceId,
      { action, label: action, targetPct: 0, irreversible: action === 'reset', resultingState: '' },
      {
        params: { ...(parameters ?? {}) },
        actionLayer: true,
        publish: async (request: CommandRequest): Promise<CommandAck> => {
          const outcome = client.send(action, parameters);
          commandId = outcome.sent ? outcome.commandId : '';
          if (outcome.sent) recordHumanCommand(client, { commandId, deviceId, action, parameters: parameters ?? {}, requestId: request.client_request_id });
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
  } catch (error) {
    stopListening();
    return refuse(error instanceof Error ? error.message : t('robot.notSent'));
  }
  if (commandId === '') { stopListening(); return refuse(t('robot.notSent')); }
  setEvent(deviceId, { action, commandId, atMs: Date.now(), line: t('arm.event.sent', { action }), tone: 'info', result: null, done: false });

  const deadline = Date.now() + ACCEPT_WAIT_MS;
  for (;;) {
    const answer = seen.find((m) => m.commandId === commandId && m.kind === 'acceptance');
    if (answer !== undefined && answer.kind === 'acceptance') {
      if (!answer.accepted) {
        stopListening();
        const message = t('arm.cmd.rejected', { action, detail: rejectText(answer.code, answer.message) });
        patchEvent(deviceId, commandId, { line: message, tone: 'bad', done: true });
        return { sent: true, commandId, accepted: false, message };
      }
      // 결과가 먼저 와 있으면 그 줄을 덮지 않는다.
      if (!seen.some((m) => m.commandId === commandId && m.kind === 'result')) {
        // 정지 · 리셋은 수락이 곧 끝이다 — 그 뒤의 키를 막지 않는다.
        patchEvent(deviceId, commandId, { line: t('arm.cmd.accepted', { action }), tone: 'ok', ...(MOTION.has(action) ? {} : { done: true }) });
      }
      setTimeout(() => patchEvent(deviceId, commandId, { done: true }), BUSY_GIVE_UP_MS);
      setTimeout(stopListening, RESULT_WAIT_MS);
      return { sent: true, commandId, accepted: true, message: t('arm.cmd.accepted', { action }) };
    }
    const left = deadline - Date.now();
    if (left <= 0) break;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, left);
      wake = () => { clearTimeout(timer); resolve(); };
    });
    wake = null;
  }
  setTimeout(stopListening, RESULT_WAIT_MS);
  const message = t('arm.cmd.noAnswer', { action, sec: ACCEPT_WAIT_MS / 1000 });
  patchEvent(deviceId, commandId, { line: message, tone: 'warn', done: true });
  return { sent: true, commandId, accepted: null, message };
}
