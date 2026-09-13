/**
 * src/shared/notifications.ts
 *
 * **머리줄의 통합 알림.** 탭을 보고 있지 않을 때도 알아야 하는 것만 여기로 온다.
 *
 * ## 시작할 때 비어 있다 (260913 지시 — 「실제 사건이 아닌 목 데이터는 최소화」)
 *
 * 전에는 두 줄이 박혀 있었다.
 *
 *     AI-FAIL-01   외부 AI 분류 응답 지연 (VZ-I-10)      2026-08-27
 *     GEN-FAIL-01  마일스톤 생성 검증 1건 실패 (F15)     2026-08-27
 *
 * 구 대시보드에서 넘어온 예시이고 **일어난 적이 없는 일**이다. 그런데 뱃지는 늘 「알림 2」
 * 였고, 무대에서 그것을 보면 방금 무슨 일이 난 줄 안다. 실패 사유에서 지어낸 문장을 걷어낸
 * 것과 같은 이유로 지운다 — **없으면 0이라고 적는 편이 맞다.**
 *
 * 실제로 쌓이는 것은 둘이다.
 *
 *   command      명령 발행 거부·상태 (`shared/commandEgress.ts` · `transport/WsTransport.ts`)
 *   external-ai  외부 AI 실패 이벤트 (`tabs/aiFailureBridge.ts` — 게이트웨이가 줄 때)
 *
 * `mission-generation` 은 **올리는 코드가 아직 없다.** 종류만 자리로 남겨 둔다 — 생성 쪽이
 * 검증 실패를 내보내기 시작하면 그때 여기로 온다.
 */

import { useSyncExternalStore } from 'react';

export type AppNotification = { id: string; source: 'external-ai' | 'mission-generation' | 'command'; message: string; occurredAt: string };

/** **비어 있는 채로 시작한다.** 실제 사건이 와야 는다. */
const items: AppNotification[] = [];
const listeners = new Set<() => void>();

export function pushNotification(item: AppNotification) {
  items.unshift(item);
  listeners.forEach((listener) => listener());
}

export function useNotifications() {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    () => items,
    () => items,
  );
}
