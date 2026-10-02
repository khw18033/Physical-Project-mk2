import type { MissionTaskStatus } from '../shared/statusTypes.ts';

export type TaskStatus = MissionTaskStatus;
export type Connection = 'online' | 'offline' | 'maintenance';
export type Hardware = { id: string; kind: string; connection: Connection; battery: number; rssi: number; latency: number; ip: string; firmware: string; temperature: number; heartbeat: string };
/**
 * **액션 아이템이 기록 열로 흐르기 위한 정의** (260920 — 명령 기록 합류 §5).
 *
 * 대본은 **정의**를 들고, 재생기가 그것을 `commanded` · `answered` · `expired` 사건으로
 * 흘리고, 화면은 흘러온 것만 접는다. 선택 필드라 이 값이 없는 옛 편은 한 글자도 안
 * 고치고 유효하고, 흐르지도 않는다.
 *
 * 액션 아이템의 `id` 가 곧 목에서의 `commandId` 다 — 새 식별자를 만들지 않는다.
 */
export type ActionItemCommand = {
  /** 명령이 나간 시각. 태스크 사건과 **같은 축**이다. */
  atSec: number;
  /** 로봇에 낸 명령 이름 (`scan_mission` · `turn` · `move_forward` …). */
  action: string;
  /**
   * **실제로 실려 나간 값.** 화면에 적힌 계획값(`params`)이 아니다 — 시험에서 둘이
   * 갈리는 자리가 있어(`TEST_FORWARD_M`) 따로 든다. `robotSession.ts` 가 못박아 둔 원칙이다.
   */
  parameters: Record<string, number>;
  /** 누가 눌렀나. 없으면 `mission` — 대본의 명령은 임무가 낸 것이다. */
  issuedBy?: 'human' | 'mission';
  /** 로봇이 돌려준 줄들. **빈 배열이 「응답이 없었다」는 뜻이 아니다** — 그것은 `expired` 가 말한다. */
  answers?: Array<{
    atSec: number;
    kind: 'acceptance' | 'status' | 'result';
    text: string;
    /** 회전 걸음 번호. 회전 보고가 아니면 없다. */
    index?: number | null;
    /** 종료 줄일 때 어떻게 끝났는가. */
    outcome?: 'done' | 'failed';
  }>;
  /** **기다림이 끝났다.** 이 칸이 있으면 「영영 안 왔다」, 없으면 「아직 기다리는 중」이다. */
  expired?: { atSec: number; waitedMs: number; reason: string };
};
export type ActionItem = { id: string; label: string; params: Record<string, string | number>; status: TaskStatus; command?: ActionItemCommand };
/**
 * 대본 재생(260831) 확장 — 대체가 아니다.
 *  - `target`: 대상 장비가 없는 태스크(임무 종료 처리)는 null. 옛 파일은 전부 문자열이다.
 *  - `milestone`: 이 태스크가 접히는 마일스톤. 옛 파일에는 없다(전부 MS-C 암묵 —
 *    적재할 때 채운다). 마일스톤 상태는 태스크 상태를 접은 결과라서 이 연결이 필요하다.
 */
/**
 * 노드 문법 5종 (260831 — 노드 분화). 마일스톤을 임의로 쪼개지 않기 위한 규칙이다:
 * sense(관측) · decide(판정) · act(구동) · verify(검증) · report(보고).
 */
export type NodeKind = 'sense' | 'decide' | 'act' | 'verify' | 'report';
export type Task = { id: string; title: string; deps: string[]; target: string | null; actionItems: ActionItem[]; milestone?: string; nodeKind?: NodeKind; evaluation?: { criteria: string[]; judgedBy: 'ai' | 'backend' | 'human' } };
/**
 * 되돌아가는 참조 엣지 (260831 — 2편 재탐색 루프). **`deps` 가 아니다** —
 * `graph/layout.ts` 의 depths() 에 순환이 들어가면 안 되므로, 레이아웃·깊이 계산에는
 * 넣지 않고 점선으로 **그리기만** 한다. 그리지 않으면 사용자는 대본이 되돌아간다는 것을 모른다.
 */
export type RefEdge = { from: string; to: string; label: string; note?: string };
/**
 * `status` 는 옛 파일의 정적 필드다 — **무시하되 지우지 않는다.** 마일스톤 상태는
 * `statusesAt()` 이 태스크 상태를 접어 돌려준다(되감기와 어긋나지 않게).
 * 태스크가 없는 마일스톤(옛 파일의 MS-A·B·D~G)만 이 정적 값으로 그린다 — 접을 재료가 없다.
 */
export type Milestone = { id: string; title: string; status?: TaskStatus; assignedTargets: string[] };
/** `payload`(평가 근거값·파생 사유)와 `derivedFrom` 은 대본 확장 — 옛 파일에는 없다. */
/**
 * `producedBy` 에 `robot` 이 있는 이유 (260920) — 로봇 응답과 **안 온 응답**(`expired`)이
 * 기록 열로 들어오면서 넷째 주체가 생겼다. `backend` 로 뭉개면 「AI·백엔드·사람 셋 중
 * 누가 만든 값인가」(논문 §4-3)에 로봇이 백엔드로 답하게 된다 — 그것은 다른 사실이다.
 */
export type ScenarioEvent = { seq: number; atSec: number; nodeId: string; status: TaskStatus; kind: string; producedBy: 'ai' | 'backend' | 'human' | 'robot'; attempt?: number; payload?: Record<string, unknown>; derivedFrom?: string };
/**
 * 번들 임무 형식. 옛 파일(MSN-260826-01)이 그대로 유효하고, 대본(MSN-260831-**)은
 * `hardware` 대신 `cast` 를 갖는다(선택 필드 — src/scenarios/types.ts 의 ScriptScenario 참조).
 */
export type Scenario = { missionId: string; utterance: { text: string; engine: string; confidence: number; audioRef: string | null }; durationSec: number; milestones: Milestone[]; hardware?: Hardware[]; tasks: Task[]; events: ScenarioEvent[] };
