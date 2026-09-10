/**
 * src/physical/robotCommands.ts (260910 신설 — 화면 연결 §1 · §2 · §4 · §5)
 *
 * **화면이 로봇에게 명령을 내는 자리.** 버튼은 여기를 부르고, 여기는 `CommandTracker` 를 지난다.
 *
 * ## 왜 추적기를 지나는가
 *
 * 로봇 명령이 추적기를 우회하면 `VZ-O-02`(4단계 추적)와 `VZ-O-03`(감사)이 **그 명령만**
 * 못 본다. 탭 이식 때 추적기를 출구 본체로 삼은 이유가 그것이다. 그래서 출구는 그대로 두고
 * **나가는 수단만** MQTT 로 갈아 끼운다(`IssueOptions.publish`).
 *
 * ## 승인 전에는 바이트가 안 나간다
 *
 * 매칭 결과는 제안이고 사람이 승인하기 전에는 아무것도 나가지 않는다(`VZ-U-07`).
 * 아래 모든 임무 명령이 `canIssueRobotCommand()` 를 먼저 묻는다. `verify:no-publish-before-approval`
 * 이 승인 전 발행 0건을 확인한다.
 *
 * **`ping` 은 예외다** — 임무 명령이 아니라 연결 확인이고, 발표 직전에 무대에 오르기 전
 * 누르는 것이라 승인이라는 개념 자체가 없다. 규약과 무관한 왕복 확인이다.
 */

import { commandTracker } from '../shared/commandCenter.ts';
import type { CommandAck, CommandRequest } from '../transport/index.ts';
import type { PhysicalAction } from './encode.ts';
import { PAUSE_ACTION, SDK_ACTIONS } from './presets.ts';
import { NO_NODE } from './missionLink.ts';
import { commandForTask, missionGeometry } from './missionLink.ts';
import type { PhysicalClient } from './PhysicalClient.ts';
import type { UplinkMessage } from './uplink.ts';
import { STOP_ACTION, STOP_REASON } from './presets.ts';
import {
  canIssueRobotCommand, clearScanIssued, lockPaused, lockStopped, markApproachIssued, markScanIssued,
  notePauseFailure, pickDoorIndex, recordCommand, releasePaused, robotDrives, robotSession, runningTaskId,
  type PauseState, type StopState,
} from './robotSession.ts';

export type IssueOutcome = {
  sent: boolean;
  commandId: string;
  requestId: string | null;
  reason?: string;
};

/**
 * 추적기의 발행 수단을 MQTT 로 갈아 끼운다. **추적·감사는 갈리지 않는다** — 추적기가
 * 이미 기록했고 아래에서 같은 자리로 ACK 를 돌려준다.
 *
 * MQTT 는 QoS 1 이라 브로커가 받았다는 것까지만 안다. 로봇이 받았는지는 uplink 의
 * `Acceptance` 가 말한다 — 그래서 여기서는 「보냈다」까지만 참이라고 말한다.
 */
function mqttEgress(client: PhysicalClient, action: PhysicalAction, parameters?: Record<string, number>) {
  return async (request: CommandRequest): Promise<CommandAck> => {
    const outcome = client.send(action, parameters);
    return {
      clientRequestId: request.client_request_id,
      // 상관 키는 우리가 만든 command_id 다 — uplink 가 이 키로 돌아온다.
      commandId: outcome.sent ? outcome.commandId : null,
      accepted: outcome.sent,
      reasonCode: outcome.sent ? null : 'physical_not_connected',
      message: outcome.sent ? '브로커로 발행했습니다 (로봇 수락은 uplink 가 말한다)' : (outcome.reason ?? '보내지 못했습니다'),
    };
  };
}

/** 태스크 하나가 자기 명령을 낸다. 무엇을 쏘는지는 `commandForTask()` 가 정한다. */
async function issueTask(
  client: PhysicalClient,
  taskId: string,
  params: Record<string, unknown> | null,
): Promise<IssueOutcome | null> {
  const command = commandForTask(taskId, missionGeometry(params));
  if (command === null) return null;
  if (!canIssueRobotCommand()) {
    return { sent: false, commandId: '', requestId: null, reason: '승인 전이거나 정지된 상태입니다' };
  }
  return issueThroughTracker(client, taskId, command.action, command.parameters);
}

