/**
 * src/physical/seqPlan.ts (261113 신설 — 드론 복합 이동 미션)
 *
 * **pi3 의 `mission_seq.py` 에 넘길 단계 목록.** 「5m 이륙 → 오른쪽 3m → 앞 1m → 착륙」처럼 여러 동작을 한 미션으로
 * 날린다. 규약은 저장소 루트 `MISSION_SEQ_요청_VZ.md` 이고, 기존 왕복 시험(`flightPlan.ts`)에 **더해지는** 것이다.
 *
 * 여기는 비행 코드가 아니다. 가진 것은
 *
 *   - 단계 · 미션 설정과 허용 범위(§3) — 최종 판정은 스크립트(종료 코드 2)이고, 화면은 먼저 걸러 버튼을 닫는다,
 *   - **미리보기 계산(§6)** — 드론 쪽 `scripts/seq_plan.py` 와 같은 식. 기체 기준(위 = 이륙 직전 기수) 평면 좌표,
 *   - **미션 키(§6)** — dry-run 한 미션과 지금 편집기의 미션이 같은지 맞춰 보는 글자. 드론이 `mission_key` 로 되돌려 준다,
 *   - 규약 파라미터(`map<string,double>`)와 명령줄 미리보기
 *
 * 뿐이다. `verify:seq-mission` 이 요청 문서의 시험 벡터(키 · sha256 · 단계 끝 좌표)와 대조한다.
 */

export type StepKind = 'forward' | 'back' | 'right' | 'left' | 'cw' | 'ccw' | 'hover';
export type LandAt = 'here' | 'home';
export type SeqAbort = 'rtl' | 'hold' | 'land';

export type SeqStep = {
  kind: StepKind;
  /** 이동 m · 회전 ° · 대기 초. */
  value: number;
  /** 이 단계만의 속도(m/s). `null` 이면 미션 기본 속도. 이동 단계만. */
  speedMps: number | null;
  capture: boolean;
};

export type SeqMission = {
  altitudeM: number;
  speedMps: number;
  land: LandAt;
  abort: SeqAbort;
  maxRadiusM: number;
  steps: readonly SeqStep[];
};

export const STEP_KINDS: readonly StepKind[] = ['forward', 'back', 'right', 'left', 'cw', 'ccw', 'hover'];
export const MOVE_KINDS: readonly StepKind[] = ['forward', 'back', 'right', 'left'];
export const LANDS: readonly LandAt[] = ['here', 'home'];
export const SEQ_ABORTS: readonly SeqAbort[] = ['rtl', 'hold', 'land'];

/** 규약 번호 (§3). */
export const STEP_KIND_CODE: Readonly<Record<StepKind, number>> = { forward: 0, back: 1, right: 2, left: 3, cw: 4, ccw: 5, hover: 6 };
export const LAND_CODE: Readonly<Record<LandAt, number>> = { here: 0, home: 1 };
export const SEQ_ABORT_CODE: Readonly<Record<SeqAbort, number>> = { rtl: 0, hold: 1, land: 2 };

export type StepClass = 'move' | 'rot' | 'hover';
export function stepClass(kind: StepKind): StepClass {
  if (kind === 'cw' || kind === 'ccw') return 'rot';
  if (kind === 'hover') return 'hover';
  return 'move';
}

type Range = { min: number; max: number };
export const SEQ_LIMITS = {
  altitudeM: { min: 2, max: 30 },
  speedMps: { min: 0.5, max: 5 },
  maxRadiusM: { min: 1, max: 100 },
  steps: { min: 1, max: 20 },
  move: { min: 1, max: 50 },
  rot: { min: 1, max: 360 },
  hover: { min: 1, max: 60 },
} as const satisfies Record<string, Range>;
/** 꼭짓점 사이 거리 합의 상한(§3 · §6). */
export const MAX_PATH_M = 300;

export const STEP_DEFAULTS: Readonly<Record<StepKind, number>> = { forward: 2, back: 2, right: 2, left: 2, cw: 90, ccw: 90, hover: 5 };

export function newStep(kind: StepKind = 'forward'): SeqStep {
  return { kind, value: STEP_DEFAULTS[kind], speedMps: null, capture: false };
}

/** 종류를 바꾸면 값이 그 종류의 범위로 들어오게 · 이동이 아니면 단계 속도를 지운다. */
export function withKind(step: SeqStep, kind: StepKind): SeqStep {
  const cls = stepClass(kind);
  const range = SEQ_LIMITS[cls];
  const keep = stepClass(step.kind) === cls && step.value >= range.min && step.value <= range.max;
  return { ...step, kind, value: keep ? step.value : STEP_DEFAULTS[kind], speedMps: cls === 'move' ? step.speedMps : null };
}

