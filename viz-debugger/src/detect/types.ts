/**
 * src/detect/types.ts (260912 신설 — 탐지 연동 2단계-B)
 *
 * **탐지 담당이 실제로 내놓는 모양.** 우리가 그려 보낸 규약(`문서/탐지_명령규약_260910.md`)과
 * 다른 자리가 여럿이라, **우리 쪽을 저쪽에 맞췄다**(260912 결정).
 *
 * | 규약 초안 | 실제 | 어떻게 |
 * |---|---|---|
 * | `index` 0~7 | 없음 · `rotation_deg` | 우리가 유도 (`rotation_deg / step_deg`) |
 * | `door` | `found` | 이름만 다르다 |
 * | `confidence` 0~1 | `final_score` **0.27** | 확률이 아니다 — 「특징 최고값」으로 적는다 |
 * | `bbox [x,y,w,h]` | `box_xyxy [x1,y1,x2,y2]` | **우리가 변환한다** |
 * | `reason` 한 문장 | 없음 | **우리가 조립한다** (관문 넷에서) |
 *
 * 여기 적힌 것은 **받는 모양 그대로**다. 화면이 읽는 모양으로 바꾸는 것은 `parse.ts` 하나가
 * 한다 — 두 곳에서 바꾸면 한쪽만 고쳐지는 날이 온다.
 */

/** 한 각도에서 무엇을 봤나. `target_summary.json` 의 `frames[]` 한 칸. */
export type DetectFrame = {
  /** `frame_000113.jpg`. 우리 `step` 과 잇는 유일한 이름이다. */
  frame: string;
  /** **스캔 시작이 0도.** 오른쪽(시계)으로 45도씩 (0·45·…·315). */
  rotation_deg: number;
  found: boolean;
  /** 도면 기준 절대 방위. 받침대로 자세를 역산해야 나온다 — 없을 수 있다. */
  absolute_bearing_deg?: number;
  /** 깊이 추정. **문에서는 못 쓴다** — 아래 `in_valid_calibration_range` 참고. */
  rel_depth?: number;
  distance_cm?: number;
  /** `false` 면 위 `distance_cm` 은 거리가 아니다. 그리면 안 된다. */
  in_valid_calibration_range?: boolean;
};

/** 한 각도의 통과 관문. **찾았다는 판정은 점수가 아니라 이 넷이 정한다.** */
export type DetectGate = {
  required: boolean;
  passed: boolean;
  /** 색·모양 관문은 후보 중 이긴 것을 적어 준다. */
  winning_color?: string;
  winning_shape?: string;
  /** 기준영상 관문은 유사도와 임계를 적어 준다. */
  similarity?: number;
  threshold_min?: number;
  /** 채도 관문. */
  median_saturation?: number;
  min_saturation?: number;
};

/** 한 각도의 근거. `frame_0000NN/evidence.json`. */
export type DetectFrameEvidence = {
  target_class: string;
  frame: string;
  rotation_deg: number;
  /** **`[x1,y1,x2,y2]` 다.** 화면이 쓰는 `[x,y,w,h]` 로는 `parse.ts` 가 바꾼다. */
  box_xyxy: readonly number[];
  feature_similarities: Readonly<Record<string, number>>;
  /** 특징 여덟 중 **최고값**이다. 확률이 아니다. */
  final_score: number;
  mandatory_gates: Readonly<Record<string, DetectGate>>;
};

/** 한 클래스의 요약. `target_summary.json`. */
export type DetectSummary = {
  target_class: string;
  localization_ok: boolean;
  frames: readonly DetectFrame[];
  distance_note?: string;
};

/** 경로 산출. `evidence.json`. 스캔이 끝나야 나온다. */
export type DetectPath = {
  target_class: string;
  ok: boolean;
  target_resolution: { position_cm: readonly number[]; source: string; detail: string };
  robot_position_cm: readonly number[];
  current_heading_map_deg: number;
  target_position_cm: readonly number[];
  map_bearing_to_target_deg: number;
  turn_instruction: string;
  distance_to_target_cm: number;
  standoff_cm: number;
  forward_distance_cm: number;
  goal_cm: readonly number[];
  /** 식과 대입값이 문자열로 들어 있다 — **우리가 다시 계산하지 않는다.** */
  path_calculation: Readonly<Record<string, { formula: string; substituted: string }>>;
  pedestal_obstacle_clear?: boolean;
};

/** 무엇을 그 클래스라고 물었나. `features_sent.json`. */
export type DetectFeatures = {
  target_class: string;
  requested_by_command: boolean;
  is_localization_landmark: boolean;
  features_compared: readonly string[];
};