async function issueThroughTracker(
  client: PhysicalClient,
  taskId: string,
  action: PhysicalAction,
  parameters?: Record<string, number>,
): Promise<IssueOutcome> {
  let commandId = '';
  const tracked = await commandTracker.issue(
    // 대상은 화면의 장비 id 다 — 하드웨어 id 로 바꾸는 것은 경계 안쪽 일이다.
    'robot-01',
    { action, label: action, targetPct: 0, irreversible: false, resultingState: '' },
    {
      params: { ...(parameters ?? {}), task_id: taskId },
      publish: async (request) => {
        const ack = await mqttEgress(client, action, parameters)(request);
        commandId = ack.commandId ?? '';
        return ack;
      },
    },
  );
  const sent = commandId !== '';
  if (sent) {
    recordCommand({
      taskId, commandId, action, requestId: tracked.requestId,
      state: 'issued', code: null, message: null, result: {},
    });
  }
  return {
    sent,
    commandId,
    requestId: tracked.requestId,
    ...(sent ? {} : { reason: tracked.lastDetail }),
  };
}

/**
 * 승인 → `T-A3` 가 `scan_mission` 을 쏜다. `forward_m=0` 이라 스캔만 돈다.
 *
 * **표시를 먼저 세운다.** 발행을 기다렸다가 세우면 그 사이의 다시 그리기에서 관문이
 * 아직 열려 있어 스캔이 여러 번 나간다 — 260910 에 진행률이 「40 / 10」으로 찍혔다.
 * 로봇이 네 번 돈 것이다. 실패하면 도로 내린다.
 */
export async function issueScan(client: PhysicalClient, params: Record<string, unknown> | null): Promise<IssueOutcome> {
  // **막히면 왜 막혔는지 말한다.** 조용히 null 을 돌려주면 발표장에서 「왜 안 가지」가 된다.
  if (robotSession().scanIssued) {
    return { sent: false, commandId: '', requestId: null, reason: '이미 쐈습니다 — 승인 한 번에 한 번만 나갑니다' };
  }
  if (!robotDrives()) {
    return { sent: false, commandId: '', requestId: null, reason: '브로커에 안 붙어 있습니다 — 대본이 돕니다' };
  }
  markScanIssued();
  // **문 방향을 하나 뽑아 둔다** — 탐지가 붙기 전까지의 임시 자리 (260910 지시).
  // 판이 시작할 때 한 번만 뽑는다. `door_turn` 이 올 때 뽑으면 이미 늦고, 다시 그릴
  // 때마다 뽑으면 초록 칸이 돌아다닌다.
  pickDoorIndex(typeof params?.viewpoint_count === 'number' ? params.viewpoint_count : 8);
  const outcome = await issueTask(client, 'T-A3', params);
  if (outcome === null || outcome.sent !== true) clearScanIssued();
  return outcome ?? { sent: false, commandId: '', requestId: null, reason: 'T-A3 에 낼 명령이 없습니다' };
}

/**
 * 승인 뒤 스캔을 **한 번만** 쏜다. 화면이 다시 그려질 때마다 부르면 로봇이 여러 번 돈다.
 *
 * 브로커에 안 붙어 있으면 안 쏜다. **그때 대신 도는 대본은 이제 없다**(260910) — 진행이
 * 아예 없는 것이 맞다. 없는 진행을 대본으로 지어 보이면 무대에서 「되는 줄」 알고 넘어간다.
 */
export function shouldIssueScan(): boolean {
  const session = robotSession();
  return session.approved && !session.scanIssued && session.stopped === null && robotDrives();
}

/**
 * 「접근 시작」 → `T-B2` 가 `move_forward` 를 쏜다.
 *
 * **자동으로 이어지지 않는다** (§1). 스캔이 끝나면 화면이 초록 노드를 보여 주고 거기서 한
 * 박자 쉰다 — 발표자가 "이 방향으로 갑니다"를 말하고 누르면 로봇이 간다. 그 한 박자가
 * 시연에서 가장 좋은 자리다.
 */
