/**
 * src/capability/types.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 상태 서비스가 주는 것의 모양.** 원본은
 * `mk2-jny/perception-framework/tools/status_ui/serve.py` 이고 전달본은
 * `mk2-jny/docs/ai/status-ui-visualization-handoff.md` 다.
 *
 * ## 응답은 언어 중립이다
 *
 * 서버는 **ID 만** 준다(`function_id` · `capability_kind` · `role` · `reason_token`). 사람이 읽는
 * 글자는 `GET /api/labels` 로 따로 온다. 그래서 여기 타입에는 한국어도 영어도 없다 —
 * 화면이 `CapLabels` 로 푼다. **번역 문구를 조건식에 쓰지 않는다**(전달본 「API 연결 기준」).
 *
 * ## 모르는 값은 null 이다
 *
 * 뜯지 못한 칸은 `null` 이고 지어 채우지 않는다. `state` 를 문자열로 둔 것도 같은 이유다 —
 * `ACTIVE`·`DEGRADED`·`DISABLED` 셋이 지금 전부이지만 새 값이 오면 **원문을 그대로 적는다**
 * (전달본: 「알 수 없는 ID 는 원문을 표시하며 신규 role·kind 에도 화면이 유지되도록 한다」).
 */

/** 요구 비용. **실시간 사용률이 아니다** — manifest 에 적힌 요구량이다. */
export type CapCost = { computeUnits: number | null; memoryMb: number | null };

/** 대안 provider 하나와 그것이 떨어진 사유. */
export type CapAlternative = {
  providerId: string;
  reason: string | null;
  reasonToken: string | null;
  /** 사유의 **알맹이** — `required_hw_tag_missing` 이면 없는 그 태그. 없으면 null. */
  reasonData: string | null;
};

/** 한 노드가 한 capability 에 대해 낸 결과 — 개발자 단계가 그린다. */
export type CapNodeRow = {
  kind: string;
  /** 원본 `CapabilityState` — `ACTIVE` · `DEGRADED` · `DISABLED`. 모르는 값은 원문 그대로. */
  state: string;
  /** UI 파생 등급(`READY`·`DEGRADED`·`MISSING`·`STALE`·`BLOCKED`). 서버가 낸 것을 그대로 쓴다. */
  derivedGrade: string | null;
  providerId: string | null;
  providerVersion: string | null;
  reason: string | null;
  reasonToken: string | null;
  /** 사유의 알맹이 — 「태그가 없음」의 **그 태그**. 이것이 없으면 고칠 수가 없다. */
  reasonData: string | null;
  cost: CapCost | null;
  priority: number | null;
  requiredHwTags: readonly string[];
  /** `k=v` 로 이어 붙인 것. 서버는 객체로 준다. */
  nodeSelector: string | null;
  alternatives: readonly CapAlternative[];
};

/** 노드 하나 — 계층·자원 단계가 그린다. */
export type CapNode = {
  nodeId: string;
  /** 서버가 준 표시 이름. 없으면 null 이고 화면은 `nodeId` 를 적는다. */
  label: string | null;
  /** 계층. **자유 문자열이다** — 고정 enum 으로 제한하지 않는다(전달본). */
  role: string;
  tags: readonly string[];
  budget: CapCost | null;
  excludeProviders: readonly string[];
  rows: readonly CapNodeRow[];
};

/** 어느 노드가 그 kind 를 제공하는가. */
export type CapServedBy = {
  nodeId: string;
  role: string;
  providerId: string;
  priority: number | null;
  cost: CapCost | null;
  state: string;
};

/** 왜 이 노드에서는 안 되는가. */
export type CapWhy = {
  nodeId: string;
  role: string;
  reason: string | null;
  reasonToken: string | null;
  reasonData: string | null;
  alternatives: readonly string[];
};

/** 기능이 요구하는 capability 한 줄. */
export type CapKindRow = {
  kind: string;
  /** 프로파일에서 켜져 있는가. `false` 는 배치에서 끈 것이지 고장이 아니다. */
  activated: boolean;
  /** 아무 노드도 제공하지 않는다. */
  missing: boolean;
  servedBy: readonly CapServedBy[];
  why: readonly CapWhy[];
};

/** 부족한 kind 를 계층별 사유와 함께. */
export type CapSupplement = {
  kind: string;
  role: string;
  reason: string | null;
  reasonToken: string | null;
  reasonData: string | null;
};

/** 기능 하나 — 기능 단계가 그린다. */
export type CapFunction = {
  functionId: string;
  state: string;
  derivedGrade: string | null;
  reason: string | null;
  reasonToken: string | null;
  required: readonly CapKindRow[];
  optional: readonly CapKindRow[];
  /** 계층별 요구 비용 합계. 키는 role. */
  byRole: Readonly<Record<string, CapCost>>;
  supplement: readonly CapSupplement[];
};

/** `GET /api/functions` 한 건 — 기능·노드가 같이 온다. */
export type CapSnapshot = {
  functions: readonly CapFunction[];
  nodes: readonly CapNode[];
  /** 받은 시각(이 노트북 시계, ms). */
  receivedAtMs: number;
};

/** `GET /api/config` 중 화면이 쓰는 만큼 — 배치 모드가 폴백했는지. */
export type CapControl = {
  requested: string | null;
  active: string | null;
  reason: string | null;
};

/**
 * `GET /api/labels` — 서버가 주는 ko/en 한 쌍.
 *
 * **우리 사전(`src/i18n/`)과 섞지 않는다.** 이쪽은 상대의 어휘(기능·capability·role·사유
 * 토큰)이고 그 원천은 `config/status_ui.labels.json` 하나다. 우리가 베껴 두면 상대가 라벨을
 * 고쳤을 때 두 벌이 갈라진다 — `registry.json` 을 사본 없이 경로로 참조하는 것과 같은 규칙이다.
 */
export type CapLabelPair = { ko: string | null; en: string | null };
export type CapLabelGroup = Readonly<Record<string, CapLabelPair>>;

export type CapLabels = {
  functions: CapLabelGroup;
  capabilityKinds: CapLabelGroup;
  roles: CapLabelGroup;
  states: CapLabelGroup;
  grades: CapLabelGroup;
  reasons: CapLabelGroup;
};

/** 빈 라벨 묶음 — 아직 안 받았을 때. 화면은 그때 ID 를 그대로 적는다. */
export const EMPTY_LABELS: CapLabels = {
  functions: {}, capabilityKinds: {}, roles: {}, states: {}, grades: {}, reasons: {},
};
