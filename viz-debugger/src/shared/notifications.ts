import { useSyncExternalStore } from 'react';

export type AppNotification = { id: string; source: 'external-ai' | 'mission-generation' | 'command'; message: string; occurredAt: string };

const items: AppNotification[] = [
  { id: 'AI-FAIL-01', source: 'external-ai', message: '외부 AI 분류 응답 지연 (VZ-I-10)', occurredAt: '2026-08-27T14:20:00+09:00' },
  { id: 'GEN-FAIL-01', source: 'mission-generation', message: '마일스톤 생성 검증 1건 실패 (F15)', occurredAt: '2026-08-27T14:22:00+09:00' },
];
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
