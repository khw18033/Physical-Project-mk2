/**
 * src/data/plans.ts
 *
 * 계획 승인 (VZ-U-07) · 서브태스크 진행 (VZ-U-05).
 *
 * 화면은 `plan`과 `plan_progress` 두 채널을 받는다.
 *  - `plan`          : 계획 본문 + 근거 + 승인 상태. 승인/거부 시점에만 바뀐다.
 *  - `plan_progress` : 구간 상태. 하달·시작·완료·실패 **네 시점에만** 온다.
 *
 * **주기 폴링이 없다.** 구간 상태는 그 네 시점에만 바뀌므로 폴링은 전부 낭비이고,
 * 수행 결과가 로봇 상태 데이터에 실려 오므로 별도 조회 경로도 필요 없다.
 */

import { getTransport } from '../transport/index.ts';

export type SegmentStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped';

export const SEGMENT_STATUS_LABEL: Record<SegmentStatus, string> = {
  pending: '대기',
  running: '진행중',
  done: '완료',
  failed: '실패',
  // 앞 구간이 실패해 **하달 자체가 되지 않은** 구간. '대기'와 구분해야
  // "왜 5구간이 안 돌았나"가 화면에서 설명된다.
  skipped: '건너뜀',
};

export type PlanSegment = {
  index: number;
  total: number;
  title: string;
  zone: string;
  status: SegmentStatus;
  elapsed_s: number | null;
  failure: {
    failed_stage: string;
    reason: string;
    dispatched_at: string;
    acked_at: string | null;
    failed_at: string;
    judged_by: string;
  } | null;
};

export type PlanEvidence = {
  mission: { id: string; title: string; requested_by: string; created_at: string };
  zones: Array<{ zone: string; order: number; segment_count: number }>;
  validations: Array<{ rule: string; result: 'pass' | 'warn'; detail: string }>;
  generator: { name: string; version: string; context_version: string };
};

export type Plan = {
  plan_id: string;
  entity: string;
  decision: 'pending' | 'approved' | 'rejected';
  decided_at: string | null;
  reject_reason: string | null;
  evidence: PlanEvidence;
  segments: PlanSegment[];
  command_id: string | null;
};

/** 승인/거부 발행. 승인 전에는 서버가 진행 이벤트를 내보내지 않는다. */
export function decidePlan(planId: string, decision: 'approve' | 'reject', reason?: string): void {
  getTransport().decidePlan(planId, decision, reason);
}

/** 진행률 요약 — 완료 구간 수 / 전체. */
export function planProgressSummary(segments: PlanSegment[]): { done: number; total: number; failedAt: number | null } {
  const done = segments.filter((s) => s.status === 'done').length;
  const failed = segments.find((s) => s.status === 'failed');
  return { done, total: segments.length, failedAt: failed?.index ?? null };
}
