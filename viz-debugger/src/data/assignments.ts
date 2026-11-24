/**
 * src/data/assignments.ts (261124 신설 — 끌어 놓은 장비가 명령까지 가게)
 *
 * **마일스톤에 끌어 놓은 장비.** 전에는 `main.tsx` 의 컴포넌트 상태였다. 그러면 그림(태스크의 대상 칸)만 바뀌고
 * 명령 · 영상 고르기는 그 사실을 못 본다 — Go1 과 EP 를 같이 붙이고 Go1 을 끌어 놓아도 회전은 첫 줄(EP)로,
 * 영상은 옛 표(`go1-001`)로 갔다(261124 실측). 그래서 화면과 명령 쪽이 같이 읽는 모듈로 옮겼다.
 *
 * 자리(slot)를 쓰는 편은 `slots.ts` 가 따로 든다 — 이 표는 자리를 안 쓰는 편의 것이다.
 * 임무가 바뀌면 비운다(전과 같다).
 */

import { useSyncExternalStore } from 'react';

export type MilestoneAssignments = Readonly<Record<string, readonly string[]>>;

let assignments: MilestoneAssignments = {};
let boundMission = '';
const listeners = new Set<() => void>();

function commit(next: MilestoneAssignments): void {
  assignments = next;
  for (const listener of listeners) listener();
}

export function milestoneAssignments(): MilestoneAssignments {
  return assignments;
}

export function subscribeAssignments(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useMilestoneAssignments(): MilestoneAssignments {
  return useSyncExternalStore(subscribeAssignments, milestoneAssignments, milestoneAssignments);
}

/** 임무가 바뀌면 비운다. 같은 임무면 남긴다 — `holdSlotsFor` 와 같은 규칙. */
export function holdAssignmentsFor(missionId: string): void {
  if (missionId === boundMission) return;
  boundMission = missionId;
  if (Object.keys(assignments).length > 0) commit({});
}

/** 마일스톤 하나에 장비 하나를 더한다. 이미 있으면 그대로. */
export function assignToMilestone(milestoneId: string, deviceId: string): void {
  if (milestoneId === '' || deviceId === '') return;
  const current = assignments[milestoneId] ?? [];
  if (current.includes(deviceId)) return;
  commit({ ...assignments, [milestoneId]: [...current, deviceId] });
}

/** 이 임무에 끌어 놓은 장비 전부(겹침 없이, 놓은 차례). */
export function assignedDeviceIds(): readonly string[] {
  return [...new Set(Object.values(assignments).flat())];
}

/** 검사용 — 전부 비운다. */
export function resetAssignments(): void {
  boundMission = '';
  commit({});
}