export async function issueApproach(client: PhysicalClient, params: Record<string, unknown> | null) {
  const outcome = await issueTask(client, 'T-B2', params);
  if (outcome?.sent === true) markApproachIssued();
  return outcome;
}

/**
 * **구동 브리지를 사람이 쥔다** (연동 가이드 §4-3 · 260910 지시).
 *
 * 로봇은 평시에 「연결만 된 상태」다. 브리지(`go1-sdk`)는 내려가 있고, 기동하는 순간
 * 로봇이 **일어선다.** 그래서 부팅 자동시작이 꺼져 있다.
 *
 * 임무 쪽은 손댈 것이 없다 — 이동 명령이 알아서 브리지를 띄우고 그 사이 `sdk_starting`
 * 을 보고한다. 여기 있는 셋은 **사람이 미리 쥐고 싶을 때**의 손잡이다.
 *
 *   준비    무대 오르기 전에 세워 둔다. 일어서는 몇 초를 시연 중에 안 쓴다
 *   내림    선 채로 남는다. 리허설 사이에 내려 둔다
 *   자동    끄면 이동 명령이 `go1_sdk_not_running` 으로 거절된다 —
 *           「로봇이 스스로 일어서는 일이 절대 없게」 하고 싶을 때
 *
 * ## 승인과 무관하다 (ping 과 같은 자리)
 *
 * 임무 명령이 아니다. 「승인 전에 나가는 바이트가 없어야 한다」는 대본 실행을 막는
 * 규칙이고, 이것은 사람이 버튼을 눌러 장비를 준비시키는 일이다. 대신 **추적기를
 * 지난다** — 로봇을 일으켜 세우는 명령이라 감사에 남을 이유가 더 크다.
 */
export async function issueSdkStart(client: PhysicalClient): Promise<IssueOutcome> {
  return issueThroughTracker(client, NO_NODE, SDK_ACTIONS.start);
}

export async function issueSdkStop(client: PhysicalClient): Promise<IssueOutcome> {
  return issueThroughTracker(client, NO_NODE, SDK_ACTIONS.stop);
}

/** 자동 기동 켜기/끄기. 규약이 `map<string, double>` 이라 참·거짓을 1·0 으로 싣는다. */
export async function issueSdkAuto(client: PhysicalClient, on: boolean): Promise<IssueOutcome> {
  return issueThroughTracker(client, NO_NODE, SDK_ACTIONS.auto, { on: on ? 1 : 0 });
}

/** 접근을 눌러도 되는가 — `door_turn` 이 왔고, 아직 안 쐈고, 잠기지 않았을 때. */
export function canApproach(): boolean {
  const session = robotSession();
  return session.doorTurn !== null && !session.approachIssued && canIssueRobotCommand();
}

/**
 * **연결 확인.** `ping` **왕복**. 발표 직전에 이걸 눌러 초록을 보고 무대에 오른다.
 * 임무 명령이 아니라 승인과 무관하다.
 *
 * ## 발행 성공은 왕복 성공이 아니다 (260910 — 실제로 났던 거짓말)
 *
 * 처음에 `client.send()` 가 참을 돌려주면 곧바로 `ok: true` 로 적었다. 그건 **브로커가
 * 받았다**는 뜻이지 로봇이 답했다는 뜻이 아니다. 로봇을 꺼 놓고 눌렀는데 「로봇 ✓ 1ms」가
 * 떴다 — 1ms 는 왕복이 아니라 `send()` 가 걸린 시간이었다.
 *
 * 「붙었다」와 「답한다」를 가른 것이 연결 관리의 요점인데, 정작 로봇 줄이 브로커를 다시
 * 재고 있었다. 이제 **그 command_id 의 uplink 가 올 때까지 기다린다.** 안 오면 빨갛다.
 */
