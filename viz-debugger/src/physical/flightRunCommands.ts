/**
 * src/physical/flightRunCommands.ts (261014 신설 — 드론 비행 제어 탭)
 *
 * **pi3 실행기에 보내는 세 명령** — 시작(`rtk_test_start`) · 중단(`rtk_test_stop`) · 비상(`rtk_test_emergency`).
 * 규약은 `261014_드론비행실행기_요청_VZ.md` §2 이고, 봉투는 기존 `PhysicalCommandEnvelope.Command` 그대로다.
 *
 * ## 고르는 규칙 — `sarCommands.ts` 와 같다
 *
 *   시작   장비가 `Capability` 에 **선언해야** 보낸다. 모르는데 비행을 시작시키지 않는다.
 *          화면 정지(`robotSession().stopped`)가 걸려 있으면 막는다.
 *   중단 · 비상   선언했거나 **모르면 보낸다** — 못 멈추는 것보다 낫다. 선언 안 했다고 밝혔으면 조종기로.
 *
 * 대상은 카드가 고른 장비이고, 소켓은 그 장비가 자기를 밝힌 브로커다(`clientForDevice`) — 드론이 둘이어도 안 섞인다.
 *
 * ## 추적기를 지난다
 *
 * 다른 로봇 명령처럼 `commandTracker.issue` 를 지난다(`verify:single-egress` · `verify:command-through-tracker`).
 *
 * ## dry-run 을 지나야 비행이 열린다
 *
 * 같은 설정(`planSignature`)으로 보낸 dry-run 이 **종료 코드 0** 으로 끝났을 때만 비행 버튼이 열린다. 짝은
 * 실행기가 상태 토픽에 되돌려 주는 `command_id` 로 맞춘다 — 다른 사람이 보낸 dry-run 을 내 것으로 치지 않는다.
 * 페이지를 새로 열면 잊는다(다시 dry-run).
 */

import { t } from '../i18n/dict.ts';
import { commandTracker } from '../shared/commandCenter.ts';
import { recordHumanCommand } from './humanCommands.ts';
import type { CommandAck, CommandRequest } from '../transport/index.ts';
import { deviceCandidates } from './deviceIdentity.ts';
import type { PhysicalAction } from './encode.ts';
import { EMERGENCY_CODE, planSignature, scriptFor, startParams, type EmergencyMode, type FlightPlan } from './flightPlan.ts';
import type { FlightRunEntry } from './flightRunFeed.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { clientForDevice } from './robotClient.ts';
import { robotSession } from './robotSession.ts';
import { deviceTelemetry, isTelemetryStale, telemetryValue } from '../shared/deviceTelemetry.ts';
import { isRtcmReportStale, rtcmReports } from '../shared/rtcmStatus.ts';
import type { UplinkMessage } from './uplink.ts';

export const RTK_TEST_START: PhysicalAction = 'rtk_test_start';
export const RTK_TEST_STOP: PhysicalAction = 'rtk_test_stop';
export const RTK_TEST_EMERGENCY: PhysicalAction = 'rtk_test_emergency';

export type FlightSupport = 'yes' | 'no' | 'unknown';

export type FlightLink = {
  client: PhysicalClient | null;
  deviceId: string;
  start: FlightSupport;
  stop: FlightSupport;
  emergency: FlightSupport;
  /** 소켓을 못 찾은 사유(이미 푼 글자). 찾았으면 빈칸. */
  reason: string;
};

function supportOf(actions: readonly string[] | null, action: string): FlightSupport {
  if (actions === null) return 'unknown';
  return actions.includes(action) ? 'yes' : 'no';
}

/** 이 장비에 보낼 길. 소켓이 없으면 셋 다 `no` 다 — 보낼 데가 없다. */
export function flightLink(deviceId: string): FlightLink {
  const client = clientForDevice(deviceId);
  if (client === null || client.getStatus().state !== 'open') {
    return { client: null, deviceId, start: 'no', stop: 'no', emergency: 'no', reason: t('flight.link.noBroker') };
  }
  const actions = deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null;
  return {
    client,
    deviceId,
    start: supportOf(actions, RTK_TEST_START),
    stop: supportOf(actions, RTK_TEST_STOP),
    emergency: supportOf(actions, RTK_TEST_EMERGENCY),
    reason: '',
  };
}

// ── 어느 스크립트로 날까 (261022) ────────────────────────────────────────

