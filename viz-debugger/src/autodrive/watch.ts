/**
 * src/autodrive/watch.ts (260915 신설 — 자율주행 편 · 장애물 탐지)
 *
 * **자율주행 판이 열려 있는 동안 장애물 JSON 을 계속 받는다.** 판이 열리는 것은 중계 편
 * (`driver: 'relay'`)을 승인할 때뿐이다(`physical/navRun.ts`) — 문 찾기 시연 편을 올리면 판이 안 열리고,
 * 그래서 이 폴링도 안 돈다.
 *
 * 판 내내 받는 이유는 **줄(가까운 장애물 생김/사라짐)** 때문이다. 액션 아이템을 열었을 때만 받으면
 * 이동 중에 무엇이 가까워졌는지가 남지 않는다.
 */

import { receiveObstacleSnapshot } from '../physical/navLink.ts';
import { navRun, subscribeNavRun } from '../physical/navRun.ts';
import { clearObstacleLog, holdObstaclePolling, obstacleState, subscribeObstacle } from './obstacle.ts';

let started = false;

/**
 * 판이 열려 있는 동안 장애물 JSON 을 받고, 받은 것을 「장애물 탐지」(T-NB2) 노드로 넘긴다 (260915).
 * 노드를 칠하는 규칙(처음 오면 진행 중 · 가까운 장애물이 바뀌면 진행 줄 · 도착과 함께 완료)은 `navLink.ts` 에 있다.
 */
export function startObstacleWatch(): () => void {
  if (started) return () => undefined;
  started = true;
  let release: (() => void) | null = null;
  let serial: number | null = null;
  let lastSeen: unknown = null;
  const offObstacle = subscribeObstacle(() => {
    const latest = obstacleState().latest;
    if (latest === null || latest === lastSeen) return;
    lastSeen = latest;
    receiveObstacleSnapshot(latest);
  });
  const sync = () => {
    const run = navRun();
    if (run === null) {
      release?.();
      release = null;
      serial = null;
      return;
    }
    if (run.serial === serial) return;
    serial = run.serial;
    clearObstacleLog();
    if (release === null) release = holdObstaclePolling();
  };
  const off = subscribeNavRun(sync);
  sync();
  return () => {
    off();
    offObstacle();
    release?.();
    release = null;
    started = false;
  };
}
