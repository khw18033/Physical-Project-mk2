/**
 * src/detect/views/DetectActionLog.tsx (260914 신설)
 *
 * **액션 아이템에 붙는 탐지 쪽 두 자리.**
 *
 *   PrepFacts        T-A1 · T-A2 가 실제로 받아 온 값 — 도면과 문 자리, 로봇의 지금 방위(yaw)
 *   DetectLogLines   탐지 경로에서 오간 줄 — 로봇 → 탐지 · 탐지 → 화면 · 화면의 판단
 *
 * 로봇 명령 로그(`ActionModal` 의 RobotCommands)와 같은 규칙이다 — **받은 값만 적고, 없으면
 * 없다고 적는다.**
 */

import { useEffect, useState } from 'react';
import { useDeviceStates } from '../../physical/deviceState.ts';
import { hardwareTarget } from '../../physical/encode.ts';
import { viewpointTaskIndex } from '../../physical/missionLink.ts';
import { usePrepStage } from '../../physical/prepStage.ts';
import { DETECT_TASKS, LANE_WORDS, useDetectLog } from '../detectLog.ts';
import { useDetect } from '../store.ts';

const ROBOT_ENTITY = 'robot-01';

/** 탐지 경로의 태스크인가 — 액션 아이템이 이 자리를 열지 정한다. */
export function isDetectTask(taskId: string): boolean {
  return viewpointTaskIndex(taskId) !== null
    || (Object.values(DETECT_TASKS) as string[]).includes(taskId);
}

/** 초 단위로 다시 그린다 — 「몇 초 전 값」이 멈춰 있으면 낡은 값을 지금 값으로 읽는다. */
function useTick(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}

const ago = (now: number, at: number | null) => (at === null ? '받은 적 없음' : `${Math.max(0, Math.round((now - at) / 1000))}초 전`);

/**
 * **T-A1 · T-A2 가 받아 온 값** (260914 지시 — 「로봇의 현재 실제 yaw 값을 T-A2 액션 아이템에서」).
 *
 * T-A2 는 세 값을 나란히 놓는다. 셋은 **기준이 다르다** — 섞어 한 숫자로 적지 않는다.
 *
 *   지금 로봇 방위      로봇이 5초마다 보내는 state.position.heading_deg — 실시간으로 바뀐다
 *   T-A2 가 잡은 방위   준비 단계가 끝날 때 받은 값 — 한 바퀴의 출발 방위다
 *   탐지가 역산한 방위  한 바퀴 뒤 탐지가 받침대로 역산한 **도면 기준** 방위 — 기준점이 다르다
 */
export function PrepFacts({ taskId }: { taskId: string }) {
  const prep = usePrepStage();
  const devices = useDeviceStates();
  const detect = useDetect();
  const now = useTick();

  if (taskId === DETECT_TASKS.map) {
    const map = prep.map;
    return <section className="prep-facts">
      <h3>도면 · 문 위치</h3>
      <dl>
        <div><dt>상태</dt><dd>{STEP_WORDS[map.step]}{map.reason !== null && ` — ${map.reason}`}</dd></div>
        <div><dt>도면</dt><dd>{map.url === null ? '아직 안 받았습니다' : <>{map.bundled ? '저장소 사본' : '탐지 창구'} · <code>{map.url}</code></>}</dd></div>
        <div><dt>문 도면 위치</dt><dd>({map.doorCm.x.toFixed(1)}, {map.doorCm.y.toFixed(1)}) cm · px ({map.doorPx.x}, {map.doorPx.y}) <small>GT 고정값 — 검출값이 아닙니다</small></dd></div>
        {map.atIso !== null && <div><dt>받은 시각</dt><dd>{map.atIso.slice(11, 23)}</dd></div>}
      </dl>
    </section>;
  }

  if (taskId !== DETECT_TASKS.pose) return null;
  const device = devices[hardwareTarget(ROBOT_ENTITY)] ?? null;
  const live = device?.position ?? null;
  const caught = prep.pose.value;
  const loc = detect.localization;
  return <section className="prep-facts">
    <h3>로봇 방위 (yaw)</h3>
    <dl>
      <div className="prep-facts__live">
        <dt>지금 로봇 방위</dt>
        <dd>{live === null
          ? '로봇 state 를 받은 적이 없습니다 — 브로커에 붙어 있는지 볼 것'
          : <><b>{live.headingDeg.toFixed(1)}°</b> · x {live.x.toFixed(2)} m · y {live.y.toFixed(2)} m
            <small> {ago(now, device?.positionAtMs ?? null)} · 로봇 시각 {device?.timestamp?.slice(11, 19) ?? '없음'} · 오도메트리 기준</small></>}
        </dd>
      </div>
      <div>
        <dt>T-A2 가 잡은 방위</dt>
        <dd>{caught === null
          ? <>{STEP_WORDS[prep.pose.step]}{prep.pose.reason !== null && ` — ${prep.pose.reason}`}</>
          : <><b>{caught.headingDeg.toFixed(1)}°</b> · x {caught.xM.toFixed(2)} m · y {caught.yM.toFixed(2)} m
            <small> 받은 시각 {caught.receivedAtIso.slice(11, 19)} · 한 바퀴의 출발 방위</small></>}
        </dd>
      </div>
      <div>
        <dt>탐지가 역산한 방위</dt>
        <dd>{loc?.current_heading_map_deg === undefined
          ? '아직 없습니다 — 탐지는 한 바퀴를 다 받은 뒤에 역산합니다'
          : <><b>{loc.current_heading_map_deg}°</b> · 위치 ({loc.robot_position_cm?.map((n) => n.toFixed(1)).join(', ')}) cm
            <small> 도면 기준 — 로봇 방위와 기준점이 다릅니다</small></>}
        </dd>
      </div>
    </dl>
  </section>;
}

/** `idle` 은 「임무 시작」 전이거나, 로봇이 안 몰아 대본이 노드를 칠한 경우다. */
const STEP_WORDS = { idle: '아직 안 했습니다 — 로봇이 몰 때 「임무 시작」 뒤에 채워집니다', running: '진행 중', done: '완료', failed: '실패' } as const;

/** **탐지 경로에서 오간 줄.** 그 태스크에 붙은 것만, 받은 순서 그대로. */
export function DetectLogLines({ taskId }: { taskId: string }) {
  const all = useDetectLog();
  const lines = all.filter((line) => line.tasks.includes(taskId));
  return <section className="detect-log">
    <h3>탐지 · 오간 로그</h3>
    {lines.length === 0
      ? <p className="robot-log__empty">이 태스크에 붙은 탐지 쪽 줄이 아직 없습니다 — 로봇이 프레임을 보내거나 탐지 창구가 답하면 여기에 쌓입니다</p>
      : <ol className="detect-log__lines">
        {lines.map((line, at) => <li key={`${line.atIso}-${at}`} className={`is-${line.level} lane-${line.lane}`}>
          <time>{line.atIso.slice(11, 23)}</time>
          <em>{LANE_WORDS[line.lane]}</em>
          <span>{line.text}</span>
          {line.detail !== '' && <code>{line.detail}</code>}
        </li>)}
      </ol>}
  </section>;
}
