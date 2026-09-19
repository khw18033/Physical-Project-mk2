export type OriginKind = 'physical' | 'simulation' | 'replay';

/**
 * **키를 담는다.** 최상위 상수라 여기서 `t()` 를 부르면 로드 시점 언어로 굳는다 —
 * 언어 버튼으로 바꿔도 안 따라온다 (`verify:i18n-no-frozen`).
 */
export const ORIGIN_LABEL_KEY: Record<OriginKind, string> = {
  physical: 'pr.1',
  simulation: 'pr.2',
  replay: 'pr.3',
};
