/**
 * src/physical/sarCommands.ts (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **SAR 패스 시작 · 중단 명령.** 규약은 기존 그대로다 — `PhysicalCommandEnvelope.Command` 의
 * `action` 문자열과 `map<string, double>` 파라미터. `.proto` 는 한 줄도 안 고친다.
 *
 * ## 기종이 아니라 선언으로 고른다
 *
 * 「드론이면」이 아니다. **`Capability.actions` 에 `sar_start` 를 선언한 장비**가 있는 브로커로 보낸다
 * (`walkingClient()` 가 `move_forward` 로 고르는 것과 같은 규칙). 드론 에이전트가 아직 선언하지 않았으면
 * 시작 버튼은 닫히고 그 사유가 적힌다.
 *
 *   시작   선언이 **있어야** 보낸다. 모르는데 비행을 시작시키지 않는다.
 *   중단   `stopSupport()` 와 같은 규칙 — 선언했거나 **모르면 보낸다.** 선언 안 했으면 조종기로 멈추라고 적는다.
 *
 * ## 추적기를 지난다
 *
 * 다른 로봇 명령과 같이 `commandTracker.issue` 를 지난다(`verify:single-egress` · `verify:command-through-tracker`).
 * 대상은 그 장비가 밝힌 id 다 — 상수로 적지 않는다.
 *
 * ## 화면 정지 뒤에는 시작하지 않는다
 *
 * 화면 상단의 정지가 걸려 있으면(`robotSession().stopped`) 시작을 막는다. 중단은 언제든 나간다.
 */

import { t } from '../i18n/dict.ts';
import { commandTracker } from '../shared/commandCenter.ts';
import { sarReports } from '../shared/sarStatus.ts';
import type { CommandAck, CommandRequest } from '../transport/index.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';
import type { PhysicalAction } from './encode.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import { syncRobotClients } from './robotClient.ts';
import { robotSession } from './robotSession.ts';
import type { UplinkMessage } from './uplink.ts';

export const SAR_START: PhysicalAction = 'sar_start';
export const SAR_ABORT: PhysicalAction = 'sar_abort';

export type SarSupport = 'yes' | 'no' | 'unknown';

/** 명령을 받을 장비 하나와, 시작 · 중단을 보낼 수 있는지. */
export type SarLink = {
  client: PhysicalClient | null;
  deviceId: string | null;
  start: SarSupport;
  abort: SarSupport;
  /** 못 고른 사유(사전 키가 아니라 이미 푼 글자). 골랐으면 빈칸. */
  reason: string;
};

type ClientLike = Pick<PhysicalClient, 'address' | 'getStatus' | 'send' | 'onMessage'>;

function supportOf(actions: readonly string[] | null, action: string): SarSupport {
  if (actions === null) return 'unknown';
  return actions.includes(action) ? 'yes' : 'no';
}

/**
 * **SAR 명령을 받을 장비.** 붙어 있는 브로커들 가운데
 *
 *  1. `sar_start` 를 선언한 장비가 **정확히 하나**면 그것,
 *  2. 없으면 SAR 상태를 보내 온 브로커의 장비(선언 목록을 못 받았을 수 있다 — 중단만 열린다).
 *
 * 둘 이상이면 고르지 않는다 — 어느 드론을 날릴지 짐작하지 않는다.
 */
export function sarLink(clients: readonly ClientLike[] = syncRobotClients()): SarLink {
  const open = clients.filter((client) => client.getStatus().state === 'open');
  const declared = open.filter((client) => deviceIdentityFor(client.address())?.actions?.includes(SAR_START) === true);
  if (declared.length > 1) {
    return { client: null, deviceId: null, start: 'no', abort: 'no', reason: t('sar.link.many', { n: declared.length }) };
  }
  const reports = Object.values(sarReports());
  const chosen = declared[0] ?? open.find((client) => reports.some((report) => report.origin === client.address()));
  if (chosen === undefined) {
    return {
      client: null, deviceId: null, start: 'no', abort: 'no',
      reason: open.length === 0 ? t('sar.link.noBroker') : t('sar.link.noDevice'),
    };
  }
  const identity = deviceIdentityFor(chosen.address());
  const actions = identity?.actions ?? null;
  return {
    client: chosen as PhysicalClient,
    // 장비가 밝힌 id 가 먼저다. 못 들었으면 SAR 보고의 `source_id` — 둘 다 장비가 한 말이다.
    deviceId: identity?.deviceId ?? reports.find((report) => report.origin === chosen.address())?.deviceId ?? null,
    start: supportOf(actions, SAR_START),
    abort: supportOf(actions, SAR_ABORT),
    reason: '',
  };
}

