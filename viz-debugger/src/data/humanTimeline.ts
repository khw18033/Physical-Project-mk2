/**
 * src/data/humanTimeline.ts (261023 신설 — 사람 명령 액션 층 §3)
 *
 * **되감기 타임라인의 사람 줄에 무엇을 찍나.** 순수 함수다 — 저장소도 React 도 모른다.
 *
 * ## 점을 구간으로 묶는 판단 (260904 의 판단을 일부 뒤집는다)
 *
 * 260904 에는 「조작은 구간이 아니라 **순간**이라 점으로 찍는다」고 정했다. 그때 사람 줄에 오는 것은 단추를
 * 누른 사실(승인 · 재시작 · 제어 패널 한 번)이었고, 그 판단은 그 재료에 맞았다. 지금도 그 재료는 점이다.
 *
 * 바뀐 것은 **재료**다. 수동 제어는 키를 누르고 있는 동안 속도가 바뀔 때마다 명령이 나간다 — 한 판에 `teleop`
 * 500건까지 갔다(`261020/225704`). 명령 하나하나는 순간이지만 **사람이 한 일은 「그 사이 몰았다」라는 구간**이다.
 * 점 500개로 그리면 세 가지를 잃는다.
 *
 *   1. 줄이 까맣게 덮여 그 사이의 누름(재시작 · 정지)이 안 보인다 — 원인 추적에서 먼저 찾는 점이 묻힌다
 *   2. 몇 건이었는지 · 언제 시작해 언제 끝났는지가 안 읽힌다 — 점의 밀도로는 셀 수 없다
 *   3. 같은 시각에 겹치면 500개가 한 점이 되어 「한 번 눌렀다」로 읽힌다(실측 판은 전부 0초에 겹쳤다)
 *
 * 그래서 **사람이 같은 장비에 연달아 낸 명령**만 묶는다. 묶는 기준은 장비가 같고 앞 명령과의 간격이
 * `HUMAN_SPAN_GAP_SEC` 이내인 것이다. 누름과 장비가 없는 명령(정지 · 일시정지 · 값 조정)은 그대로 점이다.
 * 묶인 것이 하나뿐이면 그것도 점이다 — 구간이 아니다.
 */

import type { ScenarioEvent } from '../model/types.ts';
import { ACTION_KINDS } from './actionTrace.ts';

/** 같은 몰기로 칠 간격. 키를 바꿔 잡는 사이(1~2초)는 이어지고, 손을 뗀 휴지는 끊긴다. */
export const HUMAN_SPAN_GAP_SEC = 2;

export type HumanSpan = {
  device: string;
  start: number;
  end: number;
  /** 묶인 명령 수. */
  count: number;
  /** 첫 명령의 seq — 화면의 key 로 쓴다. */
  seq: number;
  /** 낸 명령 이름들. 「teleop 만」인지 「걸음 · 회전」이 섞였는지 툴팁이 말한다. */
  actions: readonly string[];
};

export type HumanTimeline = {
  /** 순간 — 누름 · 장비 없는 사람 명령 · 낱건 몰기. */
  points: readonly ScenarioEvent[];
  /** 구간 — 같은 장비에 연달아 낸 사람 명령. */
  spans: readonly HumanSpan[];
};

const deviceOf = (event: ScenarioEvent): string | null => {
  if (event.kind !== ACTION_KINDS.commanded) return null;
  const device = (event.payload as { device?: unknown } | undefined)?.device;
  return typeof device === 'string' && device !== '' ? device : null;
};

/**
 * 사람 줄. 받는 것은 **흘러온 기록 열 전체**이고 고르는 기준은 전과 같다(`producedBy === 'human'`).
 * 되감기는 줄 위의 머리 눈금이 맡는다 — 이 함수는 시각으로 자르지 않는다(전과 같다).
 */
export function humanTimeline(trace: readonly ScenarioEvent[], gapSec = HUMAN_SPAN_GAP_SEC): HumanTimeline {
  const human = trace.filter((event) => event.producedBy === 'human');
  const points: ScenarioEvent[] = [];
  const runs = new Map<string, ScenarioEvent[][]>();
  for (const event of human) {
    const device = deviceOf(event);
    if (device === null) { points.push(event); continue; }
    const groups = runs.get(device) ?? [];
    const last = groups.at(-1);
    if (last !== undefined && event.atSec - (last.at(-1)?.atSec ?? -Infinity) <= gapSec) last.push(event);
    else groups.push([event]);
    runs.set(device, groups);
  }
  const spans: HumanSpan[] = [];
  for (const [device, groups] of runs) {
    for (const group of groups) {
      if (group.length === 1) { points.push(group[0]); continue; }
      spans.push({
        device,
        start: group[0].atSec,
        end: group.at(-1)!.atSec,
        count: group.length,
        seq: group[0].seq,
        actions: [...new Set(group.map((event) => String((event.payload as { action?: unknown } | undefined)?.action ?? '')))],
      });
    }
  }
  points.sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));
  spans.sort((a, b) => a.start - b.start);
  return { points, spans };
}

/** 사람 줄에 적힌 것 전부의 수 — 묶어도 건수는 그대로 센다. */
export function humanCount(timeline: HumanTimeline): number {
  return timeline.points.length + timeline.spans.reduce((sum, span) => sum + span.count, 0);
}
