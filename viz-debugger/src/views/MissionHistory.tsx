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
 * ## 파일로 남은 판을 그린다 (260914)
 *
 * 기록기(`record/recorder.ts`)가 판마다 저장소 루트 `mission-history/<날짜>/<시각_임무>/` 에 쓴다.
 * 목록은 그 폴더를 읽어 날짜별로 그리고, 줄마다 「다시보기」가 그 판을 같은 화면에 다시 올린다.
 * 새로고침해도 남는다.
 *
 * 기록 창구가 없으면(개발 서버 밖) 이 세션에서 끝난 판만 그리고, 새로고침하면 빈다고 적는다.
 * DB 가 보관할 이력은 여전히 남이 줄 값이다(`mission-history` 자리표시).
 */

import { useEffect, useRef, useState } from 'react';
import type { MissionView } from '../data/scenario.ts';
import { closeRecordReplay } from '../data/scenario.ts';
import {
  noteMissionEnd, OUTCOME_KEYS, useMissionHistory,
  type MissionOutcome,
} from '../data/missionHistory.ts';
import { PendingSource } from '../shared/PendingSource.tsx';
import { failureOfTask } from '../physical/robotCommands.ts';
import { useRobotSession } from '../physical/robotSession.ts';
import type { FoldedStatuses } from '../data/fold.ts';
import { openRecordedRun } from '../record/loadRecord.ts';
import { listRecordedRuns, type RecordedRun } from '../record/recordClient.ts';
import { useRecorderStatus } from '../record/recorder.ts';
import { isReplayingRecord, useReplayTarget } from '../record/replayMode.ts';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';

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
    // 다시보기는 지난 판이다 — 끝난 모습을 이 세션의 새 판으로 또 적지 않는다.
    if (view.missionId === '' || isReplayingRecord()) return;
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
        ? (session.stopped?.failure ?? t('hist.stoppedByHuman'))
        : (why?.words ?? ''),
    });
  }, [view.missionId, allDone, failed?.id, stopped, done, tasks.length]);
}

/** `260914` → `26.09.14` · `153012_…` → `15:30:12`. */
const dateWords = (date: string) => `${date.slice(0, 2)}.${date.slice(2, 4)}.${date.slice(4, 6)}`;
const timeWords = (run: string) => `${run.slice(0, 2)}:${run.slice(2, 4)}:${run.slice(4, 6)}`;

/**
 * 저장된 판 목록. 기록기가 새로 쓸 때마다 다시 읽되 5초에 한 번까지만.
 * `runs` 가 `null` 이면 창구가 없다 — 「비었다」와 가른다.
 */
function useRecordedRuns(): { runs: RecordedRun[] | null; dir: string; refresh(): void } {
  const [answer, setAnswer] = useState<{ runs: RecordedRun[] | null; dir: string }>({ runs: null, dir: '' });
  const recorder = useRecorderStatus();
  const lastRead = useRef(0);
  const refresh = () => {
    lastRead.current = Date.now();
    void listRecordedRuns().then((listed) => setAnswer(listed === null ? { runs: null, dir: '' } : listed));
  };
  useEffect(refresh, []);
  useEffect(() => {
    if (recorder.lastSavedAtIso === null) return;
    const wait = Math.max(0, 5000 - (Date.now() - lastRead.current));
    const timer = setTimeout(refresh, wait);
    return () => clearTimeout(timer);
  }, [recorder.lastSavedAtIso, recorder.folder]);
  return { ...answer, refresh };
}

/**
 * 목록 하나. 두 자리가 이것을 그린다.
 * `onReplay` — 다시보기를 연 뒤 부른다. 셸 판에서 누르면 리플레이 화면으로 옮긴다.
 */
export function MissionHistoryList({ compact = false, onReplay }: { compact?: boolean; onReplay?: () => void }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  const entries = useMissionHistory();
  const { runs, dir, refresh } = useRecordedRuns();
  const recorder = useRecorderStatus();
  const replaying = useReplayTarget();
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const open = (run: RecordedRun) => {
    const key = `${run.date}/${run.run}`;
    setOpening(key);
    setOpenError(null);
    void openRecordedRun(run.date, run.run).then((result) => {
      setOpening(null);
      if (!result.ok) { setOpenError(`${key} — ${result.reason}`); return; }
      onReplay?.();
    });
  };

  const recorderLine = recorder.state === 'recording'
    ? <>{t('hist.recordingNow')}<code>{recorder.folder}</code></>
    : recorder.state === 'waiting'
      ? <>{t('hist.approvedRun')}</>
      : recorder.state === 'unavailable'
        ? <>{t('hist.noEndpoint')}<code>npm run dev</code>{t('hist.onlyVia')}</>
        : null;

  return <div className="history-list">
    {replaying !== null && <div className="history-replaying">
      <b>{t('hist.replaying')}</b> <code>{replaying.date}/{replaying.run}</code>
      <button type="button" className="history-action" onClick={() => closeRecordReplay()}>{t('hist.closeReplay')}</button>
      <small>{t('hist.replayNote')}</small>
    </div>}
    {recorderLine !== null && <p className="history-recorder">
      {recorderLine}
      {recorder.lastError !== null && recorder.state !== 'unavailable' && <small> {t('hist.saveError', { reason: recorder.lastError })}</small>}
    </p>}
    {openError !== null && <p className="history-why">{t('hist.openFailed', { reason: openError })}</p>}

    {runs === null
      ? <SessionEntries entries={entries} compact={compact} />
      : runs.length === 0
        ? <p className="history-empty">{t('hist.noSaved')}<small>{t('hist.noSavedWhy')}</small>
        </p>
        : groupByDate(runs).map(([date, items]) => <section key={date} className="history-day">
          <h3>{dateWords(date)} <small>{t('hist.runCount', { n: items.length })}</small></h3>
          <ul>
            {items.map((item) => <RunLine key={`${item.date}/${item.run}`} item={item} compact={compact}
              recordingFolder={recorder.folder}
              replayingKey={replaying === null ? null : `${replaying.date}/${replaying.run}`}
              opening={opening} onOpen={open} />)}
          </ul>
        </section>)}

    {/* **DB 가 보관할 이력은 여전히 남이 줄 값이다** (`mission-history`). 지금은 파일이 그 자리를 대신한다. */}
    <p className="history-note">
      {runs !== null && <>{t('hist.location')}<code>{dir}</code> <button type="button" className="history-action" onClick={refresh}>{t('hist.refresh')}</button><br /></>}
      <PendingSource id="mission-history" inline>
        {runs === null
          ? t('hist.sessionOnly')
          : t('hist.fileFallback')}
      </PendingSource>
    </p>
  </div>;
}

