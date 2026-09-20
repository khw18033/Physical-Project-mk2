/**
 * src/views/ActionModal.tsx
 *
 * 노드 하나를 열었을 때의 상세. **여기 적히는 값은 실제로 오간 것이다** (260912 지시).
 *
 * 전에는 두 자리가 손으로 쓴 예시였다.
 *
 *   액션 아이템   대본의 빈 목록. 로봇 시연 편에서는 늘 0건이라 표가 비어 있었다
 *   실패 사유     「진입 중 측면 클리어런스 0.06 m …」 — 일어난 적 없는 일이 실패마다 떴다
 *
 * 그 둘을 **로봇이 실제로 주고받은 것**으로 바꿨다. 낸 명령과 그때 실린 파라미터, 그
 * 명령으로 오간 로그 줄, 종료 응답. **없으면 비운다** — 지어 채우지 않는다.
 *
 * ## 260920 — 명령 표가 재생 머리를 따라간다 (명령 기록 합류 §4)
 *
 * 전까지 이 표는 작업대(`robotSession`)를 **직접** 읽었다. 작업대는 지금 값이라 되감아도
 * 안 따라온다 — 재생 머리를 10초로 옮겨 놓아도 표에는 40초에 온 줄까지 전부 떠 있었다.
 * 「모든 노드가 같은 재생 머리를 쓴다」(논문 §4-4)가 이 화면에서 깨져 있던 자리다.
 *
 * 이제 **접은 결과**(`actionsAt()`)를 읽는다. 명령도 응답도 기록 열에 들어와 있으므로
 * 그 시점까지의 것만 접힌다. 라이브든 목이든 읽는 곳이 같다 — 로봇 없이도 같은 표가 뜬다.
 *
 * ## 다 적는 것과 다 보여주는 것은 다르다 (§4-5)
 *
 * 기록에는 전부 남긴다. 화면은 **접힌 상태에서 판정과 숫자**만 보이고, 한 번 더 눌러야
 * 줄이 열린다. 격리로 600줄을 40줄로 줄여 놓고 화면에서 다시 600줄을 보이면 줄인 의미가
 * 없다 — 값을 **감추는 것이 아니라** 한 번 더 눌러야 나오게 두는 것이다.
 */

import { useState } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { actionsAt, displayMission, recordAdjusted, traceFor, useMission, type MissionView } from '../data/scenario.ts';
import {
  actionsOfTask, neverAnswered, planAdjustments, stillWaiting,
  type ActionStatus, type FoldedAction,
} from '../data/actionTrace.ts';
import { relayDriven } from '../scenarios/library.ts';
import { isNavTask } from '../physical/navLink.ts';
import { NavFacts } from '../physical/NavFacts.tsx';
import { OBSTACLE_TASK } from '../autodrive/obstacle.ts';
import { ObstacleEvidence, ObstacleFacts } from '../autodrive/views/AutodriveViews.tsx';
import type { Hardware, Task } from '../model/types.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { stateLabel } from '../graph/stateStyle.ts';
import { failureOfTask } from '../physical/robotCommands.ts';
import { viewpointTaskIndex } from '../physical/missionLink.ts';
import { useRobotSession } from '../physical/robotSession.ts';
import { DeviceStrip } from './DeviceStrip.tsx';
import { ApproachFacts, DetectLogLines, isDetectTask, PathFacts, PrepFacts, SweepFacts } from '../detect/views/DetectActionLog.tsx';
import { t } from '../i18n/dict.ts';
import { Rich } from '../i18n/RichText.tsx';
import { useLang } from '../shared/language.ts';

/** 명령 하나의 상태를 사람 말로. 로봇이 준 상태 그대로를 옮긴다. */
const COMMAND_STATE_KEY: Record<ActionStatus, string> = {
  issued: 'cmd.published',
  running: 'cmd.running',
  done: 'task.state.done',
  failed: 'task.state.failed',
};

/** 낸 시각과 마지막 응답 시각의 차. 응답이 없으면 null — 0초라고 적지 않는다. */
function tookSec(action: FoldedAction): number | null {
  const last = action.lines.at(-1);
  if (last === undefined) return null;
  return last.atSec - action.issuedAtSec;
}

/** 값 하나를 그릴 수 있는 글자로. 없는 것은 「—」다 — `null` 을 0으로 적지 않는다. */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * **전후 짝.** 후만 그리면 무엇이 바뀌었는지 모른다 — 그 한 줄이 §4 의 요구다.
 */
