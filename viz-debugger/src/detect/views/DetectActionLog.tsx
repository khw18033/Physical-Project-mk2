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

import { useLang } from '../../shared/language.ts';
import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import { useEffect, useState } from 'react';
import { planApproach, wrapDeg } from '../../physical/approachPlan.ts';
import { commandsOfTask, useRobotSession } from '../../physical/robotSession.ts';
import { useDeviceStates } from '../../physical/deviceState.ts';
import { hardwareTarget } from '../../physical/encode.ts';
import { viewpointTaskIndex } from '../../physical/missionLink.ts';
import { usePrepStage } from '../../physical/prepStage.ts';
import { DETECT_TASKS, LANE_WORDS_KEY, useDetectLog, lineText, lineDetail } from '../detectLog.ts';
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

const ago = (now: number, at: number | null) => (at === null
  ? t('dlog.neverReceived')
  : t('dlog.secondsAgo', { sec: Math.max(0, Math.round((now - at) / 1000)) }));

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
  useLang();
  const prep = usePrepStage();
  const devices = useDeviceStates();
  const detect = useDetect();
  const now = useTick();

  if (taskId === DETECT_TASKS.map) {
    const map = prep.map;
    return <section className="prep-facts">
      <h3>{t('dlog.1')}</h3>
      <dl>
        <div><dt>{t('dlog.state')}</dt><dd>{t(STEP_WORDS_KEY[map.step])}{map.reason !== null && ` — ${map.reason}`}</dd></div>
        <div><dt>{t('dlog.5')}</dt><dd>{map.url === null ? t('dlog.2') : <>{map.bundled ? t('dlog.3') : t('dlog.4')} · <code>{map.url}</code></>}</dd></div>
        <div><dt>{t('dlog.6')}</dt><dd>({map.doorCm.x.toFixed(1)}, {map.doorCm.y.toFixed(1)}) cm · px ({map.doorPx.x}, {map.doorPx.y}) <small>{t('dlog.7')}</small></dd></div>
        {map.atIso !== null && <div><dt>{t('dlog.8')}</dt><dd>{map.atIso.slice(11, 23)}</dd></div>}
      </dl>
    </section>;
  }

  if (taskId !== DETECT_TASKS.pose) return null;
  const device = devices[hardwareTarget(ROBOT_ENTITY)] ?? null;
  const live = device?.position ?? null;
  const caught = prep.pose.value;
  const loc = detect.localization;
  // 다시보기면 「지금 로봇 방위」는 이 판의 값이 아니다 — 지난 판 옆에 지금 값을 놓으면 섞어 읽는다.
  const replaying = detect.recordRun !== null;
  return <section className="prep-facts">
    <h3>{t('dlog.9')}</h3>
    <dl>
      <div className="prep-facts__live">
        <dt>{t('dlog.10')}</dt>
        <dd>{replaying
          ? t('dlog.11')
          : live === null
          ? t('dlog.12')
          : <><b>{live.headingDeg.toFixed(1)}°</b> · x {live.x.toFixed(2)} m · y {live.y.toFixed(2)} m
            <small> {t('dlog.liveMeta', { ago: ago(now, device?.positionAtMs ?? null), clock: device?.timestamp?.slice(11, 19) ?? t('dlog.13') })}</small></>}
        </dd>
      </div>
      <div>
        <dt>{t('dlog.14')}</dt>
        <dd>{caught === null
          ? <>{t(STEP_WORDS_KEY[prep.pose.step])}{prep.pose.reason !== null && ` — ${prep.pose.reason}`}</>
          : <><b>{caught.headingDeg.toFixed(1)}°</b> · x {caught.xM.toFixed(2)} m · y {caught.yM.toFixed(2)} m
            <small> {t('dlog.caughtMeta', { clock: caught.receivedAtIso.slice(11, 19) })}</small></>}
        </dd>
      </div>
      <div>
        <dt>{t('dlog.15')}</dt>
        <dd>{loc?.current_heading_map_deg === undefined
          ? t('dlog.16')
          : <><b>{loc.current_heading_map_deg}°</b> {t('dlog.positionCm', { xy: loc.robot_position_cm?.map((n) => n.toFixed(1)).join(', ') ?? '' })}
            <small> {t('dlog.17')}</small></>}
        </dd>
      </div>
    </dl>
  </section>;
}

/**
 * **`T-A3` 로봇이 1바퀴 돈다 — 한 바퀴 뒤 방위** (260914 지시).
 *
 * 각도 칸의 액션 아이템에는 그 회전 보고의 yaw 가 있지만, 여덟째 회전(출발 방향 복귀)은 칸이 없어 어디에도
 * 안 보였다. 그 보고의 yaw 는 이미 받고 있다(`scan_turn` step 8 → `scanReturnYaw`) — pi7 쪽 변경 없이 여기 적는다.
 *
 * 출발 방위와 견준 차이가 한 바퀴의 누적 오차다. 탐지의 회전각은 출발 방향 기준이므로 이 차이만큼 이동이 어긋난다.
 * 모든 값은 로봇 오도메트리 기준이고, 로봇이 안 실은 값은 「모름」으로 둔다.
 */
