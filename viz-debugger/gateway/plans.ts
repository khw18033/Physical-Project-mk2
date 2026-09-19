// 이식: web-dashboard/mock-gateway/plans.ts @ 700ed91 — 대본 재생(260831)에서 proposeScript()·onScriptApproved 추가
//
// 대본(시나리오 대본) 경로가 더해졌다. 발화가 대본에 매칭되면 **같은 승인 절차**(VZ-U-07 ·
// REQ-1506)를 지나야 한다 — 새 승인 경로를 만들면 「승인 전 실행 없음」이 두 벌이 된다.
// 대본 계획은 승인 뒤 구간 시뮬레이션(dispatchFrom)이 아니라 **대본 재생기**로 넘어간다.
// 구간(segments)은 대본의 마일스톤이고, 재생기가 태스크 상태를 접어 갱신해 준다.
/**
 * mock-gateway/plans.ts
 *
 * 계획 승인 (VZ-U-07) + 서브태스크 진행 (VZ-U-05).
 *
 * **중계자는 백엔드다** (BE-X-04). AI는 계획 **생성**(AI-D-01)과 **검증**(AI-D-02)까지고,
 * 계획을 가시화에 전달하고 승인·거부를 받아 승인된 계획만 엣지·로봇으로 발행하는
 * 왕복 중계는 백엔드가 한다. 그래서 이 엔진은 **백엔드 역할**로 동작하고,
 * AI는 계획의 **출처**로만 근거(provenance)에 남는다.
 *
 * **승인 전에는 실행되지 않는다.** 이게 이 파일의 두 번째 규칙이다 —
 * 승인 없이 자동 실행하면 사고가 났을 때 "AI가 했다"로 끝나 책임소재가 성립하지 않는다.
 * 그래서 서버가 pending 상태로 계획을 내려놓고, plan_decision을 받기 전까지는
 * 진행 이벤트를 **하나도** 발행하지 않는다.
 *
 * 진행 상태는 **이벤트 기반**이다. 구간 상태는 하달·시작·완료·실패 네 시점에만 바뀌므로
 * 주기 폴링은 전부 낭비다.
 */

import { say, type Text } from './i18n.ts';
import { SCENARIO_TIMING } from './config.ts';
import type { Hub } from './hub.ts';

export type SegmentStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped';

export type PlanSegment = {
  index: number;
  total: number;
  title: Text;
  /** 이 구간이 지나는 구역. 여러 구역에 걸친 계획은 구역별 구간과 순서를 함께 본다. */
  zone: Text;
  /** 대본 계획의 구간 = 마일스톤. 재생기가 태스크 상태를 접어 이 id 로 갱신한다. */
  milestone_id?: string;
  status: SegmentStatus;
  /** 소요 시간(초). 완료된 구간만. */
  elapsed_s: number | null;
  /** 실패 구간의 상세 — **어느 단계에서 왜**인지. */
  failure: {
    /** 하달 → ACK → 수행 중 어느 단계에서 멈췄나. */
    failed_stage: Text;
    reason: Text;
    dispatched_at: string;
    acked_at: string | null;
    failed_at: string;
    /** 이 판정이 어디서 왔는가. 화면이 근거를 되짚을 수 있어야 한다. */
    judged_by: Text;
  } | null;
};

/**
 * 근거 한 조각이 **누구의 산출물인가**.
 *
 * 승인이 안 먹었을 때 어느 구간에서 끊겼는지 보려면, 근거를 한 덩어리로 보여주면 안 된다.
 * AI가 만든 것(계획·검증)과 백엔드가 중계한 것(전달·승인 수신·발행)이 구분되어야
 * "AI가 계획을 못 만든 것"과 "백엔드 중계가 끊긴 것"을 화면에서 가를 수 있다.
 */
export type ProducedBy = 'ai' | 'backend' | 'human';

export type ProvenanceStep = {
  stage: Text;
  produced_by: ProducedBy;
  /** 어느 요구사항이 이 구간의 담당을 정하는가. */
  ref: string;
  at: string | null;
  detail: Text;
};

/** VZ-U-07 — 승인 화면이 펼쳐 보여야 하는 근거. */
export type PlanEvidence = {
  /** 전역 임무 — 이 계획이 어디서 나왔나. */
  mission: { id: string; title: Text; requested_by: Text; created_at: string };
  /** 구역 분할 — 어느 구역을 어떤 순서로. */
  zones: Array<{ zone: Text; order: number; segment_count: number }>;
  /** 검증 결과 — 무슨 검증을 통과했나. **AI 산출물이다**(AI-D-02). */
  validations: Array<{ rule: Text; result: 'pass' | 'warn'; detail: Text }>;
  /** 생성기·입력 맥락 버전. 같은 입력에 다른 결과가 나올 때 되짚는 근거. */
  generator: { name: string; version: string; context_version: string };
  /** 어디까지가 AI 산출물이고 어디부터가 백엔드 중계인가. */
  provenance: ProvenanceStep[];
};