function AdjustList({ items }: { items: readonly { atSec: number; field: string; before: unknown; after: unknown }[] }) {
  useLang();
  if (items.length === 0) return null;
  return <div className="robot-log__adjust">
    <b>{t('act.adjusted')}</b>
    <ul>
      {items.map((item, at) => <li key={`${item.field}-${item.atSec}-${at}`}>
        {t('act.adjustPair', { field: item.field, before: shown(item.before), after: shown(item.after) })}
        <small> · T+{item.atSec.toFixed(0)}s</small>
      </li>)}
    </ul>
  </div>;
}

/**
 * **로봇과 실제로 오간 것.** 낸 명령 · 실린 파라미터 · 그 뒤로 온 모든 줄.
 *
 * 한 태스크가 명령을 여럿 낼 수 있다 — 「산출된 경로에 따라 이동」은 회전과 직진 둘이다.
 * 그래서 이름이 아니라 **낸 순서대로** 늘어놓는다.
 */
function RobotCommands({ taskId }: { taskId: string }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  // **재생 머리가 움직이면 다시 접는다.** 전에는 작업대만 구독해서, 되감아도 표가 그대로였다.
  useMission();
  useRobotSession();                       // 로그가 오는 대로 다시 그린다

  /**
   * **각도 칸은 한 명령의 제 몫만 본다** (260912 지시).
   *
   * 한 바퀴는 명령 하나(`scan_mission`)인데 노드는 여덟이다. 각 칸에 그 명령 전체를
   * 붙이면 여덟 칸이 똑같은 표 여덟 개가 된다 — 「이 각도에서 무슨 일이 있었나」를
   * 물었는데 한 바퀴 전체가 나온다. 그래서 걸음 번호로 갈라 준다.
   *
   * 260920 — 가르는 재료가 작업대에서 **접은 결과**로 바뀌었다. 규칙은 그대로다.
   */
  const angle = viewpointTaskIndex(taskId);
  const folded = actionsAt();
  const groups = angle === null
    ? actionsOfTask(folded, taskId).map((action) => ({ action, lines: action.lines }))
    : folded
        .map((action) => ({ action, lines: action.lines.filter((line) => line.index === angle) }))
        .filter((group) => group.lines.length > 0);

  if (groups.length === 0) {
    return <p className="robot-log__empty">
      {angle === null
        ? t('act.noCommands')
        : angle === 0
          ? t('act.zeroDegree')
          : t('act.noRowsYet')}
    </p>;
  }
  return <div className="robot-log">
    {groups.map(({ action, lines }, index) => {
      const took = tookSec(action);
      const params = Object.entries(action.parameters);
      return <section key={action.commandId} className={`robot-log__cmd is-${action.status}`}>
        <header>
          <b>{index + 1}. {action.action}</b>
          <span>{t(COMMAND_STATE_KEY[action.status])}</span>
          {/**
            * **「아직 기다림」과 「영영 안 옴」을 다르게 적는다** (§2 · §4).
            *
            * 둘 다 응답이 0줄이라 글자가 같으면 화면에서 영원히 구분되지 않는다. 느린 것과
            * 죽은 것은 원인이 완전히 다르므로, 여기가 그 구분이 사람 눈에 닿는 유일한 자리다.
            */}
          {neverAnswered(action) && <span className="robot-log__flag is-expired">{t('act.noAnswer')}</span>}
          {stillWaiting(action) && <span className="robot-log__flag is-waiting">{t('act.waiting')}</span>}
          {/* **응답이 없으면 시간을 안 적는다.** 0초로 적으면 즉시 끝난 것으로 읽힌다. */}
          {took !== null && <span>{t('act.tookSec', { sec: took.toFixed(1) })}</span>}
          {/* 각도 칸에서는 **이 표가 한 명령의 일부**라는 것을 적는다. */}
          {angle !== null && <span>{t('act.nthStep', { n: angle + 1 })}</span>}
          <code>{action.commandId}</code>
        </header>
        <p className="robot-log__params">
          {params.length === 0
            ? t('act.noParams')
            : params.map(([key, value]) => `${key}=${value}`).join(' · ')}
        </p>
        {/* 기한이 끝났으면 **얼마나 기다렸고 왜 끝났는지**까지 적는다. 그것도 디버깅 정보다. */}
        {action.expired !== null && <p className="robot-log__expired">
          {t('act.waitedFor', { sec: (action.expired.waitedMs / 1000).toFixed(0), reason: action.expired.reason })}
        </p>}
        <AdjustList items={action.adjustments} />
        <LogLines lines={lines} />
      </section>;
    })}
  </div>;
}

