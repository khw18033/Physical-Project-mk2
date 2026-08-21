/**
 * src/data/aggregation.ts
 *
 * VZ-C-03 — 집약 계층 경계 표기와 **재집약 차단**.
 *
 * ── 이건 미래 대비가 아니라 현재 상태다
 *
 * 예전에는 "나중에 집약이 서버로 옮겨가면"이라는 가정으로 자리만 열어 뒀다. 그런데
 * `BE-S-03`이 정한 구조에서는 **평시에 이미** 엣지가 raw를 로컬 보관하고 구역 요약만
 * 백엔드로 올라온다. 즉 화면이 평시에 받는 지표는 **이미 집약된 값**이고, `BE-S-06`이
 * 값마다 집약 계층을 표기해 보낸다. 지금부터 그 표기를 읽어야 한다.
 *
 * ── 경고가 아니라 차단이다
 *
 * 재집약 오류는 **화면상으로 드러나지 않는다.** 그래프가 그려지고 숫자가 나오는데
 * 그 숫자가 틀렸을 뿐이다. 콘솔 경고는 아무도 안 보고, 운영 빌드에서는 아예 없다.
 * 그래서 집약값에 집약 연산이 들어오면 **계산 자체를 수행하지 않고** 차단 사실을
 * 기록해 화면이 표시로 대체하게 한다.
 *
 * 표기 해석도 여기 한 곳에서만 한다 — 컴포넌트는 아래 `aggregationBadge()`가 주는
 * 표시용 형태만 받는다.
 */

import type { WireAggregation } from '../transport/index.ts';

/** 와이어의 축약형('raw')과 객체형을 하나로 정규화한 형태. */
export type Aggregation = {
  mode: 'raw' | 'aggregated';
  /** 어느 계층에서 집약되었나. 평시 지표는 'zone'. 원본이면 null. */
  level: string | null;
  method: string | null;
  /** 집약 창 크기(초). */
  windowSec: number | null;
};

export const RAW: Aggregation = { mode: 'raw', level: null, method: null, windowSec: null };

/** 계층 이름을 사람이 읽는 말로. 계약이 영문 enum이므로 표시용 사전을 여기 둔다. */
const LEVEL_LABEL: Record<string, string> = {
  device: '장치',
  edge: '엣지',
  zone: '구역',
  server: '서버',
};

/**
 * 와이어 값 정규화.
 *
 * ※ 정식 계약이 축약형/객체형 중 무엇을 쓸지, 필드 이름을 `kind/level/window_sec`로 할지
 *   `mode/layer/window_ms`로 할지 아직 확정되지 않았으므로 **둘 다 받는다.**
 *   확정되면 이 함수 하나만 좁히면 된다.
 */
export function normalizeAggregation(wire: WireAggregation | undefined): Aggregation {
  if (wire === undefined || wire === 'raw') return { mode: 'raw', level: null, method: null, windowSec: null };
  if (typeof wire === 'string') return { mode: 'raw', level: null, method: null, windowSec: null };

  const mode = wire.kind ?? wire.mode ?? 'raw';
  const windowSec = wire.window_sec ?? (wire.window_ms === undefined ? null : Math.round(wire.window_ms / 1000));

  return {
    mode,
    level: wire.level ?? wire.layer ?? null,
    method: wire.method ?? null,
    windowSec,
  };
}

export function describeAggregation(a: Aggregation): string {
  if (a.mode === 'raw') return '원본 측정';
  const parts = ['집약값'];
  if (a.level) parts.push((LEVEL_LABEL[a.level] ?? a.level) + ' 계층');
  if (a.method) parts.push(a.method);
  if (a.windowSec) parts.push(a.windowSec + '초 창');
  return parts.join(' · ');
}

/**
 * 화면에 다는 **표시용 표기**.
 *
 * "지금 보는 값이 요약인지 원본인지"가 그래프·카드에 보여야 한다는 것이 요구사항이므로,
 * 컴포넌트가 각자 문자열을 조립하지 않게 여기서 만들어 넘긴다. 컴포넌트는 `short`를
 * 작게 달고 `title`을 툴팁으로 쓰면 된다.
 */
