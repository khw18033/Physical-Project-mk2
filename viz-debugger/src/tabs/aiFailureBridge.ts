/**
 * src/tabs/aiFailureBridge.ts
 *
 * 외부 AI 실패 이벤트(`VZ-I-10`)를 **상단 공통 알림**으로 올린다.
 *
 * 구 「판단·알림」 탭에서는 이 이벤트가 그 탭 안의 상자에 쌓였다. 통합 앱에서는 그러면 안 된다 —
 * **탭을 보고 있지 않을 때도 알아야 하는 것**이기 때문이다. 탭 여섯 중 하나에만 뜨면
 * 다섯 번 중 다섯 번은 놓친다.
 *
 * 알림은 지표 폴링이 아니라 **도착 즉시**다. 스토어에 새 봉투가 꽂히는 순간 올린다.
 * `event_id` 로 중복을 막는다 — 스토어 스냅샷은 같은 이벤트를 여러 번 돌려주기 때문이다.
 */

import type { AiFailure } from '../transport/index.ts';
import { pushNotification } from '../shared/notifications.ts';
import { store } from './data/index.ts';

const announced = new Set<string>();

function sweep(): void {
  for (const record of store.getSnapshot().values()) {
    const slot = record.aiFailure;
    if (!slot) continue;
    const failure = slot.payload as AiFailure;
    if (!failure?.event_id || announced.has(failure.event_id)) continue;
    announced.add(failure.event_id);
    pushNotification({
      id: failure.event_id,
      source: 'external-ai',
      message: `${failure.error_code} — ${failure.component} ${failure.model_version} · ${failure.detail} (입력 ${failure.input_ref})`,
      occurredAt: failure.occurred_at,
    });
  }
}

/**
 * 한 번만 건다. 데이터 계층 수명과 같다.
 *
 * **훅이 아니라 기동 함수다** (260916 — 단독 빌드 정합 §2). 전에는 `useAiFailureNotifications()`
 * 였고 셸이 `useTabsDataLayer()` 를 통해 직접 불렀다 — 그래서 셸이 `tabs/` 를 알게 됐다.
 * 지금은 통합 진입점이 `registerAppService()` 로 주입하고 셸은 무엇이 도는지 모른다.
 */
export function startAiFailureNotifications(): () => void {
  sweep();
  return store.subscribe(sweep);
}
