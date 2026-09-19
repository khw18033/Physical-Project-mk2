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
 */

import { useState } from 'react';
import { issueCommand } from '../shared/commandEgress.ts';
import { traceFor, type MissionView } from '../data/scenario.ts';
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
import {
  commandsOfTask, logAtIndex, useRobotSession,
  type CommandLogLine, type TaskCommandRecord,
} from '../physical/robotSession.ts';
import { DeviceStrip } from './DeviceStrip.tsx';
import { ApproachFacts, DetectLogLines, isDetectTask, PathFacts, PrepFacts, SweepFacts } from '../detect/views/DetectActionLog.tsx';
import { t } from '../i18n/dict.ts';
import { Rich } from '../i18n/RichText.tsx';
import { useLang } from '../shared/language.ts';

/** 명령 하나의 상태를 사람 말로. 로봇이 준 상태 그대로를 옮긴다. */
const COMMAND_STATE_KEY: Record<TaskCommandRecord['state'], string> = {
  issued: 'cmd.published',
  running: 'cmd.running',
  done: 'task.state.done',
  failed: 'task.state.failed',
};

/** 낸 시각과 마지막 응답 시각의 차. 응답이 없으면 null — 0초라고 적지 않는다. */
function tookSec(record: TaskCommandRecord): number | null {
  const last = record.log.at(-1);
  if (last === undefined) return null;
  return (Date.parse(last.atIso) - Date.parse(record.issuedAtIso)) / 1000;
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
  useRobotSession();                       // 로그가 오는 대로 다시 그린다

  /**
   * **각도 칸은 한 명령의 제 몫만 본다** (260912 지시).
   *
   * 한 바퀴는 명령 하나(`scan_mission`)인데 노드는 여덟이다. 각 칸에 그 명령 전체를
   * 붙이면 여덟 칸이 똑같은 표 여덟 개가 된다 — 「이 각도에서 무슨 일이 있었나」를
   * 물었는데 한 바퀴 전체가 나온다. 그래서 걸음 번호로 갈라 준다.
   */
  const angle = viewpointTaskIndex(taskId);
  const groups = angle === null
    ? commandsOfTask(taskId).map((record) => ({ record, lines: record.log }))
    : logAtIndex(angle);

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
    {groups.map(({ record, lines }, index) => {
      const took = tookSec(record);
      const params = Object.entries(record.parameters);
      return <section key={record.commandId} className={`robot-log__cmd is-${record.state}`}>
        <header>
          <b>{index + 1}. {record.action}</b>
          <span>{t(COMMAND_STATE_KEY[record.state])}</span>
          {/* **응답이 없으면 시간을 안 적는다.** 0초로 적으면 즉시 끝난 것으로 읽힌다. */}
          {took !== null && <span>{t('act.tookSec', { sec: took.toFixed(1) })}</span>}
          {/* 각도 칸에서는 **이 표가 한 명령의 일부**라는 것을 적는다. */}
          {angle !== null && <span>{t('act.nthStep', { n: angle + 1 })}</span>}
          <code>{record.commandId}</code>
        </header>
        <p className="robot-log__params">
          {params.length === 0
            ? t('act.noParams')
            : params.map(([key, value]) => `${key}=${value}`).join(' · ')}
        </p>
        <LogLines lines={lines} />
      </section>;
    })}
  </div>;
}

/** 오간 줄. 받은 순서 그대로이고 문장은 로봇이 준 값으로만 만든다. */
function LogLines({ lines }: { lines: readonly CommandLogLine[] }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  return <ol className="robot-log__lines">
    {lines.map((line, at) => <li key={`${line.atIso}-${at}`} className={`is-${line.kind}`}>
      <time>{line.atIso.slice(11, 23)}</time>
      <span>{line.text}</span>
      {line.raw !== '' && <code>{line.raw}</code>}
    </li>)}
    {lines.length === 0 && <li className="is-empty"><span>{t('act.noResponse')}</span></li>}
  </ol>;
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
  const [speed, setSpeed] = useState('0.35'); const [clearance, setClearance] = useState('0.18');
  const action = (kind: string) => void issueCommand({ action: kind, entity: task.id, params: { speed, clearance } });
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
        ? t('act.commandCount', { n: commandsOfTask(task.id).length })
        : t('act.logAtAngle', { n: logAtIndex(viewpointTaskIndex(task.id)!).reduce((sum, group) => sum + group.lines.length, 0) })}{task.actionItems.length > 0 && t('act.actionItemCount', { n: task.actionItems.length })} · target {task.target ?? t('gen.none')}</small></div><button onClick={onClose}>{t('conn.close')}</button></header>
    {failure ? <FailureReason taskId={task.id} /> : device && <PendingSource id="robot-status-strip" minHeight={104}><DeviceStrip device={device} /></PendingSource>}
    {/* **로봇이 실제로 낸 명령이 있으면 이 폼을 안 띄운다** (260912 지시).
        「진입 속도 · 최소 클리어런스」는 구판 편의 입력칸이다. 회전·직진이 실패한 자리에
        그 둘을 띄우면 그 값을 고쳐 다시 하면 되는 것처럼 읽힌다 — 실패한 명령에는 그런
        파라미터가 아예 없다. 구판 편에서는 그대로 둔다. */}
    {failure && commandsOfTask(task.id).length === 0 && <div className="parameter-form"><label>{t('act.entrySpeed')}<input value={speed} onChange={(event) => setSpeed(event.target.value)} /> m/s</label><label>{t('act.minClearance')}<input value={clearance} onChange={(event) => setClearance(event.target.value)} /> m</label></div>}
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
