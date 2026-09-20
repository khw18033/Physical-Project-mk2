/**
 * src/capability/store.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 상태 한 벌의 저장소.** `src/detect/store.ts` 와 같은 자리·같은 모양이다.
 *
 * ## 테스트와 실제가 섞이면 안 된다
 *
 * 탐지는 테스트를 **끌 때만** 값을 비웠다(`setTestMode`). 여기는 **양쪽 다 비운다.**
 * 이유는 이 판이 「지금 무엇이 가능한가」를 말하는 화면이라서다 — 실제 클러스터에 붙은
 * 화면에 테스트 자료의 노드가 한 줄이라도 남아 있으면 그것은 **없는 인프라를 있다고
 * 말하는 것**이고, 이 저장소에서 가장 하면 안 되는 종류의 거짓말이다.
 *
 * 그래서 규칙이 하나다: **`testMode` 가 바뀌면 값은 통째로 없다.** 다시 읽어 와야 뜬다.
 * `verify:capability-source` 가 그 성질을 검사한다.
 *
 * 값에는 **그 값이 어디서 왔는지**(`via`)가 같이 붙어 다닌다. 화면은 그것을 보고 배지를
 * 그리고, 배지는 끌 수 없다.
 */

import { useSyncExternalStore } from 'react';
import { fetchControl, fetchLabels, fetchSnapshot, sourceOf, type FetchLike } from './CapabilityClient.ts';
import { EMPTY_LABELS, type CapControl, type CapLabels, type CapSnapshot } from './types.ts';

export type CapabilityState = {
  /** 연결 관리의 「테스트」가 켜져 있는가. 켜면 `sample.ts` 를 읽는다. */
  testMode: boolean;
  snapshot: CapSnapshot | null;
  labels: CapLabels;
  control: CapControl | null;
  /**
   * 지금 들고 있는 값이 어디서 왔는가. `null` 이면 아직 아무것도 안 읽었다.
   *
   * **`testMode` 와 따로 둔다.** 체크박스는 「앞으로 어디서 읽을 것인가」이고 이것은
   * 「지금 화면에 있는 값이 어디서 왔는가」다. 체크를 껐는데 아직 안 읽어 왔으면 둘이
   * 다르고, 그 순간 화면이 옛 배지를 달고 있으면 안 된다 — 그래서 끌 때 값을 비운다.
   */
  via: 'relay' | 'direct' | 'sample' | null;
  loading: boolean;
  /** 못 읽었으면 왜. 조용히 비워 두지 않는다. */
  error: string | null;
  /** 마지막으로 읽어 온 시각(ms). 0 이면 아직 한 번도 안 읽었다. */
  fetchedAtMs: number;
};

const EMPTY: Omit<CapabilityState, 'testMode'> = {
  snapshot: null,
  labels: EMPTY_LABELS,
  control: null,
  via: null,
  loading: false,
  error: null,
  fetchedAtMs: 0,
};

let state: CapabilityState = { testMode: false, ...EMPTY };
const listeners = new Set<() => void>();

function commit(next: CapabilityState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function capabilityState(): CapabilityState {
  return state;
}

export function subscribeCapability(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useCapability(): CapabilityState {
  return useSyncExternalStore(subscribeCapability, capabilityState, capabilityState);
}

/**
 * **테스트를 켜고 끈다. 값은 양쪽 다 버린다.**
 *
 * 버리지 않으면 실제 클러스터 화면에 테스트 노드가 남는다. 읽는 중이던 요청이 뒤늦게
 * 돌아와도 안 실린다 — `load()` 가 자기가 출발할 때의 `testMode` 를 들고 돌아와 대조한다.
 */
export function setCapabilityTestMode(on: boolean): void {
  if (state.testMode === on) return;
  commit({ testMode: on, ...EMPTY });
}

/**
 * **주소가 바뀌었다** — 들고 있던 값은 다른 클러스터의 것이다. 같은 이유로 버린다.
 * 테스트 중이면 주소와 무관하므로 그대로 둔다.
 */
export function clearCapabilityForAddressChange(): void {
  if (state.testMode || state.via === null) return;
  commit({ testMode: false, ...EMPTY });
}

let serial = 0;

/**
 * 한 벌을 읽어 온다. 기능·노드가 한 응답에 같이 오므로(`/api/functions`) 그것이 본체이고,
 * 라벨과 배치 모드를 같이 받는다.
 *
 * **늦게 온 답은 버린다** — 주소를 바꾸거나 테스트를 토글한 뒤에 옛 요청이 돌아오면
 * 그 값은 지금 화면의 것이 아니다.
 */
export async function loadCapability(fetcher?: FetchLike): Promise<void> {
  const mine = ++serial;
  const testMode = state.testMode;
  const source = sourceOf(testMode);
  commit({ ...state, loading: true, error: null });

  const [outcome, labels, control] = await Promise.all([
    fetchSnapshot(source, fetcher),
    fetchLabels(source, fetcher),
    fetchControl(source, fetcher),
  ]);

  // 그 사이에 테스트가 토글됐거나 더 새 요청이 떴다 — 이 답은 지금 화면의 것이 아니다.
  if (mine !== serial || state.testMode !== testMode) return;

  if (!outcome.ok) {
    commit({ ...state, loading: false, error: outcome.reason, snapshot: null, via: null, control: null });
    return;
  }
  commit({
    testMode,
    snapshot: outcome.snapshot,
    labels,
    control,
    via: outcome.via,
    loading: false,
    error: null,
    fetchedAtMs: Date.now(),
  });
}

/** 검사가 판을 비울 때. */
export function resetCapability(): void {
  serial += 1;
  commit({ testMode: false, ...EMPTY });
}
