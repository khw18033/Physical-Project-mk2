/**
 * mock-gateway/commands.ts
 *
 * 제어 명령 왕복 엔진 (VZ-O-01 · VZ-O-02) + 제어 잠금 (VZ-O-05) + 감사 적재 (VZ-I-05).
 *
 * **명령은 이 파일 안에서만 왕복한다.** 실제 디바이스로 나가는 경로는 만들지 않는다
 * — 백엔드 시트가 비어 있어 지금 만들면 확정 후 버려야 한다.
 *
 * 여기가 지키는 것 넷.
 *  1. **만료 검사를 서버가 한다** (REQ-909). 화면이 "만료됐다"고 말만 하는 게 아니라
 *     서버가 실제로 거부해야, 만료 필드가 계약에서 의미를 갖는다.
 *  2. **네 단계로 응답한다** — ack → executing(200ms 진행) → physical_state_changed → settled.
 *  3. **실패하면 이전 상태로 되돌린다.** 화면과 현실이 어긋나는 것이 관제에서 가장 위험하다.
 *  4. **잠긴 대상의 명령은 접수하지 않는다.** 화면 차단은 사용자 편의이고 실제 차단은 서버다.
 */

import { INTERVALS, SCENARIO_TIMING } from './config.ts';
import type { Hub } from './hub.ts';
import type { AuditRecord, CommandRequest, CommandResult, ControlLock } from './protocol.ts';

/**
 * 액션 카탈로그.
 * `irreversible`이 참이면 **ACK가 아니라 실제 수행 결과로 확정 표시**해야 하는 명령이다
 * (VZ-O-02). 수문처럼 되돌리기 어려운 것이 여기 해당한다.
 * ※ 미결: 실제 액션 어휘집(REQ-1208)은 백엔드 소관이며 형태가 Tier 2다.
 */
export type ActionSpec = {
  action: string;
  label: string;
  targetPct: number;
  irreversible: boolean;
  /** 이 액션이 만드는 물리 상태 이름. 화면의 "현재 상태" 표기에 쓴다. */
  resultingState: string;
};

export const ACTION_CATALOG: Record<string, ActionSpec[]> = {
  'actuator-01': [
    { action: 'open_gate', label: '수문 개방', targetPct: 100, irreversible: true, resultingState: 'open' },
    { action: 'close_gate', label: '수문 폐쇄', targetPct: 0, irreversible: true, resultingState: 'closed' },
  ],
};

type ActiveCommand = {
  req: CommandRequest;
  spec: ActionSpec;
  startedMs: number;
  /** 실패 시 되돌릴 값. */
  previousPct: number;
  previousState: string;
  timers: Array<ReturnType<typeof setTimeout>>;
  /** 다음 결과가 실패여야 하는가(시나리오 주입). */
  failAt: number | null;
};

export class CommandEngine {
  private readonly hub: Hub;
  private readonly active = new Map<string, ActiveCommand>();
  private readonly audit: AuditRecord[] = [];
  private readonly locks = new Map<string, ControlLock>();

  /** 다음 명령 1건을 실패시킨다(시나리오 주입). */
  failNext = false;

  /**
   * 명령 시작·종료 시 장치 발행 주기를 다시 걸도록 알리는 훅.
   * 엔진이 장치를 직접 알지 않게 하려고 콜백으로 둔다.
   */
  onActivityChange: ((entity: string) => void) | null = null;

  /** 대상별 현재 물리 상태 이름. 화면의 "현재 상태 closed" 표기. */
  private readonly physicalState = new Map<string, string>();
  private readonly positionPct = new Map<string, number>();

  constructor(hub: Hub) {
    this.hub = hub;
    for (const entity of Object.keys(ACTION_CATALOG)) {
      this.physicalState.set(entity, 'closed');
      this.positionPct.set(entity, 0);
      this.setLock(entity, { locked: false, phase: 'unlocked', reason: null, safe_state_held: false, since: nowIso() });
    }
  }

  // ── 제어 잠금 (VZ-O-05) ────────────────────────────────────────────────────

  getLock(entity: string): ControlLock | null {
    return this.locks.get(entity) ?? null;
  }

  private setLock(entity: string, lock: ControlLock): void {
    this.locks.set(entity, lock);
    if (this.hub.runtime.has(entity)) {
      this.hub.publish(entity, 'control_lock', lock, { fromDevice: false, quality: lock.locked ? 'unknown' : 'good' });
    }
  }

  /** 통신 두절 주입 — 즉시 잠근다. 늦게 알면 관제사가 헛버튼을 계속 누른다. */
  lockForCommLoss(entity: string, reason: string): void {
    this.setLock(entity, {
      locked: true,
      phase: 'comm_lost',
      reason,
      safe_state_held: true,
      since: nowIso(),
    });
  }

