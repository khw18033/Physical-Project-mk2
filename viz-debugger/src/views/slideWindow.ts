/**
 * src/views/slideWindow.ts (261110 신설 — 전체 장치 확인의 2×2 칸과 슬라이더)
 *
 * 계산만 한다 — 화면(`AllDevicesOverlay.tsx`)이 부르고, 검사(`verify-server-status.mjs`)가 그대로 부른다.
 */

/** 한 화면의 칸 수 — 가로 2 × 세로 2. */
export const SLOTS = 4;

/**
 * **보이는 칸의 첫 번호.** 한 칸씩 민다(지시 — 페이지 단위가 아니다) — `start` 는 0 부터 `count - slots` 까지.
 * 칸이 줄면(장비가 빠짐 · 모델을 끔) 끝을 넘지 않게 당긴다. 네 칸 이하면 늘 0 이다.
 */
export function clampStart(start: number, count: number, slots = SLOTS): number {
  return Math.max(0, Math.min(start, count - slots));
}