export type Plan = {
  plan_id: string;
  entity: string;
  /** pending → approved/rejected. **pending 동안 진행 이벤트가 없다.** */
  decision: 'pending' | 'approved' | 'rejected';
  decided_at: string | null;
  reject_reason: Text | null;
  evidence: PlanEvidence;
  segments: PlanSegment[];
  /**
   * 승인된 계획에 붙는 상관 키 (BE-X-01).
   * **백엔드가 발급하고 plan_id와의 매핑도 백엔드가 보유한다.**
   */
  command_id: string | null;
  /**
   * 이 계획이 어느 경로로 왔고 승인이 어디로 돌아가는가 (BE-X-04).
   * 화면이 "AI와 직접 주고받는 것이 아니다"를 표시하는 근거.
   */
  route: {
    generated_by: Text;
    delivered_by: Text;
    decision_returns_to: Text;
    dispatches_to: Text;
  };
  /** 승인 수신 → 엣지·로봇 발행 사이의 중계 상태. */
  relay_stage: 'awaiting_decision' | 'decision_received' | 'dispatched' | 'halted';
  /**
   * 이 계획이 **대본 조회**에서 나왔는가 (260831). 있으면 LLM이 아니라 키워드 대조다 —
   * 화면이 그 사실을 감추지 않도록 맞은 키워드와 대본 ID 를 그대로 싣는다 (REQ-1207의 정신).
   */
  script?: {
    mission_id: string;
    title: Text;
    matched_keywords: string[];
    world: 'registry' | 'legacy';
  };
};

/** proposeScript() 의 입력 — 대본(또는 옛 편)에서 계획을 만드는 데 필요한 만큼만. */
export type ScriptPlanSeed = {
  missionId: string;
  /** 화면이 그리는 임무 이름. 만들 때는 표지일 수 있다 (`gateway/i18n.ts`). */
  title: Text;
  world: 'registry' | 'legacy';
  utteranceText: string;
  matchedKeywords: string[];
  /** 등장 장비가 속한 구역. 구판 세계는 구역과 연결되지 않으므로 **표기용**이다. */
  zone: Text;
  milestones: Array<{ id: string; title: string }>;
};

function nowIso(): string {
  return new Date().toISOString();
}

const SEGMENT_TITLES = [
  { title: say('seg.start'), zone: 'zone-503' },
  { title: say('seg.corridor'), zone: 'zone-503' },
  { title: say('seg.junction'), zone: 'zone-504' },
  { title: say('seg.avoid'), zone: 'zone-504' },
  { title: say('seg.stopAtEntry'), zone: 'zone-503' },
];

export class PlanEngine {
  private readonly hub: Hub;
  private plan: Plan | null = null;
  private timers: Array<ReturnType<typeof setTimeout>> = [];
  private commandSeq = 0;
  /** 다음 실행에서 실패시킬 구간 번호(1-base). null이면 전부 성공. */
  failSegment: number | null = null;

  constructor(hub: Hub) {
    this.hub = hub;
  }