export type ScriptGuess = {
  /** 실행기 기준으로 RTK 인가(보정 유입 또는 FC 가 이미 RTK). 모르면 `null`. */
  corrections: boolean | null;
  /** 그러면 실행기가 띄울 스크립트. 모르면 `null`. */
  script: string | null;
};

/** 실행기 `rtk_connected()` 가 RTK 로 치는 FC fix (REPORT_pi3_261022 §6). */
const RTK_FIXES = new Set(['RTK_FLOAT', 'RTK_FIXED']);

/**
 * **실행기가 고를 스크립트를 미리 짐작한다.** 실행기 판정(`rtk_connected()`)을 그대로 옮겼다 — 드론 `state.rtk` 는
 * 실행기가 보는 것과 같은 `DroneLink.snapshot()` 이고, `corrections` 이거나 `fix` 가 RTK_FLOAT/FIXED 면 RTK 판이다.
 * `state.rtk` 가 없으면 보정 전달기의 `rtcm` 보고(`receiving`)로 물러선다. 둘 다 낡았거나 없으면 모른다.
 * 정하는 것은 실행기이고(시작 명령을 받은 순간), 실제로 띄운 것은 `flight_run.run.script` 로 돌아온다.
 */
export function scriptGuess(deviceId: string, nowMs = Date.now()): ScriptGuess {
  const report = deviceTelemetry(deviceId);
  const rtk = telemetryValue(deviceId, 'rtk');
  let corrections: boolean | null = null;
  if (report !== null && !isTelemetryStale(report, nowMs) && rtk !== null && typeof rtk === 'object' && !Array.isArray(rtk)) {
    const { corrections: flowing, fix } = rtk as Record<string, unknown>;
    corrections = flowing === true || (typeof fix === 'string' && RTK_FIXES.has(fix));
  } else if (report !== null && !isTelemetryStale(report, nowMs) && rtk === null && telemetryValue(deviceId, 'fc_link') === false) {
    corrections = false; // FC 링크가 없으면 실행기는 `test_sar.py` 로 간다
  } else {
    const rtcm = rtcmReports()[deviceId];
    if (rtcm !== undefined && !isRtcmReportStale(rtcm, nowMs)) corrections = rtcm.receiving;
  }
  return { corrections, script: scriptFor(corrections) };
}

/** 실행이 실제로 쓴 스크립트. 이 칸이 없던 실행기는 늘 `test_sar_rtk.py` 였다. */
export function scriptOf(run: FlightRunEntry['run']): string | null {
  if (run === null) return null;
  return run.script ?? 'test_sar_rtk.py';
}

export type FlightIssueOutcome = {
  sent: boolean;
  commandId: string;
  /** 장비의 `Acceptance`. `null` 은 시한 안에 답이 없었다. */
  accepted: boolean | null;
  code: string | null;
  message: string;
};

/** 실행기는 프로세스를 띄운 뒤 답한다 — 핑보다 넉넉히. */
const ACCEPT_WAIT_MS = 6000;

async function issue(
  link: FlightLink,
  action: PhysicalAction,
  parameters: Record<string, number> | undefined,
  irreversible: boolean,
): Promise<FlightIssueOutcome> {
  const client = link.client;
  if (client === null) return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('flight.link.noBroker') };

  // 귀를 먼저 연다 — 빠른 응답을 놓치지 않게(`issueSar` 와 같은 이유).
  const seen: UplinkMessage[] = [];
  let wake: (() => void) | null = null;
  const off = client.onMessage((message) => { seen.push(message); wake?.(); });

  let commandId = '';
  try {
    await commandTracker.issue(
      link.deviceId,
      { action, label: action, targetPct: 0, irreversible, resultingState: '' },
      {
        params: { ...(parameters ?? {}) },
        // **액션 층이 적는다** (261023) — 명령이라 액션 층, 사람이 냈으니 주체 human. 사람 층에는 안 적는다.
        actionLayer: true,
        publish: async (request: CommandRequest): Promise<CommandAck> => {
          const outcome = client.send(action, parameters);
          commandId = outcome.sent ? outcome.commandId : '';
          if (outcome.sent) recordHumanCommand(client, { commandId, deviceId: link.deviceId, action, parameters: parameters ?? {}, requestId: request.client_request_id });
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
    if (commandId === '') return { sent: false, commandId: '', accepted: null, code: null, message: t('robot.notSent') };
    const deadline = Date.now() + ACCEPT_WAIT_MS;
    for (;;) {
      const answer = seen.find((m) => m.commandId === commandId && m.kind === 'acceptance');
      if (answer !== undefined && answer.kind === 'acceptance') {
        return {
          sent: true, commandId, accepted: answer.accepted, code: answer.code,
          message: answer.accepted
            ? t('flight.cmd.accepted', { action })
            : t('flight.cmd.rejected', { action, detail: rejectText(answer.code, answer.message) }),
        };
      }
      const left = deadline - Date.now();
      if (left <= 0) break;
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, left);
        wake = () => { clearTimeout(timer); resolve(); };
      });
      wake = null;
    }
    return { sent: true, commandId, accepted: null, code: null, message: t('flight.cmd.noAnswer', { action, sec: ACCEPT_WAIT_MS / 1000 }) };
  } finally {
    off();
  }
}

