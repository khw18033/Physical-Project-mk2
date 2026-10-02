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
 *
 * ## 가상 조건도 같은 규칙을 탄다 (260921)
 *
 * `overrides` 와 `whatif` 는 **값과 함께 버려진다.** 안 버리면 두 가지가 깨진다:
 *
 *   1. 다른 클러스터의 `node_id` 가 그대로 남아 서버가 `unknown_node:<id>` 로 400 을 낸다.
 *   2. 더 나쁜 쪽 — 옛 클러스터의 가정이 새 클러스터의 화면에 얹힌 채로 보인다.
 *
 * 기준선과 가상값은 **따로 들고 있는다**(`snapshot` 과 `whatif.after`). 하나로 합쳐
 * 덮어써 두면 「원래 무엇이었는지」를 잃고, 그러면 조건이 걸린 노드를 셀 수가 없다 —
 * 비교 대상이 자기 자신이 되기 때문이다.
 */

import { useSyncExternalStore } from 'react';
import {
  fetchControl, fetchLabels, fetchSnapshot, fetchWhatif, sourceOf, type FetchLike,
} from './CapabilityClient.ts';
import { hasOverrides, withOverride } from './options.ts';
import {
  EMPTY_LABELS,
  type CapControl, type CapLabels, type CapOverride, type CapOverrides, type CapSnapshot,
  type CapWhatif,
} from './types.ts';

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

  /** 지금 걸어 둔 가상 조건. 비어 있으면 기준선이다. */
  overrides: CapOverrides;
  /**
   * 그 조건으로 받은 답. `null` 이면 조건이 없거나 아직 못 받았다.
   *
   * **`overrides` 와 따로 둔다** — 조작면은 「무엇을 걸었나」이고 이것은 「그래서 어떻게
   * 되나」다. 조건을 만지는 순간과 답이 오는 순간 사이에 둘이 다르고, 그때 화면이
   * 옛 답을 새 조건의 것처럼 그리면 안 된다.
   */
  whatif: CapWhatif | null;
  whatifLoading: boolean;
  whatifError: string | null;
};