  /**
   * 계획을 하나 만들어 **승인 대기 상태로** 내려놓는다. 아직 실행되지 않는다.
   *
   * 근거에는 AI가 만든 구간(생성·검증)과 백엔드가 한 구간(중계 전달)이 시각과 함께
   * 나뉘어 들어간다 — 나중에 승인이 안 먹었을 때 어디서 끊겼는지 보기 위한 것이다.
   */
  propose(): Plan {
    this.reset();

    const planId = 'plan-' + Date.now().toString(36);
    const generatedAt = new Date(Date.now() - 1_200).toISOString();
    const validatedAt = new Date(Date.now() - 400).toISOString();

    this.plan = {
      plan_id: planId,
      entity: 'robot-01',
      decision: 'pending',
      decided_at: null,
      reject_reason: null,
      command_id: null,
      relay_stage: 'awaiting_decision',
      route: {
        generated_by: say('relay.aiPlanner'),
        delivered_by: say('relay.backend'),
        decision_returns_to: say('relay.backend'),
        dispatches_to: say('relay.edgeRobot'),
      },
      evidence: {
        mission: {
          id: 'msn-503-01',
          title: say('plan.demoTitle'),
          requested_by: say('plan.byOperator'),
          created_at: nowIso(),
        },
        zones: [
          { zone: 'zone-503', order: 1, segment_count: 3 },
          { zone: 'zone-504', order: 2, segment_count: 2 },
        ],
        validations: [
          { rule: say('val.noConflict'), result: 'pass', detail: say('val.noConflict.d') },
          { rule: say('val.battery'), result: 'pass', detail: say('val.battery.d') },
          { rule: say('val.zoneRight'), result: 'pass', detail: say('val.zoneRight.d') },
          { rule: say('val.mapFresh'), result: 'warn', detail: say('val.mapFresh.d') },
        ],
        generator: { name: 'plan-generator', version: '0.4.2', context_version: 'ctx-2026-08-20T09:00Z' },
        provenance: [
          {
            stage: say('prov.generate'),
            produced_by: 'ai',
            ref: 'AI-D-01',
            at: generatedAt,
            detail: say('prov.generate.d'),
          },
          {
            stage: say('prov.validate'),
            produced_by: 'ai',
            ref: 'AI-D-02',
            at: validatedAt,
            detail: say('prov.validate.d'),
          },
          {
            stage: say('prov.deliver'),
            produced_by: 'backend',
            ref: 'BE-X-04',
            at: nowIso(),
            detail: say('prov.deliver.ai'),
          },
        ],
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
   * 대본 계획을 승인 시 재생으로 넘기는 훅. server.ts 가 ScriptEngine 을 연결한다.
   * 엔진이 재생기를 직접 알지 않게 하려고 콜백으로 둔다 (permissionCheck 와 같은 방식).
   */
  onScriptApproved: ((plan: Plan) => void) | null = null;

  /**
   * **대본 조회에서 나온 계획 제안** (260831 · VZ-U-07 · REQ-1506).
   *
   * 발화가 대본에 매칭되면 여기로 온다. 데모 계획(propose)과 같은 승인 절차를 지나며,
   * **승인 전에는 재생이 하나도 일어나지 않는다.** 구간은 대본의 마일스톤이고,
   * 근거에는 「이것은 LLM이 아니라 키워드 대조」라는 사실이 그대로 실린다 (REQ-1207).
   */
  proposeScript(seed: ScriptPlanSeed): Plan {
    this.reset();

    const planId = 'plan-' + Date.now().toString(36) + '-scr';
    const now = nowIso();

    this.plan = {
      plan_id: planId,
      // 계획의 대상은 장비가 아니라 임무다. 임무 entity 는 mission-trace 노드에 등록돼
      // 있어 구역 구독(zone-503)에는 딸려 오지 않는다 — 셸이 임무 축을 따로 구독한다.
      entity: seed.missionId,
      decision: 'pending',
      decided_at: null,
      reject_reason: null,
      command_id: null,
      relay_stage: 'awaiting_decision',
      script: {
        mission_id: seed.missionId,
        title: seed.title,
        matched_keywords: [...seed.matchedKeywords],
        world: seed.world,
      },
      route: {
        generated_by: say('relay.scriptLookup'),
        delivered_by: say('relay.backend'),
        decision_returns_to: say('relay.backend'),
        dispatches_to: say('relay.scriptPlayer'),
      },
      evidence: {
        mission: {
          id: seed.missionId,
          title: seed.title,
          requested_by: say('plan.byUtterance'),
          created_at: now,
        },
        zones: [{ zone: seed.zone, order: 1, segment_count: seed.milestones.length }],
        validations: [
          {
            rule: say('val.scriptMatch'),
            result: 'pass',
            detail: say('val.scriptMatch.d', { keywords: seed.matchedKeywords.join(' · '), id: seed.missionId }),
          },
          seed.world === 'registry'
            ? {
                rule: say('val.castReal'),
                result: 'pass' as const,
                detail: say('val.castReal.d'),
              }
            : {
                rule: say('val.worldLink'),
                result: 'warn' as const,
                detail: say('val.worldLink.d'),
              },
        ],
        generator: { name: 'script-library', version: '260831', context_version: seed.missionId },
        provenance: [
          {
            stage: say('prov.lookup'),
            produced_by: 'backend',
            ref: 'REQ-1207',
            at: now,
            detail:
              say('prov.lookup.d', { text: seed.utteranceText }),
          },
          {
            stage: say('prov.deliver'),
            produced_by: 'backend',
            ref: 'BE-X-04',
            at: now,
            detail: say('prov.deliver.script'),
          },
        ],
      },
      segments: seed.milestones.map((m, i) => ({
        index: i + 1,
        total: seed.milestones.length,
        title: m.title,
        zone: seed.zone,
        milestone_id: m.id,
        status: 'pending',
        elapsed_s: null,
        failure: null,
      })),
    };

    this.publishPlan();
    return this.plan;
  }

  /**
   * 재생기가 태스크 상태를 마일스톤 단위로 접은 결과를 구간 상태에 반영한다.
   * 대본 계획의 구간 진행은 시뮬레이션이 아니라 **대본 기록 열의 파생**이다.
   */
  applyScriptMilestones(planId: string, statuses: Record<string, SegmentStatus>): void {
    const plan = this.plan;
    if (plan === null || plan.plan_id !== planId || plan.script === undefined) return;
    let changed = false;
    for (const seg of plan.segments) {
      const next = seg.milestone_id !== undefined ? statuses[seg.milestone_id] : undefined;
      if (next !== undefined && next !== seg.status) {
        seg.status = next;
        changed = true;
      }
    }
    if (changed) this.publishProgress();
  }

  /**
   * 승인/거부. **백엔드 채널로 들어와 백엔드 채널로 처리된다** (BE-X-04).
   *
   * 승인이어도 곧바로 구간이 돌지 않는다 — 승인 수신과 엣지·로봇 발행 사이에
   * 중계 구간을 한 박자 두어, 화면에서 "승인이 AI로 바로 간 것이 아니라 백엔드를
   * 거쳐 발행된다"가 눈에 보이게 한다. 거부도 같은 경로로 백엔드에 남는다.
   */
  decide(planId: string, decision: 'approve' | 'reject', reason?: string): { ok: boolean; message: Text; relayedBy: Text } {
    const relayedBy = say('relay.backend');
    const plan = this.plan;
    if (plan === null || plan.plan_id !== planId) {
      return { ok: false, message: say('plan.notFound', { id: planId }), relayedBy };
    }
    if (plan.decision !== 'pending') {
      return { ok: false, message: say('plan.alreadyDecided', { decision: plan.decision }), relayedBy };
    }

    plan.decided_at = nowIso();
    plan.relay_stage = 'decision_received';

    if (decision === 'reject') {
      plan.decision = 'rejected';
      plan.reject_reason = reason ?? say('plan.noReason');
      plan.relay_stage = 'halted';
      plan.evidence.provenance.push({
        stage: say('prov.rejected'),
        produced_by: 'backend',
        ref: 'BE-X-04',
        at: plan.decided_at,
        detail: say('prov.rejected.d', { reason: plan.reject_reason }),
      });
      this.publishPlan();
      return { ok: true, message: say('plan.rejected', { reason: plan.reject_reason }), relayedBy };
    }

    plan.decision = 'approved';
    this.commandSeq += 1;
    // BE-X-01 — 상관 키는 백엔드가 발급하고 plan_id와의 매핑도 백엔드가 보유한다.
    plan.command_id = 'cmd-' + Date.now().toString(36) + '-p' + String(this.commandSeq).padStart(2, '0');
    plan.evidence.provenance.push({
      stage: say('prov.approved'),
      produced_by: 'backend',
      ref: 'BE-X-04',
      at: plan.decided_at,
      detail: say('prov.approved.d', { key: plan.command_id }),
    });
    this.publishPlan();

    // 승인 수신 → 엣지·로봇 발행. 이 한 박자가 중계 구간이다.
    this.timers.push(
      setTimeout(() => {
        if (this.plan !== plan || plan.decision !== 'approved') return;
        plan.relay_stage = 'dispatched';
        plan.evidence.provenance.push(
          plan.script !== undefined
            ? {
                stage: say('prov.playback'),
                produced_by: 'backend',
                ref: 'BE-X-04',
                at: nowIso(),
                detail:
                  say('prov.playback.d'),
              }
            : {
                stage: say('prov.dispatch'),
                produced_by: 'backend',
                ref: 'BE-X-04 → HW-R-05',
                at: nowIso(),
                detail: say('prov.dispatch.d'),
              },
        );
        this.publishPlan();
        // 대본 계획은 구간 시뮬레이션이 아니라 재생기로 넘어간다. 구간 상태는
        // 재생기가 태스크 상태를 접어 applyScriptMilestones() 로 돌려준다.
        if (plan.script !== undefined) this.onScriptApproved?.(plan);
        else this.dispatchFrom(1);
      }, SCENARIO_TIMING.PLAN_RELAY_MS),
    );

    return { ok: true, message: say('plan.approved', { key: plan.command_id }), relayedBy };
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
            failed_stage: say('fail.whileRunning'),
            reason: say('fail.obstacle'),
            dispatched_at: dispatchedAt,
            acked_at: new Date(Date.parse(dispatchedAt) + 500).toISOString(),
            failed_at: nowIso(),
            judged_by: say('fail.judgedBy'),
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
        relay_stage: this.plan.relay_stage,
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