export function SweepFacts() {
  useLang();
  const session = useRobotSession();
  const prep = usePrepStage();
  const startCapture = session.seenYaw[0];
  const startPose = prep.pose.value?.headingDeg;
  const start = startCapture ?? startPose ?? null;
  const back = session.scanReturnYaw;
  const drift = start !== null && back !== null ? wrapDeg(back - start) : null;
  const scan = commandsOfTask(DETECT_TASKS.sweep).at(-1) ?? null;
  const resultYaw = scan?.result.yaw_deg;
  const turns = Object.entries(session.seenYaw)
    .map(([index, yaw]) => [Number(index), yaw] as const)
    .filter(([index]) => index > 0)
    .sort((a, b) => a[0] - b[0]);
  return <section className="prep-facts">
    <h3>{t('dlog.18')}</h3>
    <dl>
      <div>
        <dt>{t('dlog.19')}</dt>
        <dd>{start === null ? t('dlog.20')
          : <><b>{start.toFixed(1)}°</b> <small>{startCapture !== undefined ? t('dlog.21') : t('dlog.14')}</small></>}</dd>
      </div>
      <div className="prep-facts__live">
        <dt>{t('dlog.22')}</dt>
        <dd>{back === null
          ? (session.scanIssued ? t('dlog.23') : t('dlog.24'))
          : <><b>{back.toFixed(1)}°</b> <small>{t('dlog.25')}</small></>}</dd>
      </div>
      <div>
        <dt>{t('dlog.26')}</dt>
        <dd>{drift === null ? t('dlog.27') : <><b>{drift >= 0 ? '+' : ''}{drift.toFixed(1)}°</b> <small>{t('dlog.28')}</small></>}</dd>
      </div>
      {typeof resultYaw === 'number' && <div><dt>{t('dlog.29')}</dt><dd>{resultYaw.toFixed(1)}° <small>{t('dlog.30')}</small></dd></div>}
      {turns.length > 0 && <div>
        <dt>{t('dlog.31')}</dt>
        <dd>{turns.map(([index, yaw]) => t('dlog.turnAt', { index, yaw: yaw.toFixed(1) })).join(' · ')}{back !== null && t('dlog.turnBack', { yaw: back.toFixed(1) })}</dd>
      </div>}
    </dl>
  </section>;
}

/** 대체 경로 단계의 사람 이름. */
const STEP_NAMES_KEY: Record<string, string> = {
  A_pedestal: 'dlog.32',
  B_door_only: 'dlog.33',
  C_door_relative: 'dlog.34',
  path_map: 'dlog.35',
};

/**
 * **`T-B1` 2D 맵 기반 경로 산출이 어떻게 나왔나** (260914 지시 — 「경로 산출 과정을 액션 아이템에서」).
 *
 * 탐지가 준 산출물 그대로다 — 대체 경로가 어디서 왜 넘어갔는지, 문 거리를 무엇으로 어림했는지,
 * 식과 대입값, 탐지가 낸 로봇 명령. **다시 계산하지 않는다.**
 */
export function PathFacts() {
  useLang();
  const detect = useDetect();
  const path = detect.path ?? detect.pathFailureDetail;
  if (path === null) {
    return <section className="prep-facts">
      <h3>{t('dlog.36')}</h3>
      <p className="robot-log__empty">{t('dlog.37')}</p>
    </section>;
  }
  const distance = path.door_distance_estimate ?? null;
  const command = path.robot_command ?? null;
  return <section className="prep-facts">
    <h3>{t(path.ok ? 'dlog.pathResult' : 'dlog.pathResultFailed')}</h3>
    <dl>
      <div><dt>{t('dlog.39')}</dt><dd>{path.ok ? <><b>{path.turn_instruction}</b> {t('dlog.forwardM', { m: (path.forward_distance_cm / 100).toFixed(2) })}</> : <span className="detect-map__failed">{path.reason}</span>}</dd></div>
      {path.path_mode_words !== undefined && <div><dt>{t('dlog.40')}</dt><dd>{path.path_mode_words}</dd></div>}
    </dl>
    {(path.fallback_chain ?? []).length > 0 && <ol className="path-chain">
      {(path.fallback_chain ?? []).map((step, at) => <li key={`${step.step}-${at}`} className={step.ok ? 'is-ok' : 'is-fail'}>
        <b>{step.ok ? '✓' : '✕'} {t(STEP_NAMES_KEY[step.step]) ?? step.step}</b> <span>{step.detail}</span>
      </li>)}
    </ol>}
    {distance !== null && <>
      <h4>{t('dlog.41')}</h4>
      <p className="path-note"><code>{distance.formula}</code>{distance.substituted !== undefined && <> → {distance.substituted}</>}{distance.reason !== undefined && <> · <span className="detect-map__failed">{distance.reason}</span></>}</p>
      <table className="path-table"><thead><tr><th>{t('dlog.42')}</th><th>{t('dlog.43')}</th><th>{t('dlog.44')}</th><th>{t('dlog.45')}</th><th>{t('dlog.46')}</th><th>{t('dlog.47')}</th></tr></thead>
        <tbody>{distance.per_frame.map((row) => <tr key={row.frame}>
          <td>{row.frame}</td><td>{row.rotation_deg}°</td>
          <td>{row.box_w_px}{row.width_clipped ? t('dlog.48') : ''}</td><td>{row.box_h_px}{row.height_clipped ? t('dlog.48') : ''}</td>
          <td>{row.distance_from_width_cm ?? '—'}</td><td>{row.distance_from_height_cm ?? row.skipped_reason ?? '—'}</td>
        </tr>)}</tbody>
      </table>
    </>}
    {Object.keys(path.path_calculation ?? {}).length > 0 && <>
      <h4>{t('dlog.49')}</h4>
      <ol className="detect-steps">
        {Object.entries(path.path_calculation).map(([name, step]) => <li key={name}>
          <code>{step.formula}</code>
          <small>{step.substituted}</small>
        </li>)}
      </ol>
    </>}
    {command !== null && <p className="path-note">
      <Rich id="dlog.issuedCommand" vars={{ deg: command.turn.deg, m: command.move_forward.distance_m }} />
      <small> {t('dlog.50')}</small>
      {command.warning !== undefined && <> · <span className="detect-map__failed">{command.warning}</span></>}
    </p>}
  </section>;
}

