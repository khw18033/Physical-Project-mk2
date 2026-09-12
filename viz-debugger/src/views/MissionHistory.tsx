/**
 * src/views/MissionHistory.tsx (260912 신설 — 「임무 이력을 임시로 기능 활성화」)
 *
 * **끝난 판의 목록.** 두 자리(셸의 ◷ 임무 이력 판, 리플레이 화면의 왼쪽 기둥)가 같은
 * 목록을 그린다 — 둘이 다른 것을 보여 주면 어느 쪽이 진짜인지 묻게 된다.
 *
 * ## 무엇이 「끝났다」인가
 *
 *   완료  태스크가 전부 완료다 — `T-C1`「임무 종료 확인」까지 찬 상태다
 *   실패  하나라도 실패다. 그 노드와 **로봇이 준 사유**를 같이 적는다
 *   정지  사람이 ■ 정지를 눌렀다
 *
 * 판정은 기록 열을 접은 결과에서 나온다. 여기서 새로 계산하지 않는다.
 *
 * ## 이 세션에만 남는다고 적는다
 *
 * 진짜 이력은 백엔드가 들고 있어야 하는 것이고, 여기 쌓인 것은 이 판에서 우리가 본 것뿐이다.
 * 그 사실을 목록 아래에 적어 둔다 — 안 적으면 새로고침하고 「이력이 사라졌다」가 된다.
 */

import { useEffect } from 'react';
import type { MissionView } from '../data/scenario.ts';
import {
  noteMissionEnd, OUTCOME_WORDS, useMissionHistory,
  type MissionOutcome,
} from '../data/missionHistory.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { failureOfTask } from '../physical/robotCommands.ts';
import { useRobotSession } from '../physical/robotSession.ts';
import type { FoldedStatuses } from '../data/fold.ts';

/**
 * **판이 끝났는지 보고, 끝났으면 한 줄 적는다.**
 *
 * 그리는 중에 저장소를 건드리면 안 되므로 효과에서 적는다. 같은 판을 두 번 적지 않는 것은
 * 저장소가 맡는다(`noteMissionEnd`) — 접기 결과는 다시 그릴 때마다 나온다.
 */
export function useMissionEndWatch(view: MissionView, folded: FoldedStatuses): void {
  const session = useRobotSession();
  const stopped = session.stopped !== null;
  const tasks = view.tasks;
  const done = tasks.filter((task) => folded.tasks[task.id]?.status === 'done').length;
  const failed = tasks.find((task) => folded.tasks[task.id]?.status === 'failed') ?? null;
  const allDone = tasks.length > 0 && done === tasks.length;

  useEffect(() => {
    if (view.missionId === '') return;
    const outcome: MissionOutcome | null = allDone ? 'done' : failed !== null ? 'failed' : stopped ? 'stopped' : null;
    if (outcome === null) return;
    // **사유는 로봇이 준 것만.** 없으면 빈 문자열이고, 화면은 그 자리를 비운다.
    const why = failed === null ? null : failureOfTask(failed.id);
    noteMissionEnd({
      missionId: view.missionId,
      label: view.label,
      outcome,
      endedAtIso: new Date().toISOString(),
      done,
      of: tasks.length,
      failedTaskId: failed?.id ?? null,
      reason: outcome === 'stopped'
        ? (session.stopped?.failure ?? '사람이 정지를 눌렀습니다')
        : (why?.words ?? ''),
    });
  }, [view.missionId, allDone, failed?.id, stopped, done, tasks.length]);
}

/** 목록 하나. 두 자리가 이것을 그린다. */
export function MissionHistoryList({ compact = false }: { compact?: boolean }) {
  const entries = useMissionHistory();
  if (entries.length === 0) {
    return <p className="history-empty">
      아직 끝난 임무가 없습니다
      <small>한 판이 완료·실패·정지로 끝나면 여기에 한 줄씩 쌓입니다</small>
      <PendingSource id="mission-history" inline>
        서버가 보관하는 임무 이력은 아직 안 붙었습니다
      </PendingSource>
    </p>;
  }
  return <div className="history-list">
    <ul>
      {entries.map((entry, index) => <li key={`${entry.missionId}-${entry.endedAtIso}-${index}`} className={`is-${entry.outcome}`}>
        <b>{entry.missionId}</b>
        <span className="history-outcome">{OUTCOME_WORDS[entry.outcome]}</span>
        <span className="history-count">{entry.done}/{entry.of} 노드</span>
        <time>{entry.endedAtIso.slice(11, 19)}</time>
        {!compact && <small className="history-label">{entry.label}</small>}
        {/* 실패한 노드와 사유 — **없으면 아무것도 안 적는다.** */}
        {entry.failedTaskId !== null && <small className="history-why">
          {entry.failedTaskId}{entry.reason !== '' && ` · ${entry.reason}`}
        </small>}
        {entry.failedTaskId === null && entry.reason !== '' && <small className="history-why">{entry.reason}</small>}
      </li>)}
    </ul>
    {/* **서버의 이력은 여전히 남이 줄 값이다** (`mission-history`). 여기 쌓인 것은 이
        세션에서 우리가 본 판뿐이라, 그 구별을 자리표시로 남긴다 — 안 남기면 새로고침하고
        「이력이 사라졌다」가 된다. */}
    <p className="history-note">
      <PendingSource id="mission-history" inline>
        이 세션에서 본 것만입니다 — 새로고침하면 비고, 서버가 보관하는 임무 이력은 아직 안 붙었습니다
      </PendingSource>
    </p>
  </div>;
}