export async function issuePing(
  client: PhysicalClient,
  timeoutMs = 4000,
): Promise<{ ok: boolean; roundTripMs: number | null; message: string }> {
  // **귀를 먼저 연다.** 보내고 나서 열면 빠른 응답을 놓친다.
  let expected: string | null = null;
  let settle: ((message: UplinkMessage) => void) | null = null;
  const answered = new Promise<UplinkMessage>((resolve) => { settle = resolve; });
  const seen: UplinkMessage[] = [];
  const off = client.onMessage((message) => {
    seen.push(message);
    if (expected !== null && message.commandId === expected && settle !== null) {
      settle(message);
      settle = null;
    }
  });

  const startedAt = Date.now();
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    const outcome = client.send('ping');
    if (!outcome.sent) {
      return { ok: false, roundTripMs: null, message: outcome.reason ?? '보내지 못했습니다' };
    }
    expected = outcome.commandId;

    // 보내는 사이에 이미 왔을 수도 있다.
    const early = seen.find((m) => m.commandId === expected);
    const reply = early ?? await Promise.race([
      answered,
      new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), timeoutMs); }),
    ]);

    if (reply === null) {
      // **브로커는 받았는데 로봇이 답을 안 했다.** 이게 로봇이 꺼져 있을 때의 모습이다.
      return {
        ok: false,
        roundTripMs: null,
        message: `로봇이 ${timeoutMs}ms 안에 답하지 않았습니다 — 브로커는 받았습니다`,
      };
    }
    const roundTripMs = Date.now() - startedAt;
    // 거절도 **답한 것**이다 — 로봇은 살아 있고 그 말을 그대로 옮긴다.
    if (reply.kind === 'acceptance' && !reply.accepted) {
      return { ok: false, roundTripMs, message: `로봇이 거절했습니다 — ${reply.code ?? '사유 없음'} ${reply.message ?? ''}`.trim() };
    }
    return { ok: true, roundTripMs, message: '로봇이 답했습니다' };
  } finally {
    off();
    if (timer !== null) clearTimeout(timer);
  }
}

/**
 * **일시정지.** 정지와 뼈대가 같다 — 발행이 실패해도 멈춤은 그대로 일어난다.
 *
 *   1. `abort_mission` 발행    ← 실패할 수 있다
 *   2. 타이머 정지 · 3. 새 명령 차단  ← **1의 결과와 무관하게 일어난다**
 *
 * 정지와 다른 점은 **아무것도 안 버린다**는 것뿐이다. 여덟 칸도 진행률도 문 방향도 그대로
 * 남고, 재시작하면 그 자리에서 이어 간다.
 */
export async function pauseMission(client: PhysicalClient | null): Promise<PauseState> {
  const taskId = runningTaskId();
  let published = false;
  let failure: string | null = null;
  let commandId = '';
  try {
    if (client === null) failure = '브로커 연결 없음';
    else {
      const outcome = client.send(PAUSE_ACTION);
      published = outcome.sent;
      commandId = outcome.commandId;
      if (!outcome.sent) failure = outcome.reason ?? '보내지 못했습니다';
    }
  } catch (error) {
    failure = error instanceof Error ? error.message : String(error);
  }
  // 2 · 3 — **위 결과를 보지 않는다.** 못 보냈어도 화면은 멈추고 크게 말한다.
  const paused = lockPaused(taskId, published, failure);

  /**
   * **로봇이 뭐라 했는지까지 듣는다** (260910 지적 — 「돌고 있는 도중 일시정지가 안 된다」).
   *
   * 발행 성공은 브로커가 받았다는 뜻일 뿐이다. 로봇이 `abort_mission` 을 거절하면
   * (돌던 임무가 없다거나, 그 이름을 모른다거나) **로봇은 계속 도는데 화면만 멈춘다.**
   * 그때 아무 말이 없으면 「일시정지가 안 먹는다」로만 보이고 원인을 알 수 없다.
   *
   * 화면 멈춤은 이미 위에서 끝났다 — 여기서 듣는 것은 **문구를 채우기 위해서**다.
   * 늦게 오든 안 오든 멈춤은 그대로다.
   */
  if (client !== null && published) void reportPauseAnswer(client, commandId);
  return paused;
}

