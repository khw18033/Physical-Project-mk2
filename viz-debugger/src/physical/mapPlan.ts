/**
 * src/physical/mapPlan.ts (260929 신설 — 임무 실행기의 가상 맵 계산)
 *
 * **가상 맵 자료로 셈하는 것들.** 방위 · 거리 · 시야 · 두 경로의 간격. 전부 순수 함수다 — 장비를 모르고
 * 저장소를 안 읽는다. 실행기(`taskRunner.ts`)가 부르고, 검사가 따로 돌려 본다.
 *
 * 방위는 경로 걸음(`pathStepCommands`)과 **같은 규약**이다 — +z 가 0°, 시계 방향이 +. 규약이 둘이면
 * 「@ 쪽으로 돌았는데 경로의 첫 회전이 반대로 나간다」가 생긴다.
 */

export type MapPoint = { x: number; z: number };

export type MapDevice = {
  slot: string;
  start: MapPoint;
  start_yaw_deg?: number;
  path: Array<[number, number]>;
  path_task: string;
  move_start_task: string;
  arrive_task: string;
};

export type MapSpec = {
  frame?: string;
  place?: string;
  target: MapPoint;
  devices: MapDevice[];
};

/** 대본의 `params.virtual_map`. 모양이 안 맞으면 null. */
export function mapSpecOf(params: Record<string, unknown>): MapSpec | null {
  const spec = params.virtual_map as MapSpec | undefined;
  if (spec === undefined || spec === null || typeof spec !== 'object') return null;
  if (typeof spec.target?.x !== 'number' || !Array.isArray(spec.devices)) return null;
  return spec;
}

/** -180 ~ 180 으로 접는다 — 270° 오른쪽이 아니라 90° 왼쪽이다. */
export function wrapDeg(deg: number): number {
  return ((deg % 360) + 540) % 360 - 180;
}

/** `from` 에서 `to` 를 보는 방위(°). */
export function headingDeg(from: MapPoint, to: MapPoint): number {
  return (Math.atan2(to.x - from.x, to.z - from.z) * 180) / Math.PI;
}

/** 경로 길이(m). */
export function pathLengthM(path: ReadonlyArray<readonly [number, number]>): number {
  let total = 0;
  for (let index = 1; index < path.length; index += 1) {
    total += Math.hypot(path[index][0] - path[index - 1][0], path[index][1] - path[index - 1][1]);
  }
  return total;
}

type Segment = readonly [readonly [number, number], readonly [number, number]];

function pointSegment(p: readonly [number, number], [a, b]: Segment): number {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const length2 = dx * dx + dz * dz;
  const t = length2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / length2));
  return Math.hypot(p[0] - (a[0] + dx * t), p[1] - (a[1] + dz * t));
}

function crosses([a, b]: Segment, [c, d]: Segment): boolean {
  const side = (p: readonly [number, number], q: readonly [number, number], r: readonly [number, number]) =>
    (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = side(c, d, a);
  const d2 = side(c, d, b);
  const d3 = side(a, b, c);
  const d4 = side(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

function segments(path: ReadonlyArray<readonly [number, number]>): Segment[] {
  const out: Segment[] = [];
  for (let index = 1; index < path.length; index += 1) out.push([path[index - 1], path[index]]);
  return out;
}

/**
 * **두 경로 사이의 가장 가까운 거리**와 교차 여부. 선분끼리 견준다 — 꼭짓점끼리만 재면 두 경로가 가운데서
 * 엇갈려도 멀다고 나온다.
 */
export function pathGap(
  a: ReadonlyArray<readonly [number, number]>,
  b: ReadonlyArray<readonly [number, number]>,
): { minGapM: number; crossing: boolean } {
  let minGapM = Infinity;
  let crossing = false;
  for (const s of segments(a)) {
    for (const u of segments(b)) {
      if (crosses(s, u)) crossing = true;
      minGapM = Math.min(minGapM, pointSegment(s[0], u), pointSegment(s[1], u), pointSegment(u[0], s), pointSegment(u[1], s));
    }
  }
  return { minGapM: crossing ? 0 : minGapM, crossing };
}

/**
 * **@ 가 장치의 시야 안인가.** 장치가 보는 방위와 @ 방위의 차이가 화각의 절반 안이면 안이다.
 * 거리는 따지지 않는다 — 방 하나 크기에서 카메라가 못 볼 만큼 먼 자리는 없다.
 */
export function viewOf(from: MapPoint, yawDeg: number, target: MapPoint, fovDeg: number): {
  bearingDeg: number; relativeDeg: number; distanceM: number; halfFovDeg: number; inView: boolean;
} {
  const bearingDeg = headingDeg(from, target);
  const relativeDeg = wrapDeg(bearingDeg - yawDeg);
  const halfFovDeg = fovDeg / 2;
  return {
    bearingDeg,
    relativeDeg,
    distanceM: Math.hypot(target.x - from.x, target.z - from.z),
    halfFovDeg,
    inView: Math.abs(relativeDeg) <= halfFovDeg,
  };
}

/** 소수 둘째 자리. 기록에 남기는 값이 매번 긴 꼬리를 달지 않게. */
export const r2 = (value: number): number => Number(value.toFixed(2));
