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
import type { DetectSourceRow } from '../summary.ts';
import { cpuPlacementOf, placementOf, planEnded, type CpuAmount, type CpuPlacement, type NodeSummary, type Placement, type PlacementState } from '../placement.ts';

const gb = (mb: number | null | undefined) => (mb === null || mb === undefined ? '—' : (mb / 1024).toFixed(1));
const pct = (value: number | null | undefined) => (value === null || value === undefined ? '—' : String(Math.round(value)));
const hhmm = (atMs: number | null) => (atMs === null ? '—' : new Date(atMs).toLocaleTimeString([], { hour12: false }));

function deviceName(placement: Placement): string {
  if (placement.kind === 'laptop') return t('dms.pl.laptopName');
  if (placement.kind === 'pi') return t('dms.pl.piName', { node: placement.node ?? '?' });
  return placement.node ?? '?';
}

function cpuDeviceName(placement: CpuPlacement): string {
  return deviceName({ from: placement.from === 'stream' ? 'plan' : 'dataStream', node: placement.node, unit: null, info: placement.info, kind: placement.kind });
}

const amount = (value: CpuAmount | null, key: keyof CpuAmount) => value?.[key] ?? '—';

function hardwareText(info: NodeSummary | null): { gpu: string | null; cpu: string | null; model: string | null } | null {
  const b = info?.baseline ?? null;
  if (b === null) return null;
  const gpus = b.gpus.filter((g) => g.name !== null).map((g) => (g.memTotalMb === null ? g.name : `${g.name} ${gb(g.memTotalMb)} GB`));
  return {
    gpu: gpus.length === 0 ? null : gpus.join(' · '),
    cpu: t('dms.pl.hwCpu', { arch: b.arch ?? '?', threads: b.cpuCount ?? '?', ram: gb(b.memTotalMb) }),
    model: b.cpuModel,
  };
}

function usageText(info: NodeSummary | null): string | null {
  if (info === null) return null;
  const parts: string[] = [];
  for (const g of info.gpu) parts.push(t('dms.pl.nowGpu', { used: gb(g.memUsedMb), total: gb(g.memTotalMb), util: pct(g.utilPct), temp: pct(g.tempC) }));
  if (info.cpuPct !== null || info.memPct !== null) parts.push(t('dms.pl.nowCpu', { cpu: pct(info.cpuPct), mem: pct(info.memPct) }));
  return parts.length === 0 ? null : `${parts.join(' · ')} (${hhmm(info.atMs)})`;
}

/**
 * 상세 창의 「실행 장치」 칸(261125) — 이 포트에서 살아 있는 모델마다 어느 장치에서 도는지. 같은 장치는 한 묶음으로.
 * 배치표에 있으면 그 노드, 없으면 data_stream 기기로 확정한다(`placement.ts` 머리 주석).
 */
