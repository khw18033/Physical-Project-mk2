/**
 * src/views/FlightRunBadge.tsx (261014 신설 — 드론 비행 실행 알림)
 *
 * **화면 우측 상단 — 지금 pi3 에서 비행 스크립트가 돌고 있는 드론.** 카드를 닫고 다른 화면을 보는 동안에도
 * 어느 단계인지 보이고, **중단 · 비상 착륙을 카드를 다시 열지 않고** 누를 수 있어야 한다(수동 제어 알림과 같은 자리).
 *
 * 끝난 실행은 사람이 닫을 때까지 남긴다 — 결과(정상 · 중단 · 옵션 오류)를 못 보고 지나가지 않게.
 * 페이지를 새로 열면 retained 로 마지막 실행이 다시 오는데, 그때 이미 끝난 것은 띄우지 않는다(이 화면이 본 실행만).
 */

import { useEffect, useRef, useState } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { landingOf, readProgress, runOutcome, useFlightRuns, type FlightProcess } from '../physical/flightRunFeed.ts';
import { flightLink, issueFlightEmergency, issueFlightStop } from '../physical/flightRunCommands.ts';
import { useEverySec } from './ManualControlBadge.tsx';

/**
 * **두 번 눌러야 나가는 버튼.** 비상 명령은 스크립트 쪽에 확인 질문이 없다 — 잘못 스친 클릭 한 번으로 기체 모드가
 * 바뀌면 안 된다. 처음 누르면 「한 번 더」로 바뀌고 4초 안에 다시 눌러야 보낸다.
 */
export function ArmedButton({ label, armedLabel, onFire, className, disabled }: {
  label: string; armedLabel: string; onFire(): void; className?: string; disabled?: boolean;
}) {
  useLang();
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current !== null) clearTimeout(timer.current); }, []);
  return <button type="button" disabled={disabled} className={`${className ?? ''}${armed ? ' flight-armed' : ''}`}
    onClick={(event) => {
      event.currentTarget.blur();
      if (timer.current !== null) clearTimeout(timer.current);
      if (armed) { setArmed(false); onFire(); return; }
      setArmed(true);
      timer.current = setTimeout(() => setArmed(false), 4000);
    }}>{armed ? armedLabel : label}</button>;
}

/** 실행 한 줄 요약 — 탭의 머리와 알림이 같은 말을 쓴다. */
export function runSummary(process: FlightProcess): string {
  const outcome = runOutcome(process);
  const kind = process.dryRun === true ? t('flight.kind.dry') : t('flight.kind.fly');
  if (outcome === 'running') {
    const progress = readProgress(process.lines);
    const phase = t(`flight.phase.${progress.phase}`);
    const item = progress.itemCur !== null && progress.itemsTotal !== null
      ? ` · ${t('flight.progress.item', { cur: progress.itemCur, total: progress.itemsTotal })}` : '';
    const cap = progress.capturing !== null ? ` · ${t('flight.progress.capturing', { n: progress.capturing })}` : '';
    // 261111 — 스크립트가 착륙을 못 찍어도 FC 미션 완료 · 착지는 배지에서 보이게.
    const landing = landingOf(progress);
    const land = landing === 'none' || landing === 'confirmed' ? '' : ` · ${t(`flight.landing.short.${landing}`)}`;
    return `${kind} · ${phase}${item}${cap}${land}`;
  }
  return `${kind} · ${t(`flight.outcome.${outcome}`, { code: process.exitCode ?? '?' })}`;
}

export function FlightRunBadge() {
  useLang();
  useEverySec();
  const runs = useFlightRuns();
  // 이 화면이 「돌고 있다」로 본 실행만 끝난 뒤에도 남긴다. 닫은 것은 다시 안 띄운다.
  const seenRunning = useRef(new Set<string>());
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [notes, setNotes] = useState<Readonly<Record<string, string>>>({});

  const rows = Object.values(runs).flatMap((entry) => {
    const list: { key: string; deviceId: string; process: FlightProcess; emergency: boolean }[] = [];
    for (const [process, emergency] of [[entry.run, false], [entry.emergency, true]] as const) {
      if (process === null) continue;
      const key = `${entry.deviceId}:${emergency ? 'e' : 'r'}:${process.runId}`;
      if (process.state === 'running') seenRunning.current.add(key);
      if (!seenRunning.current.has(key) || dismissed.has(key)) continue;
      list.push({ key, deviceId: entry.deviceId, process, emergency });
    }
    return list;
  });
  if (rows.length === 0) return null;

  const note = (deviceId: string, text: string) => setNotes((current) => ({ ...current, [deviceId]: text }));

  return <aside className="manual-badge flight-badge" aria-live="polite">
    {rows.map(({ key, deviceId, process, emergency }) => {
      const running = process.state === 'running';
      const outcome = runOutcome(process);
      const tone = running ? (emergency ? 'flight-badge__row--emergency' : '') : outcome === 'ok' ? '' : 'manual-badge__row--blocked';
      const link = flightLink(deviceId);
      const progress = running && !emergency ? readProgress(process.lines) : null;
      return <div key={key} className={`manual-badge__row ${tone}`}>
        <span className={running ? 'manual-badge__dot flight-badge__dot--live' : 'manual-badge__dot'} aria-hidden="true" />
        <div>
          <b>{emergency
            ? t('flight.badge.emergency', { id: deviceId, mode: process.mode ?? '?' })
            : t('flight.badge.line', { id: deviceId })}</b>
          <small>
            {emergency ? t(`flight.outcome.${outcome}`, { code: process.exitCode ?? '?' }) : runSummary(process)}
            {progress?.live != null && <><br />{progress.live}</>}
            {notes[deviceId] !== undefined && <><br /><em>{notes[deviceId]}</em></>}
          </small>
        </div>
        <div className="flight-badge__buttons">
          {running && !emergency && <ArmedButton label={t('flight.btn.stop')} armedLabel={t('flight.btn.again')}
            disabled={link.stop === 'no'}
            onFire={() => { void issueFlightStop(link).then((outcome) => note(deviceId, outcome.message)); }} />}
          {running && !emergency && <ArmedButton className="flight-danger" label={t('flight.btn.land')} armedLabel={t('flight.btn.again')}
            disabled={link.emergency === 'no'}
            onFire={() => { void issueFlightEmergency(link, 'land').then((outcome) => note(deviceId, outcome.message)); }} />}
          {!running && <button type="button" onClick={(event) => {
            event.currentTarget.blur();
            setDismissed((current) => new Set([...current, key]));
          }}>{t('flight.badge.dismiss')}</button>}
        </div>
      </div>;
    })}
  </aside>;
}