/** 실행기가 정한 사유(요청 문서 §2)는 풀어 쓰고, 모르는 것은 장비가 준 그대로. */
const KNOWN_REJECTS = new Set(['already_running', 'not_running', 'not_confirmed']);

function rejectText(code: string | null, message: string | null): string {
  const known = [message, code].find((value) => value !== null && KNOWN_REJECTS.has(value.trim()));
  if (known != null) return t(`flight.reject.${known.trim()}`);
  return [code, message].filter((value) => value).join(' ') || t('robot.noReason');
}

// ── dry-run 짝 ──────────────────────────────────────────────────────────

const dryRuns = new Map<string, { commandId: string; signature: string }>();

/**
 * 이 설정으로 내가 보낸 dry-run 이 **종료 코드 0** 으로 끝났나. 실행기가 되돌려 준 `command_id` 가 내 것이어야 한다.
 */
export function dryRunPassed(deviceId: string, plan: FlightPlan, entry: FlightRunEntry | undefined): boolean {
  const mine = dryRuns.get(deviceId);
  const run = entry?.run ?? null;
  if (mine === undefined || run === null) return false;
  return mine.signature === planSignature(plan) && run.commandId === mine.commandId
    && run.dryRun !== false && run.state === 'exited' && run.exitCode === 0;
}

/** 이 설정으로 보낸 dry-run 이 아직 기다리는 중인가(보냈는데 결과가 안 왔다). */
export function dryRunPending(deviceId: string, plan: FlightPlan, entry: FlightRunEntry | undefined): boolean {
  const mine = dryRuns.get(deviceId);
  if (mine === undefined || mine.signature !== planSignature(plan)) return false;
  const run = entry?.run ?? null;
  return run === null || run.commandId !== mine.commandId || run.state === 'running';
}

export function resetDryRuns(): void {
  dryRuns.clear();
}

// ── 세 명령 ─────────────────────────────────────────────────────────────

/** 시작. `dryRun` 이 아니면 사람이 「yes」를 친 뒤에만 부른다(`confirmed`). */
export async function issueFlightStart(
  link: FlightLink,
  plan: FlightPlan,
  run: { dryRun: boolean; confirmed: boolean },
): Promise<FlightIssueOutcome> {
  if (robotSession().stopped !== null) {
    return { sent: false, commandId: '', accepted: null, code: null, message: t('flight.cmd.screenStopped') };
  }
  if (link.start !== 'yes') {
    return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('flight.link.notDeclared') };
  }
  if (!run.dryRun && !run.confirmed) {
    return { sent: false, commandId: '', accepted: null, code: null, message: t('flight.reject.not_confirmed') };
  }
  const outcome = await issue(link, RTK_TEST_START, startParams(plan, run), !run.dryRun);
  if (run.dryRun && outcome.sent) dryRuns.set(link.deviceId, { commandId: outcome.commandId, signature: planSignature(plan) });
  return outcome;
}

/** 중단 — 실행기가 스크립트에 SIGTERM(= Ctrl+C) 을 보내고, 스크립트가 캡처 OFF + abort 동작을 한다. */
export async function issueFlightStop(link: FlightLink): Promise<FlightIssueOutcome> {
  if (link.stop === 'no') {
    return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('flight.cmd.stopUnsupported') };
  }
  return issue(link, RTK_TEST_STOP, undefined, false);
}

/** 비상 — `emergency_land.py` 를 따로 연결해 실행. 확인 질문이 없는 명령이라 화면이 두 번 누르게 한다. */
export async function issueFlightEmergency(link: FlightLink, mode: EmergencyMode): Promise<FlightIssueOutcome> {
  if (link.emergency === 'no') {
    return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('flight.cmd.emergencyUnsupported') };
  }
  return issue(link, RTK_TEST_EMERGENCY, { mode: EMERGENCY_CODE[mode] }, true);
}