/** 기본값 그대로 두면 난다 — 요청 문서 §1 의 예(오른쪽 3m → 앞 1m, 마지막 자리 착륙). */
export const SEQ_DEFAULTS: Readonly<SeqMission> = {
  altitudeM: 5,
  speedMps: 1,
  land: 'here',
  abort: 'rtl',
  maxRadiusM: 30,
  steps: [
    { kind: 'right', value: 3, speedMps: null, capture: false },
    { kind: 'forward', value: 1, speedMps: null, capture: false },
  ],
};

// ── 미리보기 (§6) ───────────────────────────────────────────────────────

/** 기체 기준 상태 — 위 = 이륙 직전 기수. `yaw` 는 이륙 기수에서 돈 각도(시계 +). */
export type BodyPoint = { fwd: number; right: number; yaw: number };

export const MOVE_DIR: Readonly<Record<'forward' | 'right' | 'back' | 'left', number>> = { forward: 0, right: 90, back: 180, left: 270 };

export type Preview = {
  /** 단계 끝마다 하나. `ends[k-1]` 이 단계 k 의 끝. */
  ends: BodyPoint[];
  land: { fwd: number; right: number };
  /** 이륙 지점(L)과 각 단계 끝 가운데 L 에서 가장 먼 거리. */
  maxR: number;
  /** 꼭짓점 사이 거리 합(home 이면 마지막 → L 포함). */
  pathM: number;
};

/** 0 에 붙은 -0 · 부동소수 찌꺼기를 지운다 — 시험 벡터와 같은 자리수로 비교하게. */
const clean = (x: number) => { const r = Math.round(x * 1e9) / 1e9; return r === 0 ? 0 : r; };

export function previewOf(mission: Pick<SeqMission, 'steps' | 'land'>): Preview {
  let fwd = 0;
  let right = 0;
  let yaw = 0;
  const ends: BodyPoint[] = [];
  let maxR = 0;
  let pathM = 0;
  for (const step of mission.steps) {
    const cls = stepClass(step.kind);
    if (cls === 'move') {
      const b = ((yaw + MOVE_DIR[step.kind as keyof typeof MOVE_DIR]) * Math.PI) / 180;
      fwd += step.value * Math.cos(b);
      right += step.value * Math.sin(b);
      pathM += step.value;
    } else if (cls === 'rot') {
      yaw += step.kind === 'cw' ? step.value : -step.value;
    }
    const point = { fwd: clean(fwd), right: clean(right), yaw: clean(yaw) };
    ends.push(point);
    maxR = Math.max(maxR, Math.hypot(point.fwd, point.right));
  }
  const last = ends.at(-1) ?? { fwd: 0, right: 0, yaw: 0 };
  const land = mission.land === 'home' ? { fwd: 0, right: 0 } : { fwd: last.fwd, right: last.right };
  if (mission.land === 'home') pathM += Math.hypot(last.fwd, last.right);
  return { ends, land, maxR, pathM: clean(pathM) };
}

/** 이륙 기수(도, 북 0 시계) + 기체 기준 (fwd, right) → 북 · 동(m). */
export function bodyToNe(h0Deg: number, point: { fwd: number; right: number }): { n: number; e: number } {
  const h = (h0Deg * Math.PI) / 180;
  return {
    n: point.fwd * Math.cos(h) - point.right * Math.sin(h),
    e: point.fwd * Math.sin(h) + point.right * Math.cos(h),
  };
}

// ── 검사 (§3) ───────────────────────────────────────────────────────────

export type SeqProblem =
  | { field: 'altitudeM' | 'speedMps' | 'maxRadiusM'; kind: 'range'; min: number; max: number }
  | { field: 'steps'; kind: 'count'; min: number; max: number }
  | { field: 'step'; kind: 'value'; k: number; step: StepKind; min: number; max: number }
  | { field: 'step'; kind: 'speed'; k: number; min: number; max: number }
  | { field: 'step'; kind: 'speedNotMove'; k: number }
  | { field: 'radius'; kind: 'radius'; got: number; max: number }
  | { field: 'path'; kind: 'path'; got: number; max: number };

const inRange = (value: number, range: Range) => Number.isFinite(value) && value >= range.min && value <= range.max;

