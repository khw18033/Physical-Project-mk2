/**
 * src/views/ControlRecordView.tsx (261110 신설 — 조작 판 다시 보기)
 *
 * **조작 판 하나를 연다.** 임무 판의 다시보기는 저장소를 그 판으로 도로 채워 같은 화면에 그린다(`loadRecord.ts`). 조작 판은
 * 순서도가 없다 — 노드도 마일스톤도 없이 명령과 답, 막힘, 유지 신호 구간, 비행 실행기 출력뿐이다. 그래서 저장소를 건드리지
 * 않고 **창 하나에 기록 그대로** 그린다. 지금 판(라이브 화면)은 그대로 둔다.
 *
 * 글은 이 화면의 언어로 그린다 — 기록에는 값과 키만 있다(`controlRecorder.ts`).
 * 장비가 보낸 규약 문자열(거절 코드 · 상태 · 스크립트 출력)은 번역하지 않는다. 아는 거절 코드만 풀어 쓴다.
 */

import { useEffect, useState } from 'react';
import { ko, t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import type { ControlEvent, ControlProgress, ControlRecordSummary } from '../record/controlRecorder.ts';
import { fetchRecordJson } from '../record/recordClient.ts';
import { landingOf, lineTone, PHASES, readProgress, runOutcome, stripTime, type FlightProcess } from '../physical/flightRunFeed.ts';
import { ControlTelemetrySection } from './ControlTelemetryView.tsx';

type Loaded = { summary: ControlRecordSummary; progress: ControlProgress };

const clockWords = (ms: number) => new Date(ms).toLocaleTimeString([], { hour12: false });
const secWords = (ms: number) => (ms / 1000).toFixed(1);
const params = (p: Record<string, number>) => Object.entries(p).map(([k, v]) => `${k}=${v}`).join(' ') || '—';
const yesNo = (v: boolean | null) => t(v === null ? 'ctl.unknown' : v ? 'ctl.yes' : 'ctl.no');

/** 장비 거절 사유 — 아는 코드만 풀어 쓴다. 모르는 것은 장비가 준 그대로. */
function rejectWords(code: string | null, message: string | null, action: string): string {
  for (const value of [code, message]) {
    const key = value === null ? '' : value.trim();
    if (`manual.reject.${key}` in ko) return t(`manual.reject.${key}`, { action });
    if (`flight.reject.${key}` in ko) return t(`flight.reject.${key}`);
  }
  return [code, message].filter((v) => v !== null && v !== '').join(' ') || t('robot.noReason');
}

export function outcomeWordsOf(process: FlightProcess): string {
  const outcome = runOutcome(process);
  return t(`flight.outcome.${outcome}`, { code: process.exitCode ?? '' });
}

function EventRow({ event, startMs, actionOf }: { event: ControlEvent; startMs: number; actionOf: (commandId: string) => string }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 컴포넌트마다 건다 (지시서 §2 ①).
  useLang();
  const at = <td><time>{clockWords(event.atMs)}</time><small>+{secWords(event.atMs - startMs)}s</small></td>;
  switch (event.kind) {
    case 'opened':
      return <tr className="ctl-row is-mark">{at}<td colSpan={3}>{t(`ctl.ev.opened.${event.reason}`)}</td></tr>;
    case 'closed':
      return <tr className="ctl-row is-mark">{at}<td colSpan={3}>{t('ctl.ev.closed', { reason: t(`ctl.close.${event.reason}`) })}</td></tr>;
    case 'config': {
      const config = event.config as { speed?: Record<string, number>; stepM?: number; stepDeg?: number; preset?: string } | null;
      const detail = event.mode === 'velocity'
        ? params(config?.speed ?? {})
        : `${config?.stepM ?? '—'} m · ${config?.stepDeg ?? '—'}°`;
      return <tr className="ctl-row is-mark">{at}<td>{t('ctl.ev.config')}</td><td colSpan={2}><code>{event.mode}</code> · {config?.preset ?? ''} · {detail}</td></tr>;
    }
    case 'commanded':
      return <tr className="ctl-row is-command">{at}<td><b>{event.action}</b>{event.missionId !== null && <small>{t('ctl.mission', { id: event.missionId })}</small>}</td>
        <td><code>{params(event.parameters)}</code></td><td><small><code>{event.commandId}</code></small></td></tr>;
    case 'answered': {
      const action = actionOf(event.commandId);
      const words = event.answerKind === 'acceptance'
        ? event.accepted ? t('ctl.ans.accepted') : t(event.keepalive ? 'ctl.ans.keepaliveRejected' : 'ctl.ans.rejected', { why: rejectWords(event.code, event.message, action) })
        : event.answerKind === 'status' ? t('ctl.ans.status', { state: event.state ?? '' })
          : t('ctl.ans.result', { status: event.status ?? '' }) + (event.code !== null || event.message !== null ? ` · ${[event.code, event.message].filter(Boolean).join(' ')}` : '');
      const bad = event.accepted === false || (event.answerKind === 'result' && event.status !== 'SUCCEEDED');
      return <tr className={`ctl-row is-answer${bad ? ' is-bad' : ''}`}>{at}<td>{t('ctl.ev.answered')}<small>{action}</small></td>
        <td colSpan={2}>{words} <small><code>{event.commandId}</code></small></td></tr>;
    }
    case 'notSent':
      return <tr className="ctl-row is-bad">{at}<td>{t('ctl.ev.notSent')}<small>{event.action}</small></td><td colSpan={2}>{event.reason}</td></tr>;
    case 'blocked':
      return <tr className="ctl-row is-warn">{at}<td>{t('ctl.ev.blocked', { count: event.count })}</td><td colSpan={2}>{t(`manual.block.${event.block}`)}</td></tr>;
    case 'keepalive':
      return <tr className="ctl-row is-keepalive">{at}<td>{t('ctl.ev.keepalive', { count: event.count, sec: secWords(event.untilMs - event.atMs) })}</td>
        <td colSpan={2}><code>{params(event.parameters)}</code></td></tr>;
    default:
      return null;
  }
}

function FlightSection({ process, emergency }: { process: FlightProcess; emergency: boolean }) {
  useLang();
  const progress = readProgress(process.lines);
  const reached = PHASES.indexOf(progress.phase as (typeof PHASES)[number]);
  return <section className="ctl-flight">
    <h3>{t(emergency ? 'ctl.flight.emergency' : 'ctl.flight.head', { runId: process.runId })}</h3>
    <p className="ctl-flight__meta">
      {emergency
        ? <>{t('ctl.flight.mode')} <code>{process.mode ?? '—'}</code></>
        : <>dry-run {yesNo(process.dryRun)} · {t('ctl.flight.script')} <code>{process.script ?? '—'}</code> · RTK {yesNo(process.rtk)}</>}
      {' · '}<b>{outcomeWordsOf(process)}</b>
      {process.startedAt !== null && <> · {clockWords(process.startedAt * 1000)}{process.endedAt !== null && ` – ${clockWords(process.endedAt * 1000)}`}</>}
    </p>
    {process.argv.length > 0 && <p className="ctl-flight__argv"><code>{process.argv.join(' ')}</code></p>}
    {!emergency && <ol className="ctl-phases">
      {PHASES.map((phase, index) => <li key={phase} className={progress.phase === 'dryDone' ? (index <= PHASES.indexOf('verified') ? 'is-done' : '') : index <= reached ? 'is-done' : ''}>
        {t(`flight.phase.${phase}`)}
      </li>)}
      {progress.phase === 'dryDone' && <li className="is-done">{t('flight.phase.dryDone')}</li>}
    </ol>}
    {!emergency && (() => {
      // 261111 — 스크립트가 착륙을 못 찍은 판도 FC 가 말한 착륙 상태를 남긴다(실행기 출력의 진행 번호 · `[착륙감시]` 줄).
      const landing = landingOf(progress);
      if (landing === 'none' || landing === 'confirmed') return null;
      const watch = progress.landWatch;
      return <p className={`ctl-flight__landing flight-landing--${landing}`}>
        <b>{t(`flight.landing.short.${landing}`)}</b>
        {' · '}{t('flight.landing.recordItem', { cur: progress.liveItem ?? '?', total: progress.itemsTotal ?? '?' })}
        {watch.seen && <> · <code>in_air={String(watch.inAir)} landed={watch.landed ?? 'None'} armed={String(watch.armed)} mode={watch.mode ?? 'None'}</code></>}
        {watch.overlapS !== null && <> · {t('flight.landing.overlap', { s: watch.overlapS.toFixed(3) })}</>}
      </p>;
    })()}
    {progress.problems.length > 0 && <ul className="ctl-flight__problems">{progress.problems.map((line, i) => <li key={i}>{line}</li>)}</ul>}
    <details open={progress.problems.length > 0}>
      <summary>{t('ctl.flight.lines', { n: process.lines.length })}</summary>
      {process.lines.length === 0
        ? <p>{t('flight.log.empty')}</p>
        : <pre className="ctl-flight__log">{process.lines.map((line) => <span key={line.seq} className={`tone-${lineTone(line.text) || 'plain'}`}>{stripTime(line.text)}{'\n'}</span>)}</pre>}
    </details>
  </section>;
}

export function ControlRecordView({ date, run, onClose }: { date: string; run: string; onClose(): void }) {
  useLang();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetchRecordJson<ControlRecordSummary>(date, run, 'mission.json'),
      fetchRecordJson<ControlProgress>(date, run, 'progress.json'),
    ]).then(([summary, progress]) => { if (alive) setLoaded({ summary, progress }); })
      .catch((why: unknown) => { if (alive) setError(why instanceof Error ? why.message : String(why)); });
    return () => { alive = false; };
  }, [date, run]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const summary = loaded?.summary ?? null;
  const progress = loaded?.progress ?? null;
  const events = progress?.events ?? [];
  const startMs = summary === null ? 0 : Date.parse(summary.startedAtIso);
  const actions = new Map(events.flatMap((e) => (e.kind === 'commanded' ? [[e.commandId, e.action] as const] : [])));
  const actionOf = (id: string) => actions.get(id) ?? 'teleop';

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="modal ctl-record" role="dialog" aria-label={t('ctl.title', { device: summary?.deviceId ?? '' })}>
      <header>
        <div>
          <h2>{t('ctl.title', { device: summary?.deviceId ?? '…' })}</h2>
          <small><code>{date}/{run}</code></small>
        </div>
        <button type="button" onClick={onClose}>{t('ctl.close')}</button>
      </header>
      {error !== null && <p className="history-why ctl-pad">{t('ctl.loadFailed', { reason: error })}</p>}
      {summary === null && error === null && <p className="ctl-pad">{t('ctl.loading')}</p>}
      {summary !== null && progress !== null && <>
        {summary.imported !== undefined && <p className="ctl-pad ctl-imported">
          {t('ctl.importedNote', { from: [summary.imported.from, ...summary.imported.emergencyFrom, summary.imported.telemetryFrom].filter(Boolean).join(' · ') })}
          {summary.imported.result !== null && <><br /><b>{t('ctl.importedResult')}</b> {summary.imported.result}</>}
        </p>}
        <dl className="ctl-summary">
          <div><dt>{t('ctl.f.kind')}</dt><dd>{t(`ctl.kind.${summary.sessionKind}`)}</dd></div>
          <div><dt>{t('ctl.f.span')}</dt><dd>{clockWords(startMs)} – {summary.endedAtIso === null ? t('ctl.noEnd') : clockWords(Date.parse(summary.endedAtIso))}</dd></div>
          <div><dt>{t('ctl.f.closed')}</dt><dd>{summary.closeReason === null ? t('ctl.noEnd') : t(`ctl.close.${summary.closeReason}`)}</dd></div>
          <div><dt>{t('ctl.f.counts')}</dt><dd>{t('ctl.counts', summary.counts)}</dd></div>
          <div><dt>{t('ctl.f.actions')}</dt><dd>{Object.entries(summary.actions).map(([a, n]) => `${a} ×${n}`).join(' · ') || '—'}</dd></div>
          <div><dt>{t('ctl.f.missions')}</dt><dd>{summary.missions.length === 0 ? t('ctl.noMission')
            : summary.missions.map((m) => <span key={m.missionId}><b>{m.missionId}</b>{m.recordFolder !== null && <> <code>{m.recordFolder}</code></>} </span>)}</dd></div>
        </dl>
        {/* 261111 — 텔레메트리 표본(2차). 1차 판에는 표본이 없다고 적는다. */}
        <ControlTelemetrySection summary={summary} progress={progress} events={events} />
        {progress.flight !== null && <>
          {progress.flight.runs.length === 0 && <p className="ctl-pad">{t('ctl.flight.noRun')}</p>}
          {progress.flight.runs.map((p) => <FlightSection key={p.runId} process={p} emergency={false} />)}
          {progress.flight.emergencies.map((p) => <FlightSection key={p.runId} process={p} emergency />)}
        </>}
        <table className="ctl-events">
          <thead><tr><th>{t('ctl.col.time')}</th><th>{t('ctl.col.what')}</th><th colSpan={2}>{t('ctl.col.detail')}</th></tr></thead>
          <tbody>{events.map((event, index) => <EventRow key={index} event={event} startMs={startMs} actionOf={actionOf} />)}</tbody>
        </table>
      </>}
    </section>
  </div>;
}
