/**
 * src/physical/NavFacts.tsx (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * 액션 아이템에 붙는 **pi1 이 실제로 전해 준 것.** 배터리·방위 노드는 받은 값과 받은 시각,
 * 이동·재탐색 노드는 받은 사건 줄. **없으면 비운다** — 지어 채우지 않는다.
 */

import { DERIVED_TASKS, NAV_TASKS } from './navLink.ts';
import { eventTimeMs, isCancelStop, NAV_FRESH_MS, useNavFeed, type NavEvent } from './navFeed.ts';
import { navRun } from './navRun.ts';
import { useReplayTarget } from '../record/replayMode.ts';

/** 사건 이름을 사람 말로. 어디서 봤는지(`journal` · `udp…`)는 옆 줄에 그대로 적는다. */
const EVENT_WORDS: Record<NavEvent['event'], string> = {
  path_received: '경로 수신 — 브리지가 새 경로를 받았다',
  path_cancel: 'PATH_CANCEL — 이전 경로 취소 · 정지',
  // 260915 pi1 답신 — 지금 브리지(go1_sdk_pc)는 mode 98 을 보내지 않아 이 사건은 오지 않는다. 오면 적는다.
  cancel_ack: '취소 처리 ACK (브리지 mode 98)',
  path_done: '경로 끝 도달 — 브리지 완료 통지(mode 99)',
  estop: '비상 정지 — 유니티 텔레옵 estop',
  feed_started: '중계 시작',
};

/** 그 노드가 볼 사건. 배터리·방위 노드는 사건이 아니라 상태를 본다. */
const EVENTS_OF: Record<string, ReadonlyArray<NavEvent['event']>> = {
  [NAV_TASKS.move]: ['path_received', 'path_done', 'estop', 'path_cancel'],
  [NAV_TASKS.replan]: ['path_cancel', 'cancel_ack', 'path_received'],
  // 260915 — 받은 것으로 끝내는 둘. 이동경로 탐색은 첫 경로 수신, 목적지 도착은 경로 끝 통지가 근거다.
  [DERIVED_TASKS.plan]: ['path_received'],
  [DERIVED_TASKS.arrive]: ['path_done', 'path_cancel'],
};

const clock = (ms: number) => new Date(ms).toTimeString().slice(0, 8);

export function NavFacts({ taskId }: { taskId: string }) {
  const feed = useNavFeed();
  const run = navRun();
  const replaying = useReplayTarget() !== null;
  const t = feed.telemetry;

  if (taskId === NAV_TASKS.battery || taskId === NAV_TASKS.yaw) {
    const rows: Array<[string, string]> = [];
    if (t === null) {
      return <p className="robot-log__empty">pi1 중계 값이 아직 한 건도 안 왔습니다 — 연결 관리의 「자율주행 로봇 (pi1 중계)」에서 확인을 누르세요</p>;
    }
    const age = Date.now() - t.receivedAtMs;
    if (taskId === NAV_TASKS.battery) rows.push(['배터리', t.batteryPct === null ? '모름 (pi1 이 null 로 보냄)' : `${t.batteryPct}%`]);
    else {
      rows.push(['yaw', t.yawDeg === null ? '모름 (pi1 이 null 로 보냄)' : `${t.yawDeg.toFixed(1)}° · ${t.yawSource === 'bridge_state' ? '브리지 상태(유니티 규약 · 시계방향 + · 기준은 경로마다 다시 맞춤)' : 'Go1 오도메트리(반시계 +)'}`]);
      // IMU 값이 따로 오면 나란히 — 두 값의 부호·기준이 다르다는 것이 보여야 한다.
      if (t.yawOdometryDeg !== null) rows.push(['yaw (IMU)', `${t.yawOdometryDeg.toFixed(1)}° · Go1 내부 robot/state (반시계 +)`]);
    }
    rows.push(['보낸 곳', [t.nodeId, t.entityId].filter((v) => v !== '').join(' · ') || '적혀 오지 않음']);
    // 다시보기에서는 「몇 초 전 · 낡음」을 안 적는다 — 지난 판의 기록이다.
    rows.push(replaying
      ? ['기록된 마지막 값', clock(t.receivedAtMs)]
      : ['마지막 수신', `${clock(t.receivedAtMs)} · ${Math.round(age / 1000)}초 전${age > NAV_FRESH_MS ? ' (낡음 — 지금 값으로 치지 않습니다)' : ''}`]);
    if (feed.clockOffsetMs !== null) rows.push(['시계 차', `pi1 이 이 PC 보다 ${(-feed.clockOffsetMs / 1000).toFixed(1)}초 ${feed.clockOffsetMs <= 0 ? '앞섭니다' : '늦습니다'} — 늦게 온 사건의 시각을 되돌리는 데만 씁니다`]);
    if (feed.rejected > 0) rows.push(['못 읽은 건', `${feed.rejected}건 — 모양이 계약(viz-nav/1)과 다릅니다`]);
    return <dl className="device-facts">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
  }

  const kinds = EVENTS_OF[taskId];
  if (kinds === undefined) return null;
  // **pi1 시각 순으로** 적는다 — 원천마다 발행 지연이 달라 받은 순서가 일어난 순서와 다르다(260915 §4.4).
  const lines = feed.events
    .filter((event) => kinds.includes(event.event) && (run === null || eventTimeMs(event, feed) >= run.startedAtMs))
    .sort((a, b) => (a.tsMs ?? a.receivedAtMs) - (b.tsMs ?? b.receivedAtMs) || a.seq - b.seq);
  if (lines.length === 0) {
    return <p className="robot-log__empty">이 판에서 pi1 이 전해 준 사건이 아직 없습니다 — {taskId === NAV_TASKS.move
      ? '유니티가 경로를 보내면 여기에 쌓입니다'
      : '유니티가 경로를 바꾸면(PATH_CANCEL) 여기에 쌓입니다'}</p>;
  }
  return <ol className="robot-log__lines">
    {lines.map((event) => <li key={`${event.nodeId}-${event.seq}-${event.receivedAtMs}`} className="is-status">
      {/* 일어난 시각을 적는다 — 늦게 온 사건이면 받은 시각과 다르다(`eventTimeMs`). */}
      <time>{clock(eventTimeMs(event, feed))}</time>
      <span>{isCancelStop(event, feed.events)
        // 유니티가 PATH_CANCEL 과 같은 순간에 보내는 정지다 — 비상 정지로 적지 않는다(노드도 실패로 안 칠한다).
        ? '취소용 정지 — PATH_CANCEL 과 짝 (비상 정지 아님)'
        : EVENT_WORDS[event.event]}{event.pathId === null ? '' : ` · path_id ${event.pathId}`}{event.pointCount === null ? '' : ` · ${event.pointCount}점`}</span>
      <code>{[`seq ${event.seq}`, event.source, event.note].filter((v) => v !== null && v !== '').join(' · ')}</code>
    </li>)}
  </ol>;
}