const EMPTY: Omit<CapabilityState, 'testMode'> = {
  snapshot: null,
  labels: EMPTY_LABELS,
  control: null,
  via: null,
  loading: false,
  error: null,
  fetchedAtMs: 0,
  overrides: {},
  whatif: null,
  whatifLoading: false,
  whatifError: null,
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
 * **화면이 지금 그려야 할 한 벌.** 조건이 걸려 있으면 가상값, 아니면 기준선이다.
 *
 * 갈림은 여기 하나다 — 부품마다 `whatif?.after ?? snapshot` 을 적으면 언젠가 한 칸만
 * 기준선이 남고, 그 한 칸이 「이 조건에서도 이건 되는구나」라는 없는 사실을 만든다.
 */
export function shownSnapshot(value: CapabilityState = state): CapSnapshot | null {
  return value.whatif?.after ?? value.snapshot;
}

/** 기준선 한 벌 — **비교의 기준은 늘 이것이다**(`after` 의 노드는 조건이 이미 반영돼 있다). */
export function baselineSnapshot(value: CapabilityState = state): CapSnapshot | null {
  return value.snapshot;
}

/**
 * **테스트를 켜고 끈다. 값은 양쪽 다 버린다.**
 *
 * 버리지 않으면 실제 클러스터 화면에 테스트 노드가 남는다. 읽는 중이던 요청이 뒤늦게
 * 돌아와도 안 실린다 — `load()` 가 자기가 출발할 때의 `testMode` 를 들고 돌아와 대조한다.
 */
export function setCapabilityTestMode(on: boolean): void {
  if (state.testMode === on) return;
  // 미뤄 둔 계산도 같이 걷는다 — 안 걷으면 버린 뒤에 옛 조건의 요청이 뒤늦게 나간다.
  cancelScheduledWhatif();
  whatifSerial += 1;
  commit({ testMode: on, ...EMPTY });
}

/**
 * **주소가 바뀌었다** — 들고 있던 값은 다른 클러스터의 것이다. 같은 이유로 버린다.
 * 테스트 중이면 주소와 무관하므로 그대로 둔다.
 */
export function clearCapabilityForAddressChange(): void {
  if (state.testMode || state.via === null) return;
  cancelScheduledWhatif();
  whatifSerial += 1;
  commit({ testMode: false, ...EMPTY });
}

let serial = 0;

/**
 * 한 벌을 읽어 온다. 기능·노드가 한 응답에 같이 오므로(`/api/functions`) 그것이 본체이고,
 * 라벨과 배치 모드를 같이 받는다.
 *
 * **늦게 온 답은 버린다** — 주소를 바꾸거나 테스트를 토글한 뒤에 옛 요청이 돌아오면
 * 그 값은 지금 화면의 것이 아니다.
 *
 * 새로 읽으면 **가상 조건도 같이 지운다.** 새 기준선에서는 그 조건이 무엇을 바꾸는지
 * 다시 계산해야 하고, 옛 답을 들고 있으면 그 사이가 거짓이다.
 */
export async function loadCapability(fetcher?: FetchLike): Promise<void> {
  const mine = ++serial;
  const testMode = state.testMode;
  const source = sourceOf(testMode);
  // 새 기준선을 읽는 중이다 — 옛 조건으로 미뤄 둔 계산은 나가면 안 된다.
  cancelScheduledWhatif();
  whatifSerial += 1;
  commit({ ...state, loading: true, error: null });

  const [outcome, labels, control] = await Promise.all([
    fetchSnapshot(source, fetcher),
    fetchLabels(source, fetcher),
    fetchControl(source, fetcher),
  ]);

  // 그 사이에 테스트가 토글됐거나 더 새 요청이 떴다 — 이 답은 지금 화면의 것이 아니다.
  if (mine !== serial || state.testMode !== testMode) return;

  if (!outcome.ok) {
    commit({
      ...state, loading: false, error: outcome.reason, snapshot: null, via: null, control: null,
      overrides: {}, whatif: null, whatifLoading: false, whatifError: null,
    });
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
    overrides: {},
    whatif: null,
    whatifLoading: false,
    whatifError: null,
  });
}

let whatifSerial = 0;

/**
 * **묶어서 보낸다.** 조작면의 체크 하나가 왕복 하나면, 태그 핀을 연달아 네 번 누를 때
 * 네 번이 나가고 그중 셋은 도착하자마자 버려진다(`whatifSerial`). 서버는 그때마다 fleet
 * 전체를 **두 번** 계산한다(`before` 와 `after`) — 노드가 늘수록 그 낭비가 커진다.
 *
 * 그래서 마지막 조작에서 이만큼 조용하면 그때 한 번 보낸다. 사람이 체크박스를 잇달아
 * 누르는 간격(대략 100ms 안팎)보다 길고, 한 번 누르고 결과를 기다리는 사람에게는
 * 안 느껴지는 길이다.
 */
const WHATIF_DEBOUNCE_MS = 180;

let whatifTimer: ReturnType<typeof setTimeout> | null = null;
/** 묶인 요청을 기다리는 쪽들. **반드시 전부 풀어 준다** — 하나라도 남기면 `await` 가 멎는다. */
let whatifWaiting: (() => void)[] = [];

function releaseWaiters(): void {
  const waiters = whatifWaiting;
  whatifWaiting = [];
  for (const done of waiters) done();
}

/**
 * 예약을 걷는다. 값이 통째로 버려지는 자리(테스트 토글·주소 변경·재조회·초기화)에서 부른다 —
 * 안 걷으면 버린 뒤에 옛 조건의 요청이 뒤늦게 나간다.
 */
function cancelScheduledWhatif(): void {
  if (whatifTimer !== null) {
    clearTimeout(whatifTimer);
    whatifTimer = null;
  }
  releaseWaiters();
}

/**
 * 곧 한 번 보낸다. 그 사이에 또 부르면 시계를 다시 맞춘다.
 *
 * 돌려주는 약속은 **실제로 다녀온 뒤에** 풀린다 — 호출한 쪽이 `await` 로 결과를 볼 수 있어야
 * 하고, 검사도 그렇게 본다.
 */
