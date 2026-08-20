/**
 * src/data/commands.ts
 *
 * 명령 발행과 결과 추적 (VZ-O-01 · VZ-O-02 · REQ-903 · REQ-909).
 *
 * 화면은 transport를 직접 부르지 않는다 — 여기를 거친다.
 * 여기가 하는 일은 셋이다.
 *  1. `command_id`와 `expires_at`을 붙인다 (REQ-909). 화면이 만들면 화면마다 달라진다.
 *  2. 발행한 명령을 기억해 두었다가, 도착하는 `command_result`와 짝지어 **단계 이력**을 만든다.
 *  3. 네 단계를 **진행중 · 확정 · 실패 3종**으로 접는다 (REQ-903).
 *     액션별 판정 규칙을 프런트가 떠안지 않는다 — 확정은 백엔드가 승격한 값을 따른다.
 */

import { getTransport } from '../transport/index.ts';
import type { ActionSpec, CommandRequest, CommandResult } from '../transport/index.ts';
import { GATEWAY } from '../transport/index.ts';
import { buildAuditPayload } from './auditFieldMap.ts';

/** 명령 유효 시간. 서버의 COMMAND_TTL_MS와 짝을 이룬다. */
export const COMMAND_TTL_MS = 30_000;

export type CommandDisplay = 'in_progress' | 'confirmed' | 'failed';

export const COMMAND_DISPLAY_LABEL: Record<CommandDisplay, string> = {
  in_progress: '진행중',
  confirmed: '확정',
  failed: '실패',
};

/** 서버가 보내는 네 단계. 화면은 3종으로 접지만 이력에는 네 단계가 다 남는다. */
export type CommandStageEntry = {
  stage: CommandResult['stage'];
  status: CommandResult['status'];
  detail: string;
  progressPct: number | null;
  reasonCode: string | null;
  ts: string;
};

export type TrackedCommand = {
  commandId: string;
  entity: string;
  action: string;
  actionLabel: string;
  irreversible: boolean;
  expiresAt: string;
  /** 발행 시각(로컬). 서버 시각이 아니므로 표시에만 쓰고 판정에 쓰지 않는다. */
  issuedAtLocal: number;
  /** 도착한 단계 이력. 마지막 값만 남기면 ACK 단계가 화면에서 사라진다. */
  stages: CommandStageEntry[];
  display: CommandDisplay;
  /** 수행 중 진행률. */
  progressPct: number | null;
  /** 실패 시 이전 상태로 복원됐는가. */
  restored: boolean;
  reasonCode: string | null;
  lastDetail: string;
};

/** REQ-903 — 5값을 3종으로. 액션별 규칙 없이 상태값만 본다. */
export function toDisplay(status: CommandResult['status']): CommandDisplay {
  if (status === 'completed') return 'confirmed';
  if (status === 'accepted') return 'in_progress';
  return 'failed';
}

export class CommandTracker {
  private readonly commands = new Map<string, TrackedCommand>();
  private readonly listeners = new Set<() => void>();
  private snapshot: readonly TrackedCommand[] = [];
  private seq = 0;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): readonly TrackedCommand[] => this.snapshot;

  private commit(): void {
    // 최신 명령이 위로. 명령은 몇 건 안 되므로 매번 정렬해도 무해하다.
    this.snapshot = [...this.commands.values()].sort((a, b) => b.issuedAtLocal - a.issuedAtLocal);
    for (const l of this.listeners) l();
  }

  /**
   * 명령 발행.
   *
   * `expires_at`은 여기서 붙이지만 **검사는 서버가 서버 시각으로 한다.**
   * 클라이언트가 만료를 판단하면 사용자 PC 시계에 의존하게 된다.
   */
  async issue(
    entity: string,
    spec: ActionSpec,
    options: { ttlMs?: number; inputMode?: 'click' | 'voice' | 'api' | 'keyboard' } = {},
  ): Promise<TrackedCommand> {
    this.seq += 1;
    const commandId = 'c-' + Date.now().toString(36) + '-' + String(this.seq).padStart(2, '0');
    const ttl = options.ttlMs ?? COMMAND_TTL_MS;

    const request: CommandRequest = {
      command_id: commandId,
      entity,
      // 추상 action만 보낸다. 장비 명령으로의 번역은 백엔드 몫이다.
      action: spec.action,
      params: { target_pct: spec.targetPct },
      expires_at: new Date(Date.now() + ttl).toISOString(),
      // VZ-O-03 — 필드 이름은 auditFieldMap이 만든다. 여기서 이름을 쓰지 않는다.
      audit: buildAuditPayload({
        inputMode: options.inputMode ?? 'click',
        decisionSource: 'human',
      }),
    };

    const tracked: TrackedCommand = {
      commandId,
      entity,
      action: spec.action,
      actionLabel: spec.label,
      irreversible: spec.irreversible,
      expiresAt: request.expires_at,
      issuedAtLocal: Date.now(),
      stages: [],
      display: 'in_progress',
      progressPct: null,
      restored: false,
      reasonCode: null,
      lastDetail: '발행 — 가시화 → 백엔드 (감사 필드 동봉)',
    };
    this.commands.set(commandId, tracked);
    this.commit();

    const outcome = await getTransport().publishCommand(request);
    if (!outcome.accepted && this.commands.has(commandId)) {
      // 접수 거부는 즉답으로 온다. 단계 이력에도 남겨야 "왜 아무 일도 안 일어났나"가 보인다.
      const current = this.commands.get(commandId)!;
      if (current.stages.length === 0) {
        current.display = 'failed';
        current.reasonCode = outcome.reasonCode;
        current.lastDetail = outcome.message;
        this.commit();
      }
    }
    return tracked;
  }

  /** command_result 봉투 반영. 짝지음은 command_id로만 한다 (REQ-909). */
  apply(result: CommandResult): void {
    const tracked = this.commands.get(result.command_id);
    if (!tracked) return;

    tracked.stages.push({
      stage: result.stage,
      status: result.status,
      detail: result.detail,
      progressPct: result.progress_pct,
      reasonCode: result.reason_code,
      ts: result.ts,
    });

    tracked.display = toDisplay(result.status);
    tracked.progressPct = result.progress_pct;
    tracked.reasonCode = result.reason_code;
    tracked.restored = result.restored;
    tracked.lastDetail = result.detail;

    this.commit();
  }

  latestFor(entity: string): TrackedCommand | null {
    return this.snapshot.find((c) => c.entity === entity) ?? null;
  }

  clear(): void {
    this.commands.clear();
    this.commit();
  }
}

export const commandTracker = new CommandTracker();

/**
 * 액션 카탈로그 조회.
 * 화면이 액션 어휘를 하드코딩하지 않는다 — 장비가 바뀌어도 화면을 안 고친다는
 * VZ-O-01의 전제가 성립하려면 목록이 밖에서 와야 한다.
 */
export async function fetchActions(entity: string): Promise<ActionSpec[]> {
  try {
    const res = await fetch(GATEWAY.http + '/actions?entity=' + encodeURIComponent(entity));
    if (!res.ok) return [];
    const body = (await res.json()) as { actions?: ActionSpec[] };
    return body.actions ?? [];
  } catch {
    return [];
  }
}
