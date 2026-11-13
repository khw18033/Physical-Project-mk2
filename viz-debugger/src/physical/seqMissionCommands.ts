/**
 * src/physical/seqMissionCommands.ts (261113 신설 — 드론 복합 이동 미션)
 *
 * **복합 미션 실행기에 보내는 두 명령** — 시작(`seq_mission_start`) · 중단(`seq_mission_stop`). 비상은 기존
 * `rtk_test_emergency` 그대로다(어느 스크립트가 날든 같다 — `MISSION_SEQ_요청_VZ.md` §2). 보내는 길 · 고르는 규칙은
 * 왕복 시험(`flightRunCommands.ts`)과 같다 — 시작은 선언해야, 중단은 모르면 보낸다, 추적기를 지난다.
 *
 * ## dry-run 을 지나야 비행이 열린다 (§7-4)
 *
 * 내가 보낸 dry-run(실행기가 되돌려 준 `command_id` 가 내 것)이 **종료 코드 0** 으로 끝났고, 그 실행의 `mission_key` 가
 * **지금 편집기의 키와 같을 때만** 열린다. 미션 키에 없는 abort · 최대 거리까지 같아야 한다(`seqSignature`) — 최대 거리가
 * 바뀌면 스크립트의 거리 검사가 달라진다.
 *
 * ## 두 실행기는 서로 배제된다 (§2)
 *
 * 왕복 시험(`flight_run`)이나 복합 미션(`mission_run`) 어느 쪽이 돌고 있으면 시작을 막는다. 실행기도 거절하지만
 * (`other_flight_running`) 화면이 먼저 닫는다.
 */

import { t } from '../i18n/dict.ts';
import { deviceCandidates } from './deviceIdentity.ts';
import type { PhysicalAction } from './encode.ts';
import { flightLink, issueFlightAction, RTK_TEST_EMERGENCY, type FlightIssueOutcome, type FlightLink, type FlightSupport } from './flightRunCommands.ts';
import type { FlightRunEntry } from './flightRunFeed.ts';
import type { MissionRunEntry } from './missionRunFeed.ts';
import { robotSession } from './robotSession.ts';
import { missionKey, seqSignature, seqStartParams, type SeqMission } from './seqPlan.ts';

export const SEQ_MISSION_START: PhysicalAction = 'seq_mission_start';
export const SEQ_MISSION_STOP: PhysicalAction = 'seq_mission_stop';

/** 이 장비가 복합 미션을 선언했나 — 선언했을 때만 화면을 연다(§2). */
export function seqDeclared(actions: readonly string[] | null): boolean {
  return actions !== null && actions.includes(SEQ_MISSION_START);
}

function supportOf(actions: readonly string[] | null, action: string): FlightSupport {
  if (actions === null) return 'unknown';
  return actions.includes(action) ? 'yes' : 'no';
}

/** 복합 미션의 길 — 소켓은 왕복 시험과 같고, 시작 · 중단만 다른 action 을 본다. 비상은 그대로. */
export function seqLink(deviceId: string): FlightLink {
  const base = flightLink(deviceId);
  if (base.client === null) return base;
  const actions = deviceCandidates().find((candidate) => candidate.deviceId === deviceId)?.actions ?? null;
  return { ...base, start: supportOf(actions, SEQ_MISSION_START), stop: supportOf(actions, SEQ_MISSION_STOP), emergency: supportOf(actions, RTK_TEST_EMERGENCY) };
}

/** 어느 실행기든 돌고 있나 — 시작 버튼을 막는다. */
export function anyFlightRunning(flight: FlightRunEntry | undefined, mission: MissionRunEntry | undefined): 'flight' | 'mission' | null {
  if (flight?.run?.state === 'running') return 'flight';
  if (mission?.run?.state === 'running') return 'mission';
  return null;
}

// ── dry-run 짝 ──────────────────────────────────────────────────────────

const dryRuns = new Map<string, { commandId: string; signature: string }>();

export type SeqGate = 'none' | 'pending' | 'failed' | 'keyMismatch' | 'passed';

/**
 * 이 미션의 dry-run 상태.
 *
 *   none         이 미션으로 보낸 dry-run 이 없다(또는 편집기가 바뀌었다)
 *   pending      보냈고 아직 끝나지 않았다
 *   failed       끝났는데 종료 코드가 0 이 아니다
 *   keyMismatch  끝났는데 드론이 돌려준 `mission_key` 가 편집기의 키와 다르다 — 해석이 어긋났다
 *   passed       비행을 열어도 된다
 */
export function seqGate(deviceId: string, mission: SeqMission, entry: MissionRunEntry | undefined): SeqGate {
  const mine = dryRuns.get(deviceId);
  if (mine === undefined || mine.signature !== seqSignature(mission)) return 'none';
  const run = entry?.run ?? null;
  if (run === null || run.commandId !== mine.commandId || run.state === 'running') return 'pending';
  if (run.exitCode !== 0 || run.dryRun === false) return 'failed';
  if (run.missionKey !== missionKey(mission)) return 'keyMismatch';
  return 'passed';
}

/** 내가 보낸 dry-run 의 command_id — 화면이 「그 실행」 을 가리킬 때. */
export function seqDryRunCommandId(deviceId: string): string | null {
  return dryRuns.get(deviceId)?.commandId ?? null;
}

export function resetSeqDryRuns(): void {
  dryRuns.clear();
}

// ── 명령 ────────────────────────────────────────────────────────────────

const refuse = (message: string): FlightIssueOutcome => ({ sent: false, commandId: '', accepted: null, code: null, message });

/** 시작. 실비행이면 사람이 「yes」를 친 뒤에만 부른다(`confirmed`). */
export async function issueSeqStart(
  link: FlightLink,
  mission: SeqMission,
  run: { dryRun: boolean; confirmed: boolean },
): Promise<FlightIssueOutcome> {
  if (robotSession().stopped !== null) return refuse(t('flight.cmd.screenStopped'));
  if (link.start !== 'yes') return refuse(link.reason || t('seq.link.notDeclared'));
  if (!run.dryRun && !run.confirmed) return refuse(t('flight.reject.not_confirmed'));
  const outcome = await issueFlightAction(link, SEQ_MISSION_START, seqStartParams(mission, run), !run.dryRun);
  if (run.dryRun && outcome.sent) {
    dryRuns.set(link.deviceId, { commandId: outcome.commandId, signature: seqSignature(mission) });
  }
  return outcome;
}

/** 중단 — 실행기가 스크립트에 SIGTERM(= Ctrl+C → 캡처 OFF → abort 동작). */
export async function issueSeqStop(link: FlightLink): Promise<FlightIssueOutcome> {
  if (link.stop === 'no') return refuse(link.reason || t('seq.cmd.stopUnsupported'));
  return issueFlightAction(link, SEQ_MISSION_STOP, undefined, false);
}