function scheduleWhatif(fetcher?: FetchLike): Promise<void> {
  if (whatifTimer !== null) clearTimeout(whatifTimer);
  return new Promise<void>((resolve) => {
    whatifWaiting.push(resolve);
    whatifTimer = setTimeout(() => {
      whatifTimer = null;
      void refreshWhatif(fetcher).then(releaseWaiters, releaseWaiters);
    }, WHATIF_DEBOUNCE_MS);
  });
}

/**
 * 걸어 둔 조건으로 다시 계산한다. 조건이 하나도 없으면 **부르지 않고 기준선으로 돌아간다** —
 * 빈 조건을 보내면 서버가 `before`·`after` 가 같은 답을 주고, 화면은 「가상 조건」 배지를
 * 단 채 기준선을 그리게 된다.
 */
async function refreshWhatif(fetcher?: FetchLike): Promise<void> {
  const mine = ++whatifSerial;
  const testMode = state.testMode;
  const overrides = state.overrides;

  if (!hasOverrides(overrides)) {
    commit({ ...state, whatif: null, whatifLoading: false, whatifError: null });
    return;
  }
  commit({ ...state, whatifLoading: true, whatifError: null });

  const outcome = await fetchWhatif(sourceOf(testMode), overrides, fetcher);

  // 늦게 온 답은 안 싣는다 — 읽기와 같은 규칙이다. 조건을 한 번 더 만졌거나 테스트를
  // 토글했으면 이 답은 지금 화면의 것이 아니다.
  if (mine !== whatifSerial || state.testMode !== testMode) return;

  if (!outcome.ok) {
    // **답이 없으면 가상값도 없다.** 옛 `after` 를 남겨 두면 지금 조건의 결과로 읽힌다.
    commit({ ...state, whatif: null, whatifLoading: false, whatifError: outcome.reason });
    return;
  }
  commit({ ...state, whatif: outcome.whatif, whatifLoading: false, whatifError: null });
}

/**
 * 노드 하나의 조건을 바꾼다. `'*'` 를 넘기면 전체 노드의 기본값이다.
 *
 * **체크는 즉시 반영하고 계산만 미룬다** — 조작면은 `overrides` 를 보고 그리므로 누른 자리가
 * 바로 켜지고, 서버 왕복만 묶인다. 조작면을 잠그지 않는 이유도 그것이다: 잠그면 연달아
 * 누르는 일이 애초에 안 되고, 그러면 묶을 것도 없다.
 */
export function setCapabilityOverride(
  nodeId: string, patch: Partial<CapOverride>, fetcher?: FetchLike,
): Promise<void> {
  const overrides = withOverride(state.overrides, nodeId, patch);
  // 보낼 것이 있으면 막대가 먼저 「다시 계산하는 중」이 된다 — 미뤄 둔 동안이 빈칸이면
  // 사용자는 체크가 안 먹은 줄 안다.
  commit({ ...state, overrides, whatifLoading: hasOverrides(overrides) });
  return scheduleWhatif(fetcher);
}

/**
 * 조건을 전부 걷는다 — 「기준선으로」. 미뤄 둔 요청이 있으면 같이 걷는다.
 *
 * **서버를 안 부른다.** 조건이 없는 판은 기준선이고, 그것은 이미 들고 있다. 빈 조건을
 * 보내 봐야 `before` 와 `after` 가 같은 답이 오고 왕복만 는다.
 */
export function clearCapabilityOverrides(): Promise<void> {
  cancelScheduledWhatif();
  whatifSerial += 1; // 나가 있는 답이 뒤늦게 실리지 않게.
  commit({ ...state, overrides: {}, whatif: null, whatifLoading: false, whatifError: null });
  return Promise.resolve();
}

/** 검사가 판을 비울 때. */
export function resetCapability(): void {
  serial += 1;
  whatifSerial += 1;
  cancelScheduledWhatif();
  commit({ testMode: false, ...EMPTY });
}