/** 빈 배열이면 보낼 수 있다. 거리 제한은 스크립트도 다시 본다(종료 코드 2). */
export function seqProblems(mission: SeqMission): SeqProblem[] {
  const problems: SeqProblem[] = [];
  for (const field of ['altitudeM', 'speedMps', 'maxRadiusM'] as const) {
    if (!inRange(mission[field], SEQ_LIMITS[field])) problems.push({ field, kind: 'range', ...SEQ_LIMITS[field] });
  }
  const n = mission.steps.length;
  if (n < SEQ_LIMITS.steps.min || n > SEQ_LIMITS.steps.max) problems.push({ field: 'steps', kind: 'count', ...SEQ_LIMITS.steps });
  mission.steps.forEach((step, index) => {
    const k = index + 1;
    const cls = stepClass(step.kind);
    if (!inRange(step.value, SEQ_LIMITS[cls])) problems.push({ field: 'step', kind: 'value', k, step: step.kind, ...SEQ_LIMITS[cls] });
    if (step.speedMps !== null) {
      if (cls !== 'move') problems.push({ field: 'step', kind: 'speedNotMove', k });
      else if (!inRange(step.speedMps, SEQ_LIMITS.speedMps)) problems.push({ field: 'step', kind: 'speed', k, ...SEQ_LIMITS.speedMps });
    }
  });
  if (problems.some((p) => p.field === 'step' || p.field === 'steps')) return problems;
  const preview = previewOf(mission);
  if (Number.isFinite(mission.maxRadiusM) && preview.maxR > mission.maxRadiusM + 1e-9) {
    problems.push({ field: 'radius', kind: 'radius', got: preview.maxR, max: mission.maxRadiusM });
  }
  if (preview.pathM > MAX_PATH_M + 1e-9) problems.push({ field: 'path', kind: 'path', got: preview.pathM, max: MAX_PATH_M });
  return problems;
}

// ── 미션 키 (§6) ────────────────────────────────────────────────────────

/** `Number(x.toFixed(3)).toString()` — 3 → "3", 0.5 → "0.5", 1.23456 → "1.235". */
export function fmt3(x: number): string {
  return Number(x.toFixed(3)).toString();
}

/** 정규형 단계 글자 — `right:3` · `right:2@0.5+cap`. 실행기의 `run.steps` 와 같다. */
export function stepText(step: SeqStep): string {
  return `${step.kind}:${fmt3(step.value)}${step.speedMps !== null ? `@${fmt3(step.speedMps)}` : ''}${step.capture ? '+cap' : ''}`;
}

export function missionKey(mission: Pick<SeqMission, 'altitudeM' | 'speedMps' | 'land' | 'steps'>): string {
  return `v1|alt=${fmt3(mission.altitudeM)}|spd=${fmt3(mission.speedMps)}|land=${mission.land}|${mission.steps.map(stepText).join(';')}`;
}

// ── 규약 파라미터 (§3) ──────────────────────────────────────────────────

/**
 * 미션 → 파라미터. **실행 여부(`dry_run` · `confirmed`)는 넣지 않는다** — 같은 설정의 dry-run 과 비행을 이 값으로 짝짓는다.
 * 기본 속도 · 착륙 · abort · 최대 거리는 기본값이어도 싣는다(화면에 보인 값과 실행된 값이 같다는 것을 명령 기록만으로 알게).
 * 단계 속도는 정했을 때만, 캡처는 늘 싣는다.
 */
export function seqParams(mission: SeqMission): Record<string, number> {
  const params: Record<string, number> = {
    altitude_m: mission.altitudeM,
    step_count: mission.steps.length,
    speed_mps: mission.speedMps,
    land: LAND_CODE[mission.land],
    abort: SEQ_ABORT_CODE[mission.abort],
    max_radius_m: mission.maxRadiusM,
  };
  mission.steps.forEach((step, index) => {
    const k = index + 1;
    params[`s${k}_kind`] = STEP_KIND_CODE[step.kind];
    params[`s${k}_value`] = step.value;
    if (step.speedMps !== null) params[`s${k}_speed_mps`] = step.speedMps;
    params[`s${k}_capture`] = step.capture ? 1 : 0;
  });
  return params;
}

/** `seq_mission_start` 에 실을 전부. 실제 비행이면 `confirmed` 가 있어야 실행기가 받는다. */
export function seqStartParams(mission: SeqMission, run: { dryRun: boolean; confirmed: boolean }): Record<string, number> {
  const params = { ...seqParams(mission), dry_run: run.dryRun ? 1 : 0 };
  return run.dryRun ? params : { ...params, confirmed: run.confirmed ? 1 : 0 };
}

/** 같은 설정인가 — 키 순서와 무관하게 같은 글자. 미션 키에 없는 abort · 최대 거리까지 포함한다. */
export function seqSignature(mission: SeqMission): string {
  const params = seqParams(mission);
  return Object.keys(params).sort().map((key) => `${key}=${params[key]}`).join('&');
}

/**
 * 실행기가 띄우는 스크립트. 명령줄은 실행기가 만든다 — 옵션 이름을 화면이 짐작해 보여 주지 않고, 실행이 돌아온 뒤
 * `run.argv` 를 그대로 보여 준다.
 */
export const SEQ_SCRIPT = 'mission_seq.py';

/** 편집기 상태 비교용 — 같은 미션이면 같은 글자(사람 확인 창을 닫을 때 쓴다). */
export function missionFingerprint(mission: SeqMission): string {
  return JSON.stringify(mission);
}