  /**
   * 통신 복구 — **바로 풀지 않는다.**
   * 재확인 단계를 거쳐야 잠금이 해제된다. 끊긴 동안 실제로 무슨 일이 있었는지
   * 모른 채 명령을 내보내면 안 되기 때문이다.
   */
  beginRecheck(entity: string): void {
    this.setLock(entity, {
      locked: true,
      phase: 'rechecking',
      reason: '통신 복구 — 실제 상태 재확인 중 (' + Math.round(SCENARIO_TIMING.CONTROL_RECHECK_MS / 1000) + '초)',
      safe_state_held: true,
      since: nowIso(),
    });
    setTimeout(() => {
      const lock = this.locks.get(entity);
      if (lock?.phase !== 'rechecking') return;
      this.setLock(entity, { locked: false, phase: 'unlocked', reason: null, safe_state_held: false, since: nowIso() });
    }, SCENARIO_TIMING.CONTROL_RECHECK_MS);
  }

  // ── 명령 접수 ──────────────────────────────────────────────────────────────

  /**
   * 명령 접수. 거부 사유는 셋 — 만료 / 잠금 / 미지원 액션.
   * 거부도 command_result로 내려보낸다. 화면이 사유를 표시할 수 있어야 하기 때문이다.
   */
  submit(req: CommandRequest): { accepted: boolean; reasonCode: string | null; message: string } {
    const specs = ACTION_CATALOG[req.entity] ?? [];
    const spec = specs.find((s) => s.action === req.action);

    if (!spec) {
      return this.reject(req, 'unknown_action', '지원하지 않는 action: ' + req.action);
    }

    // REQ-909 — **서버 시각**으로 만료를 검사한다. 클라이언트 시계를 믿지 않는다.
    if (Date.parse(req.expires_at) <= Date.now()) {
      return this.reject(req, 'expired', '만료 시각이 지난 명령이라 실행하지 않는다 (expires_at=' + req.expires_at + ')');
    }

    const lock = this.locks.get(req.entity);
    if (lock?.locked) {
      return this.reject(req, 'control_locked', lock.reason ?? '제어 잠금 상태');
    }

    if (this.active.has(req.entity)) {
      return this.reject(req, 'busy', '이전 명령이 아직 수행 중이다');
    }

    this.begin(req, spec);
    return { accepted: true, reasonCode: null, message: spec.label + ' 명령 접수' };
  }

  private reject(req: CommandRequest, reasonCode: string, detail: string) {
    this.emitResult(req, {
      status: 'rejected',
      stage: 'settled',
      progress_pct: null,
      detail,
      reason_code: reasonCode,
      restored: false,
    });
    this.record(req, 'rejected', detail);
    return { accepted: false, reasonCode, message: detail };
  }

  // ── 4단계 수행 ─────────────────────────────────────────────────────────────

  private begin(req: CommandRequest, spec: ActionSpec): void {
    const previousPct = this.positionPct.get(req.entity) ?? 0;
    const previousState = this.physicalState.get(req.entity) ?? 'unknown';

    const cmd: ActiveCommand = {
      req,
      spec,
      startedMs: 0,
      previousPct,
      previousState,
      timers: [],
      // 시나리오가 실패를 예약했으면 진행 60% 지점에서 실패시킨다 —
      // 시작하자마자 실패하면 "이전 상태로 복원"이 눈에 보이지 않는다.
      failAt: this.failNext ? 60 : null,
    };
    this.failNext = false;
    this.active.set(req.entity, cmd);
    this.onActivityChange?.(req.entity);

    // 1단계 — 수신 확인(ACK). 화면은 여기서 '진행중'이 되지만 상태는 아직 안 바꾼다.
    cmd.timers.push(
      setTimeout(() => {
        this.emitResult(req, {
          status: 'accepted',
          stage: 'ack',
          progress_pct: null,
          detail: '디바이스 ACK 수신',
          reason_code: null,
          restored: false,
        });
      }, SCENARIO_TIMING.ACTUATOR_ACK_MS),
    );

    // 2단계 — 수행 중. 200ms마다 진행 보고 (VZ-O-02 / HW-A-04).
    cmd.timers.push(
      setTimeout(() => {
        cmd.startedMs = Date.now();
        this.tickProgress(req.entity);
      }, SCENARIO_TIMING.ACTUATOR_ACK_MS + SCENARIO_TIMING.ACTUATOR_EXEC_GAP_MS),
    );
  }

  private tickProgress(entity: string): void {
    const cmd = this.active.get(entity);
    if (!cmd) return;

    const elapsed = Date.now() - cmd.startedMs;
    const ratio = Math.min(1, elapsed / SCENARIO_TIMING.ACTUATOR_TRAVEL_MS);
    const pct = Math.round(ratio * 100);
    const pos = cmd.previousPct + (cmd.spec.targetPct - cmd.previousPct) * ratio;
    this.positionPct.set(entity, Math.round(pos * 10) / 10);

    // 시나리오가 예약한 실패 지점 — 여기서 멈추고 되돌린다.
    if (cmd.failAt !== null && pct >= cmd.failAt) {
      this.fail(entity, 'obstruction', '구동부 과부하 감지 — 개폐 중단');
      return;
    }

    if (ratio >= 1) {
      this.settle(entity);
      return;
    }

    this.emitResult(cmd.req, {
      status: 'accepted',
      stage: 'executing',
      progress_pct: pct,
      detail: '수행 중 · 개도 ' + Math.round(pos) + '%',
      reason_code: null,
      restored: false,
    });

    cmd.timers.push(setTimeout(() => this.tickProgress(entity), INTERVALS.COMMAND_PROGRESS_MS));
  }