/**
 * 오간 줄. 받은 순서 그대로이고 문장은 로봇이 준 값으로만 만든다.
 *
 * **접힌 채로 연다** (§4-5 표시 깊이) — 판정과 줄 수는 위에 이미 있고, 줄 자체는 한 번 더
 * 눌러야 나온다. 감추는 것이 아니라 기본으로 안 펴는 것이다. 여덟 칸이 각각 수십 줄을
 * 펼치면 격리로 줄여 놓은 것이 화면에서 도로 늘어난다.
 */
function LogLines({ lines }: { lines: readonly { atSec: number; kind: string; text: string; index: number | null }[] }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  if (lines.length === 0) {
    return <ol className="robot-log__lines"><li className="is-empty"><span>{t('act.noResponse')}</span></li></ol>;
  }
  return <details className="robot-log__fold">
    <summary>{t('act.showLines')} · {t('act.answerCount', { n: lines.length })}</summary>
    <ol className="robot-log__lines">
      {lines.map((line, at) => <li key={`${line.atSec}-${at}`} className={`is-${line.kind}`}>
        <time>T+{line.atSec.toFixed(0)}s</time>
        <span>{line.text}</span>
      </li>)}
    </ol>
  </details>;
}

/** **실패 사유 — 로봇이 준 것만.** 없으면 비운다 (260912 지시). */
function FailureReason({ taskId }: { taskId: string }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  useRobotSession();
  const reason = failureOfTask(taskId);
  return <div className="failure-reason">
    <b>{t('act.failReason')}</b>
    {reason === null
      ? <p className="failure-reason--empty">
          <Rich id="act.noReasonSent" />
        </p>
      : <p>{reason.words}{reason.atIso !== null && <small> · {reason.atIso.slice(11, 23)}</small>}</p>}
  </div>;
}

