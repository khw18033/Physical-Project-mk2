/**
 * src/shell/missionBridge.ts (260831 신설)
 *
 * 게이트웨이의 **임무 축**(node: mission-trace)을 현재 임무 저장소에 잇는 다리.
 *
 * 탭 데이터 계층의 구독은 구역 축(zone-503)이라 임무 채널(plan 제안·trace_event ·
 * 발화 command_result)이 딸려 오지 않는다 — 임무는 장비가 아니고 zone 이 없다
 * (gateway/mission-trace.ts 의 규칙). 그래서 셸이 임무 축을 따로 구독한다.
 *
 * **셸에만 있다.** 탭① 코어(단독 빌드)는 게이트웨이가 없으므로 이 다리도 없다 —
 * 그때는 발화 패널의 로컬 매칭과 로컬 재생기가 같은 저장소를 민다(같은 매처·같은 대본).
 *
 * 받은 봉투는 탭 데이터 계층(store)에도 넣는다 — 계획은 PlanApproval(VZ-U-07)이 읽고,
 * command_result 는 명령 추적기가 요청을 정리한다. 저장소 반영은 그 다음이다.
 */

import { useEffect } from 'react';
import { activateMission, proposeMission, receiveTrace, rejectProposal, viewForMission } from '../data/scenario.ts';
import { axesOfMission } from '../scenarios/scriptScope.ts';
import { markIntegratedBuild, observeConnection, observeEnvelope, updateClientHealth } from '../shared/observability.ts';
import { enterScenarioRender } from '../shared/renderMode.ts';
import { store } from '../tabs/data/index.ts';
import { getTransport, type Envelope } from '../transport/index.ts';
import { liveFrame } from '../viewpoint/source.ts';
import { appendViewpoint } from '../viewpoint/store.ts';

type WirePlan = {
  plan_id: string;
  decision: 'pending' | 'approved' | 'rejected';
  script?: { mission_id: string; title: string; matched_keywords?: string[]; world: 'registry' | 'legacy' };
};

type WireTrace = {
  seq?: number;
  at_sec?: number;
  node_id?: string;
  status?: string;
  kind?: string;
  produced_by?: string;
  attempt?: number;
  payload?: Record<string, unknown>;
  derived_from?: string;
};

let started = false;
/** 승인 반영은 계획당 한 번 — 승인 뒤에도 plan 봉투가 여러 번 오지만(중계 단계) 재생을 다시 세우면 안 된다. */
const activatedPlans = new Set<string>();

export function startMissionBridge(): () => void {
  if (started) return () => undefined;
  started = true;

  /**
   * 자체 관측 (`VZ-O-04` · 260904) — **수신 지연과 재연결은 게이트웨이가 있을 때만 잰다.**
   * 다리가 여기서 봉투와 연결 상태를 다 보므로 계측을 다른 곳에 또 걸 이유가 없다.
   * 단독 빌드에는 이 다리가 없고, 그래서 그 둘은 「해당 없음」으로 뜬다 — 0이 아니다.
   */
  markIntegratedBuild();
  const transport = getTransport();
  observeConnection(transport.getStatus());
  const unwatch = transport.onStatus((status) => observeConnection(status));

  const unsubscribe = transport.subscribe(
    { entity: '*', node: 'mission-trace', channel: '*' },
    (envelope) => {
      observeEnvelope(envelope);
      store.apply(envelope);
      if (envelope.channel === 'plan') applyPlan(envelope);
      if (envelope.channel === 'trace_event') applyTrace(envelope);
      if (envelope.channel === 'robot_state' || envelope.channel === 'detection') applyViewpoint(envelope);
    },
    'all',
  );
  // 임무 축 구독 하나. 탭 데이터 계층의 구역 축 구독은 그쪽이 센다.
  updateClientHealth({ subscriptions: 1 });

  return () => {
    unsubscribe();
    unwatch();
    updateClientHealth({ subscriptions: 0 });
    started = false;
  };
}

function applyPlan(envelope: Envelope): void {
  const plan = envelope.payload as WirePlan | null;
  if (!plan?.script) return; // 데모 계획(robot-01)은 임무 저장소와 무관하다.
  if (plan.decision === 'pending') {
    proposeMission({
      origin: 'script',
      missionId: plan.script.mission_id,
      title: plan.script.title,
      keywords: plan.script.matched_keywords ?? [],
      planId: plan.plan_id,
      world: plan.script.world,
    });
    return;
  }
  if (plan.decision === 'approved') {
    if (activatedPlans.has(plan.plan_id)) return;
    activatedPlans.add(plan.plan_id);
    // 재생 머리는 게이트웨이의 trace_event 가 민다 — 로컬 타이머를 세우지 않는다.
    activateMission(plan.script.mission_id, 'remote');
    // registry 세계 대본만 scenario 렌더 모드에 들어간다 (자동 · VZ-U-07 승인 뒤).
    // 구판 세계(legacy)는 탭②~⑤에 따라 움직일 것이 없다 — 안내 띠는 셸이 그린다.
    if (plan.script.world === 'registry') {
      const view = viewForMission(plan.script.mission_id);
      if (view !== null) {
        enterScenarioRender({
          missionId: view.missionId,
          title: view.label,
          cast: view.cast,
          axes: axesOfMission(view.missionId),
          playing: true, // 승인 재생 — 모드 스위치의 정지 미리보기와 화면 문구가 다르다.
        });
      }
    }
    return;
  }
  rejectProposal(); // 거부하면 아무것도 재생되지 않는다.
}

/**
 * 뷰포인트 채널 수신 (260909 §6). **라이브 입구 하나를 지난다** (`viewpoint/source.ts`) —
 * 이 봉투가 목 게이트웨이의 대본 재생에서 왔는지 실제 로봇에서 왔는지 여기서 묻지 않고,
 * 물을 방법도 없다. 실제 장치가 붙는 날 고칠 곳이 없다는 것이 이 함수의 뜻이다.
 */
function applyViewpoint(envelope: Envelope): void {
  const payload = envelope.payload as Record<string, unknown> | null;
  if (!payload) return;
  const frame = liveFrame({ channel: envelope.channel, payload });
  if (frame === null) return; // 형식에 안 맞으면 버린다 — 지어 채우지 않는다.
  appendViewpoint(envelope.entity, typeof payload.at_sec === 'number' ? payload.at_sec : 0, frame);
}

function applyTrace(envelope: Envelope): void {
  const wire = envelope.payload as WireTrace | null;
  if (!wire) return;
  receiveTrace(envelope.entity, {
    seq: wire.seq ?? 0,
    atSec: wire.at_sec ?? 0,
    nodeId: wire.node_id ?? '',
    status: (wire.status ?? 'pending') as never,
    kind: wire.kind ?? '',
    producedBy: (wire.produced_by ?? 'backend') as never,
    attempt: wire.attempt,
    payload: wire.payload,
    derivedFrom: wire.derived_from,
  });
}

/** 셸 최상위에서 한 번 — 탭 데이터 계층과 같은 수명이다. */
export function useMissionBridge(): void {
  useEffect(() => startMissionBridge(), []);
}
