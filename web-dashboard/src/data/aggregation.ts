/**
 * src/data/aggregation.ts
 *
 * VZ-C-03 — 집약 계층 경계 표기와 **재집약 방지 검사**.
 *
 * 지금은 원본을 받아 화면이 집약해도 양이 감당된다. 그러나 대상이 늘면 집약은
 * 엣지·서버에서 선행되고, 그때 화면은 **이미 집약된 값**을 받게 된다.
 * 표기가 없으면 화면이 그 값을 다시 평균 내는 **재집약 오류**가 발생한다.
 *
 * 자리를 열어놓고 코드가 무시하면 나중에 결국 같은 공사를 하게 되므로,
 * 이번 단계부터 **실제로 검사한다.** 검사 자체는 아래 한 함수가 전부다.
 */

import type { WireAggregation } from '../transport/index.ts';
import { IS_DEV } from './env.ts';

/** 와이어의 축약형('raw')과 객체형을 하나로 정규화한 형태. */
export type Aggregation = {
  mode: 'raw' | 'aggregated';
  layer: 'device' | 'edge' | 'server' | null;
  method: string | null;
  windowMs: number | null;
};

export const RAW: Aggregation = { mode: 'raw', layer: null, method: null, windowMs: null };

/**
 * 와이어 값 정규화.
 * ※ 정식 계약이 축약형/객체형 중 무엇을 쓸지 아직 정하지 않았으므로 둘 다 받는다.
 *   확정되면 이 함수 하나만 좁히면 된다.
 */
export function normalizeAggregation(wire: WireAggregation | undefined): Aggregation {
  if (wire === undefined || wire === 'raw') return RAW;
  if (typeof wire === 'string') return RAW;
  return {
    mode: wire.mode ?? 'raw',
    layer: wire.layer ?? null,
    method: wire.method ?? null,
    windowMs: wire.window_ms ?? null,
  };
}

export function describeAggregation(a: Aggregation): string {
  if (a.mode === 'raw') return '원본 측정';
  const parts = ['집약값'];
  if (a.layer) parts.push(a.layer + ' 계층');
  if (a.method) parts.push(a.method);
  if (a.windowMs) parts.push(Math.round(a.windowMs / 1000) + '초 창');
  return parts.join(' · ');
}

/** 이미 경고한 조합은 다시 띄우지 않는다. 20Hz 스트림에서 콘솔이 잠기면 아무도 안 본다. */
const warned = new Set<string>();

/**
 * **재집약 검사.** 집약값에 평균·합계 같은 집약 연산을 적용하려 하면 개발 모드에서 경고한다.
 *
 * 이 한 줄이 나중에 "집약이 서버로 옮겨갔는데 화면이 또 평균을 냈다"는 사고를 막는다.
 * 운영 빌드에서는 아무 일도 하지 않는다(검사 비용이 값보다 커지면 안 되므로).
 *
 * @returns 재집약 시도였는지 여부. 호출부가 표시를 바꾸고 싶을 때 쓴다.
 */
export function warnOnReaggregation(
  aggregation: Aggregation,
  operation: 'mean' | 'sum' | 'max' | 'min' | 'count',
  context: string,
): boolean {
  if (aggregation.mode !== 'aggregated') return false;

  if (IS_DEV) {
    const key = context + '|' + operation + '|' + (aggregation.layer ?? '?');
    if (!warned.has(key)) {
      warned.add(key);
      console.warn(
        '[VZ-C-03] 재집약 시도: ' + context + ' 의 값은 이미 ' +
          describeAggregation(aggregation) +
          ' 인데 여기에 ' + operation + ' 을(를) 적용하려 한다.\n' +
          '집약값을 다시 집약하면 가중치가 무너져 실제와 다른 수가 나온다. ' +
          '원본(raw)을 받아 계산하거나, 집약 결과를 그대로 표시할 것.',
      );
    }
  }
  return true;
}

/**
 * 검사를 통과한 평균. 집약값이 섞여 들어오면 경고하고 계산은 하지 않는다.
 * 화면이 집약 연산을 하려면 **반드시 이 함수를 거치게** 해서, 검사를 빠뜨릴 수 없게 만든다.
 */
export function guardedMean(
  samples: Array<{ value: number; aggregation: Aggregation }>,
  context: string,
): number | null {
  if (samples.length === 0) return null;
  for (const s of samples) {
    if (warnOnReaggregation(s.aggregation, 'mean', context)) return null;
  }
  return samples.reduce((acc, s) => acc + s.value, 0) / samples.length;
}

export function guardedSum(
  samples: Array<{ value: number; aggregation: Aggregation }>,
  context: string,
): number | null {
  if (samples.length === 0) return null;
  for (const s of samples) {
    if (warnOnReaggregation(s.aggregation, 'sum', context)) return null;
  }
  return samples.reduce((acc, s) => acc + s.value, 0);
}
