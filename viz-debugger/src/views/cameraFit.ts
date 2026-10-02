/**
 * src/views/cameraFit.ts (261002 신설 — 전체 카메라 판의 영상 높이)
 *
 * **한 화면에 다 들어가는 영상 높이.** `AllCamerasOverlay.tsx` 가 판 · 칸을 재서 넘기고, 이 파일은 계산만 한다 — 검사가
 * 그대로 부를 수 있게 화면 부품과 떼어 두었다(node 는 `.tsx` 를 못 읽는다).
 */

/** 영상 높이의 하한 — 이보다 작으면 무엇이 찍혔는지 못 읽는다. 그때는 맞추기를 포기하고 판이 구른다. */
export const CAM_MIN_H = 90;

/**
 * 줄마다 영상이 아닌 부분(장비 머리 · 고르는 칸 · 설명 줄)의 높이가 있고, 남는 것을 줄 수로 똑같이 나눈다. 판의 모든 영상이
 * 이 높이 하나를 쓴다 — 한 장비의 바로 받는 영상과 추론 영상의 높이가 같아지는 것이 그 덕이다.
 *
 * `needed` 는 영상들이 **자기 비율대로 칸 너비를 채울 때의 높이** 중 가장 큰 것이다. 남는 높이가 그보다 크면 그만큼만 쓴다 —
 * 더 키우면 영상은 안 커지고 위아래 검은 띠만 는다(261002 화면 — 장비가 둘일 때 띠가 영상보다 컸다). 모르면 null.
 *
 * @param available  영상 판(그리드)이 쓸 수 있는 높이
 * @param rowOverheads  줄마다 영상이 아닌 부분의 높이(그 줄 칸 중 가장 큰 것)
 * @param gap  줄 사이
 */
export function fitCameraHeight(available: number, rowOverheads: readonly number[], gap: number, needed: number | null = null): number {
  const rows = rowOverheads.length;
  if (rows === 0) return CAM_MIN_H;
  const room = available - gap * (rows - 1) - rowOverheads.reduce((sum, value) => sum + value, 0);
  const fit = Math.floor(room / rows);
  const capped = needed === null ? fit : Math.min(fit, Math.ceil(needed));
  return Math.max(CAM_MIN_H, capped);
}
