/**
 * src/detect/frameImage.ts (261102 신설 — 박스 근거)
 *
 * **한 각도의 탐지 영상으로 어느 그림을 그리나 — 규칙은 여기 하나다.**
 *
 * 전에는 탐지 영상 뷰(`DetectViews.tsx`)와 각도 칸 문지기(`physical/scanGate.ts`)가 같은 규칙
 * (`found ? 'target_overlay' : 'original'`)을 따로 갖고 있었다. 문지기는 **뷰가 그린 주소가 떴는지**로
 * 다음 회전을 허락하므로, 한쪽만 바뀌면 화면에 뜬 주소와 기다리는 주소가 달라져 회전이 안 풀린다.
 *
 * ## 박스 편은 못 찾은 각도도 상자 그림을 먼저 (261102)
 *
 * 박스 수신기는 **모든 각도에** `overlay.jpg` 를 쓴다 — 못 찾은 각도에는 버린 후보가 그려진다. 그래서
 * 박스 편은 못 찾은 각도도 `target_overlay` 를 먼저 묻고, **404 면 `original` 로 바꿔 그린다**(지난 판).
 * 바꾼 뒤에는 `original` 이 실제로 떠야 그 각도가 끝난 것이다 — 첫 주소의 실패를 「준비됨」으로 치지 않는다.
 *
 * 문 편은 그대로다. 못 찾은 각도의 상자 그림은 문 편에 없다(`verify:mission-record` — 지어 남기지 않는다).
 */

import { useSyncExternalStore } from 'react';
import { frameImageUrl, roundedImageUrl, type DetectClass, type ImageSource } from './DetectClient.ts';
import type { DetectFrame } from './types.ts';

type FrameKind = 'original' | 'target_overlay';

/** 이 각도에서 물어볼 그림의 차례. 앞의 것이 안 뜨면 뒤의 것. */
export function frameImageKinds(frame: Pick<DetectFrame, 'found'>, target: DetectClass): readonly FrameKind[] {
  if (frame.found) return ['target_overlay'];
  return target === 'box' ? ['target_overlay', 'original'] : ['original'];
}

/** 안 뜬 주소 → 대신 그릴 주소. 차례의 마지막 주소는 여기 없다(더 넘어갈 곳이 없다). */
const fallbackOf = new Map<string, string>();
/** 안 떠서 넘어간 주소. */
const fellBack = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

/**
 * **지금 그릴 주소.** 뷰와 문지기가 이 함수 하나로 같은 문자열을 얻는다.
 * 앞 주소가 안 떠서 넘어갔으면 다음 주소다.
 */
export function frameImageSrc(source: ImageSource, frame: Pick<DetectFrame, 'frame' | 'found'>, target: DetectClass, round: number): string {
  const urls = frameImageKinds(frame, target).map((kind) => roundedImageUrl(frameImageUrl(source, frame.frame, kind, target), round));
  for (let i = 0; i < urls.length - 1; i += 1) fallbackOf.set(urls[i], urls[i + 1]);
  return urls.find((url) => !fellBack.has(url)) ?? urls[urls.length - 1];
}

/**
 * **이 주소가 안 떴다.** 대신 그릴 주소가 있으면 그리로 넘기고 참 — 그때는 실패가 아니다(아직 그릴 것이 있다).
 * 대신할 주소가 없으면 거짓이고, 부른 쪽이 지금처럼 실패로 다룬다.
 */
export function fallBackFrameImage(url: string): boolean {
  if (!fallbackOf.has(url)) return false;
  if (!fellBack.has(url)) {
    fellBack.add(url);
    version += 1;
    for (const listener of listeners) listener();
  }
  return true;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 뷰가 부른다 — 주소가 넘어가면 다시 그린다. */
export function useFrameImageFallbacks(): number {
  return useSyncExternalStore(subscribe, () => version, () => version);
}

/** 검사용 — 처음 상태로. */
export function resetFrameImages(): void {
  fallbackOf.clear();
  fellBack.clear();
  version += 1;
}
