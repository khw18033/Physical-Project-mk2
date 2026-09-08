/**
 * src/generate/proposal.ts (260907 신설 — 9단계 · 지시서 §6)
 *
 * **생성 결과 → 제안.** 화면에 붙는 두 칸이 여기서 만난다.
 *
 * ```
 * 의도 분석 · 마일스톤 분리   VZ-G-01   generateMission()  ← 모델
 * 태스크 생성                VZ-G-02   solveDeps()        ← 규칙 (모델이 아니다)
 * ```
 *
 * ## 순수 함수다
 *
 * React 도, 저장소도, fetch 도 모른다. 받은 응답 하나를 제안 하나로 편다. 그래서
 * `verify:proposal-gate` 가 Node 에서 그대로 돌려 「승인 없이는 캔버스에 올라가지
 * 않는다」를 실제로 확인할 수 있다 — 화면을 띄워 눌러 보는 검사는 검사가 아니다.
 *
 * ## 제안은 실행이 아니다
 *
 * 이 파일이 만드는 것은 **그릴 수 있는 임무 하나와 그 근거**이고, 그것을 현재 임무로
 * 올리는 일은 하지 않는다. 승인 선(`VZ-U-07`)은 `data/scenario.ts` 의 상태 기계가
 * 지킨다 — 여기서 `activate` 를 부를 수 있으면 그 선은 이미 없는 것이다.
 */

import type { MissionView } from '../data/scenario.ts';
import type { AiProvenance, OverwrittenField } from '../shared/provenance.ts';
import type { NodeKind, Task } from '../model/types.ts';
import { planShapeWarnings } from './planShape.ts';
import { solveDeps, type GeneratedNode } from './solveDeps.ts';
import type { GeneratedMission, GenerateResult } from './types.ts';

const NODE_KINDS: readonly NodeKind[] = ['sense', 'decide', 'act', 'verify', 'report'];

