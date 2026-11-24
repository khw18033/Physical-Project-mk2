/**
 * src/detect/scan/types.ts (261123 신설 — 스캔 탐지를 data_stream 으로)
 *
 * data_stream 스캔 창구의 **주고받는 모양.** 원천은 `documents/협의/스캔탐지창구_요청_VZ_261123.md` §3 이다.
 * 옛 탐지기(`src/detect/types.ts`, `:8000` `/detect/*`)와는 다른 창구라 섞지 않는다.
 */

/** 무엇을 찾는가. data_stream `targeted` 대상으로는 door → demo_door · box → demo_box · object → 직접 입력. */
export type ScanTarget = 'door' | 'box' | 'object';

export type ScanState = 'loading' | 'ready' | 'collecting' | 'running' | 'done' | 'failed' | 'cancelled';

export const SCAN_TERMINAL: readonly ScanState[] = ['done', 'failed', 'cancelled'];

export type ScanPrepareRequest = {
  scan_id: string;
  /** 장치가 스스로 밝힌 하드웨어 id (`physical/` 이 정한다). data_stream 이 소스로 바꾼다. */
  device: string;
  target: ScanTarget;
  /** `object` 일 때만 — 영어 이름(가시화가 LLM 으로 옮긴 것). */
  query: string | null;
  /** `object` 일 때만 — 발화 원문. 기록용. */
  query_ko: string | null;
  steps: number;
  step_deg: number;
};

export type ScanPrepareAnswer = {
  scan_id: string;
  state: ScanState;
  stream: string | null;
  model: string | null;
  targets: string[];
  /** 판에 쓴 프로필 번호(`profile.version`). 아직 반영 전이면 null. */
  profile_version: number | null;
  error: string | null;
};

export type ScanStatusAnswer = {
  scan_id: string;
  state: ScanState;
  angles_captured: number[];
  /** 지금 반영된 프로필 번호. `ready` 때의 값이 판의 기준이다. */
  profile_version: number | null;
  error: string | null;
};

export type ScanMarkAnswer = {
  scan_id: string;
  rotation_deg: number;
  frame_captured: boolean;
  frame_n: number | null;
  captured_at: string | null;
};

export type ScanFrameResult = {
  rotation_deg: number;
  frame_n: number | null;
  found: boolean;
  score: number | null;
  box_xyxy: [number, number, number, number] | null;
  reason: string | null;
  bearing_deg: number | null;
  distance_m: number | null;
  distance_valid: boolean | null;
  distance_source: string | null;
};

export type ScanBest = {
  rotation_deg: number;
  /** 스캔 시작 방향 기준, 시계 방향 +, −180~180. */
  bearing_deg: number;
  distance_m: number | null;
  distance_valid: boolean;
  distance_source: string | null;
  distance_note: string | null;
  /**
   * 방위가 **참고값**인 사유. 둘 중 하나다(data_stream 구현 보고 `스캔탐지_창구_구현보고_261124.md` §3-6):
   * 초점 거리를 몰라 그 각도의 정면(`rotation_deg`)으로 대신했거나, Go1 처럼 어안 보정이 없다
   * (`"reference - no fisheye correction"` — **Go1 은 늘 붙는다**). 없으면 null.
   */
  bearing_note: string | null;
  /** 그 대상의 판정 하한이 측정 전 값인가. */
  provisional: boolean;
};

/** 근거 한 줄 — `[단서 이름, 0~1, 설명]`. 이름은 data_stream 이 영어로 준다. */
export type ScanCue = { name: string; value: number | null; note: string };

export type ScanResult = {
  scan_id: string;
  state: ScanState;
  target: ScanTarget | null;
  query: string | null;
  targets: string[];
  frames: ScanFrameResult[];
  best: ScanBest | null;
  cues: ScanCue[];
  enough: boolean;
  reason: string;
  model: string | null;
  profile_version: number | null;
  /** `score` · `cues` 가 그 장 값(`frame`)인가 트랙 평균(`track`)인가. 모르면 null (요청 문서 §3-5). */
  score_basis: 'frame' | 'track' | null;
  computed_at: string | null;
  error: string | null;
};

export type ScanImageKind = 'original' | 'overlay' | 'crop';
