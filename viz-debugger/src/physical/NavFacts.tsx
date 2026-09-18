/**
 * src/physical/NavFacts.tsx (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * 액션 아이템에 붙는 **pi1 이 실제로 전해 준 것.** 배터리·방위 노드는 받은 값과 받은 시각,
 * 이동·재탐색 노드는 받은 사건 줄. **없으면 비운다** — 지어 채우지 않는다.
 */

// 이 파일은 `const t = feed.telemetry` 로 `t` 를 쓴다 — 사전 함수는 다른 이름으로 들여온다.
import { t as tr } from '../i18n/dict.ts';
import { DERIVED_TASKS, NAV_TASKS } from './navLink.ts';
import { eventTimeMs, isCancelStop, NAV_FRESH_MS, useNavFeed, type NavEvent } from './navFeed.ts';
import { navRun } from './navRun.ts';
import { useReplayTarget } from '../record/replayMode.ts';

/**
 * 사건 이름의 **사전 키**. 어디서 봤는지(`journal` · `udp…`)는 옆 줄에 그대로 적는다.
 *
 * 260918 — 글자가 아니라 키다. 모듈 최상위 상수라 여기서 사전을 부르면 언어가 굳는다.
 */
const EVENT_WORD_KEYS: Record<NavEvent['event'], string> = {
  path_received: 'nav.event.pathReceived',
  path_cancel: 'nav.event.pathCancel',
  // 260915 pi1 답신 — 지금 브리지(go1_sdk_pc)는 mode 98 을 보내지 않아 이 사건은 오지 않는다. 오면 적는다.
  cancel_ack: 'nav.event.cancelAck',
  path_done: 'nav.event.pathDone',
  estop: 'nav.event.estop',
  feed_started: 'nav.event.feedStarted',
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
      return <p className="robot-log__empty">{tr('nav.noRelayYet')}</p>;
    }
    const age = Date.now() - t.receivedAtMs;
    if (taskId === NAV_TASKS.battery) rows.push([tr('nav.battery'), t.batteryPct === null ? tr('nav.unknownNull') : `${t.batteryPct}%`]);
    else {
      rows.push(['yaw', t.yawDeg === null
        ? tr('nav.unknownNull')
        : tr('nav.yawValue', {
          deg: t.yawDeg.toFixed(1),
          source: tr(t.yawSource === 'bridge_state' ? 'nav.yawFromBridge' : 'nav.yawFromOdometry'),
        })]);
      // IMU 값이 따로 오면 나란히 — 두 값의 부호·기준이 다르다는 것이 보여야 한다.
      if (t.yawOdometryDeg !== null) rows.push(['yaw (IMU)', tr('nav.yawImu', { deg: t.yawOdometryDeg.toFixed(1) })]);
    }
    rows.push([tr('nav.sender'), [t.nodeId, t.entityId].filter((v) => v !== '').join(' · ') || tr('nav.senderMissing')]);
    // 다시보기에서는 「몇 초 전 · 낡음」을 안 적는다 — 지난 판의 기록이다.
    rows.push(replaying
      ? [tr('nav.recordedLast'), clock(t.receivedAtMs)]
      : [tr('nav.lastReceived'), tr('nav.lastReceivedValue', { clock: clock(t.receivedAtMs), sec: Math.round(age / 1000) })
        + (age > NAV_FRESH_MS ? tr('nav.stale') : '')]);
    if (feed.clockOffsetMs !== null) {
      rows.push([tr('nav.clockSkew'), tr(feed.clockOffsetMs <= 0 ? 'nav.clockAhead' : 'nav.clockBehind', { sec: (-feed.clockOffsetMs / 1000).toFixed(1) })]);
    }
    if (feed.rejected > 0) rows.push([tr('nav.unreadable'), tr('nav.unreadableValue', { n: feed.rejected })]);
    return <dl className="device-facts">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
  }

  const kinds = EVENTS_OF[taskId];
  if (kinds === undefined) return null;
  // **pi1 시각 순으로** 적는다 — 원천마다 발행 지연이 달라 받은 순서가 일어난 순서와 다르다(260915 §4.4).
  const lines = feed.events
    .filter((event) => kinds.includes(event.event) && (run === null || eventTimeMs(event, feed) >= run.startedAtMs))
    .sort((a, b) => (a.tsMs ?? a.receivedAtMs) - (b.tsMs ?? b.receivedAtMs) || a.seq - b.seq);
  if (lines.length === 0) {
    return <p className="robot-log__empty">{tr('nav.noEventsYet', {
      how: tr(taskId === NAV_TASKS.move ? 'nav.willFillOnPath' : 'nav.willFillOnCancel'),
    })}</p>;
  }
  return <ol className="robot-log__lines">
    {lines.map((event) => <li key={`${event.nodeId}-${event.seq}-${event.receivedAtMs}`} className="is-status">
      {/* 일어난 시각을 적는다 — 늦게 온 사건이면 받은 시각과 다르다(`eventTimeMs`). */}
      <time>{clock(eventTimeMs(event, feed))}</time>
      <span>{isCancelStop(event, feed.events)
        // 유니티가 PATH_CANCEL 과 같은 순간에 보내는 정지다 — 비상 정지로 적지 않는다(노드도 실패로 안 칠한다).
        ? tr('nav.cancelStop')
        : tr(EVENT_WORD_KEYS[event.event])}{event.pathId === null ? '' : ` · path_id ${event.pathId}`}{event.pointCount === null ? '' : tr('nav.points', { n: event.pointCount })}</span>
      <code>{[`seq ${event.seq}`, event.source, event.note].filter((v) => v !== null && v !== '').join(' · ')}</code>
    </li>)}
  </ol>;
}
