/**
 * mock-gateway/plans.ts
 *
 * 계획 승인 (VZ-U-07) + 서브태스크 진행 (VZ-U-05).
 *
 * **승인 전에는 실행되지 않는다.** 이게 이 파일의 핵심 규칙이다 —
 * 승인 없이 자동 실행하면 사고가 났을 때 "AI가 했다"로 끝나 책임소재가 성립하지 않는다.
 * 그래서 서버가 `pending` 상태로 계획을 내려놓고, `plan_decision`을 받기 전까지는
 * 진행 이벤트를 **하나도** 발행하지 않는다.
 *
 * 진행 상태는 **이벤트 기반**이다. 구간 상태는 하달·시작·완료·실패 네 시점에만 바뀌므로
 * 주기 폴링은 전부 낭비다.
 */

import { SCENARIO_TIMING } from './config.ts';
import type { Hub } from './hub.ts';

export type SegmentStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped';

export type PlanSegment = {
  index: number;
  total: number;
  title: string;
  /** 이 구간이 지나는 구역. 여러 구역에 걸친 계획은 구역별 구간과 순서를 함께 본다. */
  zone: string;
  status: SegmentStatus;
  /** 소요 시간(초). 완료된 구간만. */
  elapsed_s: number | null;
  /** 실패 구간의 상세 — **어느 단계에서 왜**인지. */
  failure: {
    /** 하달 → ACK → 수행 중 어느 단계에서 멈췄나. */
    failed_stage: string;
    reason: string;
    dispatched_at: string;
    acked_at: string | null;
    failed_at: string;
    /** 이 판정이 어디서 왔는가. 화면이 근거를 되짚을 수 있어야 한다. */
    judged_by: string;
  } | null;
};

/** VZ-U-07 — 승인 화면이 펼쳐 보여야 하는 근거. */
export type PlanEvidence = {
  /** 전역 임무 — 이 계획이 어디서 나왔나. */
  mission: { id: string; title: string; requested_by: string; created_at: string };
  /** 구역 분할 — 어느 구역을 어떤 순서로. */
  zones: Array<{ zone: string; order: number; segment_count: number }>;
  /** 검증 결과 — 무슨 검증을 통과했나. */
  validations: Array<{ rule: string; result: 'pass' | 'warn'; detail: string }>;
  /** 생성기·입력 맥락 버전. 같은 입력에 다른 결과가 나올 때 되짚는 근거. */
  generator: { name: string; version: string; context_version: string };
};

export type Plan = {
  plan_id: string;
  entity: string;
  /** pending → approved/rejected. **pending 동안 진행 이벤트가 없다.** */
  decision: 'pending' | 'approved' | 'rejected';
  decided_at: string | null;
  reject_reason: string | null;
  evidence: PlanEvidence;
  segments: PlanSegment[];
  /** 승인된 계획에 붙는 상관 키 (REQ-909). */
  command_id: string | null;
};

function nowIso(): string {
  return new Date().toISOString();
}

const SEGMENT_TITLES = [
  { title: '출발점 → 복도 진입', zone: 'zone-503' },
  { title: '복도 통과', zone: 'zone-503' },
  { title: '교차점 진입', zone: 'zone-504' },
  { title: '장애물 회피 구간', zone: 'zone-504' },
  { title: 'zone-503 입구 정지', zone: 'zone-503' },
];

export class PlanEngine {
  private readonly hub: Hub;
  private plan: Plan | null = null;
  private timers: Array<ReturnType<typeof setTimeout>> = [];
  /** 다음 실행에서 실패시킬 구간 번호(1-base). null이면 전부 성공. */
  failSegment: number | null = null;

  constructor(hub: Hub) {
    this.hub = hub;
  }

  /** 계획을 하나 만들어 **승인 대기 상태로** 내려놓는다. 아직 실행되지 않는다. */
  propose(): Plan {
    this.reset();

    const planId = 'plan-' + Date.now().toString(36);
    this.plan = {
      plan_id: planId,
      entity: 'robot-01',
      decision: 'pending',
      decided_at: null,
      reject_reason: null,
      command_id: null,
      evidence: {
        mission: {
          id: 'msn-503-01',
          title: '503 구역 수위 상승 대응 — 하류 순찰 후 게이트 앞 대기',
          requested_by: '관제 (수동 하달)',
          created_at: nowIso(),
        },
        zones: [
          { zone: 'zone-503', order: 1, segment_count: 3 },
          { zone: 'zone-504', order: 2, segment_count: 2 },
        ],
        validations: [
          { rule: '경로 충돌 없음', result: 'pass', detail: '동시 운행 대상 2대와 시공간 충돌 0건' },
          { rule: '배터리 충분', result: 'pass', detail: '예상 소모 18% · 현재 82%' },
          { rule: '구역 진입 권한', result: 'pass', detail: 'zone-503 / zone-504 모두 허용' },
          { rule: '장애물 지도 최신성', result: 'warn', detail: '지도 갱신 4분 경과 — 계획 시점 이후 변동 가능' },
        ],
        generator: { name: 'plan-generator', version: '0.4.2', context_version: 'ctx-2026-08-20T09:00Z' },
      },
      segments: SEGMENT_TITLES.map((s, i) => ({
        index: i + 1,
        total: SEGMENT_TITLES.length,
        title: s.title,
        zone: s.zone,
        status: 'pending',
        elapsed_s: null,
        failure: null,
      })),
    };

    this.publishPlan();
    return this.plan;
  }