export function ActionModal({ task, view, device, failure, onClose }: { task: Task; view: MissionView; device?: Hardware; failure?: boolean; onClose(): void }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  // **재생 머리를 구독한다** — 아래 명령 수와 조정 목록이 접은 결과를 읽는다.
  useMission();
  const [speed, setSpeed] = useState('0.35'); const [clearance, setClearance] = useState('0.18');
  const action = (kind: string) => void issueCommand({ action: kind, entity: task.id, params: { speed, clearance } });
  /**
   * **사람이 값을 바꾸면 전후를 짝으로 남긴다** (§1 `adjusted` · §4).
   *
   * 글자 하나 칠 때마다 남기면 「0.3」→「0.35」가 두 줄이 된다. 칸에서 손을 뗄 때 한 번,
   * 그리고 **실제로 달라졌을 때만** 남긴다.
   *
   * `nodeId` 는 그 태스크다 — 이 폼이 뜨는 자리에는 아직 낸 명령이 없고(아래 조건),
   * 바꾸는 것이 **계획값**이기 때문이다. 명령이 있는 자리의 조정은 그 `commandId` 에
   * 붙는다(`actionTrace.ts` 의 `planAdjustments` 주석).
   *
   * **값을 바꾸는 것과 재시작에 잇는 것은 다르다.** 잇는 것은 2부이고, 여기서는 기록만
   * 한다 — 로봇에 나가는 것은 한 줄도 안 바뀐다.
   */
  const [beforeEdit, setBeforeEdit] = useState<Record<string, string>>({});
  const startAdjust = (field: string, value: string) => setBeforeEdit((held) => ({ ...held, [field]: value }));
  const noteAdjust = (field: string, after: string) => {
    // **들어올 때의 값**과 견준다. 나갈 때 칸을 읽으면 `onChange` 가 이미 고쳐 놓은
    // 뒤라 둘이 언제나 같고, 그러면 조정이 한 건도 안 남는다.
    const before = beforeEdit[field];
    if (before === undefined || before === after) return;
    recordAdjusted({ commandId: task.id, taskId: task.id, field, before, after });
  };
  const planChanges = planAdjustments(displayMission().headSec, traceFor(view), task.id);
  const foldedHere = actionsOfTask(actionsAt(), task.id);
  // 대본(registry 세계)의 평가는 대본 파일에서 읽는다 — 기준은 task.evaluation, 근거값은
  // 기록 열의 payload (예: MS-E 의 distance_m: 2.7). 옛 편은 전달본의 목 문구 그대로다.
  // **중계 편은 흘러온 기록에서 읽는다** (260915). 대본의 사건은 그 편의 정의일 뿐이라, 거기서 읽으면
  // pi1 이 아무것도 안 보냈는데 「배터리 82%」 같은 대본 값이 근거로 뜬다.
  const relay = relayDriven(view.missionId);
  const evidence = view.world === 'registry'
    ? (relay ? traceFor(view) : view.events).filter((e) => e.nodeId === task.id && e.payload && Object.keys(e.payload).length > 0).at(-1)?.payload ?? null
    : null;
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className={`modal ${failure ? 'failure-modal' : ''}`}>
    <header><div><h2>{failure ? '× ' : ''}{task.id} · {task.title}{failure ? t('act.failedSuffix') : ''}</h2>{/* **낸 명령 수를 적는다.** 「액션 아이템 0건」은 이 편에서 늘 0이라 아무것도 안 알려
          줬다. 대본에 목록이 실제로 들어 있는 편에서는 그 수도 같이 적는다. */}
      <small>{viewpointTaskIndex(task.id) === null
        ? t('act.commandCount', { n: foldedHere.length })
        : t('act.logAtAngle', { n: actionsAt().reduce((sum, a) => sum + a.lines.filter((line) => line.index === viewpointTaskIndex(task.id)).length, 0) })}{task.actionItems.length > 0 && t('act.actionItemCount', { n: task.actionItems.length })} · target {task.target ?? t('gen.none')}</small></div><button onClick={onClose}>{t('conn.close')}</button></header>
    {failure ? <FailureReason taskId={task.id} /> : device && <PendingSource id="robot-status-strip" minHeight={104}><DeviceStrip device={device} /></PendingSource>}
    {/* **로봇이 실제로 낸 명령이 있으면 이 폼을 안 띄운다** (260912 지시).
        「진입 속도 · 최소 클리어런스」는 구판 편의 입력칸이다. 회전·직진이 실패한 자리에
        그 둘을 띄우면 그 값을 고쳐 다시 하면 되는 것처럼 읽힌다 — 실패한 명령에는 그런
        파라미터가 아예 없다. 구판 편에서는 그대로 둔다. */}
    {failure && foldedHere.length === 0 && <div className="parameter-form">
      <label>{t('act.entrySpeed')}<input value={speed} onFocus={() => startAdjust('speed', speed)} onBlur={() => noteAdjust('speed', speed)} onChange={(event) => setSpeed(event.target.value)} /> m/s</label>
      <label>{t('act.minClearance')}<input value={clearance} onFocus={() => startAdjust('clearance', clearance)} onBlur={() => noteAdjust('clearance', clearance)} onChange={(event) => setClearance(event.target.value)} /> m</label>
      {/* **바꾼 값은 전후로 남는다.** 후만 보이면 무엇이 바뀌었는지 화면이 답할 수 없다. */}
      <AdjustList items={planChanges} />
    </div>}
    {<div className="modal-grid"><div className="modal-grid__left">
      {/* **액션 아이템 자리가 실제 제어 명령이다** (260912 지시). 대본의 목록은 로봇 편에서
          늘 0건이었고, 정작 알고 싶은 것은 무엇이 나갔고 무엇이 돌아왔는가였다.
          대본에 목록이 실제로 들어 있는 편(구판)에서는 그것도 같이 보여 준다. */}
      {/* **준비 두 걸음이 받아 온 값** (260914 지시) — T-A1 은 도면과 문 자리, T-A2 는 로봇의
          지금 방위(yaw). 이 둘은 로봇에 명령을 안 내므로 아래 로봇 명령 표는 비어 있다. */}
      <PrepFacts taskId={task.id} />
      {/* **경로 산출 과정 · 최종 제어 명령** (260914 지시). T-B1 은 탐지가 경로를 어떻게 냈는지(대체
          경로 A→B→C · 문 거리 근거 · 식), T-B2 는 그 경로가 로봇 명령으로 어떻게 바뀌었는지(방위 보정). */}
      {task.id === 'T-A3' && <SweepFacts />}
      {task.id === 'T-B1' && <PathFacts />}
      {task.id === 'T-B2' && <ApproachFacts />}
      {/* **중계 편은 화면이 명령을 안 낸다** (260915) — 로봇은 유니티가 몬다. 대신 pi1 이 전해 준 것을 붙인다. */}
      {relay
        ? <>
            {isNavTask(task.id) && <><h3>{t('act.relayValues')}</h3><NavFacts taskId={task.id} /></>}
            {/* **장애물 탐지는 AI 서버가 준 것 그대로** (260915). 문 찾기 시연의 탐지 로그와 다른 서버다. */}
            {task.id === OBSTACLE_TASK && <><h3>{t('act.obstacleAi')}</h3><ObstacleFacts /></>}
          </>
        : <><h3>{t('act.robotLog')}</h3><RobotCommands taskId={task.id} /></>}
      {/* **탐지 쪽에서 오간 것** (260914 지시). 로봇 → 탐지 프레임, 탐지 → 화면 결과, 화면의
          판단이 그 태스크 몫만 붙는다. 탐지 그림이 안 올 때 어느 구간에서 끊겼는지가 여기 남는다. */}
      {isDetectTask(task.id) && <DetectLogLines taskId={task.id} />}
      {task.actionItems.length > 0 && <table><thead><tr><th>#</th><th>{t('act.actionItems')}</th><th>{t('act.params')}</th><th>{t('act.status')}</th></tr></thead><tbody>{task.actionItems.map((item, index) => <tr key={item.id}><td>{index + 1}</td><td><b>{item.label}</b><small>{item.id}</small></td><td><code>{Object.entries(item.params).map(([key, value]) => `${key}: ${value}`).join(' · ') || t('gen.none')}</code></td><td>{stateLabel(item.status)}</td></tr>)}</tbody></table>}
    </div><aside>{view.world === 'registry'
      ? <><h3>{t('act.evaluation')}</h3>{task.evaluation
          ? task.evaluation.criteria.map((criterion) => <p key={criterion}>✓ {criterion} <small>{t('act.judgedBy', { by: task.evaluation!.judgedBy })}</small></p>)
          : <p>{t('act.noCriteria')}</p>}
        {relay && task.id === OBSTACLE_TASK && <><h3>{t('act.rationale')}</h3><ObstacleEvidence /></>}
        {/* 근거 가시화 (260909 시연 대본 §5) — 근거 **문장**이 있으면 그것부터 읽힌다.
            발표에서 사람이 소리 내어 읽을 자리라 JSON 한 덩어리로 두면 못 읽는다.
            이미지는 아직 없다 — **자리를 만들고 비워 둔다.** 더미를 그려 넣지 않는다. */}
        {typeof evidence?.reason === 'string' && evidence.reason.trim() !== ''
          ? <><h3>{t('act.rationale')}</h3>
              <p className="evidence-reason">{evidence.reason}</p>
              <figure className="evidence-image">
                {typeof evidence.image_ref === 'string' && evidence.image_ref !== ''
                  ? <img src={evidence.image_ref} alt={t('act.evidenceImage')} />
                  : <div className="evidence-image__empty">{t('act.evidenceMissing')}</div>}
                {Array.isArray(evidence.bbox)
                  ? <figcaption>{t('act.bbox', { values: (evidence.bbox as number[]).map((n) => n.toFixed(2)).join(' · ') })}</figcaption>
                  : null}
              </figure></>
          : null}
        <h3>{t('act.evidenceValues')}</h3>
        {evidence
          ? <code>{Object.entries(evidence).map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join('\n')}</code>
          : <p>{t('act.noEvidenceYet')}</p>}</>
      : <><h3>{t('act.evaluation')}</h3><p>{t('act.evalPass1')}</p><p>{t('act.evalPass2')}</p><p>{t('act.evalPending')}</p><h3>{t('act.traceMemory')}</h3><code>dispatched ai<br />acked backend<br />started backend<br />evaluated backend</code></>}</aside></div>}
    <footer><span>{t('act.humanRecorded')}</span><button onClick={() => action('counterfactual_run')}>{t('act.counterfactual')}</button><button onClick={() => action(failure ? 'derived_rerun' : 'single_action_run')}>{failure ? t('act.rerunEdited') : t('act.rerunAlone')}</button></footer>
  </section></div>;
}