async function reportPauseAnswer(client: PhysicalClient, commandId: string, timeoutMs = 4000): Promise<void> {
  const answer = await firstAnswer(client, commandId, timeoutMs);
  if (answer === null) {
    notePauseFailure(`로봇이 ${timeoutMs}ms 안에 답하지 않았습니다 — 계속 돌고 있을 수 있습니다`);
    return;
  }
  if (answer.kind === 'acceptance' && !answer.accepted) {
    notePauseFailure(`로봇이 거절했습니다 — ${answer.code ?? '사유 없음'} ${answer.message ?? ''}`.trim());
  }
}

/** 그 `command_id` 의 첫 응답. 안 오면 null. */
function firstAnswer(client: PhysicalClient, commandId: string, timeoutMs: number): Promise<UplinkMessage | null> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { off(); resolve(null); }, timeoutMs);
    const off = client.onMessage((message) => {
      if (message.commandId !== commandId) return;
      clearTimeout(timer);
      off();
      resolve(message);
    });
  });
}

/**
 * **재시작.** 멈춰 있던 태스크를 다시 낸다.
 *
 * **그 단계를 처음부터 다시 한다.** 로봇 규약에 이어 하기가 없어서다 — 스캔을 세 걸음째에
 * 세웠으면 여덟 걸음을 다시 돈다. 화면이 그렇게 적어 둔다.
 *
 * 멈출 때 돌던 태스크가 없었으면(승인 직후에 눌렀다든지) 관문만 풀고 아무것도 안 쏜다 —
 * 그때는 원래 흐름이 알아서 스캔을 낸다.
 */
export async function resumeMission(
  client: PhysicalClient,
  params: Record<string, unknown> | null,
): Promise<IssueOutcome | null> {
  const taskId = robotSession().paused?.taskId ?? null;
  releasePaused();
  if (taskId === null) return null;
  if (taskId === 'T-A3') markScanIssued();      // 관문을 다시 걸어 두 번 안 나가게
  const outcome = await issueTask(client, taskId, params);
  if (taskId === 'T-A3' && (outcome === null || outcome.sent !== true)) clearScanIssued();
  return outcome;
}

/**
 * **긴급 정지.** 누르면 넷이 일어난다.
 *
 *   1. `abort` 발행        ← 실패할 수 있다
 *   2. 추적 중단 · 3. 타이머 정지 · 4. 화면 잠금  ← **1의 결과와 무관하게 일어난다**
 *
 * 순서가 이렇다는 것이 중요하다. 발행을 먼저 시도하되 **그 결과를 기다렸다가 잠그는 것이
 * 아니라**, 결과가 무엇이든 잠근다. 발행이 예외를 던져도 잠근다.
 *
 * `abort` 는 **자기 `command_id`** 를 새로 만든다 — 돌던 임무의 id 를 재사용하면 응답이 섞인다.
 * `client.send()` 가 부를 때마다 새 id 를 만드므로 그 조건은 저절로 지켜진다.
 */
export async function emergencyStop(client: PhysicalClient | null): Promise<StopState> {
  let published = false;
  let failure: string | null = null;

  try {
    if (client === null) {
      failure = '브로커 연결 없음';
    } else {
      // **규약 밖의 파라미터를 더하지 않는다** — reason 하나뿐이다.
      const outcome = client.send(STOP_ACTION, { reason: STOP_REASON.human });
      published = outcome.sent;
      if (!outcome.sent) failure = outcome.reason ?? '보내지 못했습니다';
    }
  } catch (error) {
    // 발행이 던져도 아래 잠금은 그대로 일어난다. 이게 이 기능의 뼈대다.
    failure = error instanceof Error ? error.message : String(error);
  }

  // 2 · 3 · 4 — **위 결과를 보지 않는다.**
  return lockStopped(published, failure);
}

/** 정지 뒤 화면에 크게 띄울 문구. 조용히 성공한 척하지 않는다. */
export function stopFailureMessage(stopped: StopState): string | null {
  return stopped.published ? null : `정지 명령을 보내지 못했습니다 — ${stopped.failure ?? '알 수 없는 이유'}`;
}