  getPlan(): Plan | null {
    return this.plan;
  }

  /**
   * 승인/거부.
   * **승인일 때만** 진행 이벤트가 시작된다. 거부면 사유를 담아 그대로 둔다.
   */
  decide(planId: string, decision: 'approve' | 'reject', reason?: string): { ok: boolean; message: string } {
    const plan = this.plan;
    if (plan === null || plan.plan_id !== planId) {
      return { ok: false, message: '그런 계획이 없다: ' + planId };
    }
    if (plan.decision !== 'pending') {
      return { ok: false, message: '이미 ' + plan.decision + ' 처리된 계획이다' };
    }

    plan.decided_at = nowIso();

    if (decision === 'reject') {
      plan.decision = 'rejected';
      plan.reject_reason = reason ?? '(사유 미기재)';
      this.publishPlan();
      return { ok: true, message: '계획 거부 — ' + plan.reject_reason };
    }

    plan.decision = 'approved';
    plan.command_id = 'c-' + Date.now().toString(36);
    this.publishPlan();
    this.dispatchFrom(1);
    return { ok: true, message: '계획 승인 — 구간 실행 시작 (command_id=' + plan.command_id + ')' };
  }

  /**
   * 구간 실행.
   *
   * **구간은 앞이 끝나야 다음이 하달된다.** 타이머를 전부 미리 걸어 두면
   * 앞 구간이 실패해도 뒤 구간의 시작 타이머가 뒤늦게 발동해 '진행중'이 되어 버린다.
   * 그러면 "실패 뒤 구간은 하달 자체가 되지 않는다"는 표시가 거짓이 된다.
   *
   * 상태 변화 시점(시작·완료·실패)에만 발행하므로 주기 폴링이 필요 없다.
   */
  private dispatchFrom(index: number): void {
    const plan = this.plan;
    if (plan === null || plan.decision !== 'approved') return;

    const seg = plan.segments.find((s) => s.index === index);
    if (seg === undefined) return; // 마지막 구간까지 끝났다.

    const duration = SCENARIO_TIMING.PLAN_SEGMENT_MS;
    const dispatchedAt = nowIso();

    // 구간 시작 — 하달.
    seg.status = 'running';
    this.publishProgress();

    this.timers.push(
      setTimeout(() => {
        if (plan.decision !== 'approved') return;

        if (this.failSegment !== null && seg.index === this.failSegment) {
          seg.status = 'failed';
          seg.failure = {
            failed_stage: '수행 중 (ACK 이후)',
            reason: '계획 시점에 없던 장애물 감지, 회피 경로 없음',
            dispatched_at: dispatchedAt,
            acked_at: new Date(Date.parse(dispatchedAt) + 500).toISOString(),
            failed_at: nowIso(),
            judged_by: '로봇 상태 보고에 실린 결과로 판정 (HW-R-03)',
          };
          // 뒤 구간은 **하달하지 않는다.** '대기'가 아니라 '건너뜀'이어야
          // "왜 뒤 구간이 안 돌았나"가 화면에서 설명된다.
          for (const rest of plan.segments) {
            if (rest.index > seg.index) rest.status = 'skipped';
          }
          this.publishProgress();
          return;
        }

        seg.status = 'done';
        seg.elapsed_s = Math.round((duration / 1000) * 10) / 10;
        this.publishProgress();

        // 다음 구간을 이제서야 하달한다.
        this.timers.push(setTimeout(() => this.dispatchFrom(index + 1), 400));
      }, duration),
    );
  }

  private publishPlan(): void {
    if (this.plan === null) return;
    this.hub.publish(this.plan.entity, 'plan', this.plan, { fromDevice: false });
  }

  private publishProgress(): void {
    if (this.plan === null) return;
    this.hub.publish(
      this.plan.entity,
      'plan_progress',
      {
        plan_id: this.plan.plan_id,
        command_id: this.plan.command_id,
        decision: this.plan.decision,
        segments: this.plan.segments,
      },
      { fromDevice: false },
    );
  }

  reset(): void {
    this.timers.forEach((t) => clearTimeout(t));
    this.timers = [];
  }
}
