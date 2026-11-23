/**
 * src/views/GeneratedRunCard.tsx (261123 신설 — AI 생성 임무 실행기)
 *
 * 두 자리다.
 *  - **승인 전** (`GeneratedRunProposal`): 실행 계획 요약 · 받을 수 없는 액션 아이템 · 사람이 채울 값. 승인 버튼을 막을지는
 *    `generatedApproval()` 이 정하고, 버튼은 제안 카드(`main.tsx`)에 그대로 있다 — 승인의 문은 `acceptProposal` 하나다.
 *  - **승인 뒤** (`GeneratedRunStatus`): 어디까지 왔는가 · 사람 확인 대기면 「확인」 · 「실패로 닫기」.
 *
 * 계획서는 사람 확인 버튼을 노드 상세에 두자고 했다. 여기 둔 것은 **실행 중 늘 보이는 자리**라서다 — 노드 상세는 열어야 보이고,
 * 실행이 그 버튼을 기다리는 동안 사람이 그것을 모르면 판이 멈춘 것처럼 보인다.
 */

import { useEffect } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import type { MissionView } from '../data/scenario.ts';
import { useMission } from '../data/scenario.ts';
import { fillProblems, fillRange, generatedRunOf, type FillSlot, type GeneratedRunPlan } from '../generate/actionCommands.ts';
import { fillValues, runPlanOf, setFillValue, useFillValues } from '../generate/runFill.ts';
import { answerHuman, useGeneratedRun } from '../physical/generatedRun.ts';

/** 제안 카드가 버튼을 그릴 때 묻는다. 실행 가능한데 값에 문제가 있으면 `blocked` — 버튼을 막는다. */
export function generatedApproval(view: MissionView, values: Readonly<Record<string, number | undefined>>): {
  plan: GeneratedRunPlan;
  blocked: boolean;
} {
  const plan = runPlanOf(view.tasks);
  return { plan, blocked: plan.runnable && fillProblems(plan, values).length > 0 };
}

function taskLabel(view: MissionView, taskId: string | null): string {
  if (taskId === null) return '';
  const task = view.tasks.find((entry) => entry.id === taskId);
  return task === undefined ? taskId : `${taskId} ${task.title}`;
}

function FillRow({ view, slot, value, problem }: { view: MissionView; slot: FillSlot; value: number | undefined; problem: 'missing' | 'range' | null }) {
  useLang();
  const range = fillRange(slot.param);
  return <li className="grun-fill">
    <label>
      <span>{taskLabel(view, slot.taskId)} · <code>{slot.action}</code> · {t(slot.param === 'deg' ? 'grun.fillTurn' : 'grun.fillForward')}</span>
      <input
        type="number"
        step={slot.param === 'deg' ? 1 : 0.05}
        value={value === undefined ? '' : String(value)}
        onChange={(event) => {
          const raw = event.target.value.trim();
          const parsed = raw === '' ? undefined : Number(raw);
          setFillValue(view.missionId, slot.key, parsed !== undefined && Number.isFinite(parsed) ? parsed : undefined);
        }}
      />
    </label>
    {slot.preset !== null && <small>{t('grun.fillPreset', { v: slot.preset })}</small>}
    {problem === 'range' && <small className="grun-problem">{t('grun.fillRange', { min: range.min, max: range.max })}</small>}
  </li>;
}

/** 승인 전 — 실행 계획과 값 채우기. */
export function GeneratedRunProposal({ view }: { view: MissionView }) {
  useLang();
  const values = useFillValues(view.missionId);
  // 처음 그릴 때 모델이 적어 온 값으로 채워 둔다 — 그리기 밖에서(저장소가 알림을 낸다).
  useEffect(() => { fillValues(view.missionId, view.tasks); }, [view.missionId, view.tasks]);
  const { plan } = generatedApproval(view, values);
  const problems = new Map(fillProblems(plan, values).map((problem) => [problem.key, problem.reason]));
  return <div className="grun-card">
    <p>{t('grun.summary', { cmd: plan.commandTasks, human: plan.humanTasks, target: plan.target ?? t('gen.none') })}</p>
    {plan.commandTasks === 0 && <p className="grun-note">{t('grun.noCommands')}</p>}
    {!plan.runnable && <p className="grun-note">{t('grun.planOnly')}</p>}
    {plan.rejected.length > 0 && <>
      <h4>{t('grun.rejected')}</h4>
      <ul className="grun-rejected">
        {plan.rejected.map((rejection, index) => <li key={`${rejection.taskId}-${rejection.itemId ?? index}`}>
          {taskLabel(view, rejection.taskId)}{rejection.action !== '' && <> · <code>{rejection.action}</code></>} · {t(`grun.reason.${rejection.reason}`, { target: rejection.target ?? '' })}
        </li>)}
      </ul>
    </>}
    {plan.runnable && plan.fills.length > 0 && <>
      <h4>{t('grun.fillTitle')}</h4>
      <ul className="grun-fills">
        {plan.fills.map((slot) => <FillRow key={slot.key} view={view} slot={slot} value={values[slot.key]} problem={problems.get(slot.key) ?? null} />)}
      </ul>
      {problems.size > 0 && <p className="grun-problem">{t('grun.fillMissing')}</p>}
    </>}
    {plan.runnable && <p className="grun-note">{t('grun.approveRunNote')}</p>}
  </div>;
}

/** 승인 뒤 — 진행과 사람 확인. 걸음이 실린 생성 임무에서만 그린다. */
export function GeneratedRunStatus() {
  useLang();
  const mission = useMission();
  const run = useGeneratedRun();
  const view = mission.current;
  const items = generatedRunOf(view.params);
  if (items.length === 0) return null;
  const mine = run.missionId === view.missionId;
  const task = taskLabel(view, mine ? run.taskId : null);
  if (!mine || run.phase === 'idle') return <div className="grun-status"><p>{t('grun.status.idle', { n: items.length })}</p></div>;
  if (run.phase === 'waiting_human' && run.taskId !== null) {
    const taskId = run.taskId;
    return <div className="grun-status grun-waiting">
      <p>{t('grun.status.waiting', { task })}</p>
      <button onClick={() => answerHuman(taskId, 'done')}>{t('grun.confirm')}</button>
      <button onClick={() => answerHuman(taskId, 'failed')}>{t('grun.fail')}</button>
    </div>;
  }
  if (run.phase === 'running') return <div className="grun-status"><p>{t('grun.status.running', { i: run.index + 1, n: run.total, task })}</p></div>;
  if (run.phase === 'done') return <div className="grun-status"><p>{t('grun.status.done')}</p></div>;
  if (run.phase === 'failed') {
    const reason = run.reason === 'human' ? t('grun.reasonHuman') : run.reason || t('robot.noReason');
    return <div className="grun-status grun-failed"><p>{t('grun.status.failed', { task, reason })}</p></div>;
  }
  return <div className="grun-status grun-failed"><p>{t('grun.status.stopped', { task })}</p></div>;
}
