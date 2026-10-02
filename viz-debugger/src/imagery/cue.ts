/**
 * src/imagery/cue.ts (260929 신설 — 붙인 동영상의 재생 위치)
 *
 * **판의 시간 → 어느 영상의 어디.** 순수 함수라 검사가 따로 돌린다(`verify:media-cues`). 그리는 쪽은 `CuedVideo.tsx`.
 *
 * 한 노드에 시점이 여럿일 수 있다(260929 — 3D 가상환경: 「모니터링 진행」 때 5초 영상, 「두 번째 장치 이동」 때
 * 25초 영상). 규칙:
 *   - **가장 늦게 시작된 시점**의 영상을 튼다. 앞 영상이 먼저 끝나면 마지막 장면에서 서 있다가 다음 시점에 바뀐다.
 *   - 아직 아무 시점도 안 시작됐으면 **첫 시점의 영상을 첫 장면에서 멈춰** 둔다(260929 결정 1-A).
 *   - 영상을 안 붙인 시점은 없는 것으로 친다.
 *   - 위치 = 머리 − 그 시점의 시작 시각. 판이 멈추면 영상도 멈춘다.
 */

import type { ScenarioEvent } from '../model/types.ts';

export type Cue = { task: string; key: string };
export type CuePosition = { cue: Cue | null; started: boolean; at: number; playing: boolean };

/** 대본의 `params.media_cues[대상]` 을 읽는다. 문자열이면 시점 하나(칸은 기본 칸), 배열이면 여럿. */
export function cuesOf(raw: unknown, defaultKey: string): Cue[] {
  if (typeof raw === 'string' && raw !== '') return [{ task: raw, key: defaultKey }];
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    const cue = item as { task?: unknown; key?: unknown };
    return typeof cue.task === 'string' && cue.task !== ''
      ? [{ task: cue.task, key: typeof cue.key === 'string' && cue.key !== '' ? cue.key : defaultKey }]
      : [];
  });
}

export function cuePosition(
  trace: readonly ScenarioEvent[],
  cues: readonly Cue[],
  headSec: number,
  runPlaying: boolean,
  hasVideo: (key: string) => boolean = () => true,
): CuePosition {
  const usable = cues.filter((cue) => hasVideo(cue.key));
  if (usable.length === 0) return { cue: null, started: false, at: 0, playing: false };
  let best: { cue: Cue; atSec: number } | null = null;
  for (const cue of usable) {
    const start = trace.find((event) => event.nodeId === cue.task && event.status === 'running' && event.atSec <= headSec);
    if (start !== undefined && (best === null || start.atSec >= best.atSec)) best = { cue, atSec: start.atSec };
  }
  if (best === null) return { cue: usable[0], started: false, at: 0, playing: false };
  return { cue: best.cue, started: true, at: Math.max(0, headSec - best.atSec), playing: runPlaying };
}
