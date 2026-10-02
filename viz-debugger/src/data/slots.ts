/**
 * src/data/slots.ts (260927 신설 — 장치 두 대 편 · 장치 자리 배정)
 *
 * **대본이 장비를 정하지 않는 편의 배정.** 「첫 번째 장치」「두 번째 장치」는 자리(slot)이고,
 * 무엇이 그 자리에 앉는지는 사람이 하드웨어 카드를 마일스톤에 끌어다 놓아 정한다.
 *
 * 전까지 배정은 **마일스톤마다** 따로였다(`main.tsx` 의 `assignments`). 그 방식이면 「첫 번째 장치 연결
 * 확인」에 Go1 을 놓고도 「경로 탐지」「장치 이동」에 다시 놓아야 한다 — 세 번 끌어야 하고, 한 번 빠뜨리면
 * 같은 「첫 번째 장치」가 마일스톤마다 다른 장비가 된다. 그래서 **자리 하나에 장비 하나**를 들고,
 * 태스크의 대상(`target: "device-1"`)은 그리는 순간 이 표로 푼다.
 *
 * 자리를 선언하지 않은 편은 이 저장소를 안 쓴다 — 지금까지와 한 줄도 다르지 않다.
 *
 * 화면(`main.tsx`)과 뷰 노드(가상 맵 · 카메라)가 같은 표를 봐야 하므로 컴포넌트 상태가 아니라 모듈에 둔다.
 */

import { useSyncExternalStore } from 'react';

export type SlotBindings = Readonly<Record<string, string>>;

let bindings: SlotBindings = {};
let boundMission = '';
const listeners = new Set<() => void>();

function commit(next: SlotBindings): void {
  bindings = next;
  for (const listener of listeners) listener();
}

export function slotBindings(): SlotBindings {
  return bindings;
}

export function subscribeSlots(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useSlotBindings(): SlotBindings {
  return useSyncExternalStore(subscribeSlots, slotBindings, slotBindings);
}

/**
 * 임무가 바뀌면 비운다. **같은 임무를 다시 올리면 남긴다** — 같은 편을 한 번 더 돌릴 때 카드를 다시
 * 끌게 하면 무대에서 한 박자가 빈다.
 */
export function holdSlotsFor(missionId: string): void {
  if (missionId === boundMission) return;
  boundMission = missionId;
  if (Object.keys(bindings).length > 0) commit({});
}

/**
 * 마일스톤 하나에 장비 하나가 떨어졌다. `slots` 는 그 마일스톤이 쓰는 자리들(차례대로)이다.
 *
 *   자리가 하나   그 자리를 이 장비로 바꾼다
 *   자리가 여럿   빈 자리 중 첫 칸에 앉힌다. 다 차 있으면 첫 칸을 바꾼다
 *
 * **한 장비가 두 자리에 앉지 않는다.** 이미 다른 자리에 있으면 두 자리를 맞바꾼다 — 같은 장비가
 * 첫 번째이자 두 번째가 되면 「동시에 움직인다」가 한 장비의 일이 된다.
 *
 * @returns 바뀐 자리. 바뀐 것이 없으면 null.
 */
export function dropOnSlots(slots: readonly string[], deviceId: string): string | null {
  if (slots.length === 0 || deviceId === '') return null;
  const already = Object.entries(bindings).find(([, id]) => id === deviceId)?.[0] ?? null;
  // 여러 자리를 쓰는 마일스톤에서 이미 앉아 있는 장비를 또 놓으면 아무 일도 없다.
  if (slots.length > 1 && already !== null && slots.includes(already)) return null;
  const slot = slots.length === 1
    ? slots[0]
    : slots.find((id) => bindings[id] === undefined) ?? slots[0];
  if (bindings[slot] === deviceId) return null;
  const next: Record<string, string> = { ...bindings, [slot]: deviceId };
  if (already !== null && already !== slot) {
    // 맞바꾼다 — 비켜난 자리에는 원래 이 자리에 있던 장비가 간다(없으면 빈다).
    const previous = bindings[slot];
    if (previous === undefined) delete next[already];
    else next[already] = previous;
  }
  commit(next);
  return slot;
}

/** 대상 하나를 푼다. 자리가 아니거나 아직 비어 있으면 **그대로** 돌려준다. */
export function resolveSlot(target: string | null): string | null {
  if (target === null) return null;
  return bindings[target] ?? target;
}

/** 검사와 화면 전환이 쓴다. */
export function resetSlots(): void {
  boundMission = '';
  commit({});
}