export function PlacementSection({ row, state }: { row: DetectSourceRow | null; state: PlacementState }) {
  useLang();
  const live = row === null || row.state === 'down' ? [] : row.live;
  const groups = new Map<string, { placement: Placement; models: string[] }>();
  for (const m of live) {
    const placement = placementOf(state, row?.source ?? null, m.model);
    // GPU 단위와 CPU 작업은 같은 노드여도 근거가 달라 따로 묶는다(261127 — targeted · track 이 한 묶음이면 track 이 GPU 근거로 읽힌다).
    const key = `${placement.from}|${placement.node ?? ''}|${placement.cpuTask ?? ''}`;
    const group = groups.get(key) ?? { placement, models: [] };
    group.models.push(m.model);
    groups.set(key, group);
  }
  const plan = state.plan;
  return <section className="dms-sec dms-place">
    <h3>{t('dms.pl.title')}</h3>
    {groups.size === 0 && <p className="vn-line vn-dim">{t('dms.pl.none')}</p>}
    {[...groups.values()].map(({ placement, models }) => {
      const hw = hardwareText(placement.info);
      const usage = usageText(placement.info);
      const unit = placement.unit;
      const fps = unit !== null && row?.source != null ? unit.fpsCap[row.source] : undefined;
      return <div key={`${placement.from}|${placement.node ?? ''}|${placement.cpuTask ?? ''}`} className="dms-place__group">
        <p className={`dms-place__head dms-place__head--${placement.kind}`}>
          <b>{deviceName(placement)}</b>
          <span className="dms-badge">{t(placement.from === 'plan' ? 'dms.pl.badgePlan' : 'dms.pl.badgeDs')}</span>
        </p>
        <dl className="dms-kv">
          <dt>{t('dms.pl.models')}</dt><dd>{models.join(' · ')}</dd>
          <dt>{t('dms.pl.node')}</dt>
          <dd>{placement.node === null
            ? <span className="vn-dim">{t('dms.pl.nodeUnknown', { host: row?.host ?? '—' })}</span>
            : <><code>{placement.node}</code>{placement.info?.role != null && ` · role=${placement.info.role}`}{placement.info?.source != null && ` · ${placement.info.source}`}</>}</dd>
          <dt>{t('dms.pl.hardware')}</dt>
          <dd>{hw === null
            ? <span className="vn-dim">{t('dms.pl.hwUnknown')}</span>
            : <>{hw.gpu !== null && <>{hw.gpu}<br /></>}{hw.cpu}{hw.model !== null && <><br /><small className="vn-dim">{hw.model}</small></>}</>}</dd>
          {usage !== null && <><dt>{t('dms.pl.now')}</dt><dd>{usage}</dd></>}
          <dt>{t('dms.pl.why')}</dt>
          <dd>{placement.from === 'plan'
            ? placement.cpuTask != null
              ? t('dms.pl.whyCpu', { time: hhmm(plan?.atMs ?? null), task: placement.cpuTask, node: placement.node ?? '?' })
              : t('dms.pl.whyPlan', { time: hhmm(plan?.atMs ?? null), node: placement.node ?? '?' })
            : t('dms.pl.whyDs')}</dd>
          {unit !== null && <><dt>{t('dms.pl.share')}</dt>
            <dd>{t('dms.pl.shareText', { mb: unit.needMb ?? '—', basis: unit.needBasis ?? '—', fps: fps === undefined ? '—' : fps })}</dd></>}
          {placement.from === 'plan' && unit !== null && plan !== null && placement.node !== null && plan.where?.[placement.node] !== undefined && <>
            <dt>{t('dms.pl.runsAt')}</dt><dd>{plan.where[placement.node]}</dd></>}
          {placement.from === 'plan' && plan !== null && <><dt>{t('dms.pl.mode')}</dt>
            <dd>{t('dms.pl.modeText', { mode: plan.mode ?? '—', basis: plan.basis ?? '—' })}</dd>
            <dt>{t('dms.pl.plan')}</dt>
            <dd><code>{plan.requestId ?? '—'}</code>{plan.last !== null && ` · ${t('dms.pl.last', { event: plan.last.event ?? '—', time: hhmm(plan.last.atMs) })}`}</dd></>}
          {placement.from === 'dataStream' && plan !== null && planEnded(plan) && <><dt>{t('dms.pl.plan')}</dt>
            <dd className="vn-dim">{t('dms.pl.endedPlan', { request: plan.requestId ?? '—', time: hhmm(plan.last?.atMs ?? null) })}</dd></>}
        </dl>
      </div>;
    })}
    {state.error !== null && <p className="vn-line vn-warn">{t('dms.pl.readError', { why: state.error })}</p>}
    {state.planFrom === 'stored' && plan !== null && <p className="vn-line vn-dim">{t('dms.pl.stored', { time: hhmm(plan.atMs) })}</p>}
  </section>;
}

/**
 * 상세 창의 「만드는 작업」 칸(261125 안 2) — 이 포트의 영상을 만드는 CPU 작업이 어디서 도나. CPU 작업의 출력 포트가 아니면 안 그린다.
 * 단위 기록이 지금 위치를 말하면 그 노드(이동 기록 포함), 없거나 끝났으면 data_stream 기기(서버 고정).
 */