  /** 3~4단계 — 물리 상태 변화 → 완료. 되돌리기 어려운 명령은 여기서야 확정된다. */
  private settle(entity: string): void {
    const cmd = this.active.get(entity);
    if (!cmd) return;

    this.positionPct.set(entity, cmd.spec.targetPct);
    this.physicalState.set(entity, cmd.spec.resultingState);

    this.emitResult(cmd.req, {
      status: 'accepted',
      stage: 'physical_state_changed',
      progress_pct: 100,
      detail: '물리 상태 변화 확인 — ' + cmd.spec.resultingState,
      reason_code: null,
      restored: false,
    });

    this.emitResult(cmd.req, {
      status: 'completed',
      stage: 'settled',
      progress_pct: 100,
      detail: '백엔드가 수행 결과를 확인해 승격',
      reason_code: null,
      restored: false,
    });

    this.record(cmd.req, 'completed', cmd.spec.label + ' 완료');
    this.clear(entity);
  }

  /** 실패 — **이전 상태로 복원**하고 사유를 표시한다. */
  private fail(entity: string, reasonCode: string, detail: string): void {
    const cmd = this.active.get(entity);
    if (!cmd) return;

    this.positionPct.set(entity, cmd.previousPct);
    this.physicalState.set(entity, cmd.previousState);

    this.emitResult(cmd.req, {
      status: 'failed',
      stage: 'settled',
      progress_pct: null,
      detail: detail + ' — 이전 상태(' + cmd.previousState + ')로 복원',
      reason_code: reasonCode,
      restored: true,
    });

    this.record(cmd.req, 'failed', detail);
    this.clear(entity);
  }

  private clear(entity: string): void {
    const cmd = this.active.get(entity);
    cmd?.timers.forEach((t) => clearTimeout(t));
    this.active.delete(entity);
    this.onActivityChange?.(entity);
  }

  private emitResult(
    req: CommandRequest,
    partial: Omit<CommandResult, 'command_id' | 'entity' | 'action' | 'expires_at' | 'ts'>,
  ): void {
    const result: CommandResult = {
      command_id: req.command_id,
      entity: req.entity,
      action: req.action,
      expires_at: req.expires_at,
      ts: nowIso(),
      ...partial,
    };
    this.hub.publish(req.entity, 'command_result', result, { fromDevice: false });
  }

  // ── 감사 적재 (VZ-I-05) ────────────────────────────────────────────────────

  /**
   * 감사 기록은 **백엔드가 쓴다**(VZ-O-03). 목 서버가 그 역할을 대신하며,
   * 조작자와 시각은 클라이언트가 보낸 값이 아니라 **서버가 주입한다** —
   * 브라우저가 직접 쓰면 조작자는 자기신고가 되고 시각은 사용자 PC 시계가 된다.
   */
  private record(req: CommandRequest, result: string, detail: string): void {
    this.audit.unshift({
      command_id: req.command_id,
      entity: req.entity,
      action: req.action,
      result,
      detail,
      // 서버 주입 — 클라이언트가 보낸 값을 쓰지 않는다.
      occurred_at: nowIso(),
      actor_id: 'khw',
      actor_display_name: '김현우',
      actor_role: 'operator',
      written_by: 'mock-gateway audit-writer',
      // 클라이언트가 동봉한 책임소재 필드는 **해석하지 않고 그대로** 적재한다.
      ...(req.audit ?? {}),
    });
    if (this.audit.length > 200) this.audit.length = 200;
  }

  queryAudit(entity: string | null, limit: number): AuditRecord[] {
    const rows = entity === null ? this.audit : this.audit.filter((r) => r.entity === entity);
    return rows.slice(0, limit);
  }

  // ── 조회 ───────────────────────────────────────────────────────────────────

  getPhysicalState(entity: string): string {
    return this.physicalState.get(entity) ?? 'unknown';
  }

  getPositionPct(entity: string): number {
    return this.positionPct.get(entity) ?? 0;
  }

  isBusy(entity: string): boolean {
    return this.active.has(entity);
  }

  /** 화면의 액션 버튼 목록. 액션 어휘를 화면에 박지 않기 위해 서버가 내려준다. */
  actionsFor(entity: string): ActionSpec[] {
    return ACTION_CATALOG[entity] ?? [];
  }
}

function nowIso(): string {
  return new Date().toISOString();
}