/** `extra` 는 서비스가 그대로 넘긴 자루다. 없는 칸을 지어내지 않고 타입만 좁힌다. */
function str(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}
function num(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

/**
 * 응답 하나 → 생성 근거.
 *
 * **요약하지 않는다.** `types.ts` 가 적어 둔 규칙과 같다 — 네 축을 가중합해 점수 하나로
 * 뭉개지 않듯, 근거도 「모델 이름 한 줄」로 뭉개지 않는다.
 */
export function provenanceOf(result: GenerateResult): AiProvenance {
  // 발화와 계획의 모양이 맞는가 (11단계). **경고이지 차단이 아니다.**
  //
  // 되돌아가는 엣지는 지금 언제나 0건이다 — 생성 경로가 그것을 안 만든다(§5). 그래서
  // 루프를 요구한 발화는 늘 잡힌다. 그것이 맞다: 못 만드는 것을 못 만든다고 적는 것이다.
  const shapeWarnings = result.mission == null ? [] : planShapeWarnings(
    result.mission.utterance?.text ?? '',
    solvedDepsFor(result.mission).deps,
  );
  const extra = (result.extra ?? {}) as Record<string, unknown>;
  const rules = extra.rules_applied;
  const overwritten = extra.overwritten;
  return {
    producedBy: 'ai',
    engine: result.engine,
    model: result.model,
    stub: extra.stub === true,
    promptDigest: str(extra.prompt_digest),
    promptChars: num(extra.prompt_chars),
    grammar: result.grammar ?? null,
    // 배열이 아니면 **null 이다** — 「규칙이 0개였다」와 「서비스가 안 알려줬다」는 다른 말이다.
    rules: Array.isArray(rules) ? rules.map((rule) => String(rule)) : null,
    overwritten: Array.isArray(overwritten) ? (overwritten as OverwrittenField[]) : [],
    schemaErrors: result.schema_errors ?? [],
    elapsedSec: result.elapsed_sec,
    shapeWarnings,
    examplesGiven: num(extra.examples_given) ?? 0,
    placesGiven: extra.places_given === true,
    equipmentGiven: num(extra.equipment_given) ?? 0,
    nodeKindsGiven: extra.node_kinds_given === true,
  };
}

/**
 * `VZ-G-02` 의 규칙 부분 — 모델이 낸 노드 목록에 `deps` 를 매단다.
 *
 * ## 지금은 노드가 0개다 — 그것을 감추지 않는다
 *
 * 확정된 프롬프트(B)의 규칙 9는 「`tasks` 는 빈 배열 `[]` 로 둔다. 태스크 분해는 다음
 * 단계가 한다」이고, 8단계는 그 형식을 바꾸지 않기로 했다. 그래서 이 함수는 **거의 항상
 * 빈 결과를 낸다.** 그래도 부른다 — 규칙은 붙어 있고, 노드가 오는 날 바로 돈다.
 *
 * 대안은 둘 다 나쁘다. 화면에서 태스크 칸을 지우면 「`VZ-G-02` 의 어디까지 됐나」가
 * 화면에서 사라지고, 여기서 노드를 지어내면 그것은 **모델이 낸 것이 아닌 것을 모델의
 * 것으로 그리는 일**이다. 0개를 0개라고 적는 것이 이 저장소의 규칙이다.
 */
export type SolvedDeps = {
  /** 노드 id → 의존. **규칙이 매단 것이다** — 모델이 낸 `deps` 는 여기 없다. */
  deps: Record<string, string[]>;
  nodeCount: number;
  edgeCount: number;
  /**
   * 모델이 규칙을 어기고 적은 의존의 수. **0이 정상이다** (규칙 14: 「deps 는 빈 배열로
   * 둔다」). 0이 아니면 버렸다는 사실을 기록에 남긴다 — 조용히 버리면 「모델이 지시를
   * 지켰는가」를 영영 못 잰다. `utterance` 덮어쓰기와 같은 규칙이다.
   */
  modelDeps: number;
};

/**
 * 모델이 낸 노드 목록 → **규칙이 매단 의존.** `VZ-G-02` 의 규칙 절반이 도는 자리다.
 *
 * 화면과 측정 경로가 **이 함수 하나**를 같이 쓴다. 두 벌이면 표의 그래프 숫자와 화면에
 * 그려지는 그래프가 조용히 갈라진다.
 */
export function solvedDepsFor(mission: GeneratedMission): SolvedDeps {
  const nodes: GeneratedNode[] = [];
  let modelDeps = 0;
  for (const milestone of mission.milestones ?? []) {
    for (const task of milestone.tasks ?? []) {
      modelDeps += (task.deps ?? []).length;
      nodes.push({
        id: task.task_id,
        title: task.title,
        // 모르는 라벨은 **지어내지 않고** 관측으로 떨어뜨리지도 않는다 — 규칙의 기본값이
        // 「제약 없음」인 `sense` 라서, 모르는 것을 여기 넣으면 없던 병렬이 생긴다.
        nodeKind: NODE_KINDS.includes(task.node_kind as NodeKind) ? (task.node_kind as NodeKind) : 'act',
        target: (task as { target?: string | null }).target ?? null,
        milestoneId: milestone.milestone_id,
      });
    }
  }
  if (nodes.length === 0) return { deps: {}, nodeCount: 0, edgeCount: 0, modelDeps };
  const solved = solveDeps(nodes);
  return {
    deps: solved.deps,
    nodeCount: nodes.length,
    edgeCount: Object.values(solved.deps).reduce((sum, deps) => sum + deps.length, 0),
    modelDeps,
  };
}

/**
 * 같은 임무를, **`deps` 만 규칙이 매단 것으로 바꿔서** 돌려준다.
 *
 * 채점되는 것도 화면이 그리는 것도 이 객체다. 모델의 원본은 버리지 않는다 —
 * 실행 기록의 `raw/` 가 그대로 들고 있고, 몇 건을 버렸는지는 `modelDeps` 가 센다.
 */
export function withSolvedDeps(mission: GeneratedMission): { mission: GeneratedMission; solved: SolvedDeps } {
  const solved = solvedDepsFor(mission);
  if (solved.nodeCount === 0) return { mission, solved };
  return {
    mission: {
      ...mission,
      milestones: (mission.milestones ?? []).map((milestone) => ({
        ...milestone,
        tasks: (milestone.tasks ?? []).map((task) => ({ ...task, deps: solved.deps[task.task_id] ?? [] })),
      })),
    },
    solved,
  };
}

export function tasksFromGenerated(mission: GeneratedMission): {
  tasks: Task[];
  nodeCount: number;
  edgeCount: number;
  modelDeps: number;
} {
  const solved = solvedDepsFor(mission);
  const tasks: Task[] = [];
  for (const milestone of mission.milestones ?? []) {
    for (const task of milestone.tasks ?? []) {
      tasks.push({
        id: task.task_id,
        title: task.title,
        deps: solved.deps[task.task_id] ?? [],
        target: (task as { target?: string | null }).target ?? null,
        actionItems: [],
        milestone: milestone.milestone_id,
        ...(NODE_KINDS.includes(task.node_kind as NodeKind) ? { nodeKind: task.node_kind as NodeKind } : {}),
      });
    }
  }
  return { tasks, nodeCount: solved.nodeCount, edgeCount: solved.edgeCount, modelDeps: solved.modelDeps };
}

/**
 * 생성된 임무 하나를 **화면이 그릴 수 있는 모양**으로.
 *
 * `durationSec` 은 **0이다.** 대본이 아니라 계획이라 흘러갈 시간이 없다 — 재생할 사건이
 * 없다는 사실을 0이 그대로 말한다. 지어낸 길이를 넣으면 되감기 슬라이더가 있지도 않은
 * 기록을 가리킨다.
 */
export function viewFromGenerated(mission: GeneratedMission, label: string): MissionView {
  const { tasks } = tasksFromGenerated(mission);
  return {
    missionId: mission.mission_id,
    label,
    // 장소·장비 어휘가 registry 세계의 것이다 — 옛 편(415호)의 세계가 아니다.
    world: 'registry',
    utteranceText: mission.utterance?.text ?? '',
    durationSec: 0,
    milestones: (mission.milestones ?? []).map((milestone) => ({
      id: milestone.milestone_id,
      title: milestone.title,
      assignedTargets: milestone.assigned_targets ?? [],
      // 정적 상태를 적지 않는다 — 마일스톤 상태는 태스크를 접은 결과다. 접을 것이
      // 없으면 화면이 pending 으로 그린다.
      staticStatus: null,
    })),
    tasks,
    // **대본이 아니다.** 흘려보낼 사건이 없다 — 이 빈 배열이 「아직 아무 일도 없었다」다.
    events: [],
    cast: [...new Set((mission.milestones ?? []).flatMap((milestone) => milestone.assigned_targets ?? []))],
    // 실측 3행은 남이 줄 데이터다. 지어내지 않는다 (`VZ-D-07` · 8/31 결정).
    hardware: null,
    params: {},
    map: null,
    // 재탐색 루프를 지어내지 않는다 (§5 — 「사용자가 준 단계를 더하지 않는다」).
    refEdges: [],
  };
}