function RunLine({ item, compact, recordingFolder, replayingKey, opening, onOpen }: {
  item: RecordedRun;
  compact: boolean;
  recordingFolder: string | null;
  replayingKey: string | null;
  opening: string | null;
  onOpen(run: RecordedRun): void;
}) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  const key = `${item.date}/${item.run}`;
  const mission = item.mission;
  const outcome = mission?.outcome ?? null;
  const current = replayingKey === key;
  // 끝 표시가 없는 판 — 지금 쓰는 중이거나, 끝나기 전에 새로고침·충돌로 끊긴 판이다.
  const outcomeWords = outcome !== null ? t(OUTCOME_KEYS[outcome]) : recordingFolder === key ? t('hist.recording') : t('hist.noEndMark');
  return <li className={`${outcome === null ? 'is-open' : `is-${outcome}`}${current ? ' is-replaying' : ''}`}>
    <time>{timeWords(item.run)}</time>
    <b>{mission?.missionId ?? item.run.slice(7)}</b>
    <span className="history-outcome">{outcomeWords}</span>
    {mission !== null && <span className="history-count">{t('hist.nodes', { done: mission.done, of: mission.of })}</span>}
    <button type="button" className="history-action" disabled={opening !== null || mission === null} onClick={() => onOpen(item)}>
      {opening === key ? t('hist.opening') : current ? t('hist.reload') : t('hist.replay')}
    </button>
    {!compact && mission !== null && <small className="history-label">
      {t('hist.runLine', { label: mission.label + (mission.testMode ? t('hist.testData') : ''), images: mission.imageCount, sec: Math.round(mission.headSec) })}
    </small>}
    {mission?.path != null && <small className="history-label">{t('hist.path', { turn: mission.path.turnInstruction, forward: mission.path.forwardM.toFixed(2) })}</small>}
    {mission?.pathFailure != null && <small className="history-why">{t('hist.pathFailed', { reason: mission.pathFailure })}</small>}
    {mission !== null && mission.failedTaskId !== null && <small className="history-why">
      {mission.failedTaskId}{mission.reason !== '' && ` · ${mission.reason}`}
    </small>}
    {mission !== null && mission.failedTaskId === null && mission.reason !== '' && <small className="history-why">{mission.reason}</small>}
    {mission === null && <small className="history-why">{t('hist.unreadable')}</small>}
  </li>;
}

function groupByDate(runs: readonly RecordedRun[]): Array<[string, RecordedRun[]]> {
  const days = new Map<string, RecordedRun[]>();
  for (const run of runs) days.set(run.date, [...(days.get(run.date) ?? []), run]);
  return [...days];
}

/** 창구가 없을 때 — 이 세션에서 끝난 판만. */
function SessionEntries({ entries, compact }: { entries: ReturnType<typeof useMissionHistory>; compact: boolean }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  if (entries.length === 0) {
    return <p className="history-empty">{t('hist.noFinished')}<small>{t('hist.noFinishedWhy')}</small>
    </p>;
  }
  return <ul>
    {entries.map((entry, index) => <li key={`${entry.missionId}-${entry.endedAtIso}-${index}`} className={`is-${entry.outcome}`}>
      <b>{entry.missionId}</b>
      <span className="history-outcome">{t(OUTCOME_KEYS[entry.outcome])}</span>
      <span className="history-count">{t('hist.nodes', { done: entry.done, of: entry.of })}</span>
      <time>{entry.endedAtIso.slice(11, 19)}</time>
      {!compact && <small className="history-label">{entry.label}</small>}
      {/* 실패한 노드와 사유 — **없으면 아무것도 안 적는다.** */}
      {entry.failedTaskId !== null && <small className="history-why">
        {entry.failedTaskId}{entry.reason !== '' && ` · ${entry.reason}`}
      </small>}
      {entry.failedTaskId === null && entry.reason !== '' && <small className="history-why">{entry.reason}</small>}
    </li>)}
  </ul>;
}