/**
 * **`T-B2` 경로 → 실제로 보낼 명령** (260914). 버튼·발행과 같은 계산(`planApproach`)을 그대로 보여 준다.
 * 실제로 나간 명령과 로봇의 응답은 그 아래 「로봇 명령 · 오간 로그」에 있다.
 */
export function ApproachFacts() {
  useLang();
  useDetect();
  useRobotSession();
  useTick(2000);
  const plan = planApproach();
  return <section className="prep-facts">
    <h3>{t('dlog.51')}</h3>
    {!plan.ok
      ? <p className="robot-log__empty">{plan.reason}</p>
      : <dl>
        <div><dt>{t('dlog.52')}</dt><dd>{turnWords(plan.detectionTurnDeg)} <small>{t('dlog.53')}</small></dd></div>
        <div className="prep-facts__live"><dt>{t('dlog.54')}</dt><dd><b>{plan.steps.map((step) => step.action === 'turn'
          ? `turn ${step.parameters?.deg}°`
          : step.action === 'move_forward' ? `move_forward ${step.parameters?.distance_m} m` : t('dlog.arriveStop', { action: step.action })).join(' → ')}</b></dd></div>
        <div><dt>{t('dlog.55')}</dt><dd>{t('dlog.plannedPath', { m: plan.plannedForwardM.toFixed(3) })}{Math.abs(plan.plannedForwardM - plan.issuedForwardM) > 0.0005 && t('dlog.testOnly', { m: plan.issuedForwardM.toFixed(3) })} {t('dlog.speed', { vx: plan.forwardVx })} <small>{t('dlog.56')}</small></dd></div>
        {plan.notes.map((note) => <div key={note}><dt>{t('dlog.57')}</dt><dd>{note}</dd></div>)}
      </dl>}
  </section>;
}

const turnWords = (deg: number) => t(deg < 0 ? 'dlog.turnLeft' : 'dlog.turnRight', { deg: Math.abs(deg).toFixed(1) });

/** `idle` 은 「임무 시작」 전이거나, 로봇이 안 몰아 대본이 노드를 칠한 경우다. */
const STEP_WORDS_KEY = { idle: 'dlog.58', running: 'dlog.59', done: 'dlog.60', failed: 'dlog.61' } as const;

/** **탐지 경로에서 오간 줄.** 그 태스크에 붙은 것만, 받은 순서 그대로. */
export function DetectLogLines({ taskId }: { taskId: string }) {
  useLang();
  const all = useDetectLog();
  const lines = all.filter((line) => line.tasks.includes(taskId));
  return <section className="detect-log">
    <h3>{t('dlog.62')}</h3>
    {lines.length === 0
      ? <p className="robot-log__empty">{t('dlog.63')}</p>
      : <ol className="detect-log__lines">
        {lines.map((line, at) => <li key={`${line.atIso}-${at}`} className={`is-${line.level} lane-${line.lane}`}>
          <time>{line.atIso.slice(11, 23)}</time>
          <em>{t(LANE_WORDS_KEY[line.lane])}</em>
          {/* **반드시 이것을 거친다** — `line.text` 를 바로 읽으면 새 줄이 빈칸이다.
              새 줄은 키를 들고 있고 여기서 지금 언어로 풀린다 (`detectLog.ts`). */}
          <span>{lineText(line)}</span>
          {lineDetail(line) !== '' && <code>{lineDetail(line)}</code>}
        </li>)}
      </ol>}
  </section>;
}