export function CpuTaskSection({ row, state }: { row: DetectSourceRow | null; state: PlacementState }) {
  useLang();
  const placement = cpuPlacementOf(state, row?.source ?? null);
  if (placement === null) return null;
  const record = placement.record;
  const hw = hardwareText(placement.info);
  const usage = usageText(placement.info);
  const alive = row !== null && (row.state === 'raw' || row.state === 'models') && row.frameRate !== null && row.frameRate > 0;
  const ended = placement.ended;
  const lastMove = record !== null && record.moves.length > 0 ? record.moves[record.moves.length - 1] : null;
  return <section className="dms-sec dms-place dms-maker-sec">
    <h3>{t('dms.mk.secTitle')}</h3>
    <div className="dms-place__group">
      <p className={`dms-place__head dms-place__head--${placement.kind}`}>
        <b>{cpuDeviceName(placement)}</b>
        <span className="dms-badge">{t(placement.from === 'stream' ? 'dms.mk.badgeStream' : 'dms.mk.badgeDs')}</span>
      </p>
      <dl className="dms-kv">
        <dt>{t('dms.mk.task')}</dt><dd>{t('dms.mk.taskText', { task: placement.task })}</dd>
        <dt>{t('dms.pl.node')}</dt>
        <dd>{placement.node === null
          ? <span className="vn-dim">{t('dms.pl.nodeUnknown', { host: row?.host ?? '—' })}</span>
          : <><code>{placement.node}</code>{placement.info?.role != null && ` · role=${placement.info.role}`}{placement.info?.source != null && ` · ${placement.info.source}`}</>}</dd>
        <dt>{t('dms.pl.hardware')}</dt>
        <dd>{hw === null
          ? <span className="vn-dim">{t('dms.pl.hwUnknown')}</span>
          : <>{hw.cpu}{hw.model !== null && <><br /><small className="vn-dim">{hw.model}</small></>}</>}</dd>
        {usage !== null && <><dt>{t('dms.pl.now')}</dt><dd>{usage}</dd></>}
        {record !== null && <>
          <dt>{t('dms.mk.unit')}</dt><dd><code>{record.unitId ?? '—'}</code> · <code>{record.requestId ?? '—'}</code></dd>
          <dt>{t('dms.mk.state')}</dt>
          <dd>{record.lost
            ? <span className="vn-warn">{t('dms.mk.lost', { state: record.state, why: record.reason ?? '—' })}</span>
            : `${record.state} · ${hhmm(record.atMs)}`}</dd>
          {(record.requests !== null || record.limits !== null) && <><dt>{t('dms.mk.amount')}</dt>
            <dd>{t('dms.mk.amountText', { reqCpu: amount(record.requests, 'cpuM'), limCpu: amount(record.limits, 'cpuM'), reqMem: amount(record.requests, 'memMb'), limMem: amount(record.limits, 'memMb') })}</dd></>}
        </>}
        <dt>{t('dms.pl.why')}</dt>
        <dd>{record !== null
          ? t('dms.mk.whyStream', { time: hhmm(record.atMs), reason: lastMove?.reason ?? record.reason ?? record.state })
          : t('dms.mk.whyDs')}</dd>
        <dt>{t('dms.mk.alive')}</dt>
        <dd>{alive
          ? <><em className="dms-dot dms-dot--ok" aria-hidden="true" />{t('dms.mk.aliveYes', { rate: row?.frameRate?.toFixed(1) ?? '—' })}</>
          : <span className="vn-warn">{t('dms.mk.aliveNo')}</span>}</dd>
        {record !== null && record.moves.length > 0 && <><dt>{t('dms.mk.moves')}</dt>
          <dd>{record.moves.map((move) => <div key={`${move.from ?? ''}>${move.to}`}>{t('dms.mk.move', { time: hhmm(move.tsMs ?? move.atMs), from: move.fromNode ?? '?', to: move.toNode ?? '?' })}</div>)}</dd></>}
        {ended !== null && <><dt>{t('dms.pl.plan')}</dt>
          <dd className="vn-dim">{t('dms.mk.ended', { task: ended.task, node: ended.node ?? '?', state: ended.state, time: hhmm(ended.atMs) })}</dd></>}
      </dl>
      <p className="vn-line vn-dim dms-place__src">{t(record !== null ? 'dms.mk.src' : 'dms.mk.srcDs')}</p>
    </div>
    {state.error !== null && <p className="vn-line vn-warn">{t('dms.pl.readError', { why: state.error })}</p>}
  </section>;
}

const seenText = (seen: Readonly<Record<string, number>> | null) =>
  seen === null ? null : Object.keys(seen).length === 0 ? t('dms.seenNone') : Object.entries(seen).map(([label, n]) => `${label} ${n}`).join(' · ');

const whyText = (why: string | null) => (why === null ? '—' : why === 'empty' ? t('dms.whyEmpty') : why);

/** 지정 탐지 — `compact` 면 카드 안의 한 줄, 아니면 상세 창의 칸. 출처를 늘 같이 적는다. */
export function TargetLine({ info, compact = false }: { info: TargetInfo; compact?: boolean }) {
  useLang();
  // 빈 목록 = 이 장비는 아무것도 안 찾는다(장비별 대상을 비움, 261126) — 「모름」과 가른다.
  const targets = info.targets === null ? null : info.targets.length === 0 ? t('dms.tg.noTargets') : info.targets.join(' · ');
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
      <dt>{t('dms.tg.targets')}</dt><dd>{targets === null ? <span className="vn-dim">{t('dms.tg.unknownTargets')}</span>
        : info.targets?.length === 0 ? <span className="vn-warn">{targets}</span>
        : info.targets?.map((name) => <span key={name} className="dms-chip dms-chip--target">{name}</span>)}</dd>
      {info.processTargets !== null && <><dt>{t('dms.tg.processTargets')}</dt><dd className="vn-dim">{info.processTargets.join(' · ')}</dd></>}
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