/** 화면이 그대로 옮기는 계획 — 규약의 숫자 파라미터다. 참·거짓은 1·0 으로 싣는다. */
export type SarStartParams = {
  start_lat: number; start_lon: number; end_lat: number; end_lon: number;
  alt_m: number; speed_mps: number; passes: number; gap_s: number; lead_in_m: number;
  require_rtk: number; rtl_on_abort: number; rtl_on_done: number;
};

export type SarIssueOutcome = {
  sent: boolean;
  commandId: string;
  /** 장비의 `Acceptance`. **`null` 은 아직 못 받았다**(시한 안에 답이 없었다). */
  accepted: boolean | null;
  code: string | null;
  message: string;
};

/** 응답을 기다리는 시간. 시작은 장비가 계획을 검사하고 답하므로 핑보다 넉넉히 둔다. */
const ACCEPT_WAIT_MS = 5000;

async function issueSar(
  link: SarLink,
  action: PhysicalAction,
  parameters: Record<string, number> | undefined,
): Promise<SarIssueOutcome> {
  const client = link.client;
  // 실제 발행 대상은 `PhysicalClient.send` 가 그 소켓의 장비로 다시 정한다 — 여기 id 는 추적기용이다.
  if (client === null || link.deviceId === null) {
    return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('sar.link.noDevice') };
  }

  // **귀를 먼저 연다** — 빠른 응답을 놓치지 않게 (`issuePing` 과 같은 이유).
  const seen: UplinkMessage[] = [];
  let wake: (() => void) | null = null;
  const off = client.onMessage((message) => { seen.push(message); wake?.(); });

  let commandId = '';
  try {
    await commandTracker.issue(
      link.deviceId,
      { action, label: action, targetPct: 0, irreversible: action === SAR_START, resultingState: '' },
      {
        params: { ...(parameters ?? {}) },
        publish: async (request: CommandRequest): Promise<CommandAck> => {
          const outcome = client.send(action, parameters);
          commandId = outcome.sent ? outcome.commandId : '';
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
    if (commandId === '') {
      return { sent: false, commandId: '', accepted: null, code: null, message: t('robot.notSent') };
    }
    const deadline = Date.now() + ACCEPT_WAIT_MS;
    for (;;) {
      const answer = seen.find((m) => m.commandId === commandId && m.kind === 'acceptance');
      if (answer !== undefined && answer.kind === 'acceptance') {
        return {
          sent: true, commandId, accepted: answer.accepted, code: answer.code,
          message: answer.accepted ? t('sar.cmd.accepted') : t('robot.rejected', { code: answer.code ?? t('robot.noReason'), message: answer.message ?? '' }).trim(),
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
    return { sent: true, commandId, accepted: null, code: null, message: t('sar.cmd.noAnswer', { sec: ACCEPT_WAIT_MS / 1000 }) };
  } finally {
    off();
  }
}

/** 패스 시작. 선언이 있고 화면 정지가 안 걸렸을 때만 나간다. */
export async function issueSarStart(params: SarStartParams, link: SarLink = sarLink()): Promise<SarIssueOutcome> {
  if (robotSession().stopped !== null) {
    return { sent: false, commandId: '', accepted: null, code: null, message: t('sar.cmd.screenStopped') };
  }
  if (link.start !== 'yes') {
    return { sent: false, commandId: '', accepted: null, code: null, message: link.reason || t('sar.link.notDeclared') };
  }
  return issueSar(link, SAR_START, { ...params });
}

/** 패스 중단. 선언했거나 모르면 보낸다 — 못 멈추는 것보다 낫다. */
export async function issueSarAbort(link: SarLink = sarLink()): Promise<SarIssueOutcome> {
  if (link.abort === 'no') {
    return { sent: false, commandId: '', accepted: null, code: null, message: t('sar.cmd.abortUnsupported') };
  }
  return issueSar(link, SAR_ABORT, undefined);
}