export type AggregationBadge = {
  /** 뱃지에 들어갈 짧은 표기. 예: "요약 · 구역 · 15초". */
  short: string;
  /** 마우스를 올렸을 때의 설명. */
  title: string;
  aggregated: boolean;
};

export function aggregationBadge(a: Aggregation): AggregationBadge {
  if (a.mode === 'raw') {
    return {
      short: '원본',
      title: '원본 측정값이다. 집약 연산을 적용해도 된다.',
      aggregated: false,
    };
  }
  const level = a.level === null ? '계층 미표기' : LEVEL_LABEL[a.level] ?? a.level;
  const window = a.windowSec === null ? '창 미표기' : a.windowSec + '초';
  return {
    short: '요약 · ' + level + ' · ' + window,
    title:
      '이미 ' + describeAggregation(a) + ' 이다. 평시 지표는 엣지가 raw를 보관하고 구역 요약만 ' +
      '올라오므로(BE-S-03) 이 값에 평균·합계를 다시 적용하면 가중치가 무너진다. ' +
      '원본이 필요하면 "원본 보기"로 별도 질의해야 한다.',
    aggregated: true,
  };
}

// ── 재집약 차단 ───────────────────────────────────────────────────────────────

export type BlockRecord = {
  at: number;
  context: string;
  operation: string;
  aggregation: Aggregation;
  message: string;
};

const blocks: BlockRecord[] = [];
const blockListeners = new Set<() => void>();

/** 차단 이력. 화면이 "계산이 수행되지 않았다"를 **콘솔이 아니라 화면에** 보이는 근거. */
export function getBlockLog(): readonly BlockRecord[] {
  return blocks;
}

export function subscribeBlocks(listener: () => void): () => void {
  blockListeners.add(listener);
  return () => blockListeners.delete(listener);
}

/**
 * **재집약 차단.** 집약값에 평균·합계 같은 집약 연산을 적용하려 하면 여기서 막는다.
 *
 * 개발 모드 여부를 보지 않는다 — 운영에서만 조용히 통과하면 그게 가장 위험한 조합이다.
 * 검사 비용은 필드 하나를 읽는 정도인 반면 재집약 오류는 발견이 늦다.
 *
 * @returns 차단되었는지 여부. 참이면 **호출부는 계산 결과 대신 표시로 대체해야 한다.**
 */
export function blockReaggregation(
  aggregation: Aggregation,
  operation: 'mean' | 'sum' | 'max' | 'min' | 'count',
  context: string,
): boolean {
  if (aggregation.mode !== 'aggregated') return false;

  const message =
    context + ' 의 값은 이미 ' + describeAggregation(aggregation) + ' 인데 여기에 ' + operation +
    ' 을(를) 적용하려 했다. 집약값을 다시 집약하면 가중치가 무너져 실제와 다른 수가 나오므로 ' +
    '계산을 수행하지 않았다. 원본이 필요하면 원본 질의(VZ-I-04)로 받아 계산할 것.';

  blocks.unshift({ at: Date.now(), context, operation, aggregation, message });
  if (blocks.length > 20) blocks.length = 20;
  console.warn('[VZ-C-03 차단] ' + message);
  for (const l of blockListeners) l();
  return true;
}

/**
 * 검사를 통과한 평균.
 *
 * 화면이 집약 연산을 하려면 **반드시 이 함수를 거치게** 해서 검사를 빠뜨릴 수 없게 만든다.
 * 집약값이 섞여 들어오면 **계산하지 않고 null을 돌려준다** — 호출부는 null을 받으면
 * 숫자 대신 "요약값이라 재계산하지 않음"을 표시해야 한다.
 */
export function guardedMean(
  samples: Array<{ value: number; aggregation: Aggregation }>,
  context: string,
): number | null {
  if (samples.length === 0) return null;
  for (const s of samples) {
    if (blockReaggregation(s.aggregation, 'mean', context)) return null;
  }
  return samples.reduce((acc, s) => acc + s.value, 0) / samples.length;
}

export function guardedSum(
  samples: Array<{ value: number; aggregation: Aggregation }>,
  context: string,
): number | null {
  if (samples.length === 0) return null;
  for (const s of samples) {
    if (blockReaggregation(s.aggregation, 'sum', context)) return null;
  }
  return samples.reduce((acc, s) => acc + s.value, 0);
}
