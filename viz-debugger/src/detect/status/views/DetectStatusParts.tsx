/**
 * src/detect/status/views/DetectStatusParts.tsx (261124 신설 — 객체 탐지 상태판)
 *
 * 판과 상세 창이 같이 쓰는 두 조각 — 지정 탐지 한 줄(또는 칸)과 변경 기록 목록.
 */

import { t } from '../../../i18n/dict.ts';
import { Rich } from '../../../i18n/RichText.tsx';
import { useLang } from '../../../shared/language.ts';
import type { DetectEvent, DetectHistoryState } from '../history.ts';
import type { TargetInfo } from '../targets.ts';

const seenText = (seen: Readonly<Record<string, number>> | null) =>
  seen === null ? null : Object.keys(seen).length === 0 ? t('dms.seenNone') : Object.entries(seen).map(([label, n]) => `${label} ${n}`).join(' · ');

const whyText = (why: string | null) => (why === null ? '—' : why === 'empty' ? t('dms.whyEmpty') : why);

/** 지정 탐지 — `compact` 면 카드 안의 한 줄, 아니면 상세 창의 칸. 출처를 늘 같이 적는다. */
export function TargetLine({ info, compact = false }: { info: TargetInfo; compact?: boolean }) {
  useLang();
  const targets = info.targets === null ? null : info.targets.join(' · ');
  const line = info.source === 'mission'
    ? <Rich id="dms.tg.mission" vars={{ targets: targets ?? '—', mission: info.missionId ?? '—', c: info.angles?.captured ?? 0, n: info.angles?.total ?? 0 }} />
    : info.source === 'otherScan'
    ? <Rich id="dms.tg.otherScan" vars={{ targets: targets ?? t('dms.tg.unknownTargets'), scan: info.scanId ?? '—' }} />
    : info.source === 'profile'
    ? <Rich id="dms.tg.profile" vars={{ targets: targets ?? '—', version: info.profileVersion ?? '?', label: info.profileLabel ?? '—' }} />
    : <Rich id="dms.tg.unknown" vars={{ why: whyText(info.why) }} />;
  if (compact) return <p className={`dms-target dms-target--${info.source}`}>{line}</p>;
  const seen = seenText(info.seen);
  return <section className="dms-sec">
    <h3>{t('dms.tg.title')}</h3>
    <dl className="dms-kv">
      <dt>{t('dms.tg.targets')}</dt><dd>{targets === null ? <span className="vn-dim">{t('dms.tg.unknownTargets')}</span> : info.targets?.map((name) => <span key={name} className="dms-chip dms-chip--target">{name}</span>)}</dd>
      <dt>{t('dms.tg.source')}</dt><dd>{line}</dd>
      {info.query !== null && <><dt>{t('dms.tg.query')}</dt><dd>{info.query}</dd></>}
      {info.scanId !== null && <><dt>{t('dms.tg.scan')}</dt><dd><code>{info.scanId}</code></dd></>}
      {info.profileVersion !== null && <><dt>{t('dms.tg.profileRow')}</dt><dd>{`v${info.profileVersion}${info.profileLabel === null ? '' : ` · ${info.profileLabel}`}`}</dd></>}
      {info.provisional !== null && info.provisional.length > 0 && <><dt>{t('dms.tg.provisional')}</dt><dd>{info.provisional.join(' · ')}</dd></>}
      <dt>{t('dms.tg.seen')}</dt><dd>{seen ?? <span className="vn-dim">{t('dms.tg.seenUnknown')}</span>}</dd>
    </dl>
    {info.why !== null && info.source !== 'unknown' && <p className="vn-line vn-dim">{t('dms.tg.redisNote', { why: whyText(info.why) })}</p>}
  </section>;
}

function eventLine(event: DetectEvent): { text: string; sub: string | null; tone: 'add' | 'remove' | 'target' | 'plain' } {
  const name = event.source;
  switch (event.kind) {
    case 'start': return { text: t('dms.ev.start', { source: name, models: event.after || t('dms.ev.noModels') }), sub: event.before === undefined ? null : t('dms.ev.startTargets', { targets: event.before }), tone: 'plain' };
    case 'modelUp': return { text: t('dms.ev.modelUp', { source: name, model: event.model ?? '' }), sub: event.after === undefined ? null : `run ${event.after}`, tone: 'add' };
    case 'modelDown': return { text: t('dms.ev.modelDown', { source: name, model: event.model ?? '' }), sub: t('dms.ev.modelDownWhy'), tone: 'remove' };
    case 'modelRestart': return { text: t('dms.ev.modelRestart', { source: name, model: event.model ?? '' }), sub: `run ${event.before ?? '?'} → ${event.after ?? '?'}`, tone: 'add' };
    case 'targets': return { text: t('dms.ev.targets', { source: name, before: event.before ?? '', after: event.after ?? '' }), sub: event.detail ?? null, tone: 'target' };
    case 'profile': return { text: t('dms.ev.profile', { source: name, before: event.before ?? '', after: event.after ?? '' }), sub: null, tone: 'target' };
    case 'scanStart': return { text: t('dms.ev.scanStart', { source: name }), sub: event.after ?? null, tone: 'target' };
    case 'scanEnd': return { text: t('dms.ev.scanEnd', { source: name }), sub: event.before ?? null, tone: 'plain' };
    case 'down': return { text: t('dms.ev.down', { source: name }), sub: null, tone: 'remove' };
    case 'up': return { text: t('dms.ev.up', { source: name }), sub: event.downMs === undefined ? null : t('dms.ev.upFor', { sec: Math.round(event.downMs / 1000) }), tone: 'add' };
    default: return { text: String(event.kind), sub: null, tone: 'plain' };
  }
}

const clock = (atMs: number) => new Date(atMs).toLocaleTimeString([], { hour12: false });

/** 변경 기록 — `base` 를 주면 그 포트 것만. 최근이 위. */
export function DetectHistoryList({ history, base }: { history: DetectHistoryState; base: string | null }) {
  useLang();
  const events = history.events.filter((event) => base === null || event.base === base).slice().reverse();
  return <section className="dms-sec dms-history">
    <h3>{t('dms.ev.title')} <span className="dms-badge">{t('dms.ev.count', { n: events.length })}</span></h3>
    <p className="vn-line vn-dim">{t(history.recorded !== null ? 'dms.ev.recorded' : history.recording ? 'dms.ev.recording' : 'dms.ev.onlyMission')}</p>
    {events.length > 0 && <ul className="dms-timeline">
      {events.map((event, index) => {
        const line = eventLine(event);
        return <li key={`${event.atMs}-${index}`} className={`dms-ev dms-ev--${line.tone}`}>
          <time>{clock(event.atMs)}</time>{line.text}
          {line.sub !== null && <small>{line.sub}</small>}
        </li>;
      })}
    </ul>}
  </section>;
}
