/**
 * src/detect/status/views/DetectModelPanel.tsx (261124 신설 — 객체 탐지 상태판)
 *
 * **「기능」 판 자리.** 마일스톤 화면 오른쪽 기둥의 아래 절반이다 — 위의 하드웨어 판과 세로를 1:1 로 나누고 각자 구른다.
 * 「기능」 판(`src/capability/`)은 화면에서만 뺐고 코드는 그대로다(261124 사용자 결정).
 *
 * 보이는 것은 data_stream 이 **지금** 돌리고 있는 것이다 — 포트(소스)마다 카드 한 장, 그 안에 살아 있는 모델 칩과
 * 지정 탐지 대상. 하드웨어가 하나도 없어도 뜬다(카드는 연결 관리의 포트 줄에서 나온다).
 *
 * **조회만 한다.** data_stream 쪽 무엇도 바꾸지 않는다 — 영역 지정 · 재식별처럼 원래 있던 조작은 상세(더블클릭)의
 * 영상 칸이 하던 대로 한다.
 *
 * 조회 주기: 판은 포트 전부를 2초마다(`holdAllVisionSources({ slow: true })`), 상세가 열린 포트는 1초마다.
 * 지정 탐지 대상은 `targeted` 가 살아 있는 포트만 2초마다 Redis 마지막 한 건(`latestStore.ts`).
 *
 * 계획: `documents/작업프롬프트/작업프롬프트_탐지모델상태판_개발계획_261124.md`.
 */

import { useEffect, useState } from 'react';
import { t } from '../../../i18n/dict.ts';
import { Rich } from '../../../i18n/RichText.tsx';
import { useLang } from '../../../shared/language.ts';
import { useConnections } from '../../../shared/connections.ts';
import { useDeviceCardIds } from '../../../shared/registry.ts';
import { useReplayTarget } from '../../../record/replayMode.ts';
import { useRecorderStatus } from '../../../record/recorder.ts';
import { holdAllVisionSources, useVisionSources } from '../../../vision/store.ts';
import { visionBases } from '../../../vision/visionClient.ts';
import { deviceBrokerHost, deviceDirectBase, resolveVisionBinding, useVisionBindingChoices } from '../../../vision/binding.ts';
import { Still } from '../../../vision/views/VisionViews.tsx';
import { VISION_STREAM_PORTS } from '../../../vision/presets.ts';
import { useScanRun } from '../../scan/scanStore.ts';
import { holdLatest, latestOf, useLatestStates } from '../latestStore.ts';
import { devicesByBase, modelChipTone, summarizeDetectSources, TARGETED, type DetectSourceRow } from '../summary.ts';
import { targetInfo, type TargetInfo } from '../targets.ts';
import { noteDetectRows, useDetectHistory } from '../history.ts';
import { countDevices, holdPlacement, placementOf, shortTag, usePlacement, type PlacementSnapshot } from '../placement.ts';
import { DetectHistoryList, TargetLine } from './DetectStatusParts.tsx';

const ms = (value: number | null) => (value === null ? '—' : `${Math.round(value)} ms`);
/**
 * 서버가 이름을 밝히기 전(응답 없음 · 처음)의 카드 이름 — 포트 번호와, 표에 있으면 **보통 그 포트의 소스**(흐리게).
 * 전체 주소를 제목에 두면 카드 여섯 장이 같은 IP 로 시작해 서로 안 갈린다. 주소는 마우스를 올리면 보인다.
 */
function guessName(base: string): { port: string; usual: string | null } {
  let port = '';
  try { port = new URL(base).port; } catch { port = ''; }
  return { port, usual: VISION_STREAM_PORTS.find((item) => String(item.port) === port)?.source ?? null };
}

const perSec = (value: number | null | undefined) => (value === null || value === undefined ? '—' : value.toFixed(1));

/** 판 전체가 쓰는 계산 — 상세 창도 같은 값을 본다. */
export function useDetectRows(): { rows: DetectSourceRow[]; totals: ReturnType<typeof summarizeDetectSources>['totals']; infos: Record<string, TargetInfo | null> } {
  useConnections();
  const sources = useVisionSources();
  const choices = useVisionBindingChoices();
  const cards = useDeviceCardIds();
  const scan = useScanRun();
  // 구독만 한다 — 값은 아래 `latestOf` 가 읽는다. 계산이 가벼워(포트 열 남짓) 그릴 때마다 새로 센다.
  useLatestStates();
  const bases = visionBases();
  const bindings: Record<string, string | null> = {};
  for (const id of cards) {
    bindings[id] = resolveVisionBinding(choices[id] ?? null, deviceBrokerHost(id), sources, bases, deviceDirectBase(id)).base;
  }
  const { rows, totals } = summarizeDetectSources(bases, sources, devicesByBase(bindings));
  const infos: Record<string, TargetInfo | null> = {};
  for (const row of rows) infos[row.base] = targetInfo(row, scan, latestOf(row.base, row.source, TARGETED));
  return { rows, totals, infos };
}

/** `targeted` 가 살아 있는 포트의 Redis 마지막 한 건을 붙잡는다. */
function useHoldTargeted(rows: readonly DetectSourceRow[]): void {
  const keys = rows.filter((row) => row.state === 'models' && row.live.some((m) => m.model === TARGETED) && row.source !== null)
    .map((row) => `${row.base}|${row.source}`);
  const joined = keys.join('\n');
  useEffect(() => {
    const releases = joined === '' ? [] : joined.split('\n').map((key) => {
      const [base, source] = key.split('|');
      return holdLatest(base, source, TARGETED);
    });
    return () => { for (const release of releases) release(); };
  }, [joined]);
}

/** 칩 끝 실행 장치 꼬리표(261125). 마우스를 올리면 노드 이름까지. */
function DeviceTag({ snapshot, source, model }: { snapshot: PlacementSnapshot; source: string | null; model: string }) {
  useLang();
  const placement = placementOf(snapshot, source, model);
  const full = placement.node === null ? t('dms.pl.dsDevice') : `${placement.node}${placement.from === 'dataStream' ? ` · ${t('dms.pl.dsDevice')}` : ''}`;
  return <span className={`dms-chip__at dms-chip__at--${placement.kind}`} title={t('dms.at.title', { device: full })}>{shortTag(placement)}</span>;
}

function SourceCard({ row, info, onOpen, snapshot }: { row: DetectSourceRow; info: TargetInfo | null; onOpen(base: string, model: string | null): void; snapshot: PlacementSnapshot }) {
  useLang();
  const tone = row.state === 'models' ? 'ok' : row.state === 'down' ? 'bad' : row.state === 'noVideo' ? 'warn' : 'unknown';
  const thumb = row.state === 'models' ? (row.live[0]?.model ?? null) : null;
  return <article className={`dms-card dms-card--${row.state}`} onDoubleClick={() => onOpen(row.base, null)} title={row.base}>
    <header className="dms-card__head">
      {row.source !== null
        ? <><b><em className={`dms-dot dms-dot--${tone}`} aria-hidden="true" />{row.source}</b>{row.port !== null && <code>:{row.port}</code>}</>
        : <><b><em className={`dms-dot dms-dot--${tone}`} aria-hidden="true" /><code>:{guessName(row.base).port || row.base}</code></b>
            {guessName(row.base).usual !== null && <small className="vn-dim">{t('dms.usualSource', { name: guessName(row.base).usual ?? '' })}</small>}</>}
      <small className="dms-card__device">{row.devices.length > 0 ? `→ ${row.devices.join(', ')}` : t('dms.noDevice')}</small>
    </header>
    <p className="dms-card__line">
      {row.state === 'down'
        ? <span className="vn-warn dms-card__oneline" title={row.error ?? ''}>{t('dms.down', { why: row.error ?? '—' })}</span>
        : row.state === 'waiting'
        ? <span className="vn-dim">{t('dms.waiting')}</span>
        : row.state === 'noVideo'
        ? <span className="vn-warn">{t('dms.noVideo')}</span>
        : <span>{t('dms.rates', { frames: perSec(row.frameRate), states: perSec(row.stateRate) })}
            {row.state === 'raw' && <> · <span className="vn-dim">{t('dms.noModel')}</span></>}</span>}
    </p>
    {row.live.length > 0 && row.state !== 'down' && <div className="dms-chips">
      {row.live.map((m) => <button key={m.model} type="button" className={`dms-chip dms-chip--${modelChipTone(m)}`}
        onDoubleClick={(event) => { event.stopPropagation(); onOpen(row.base, m.model); }}
        title={t('dms.chipHint')}>
        {modelChipTone(m) === 'warn'
          ? t('dms.chipStale', { model: m.model, age: m.ageS === null ? '—' : Math.round(m.ageS) })
          : t('dms.chip', { model: m.model, rate: perSec(row.rate[m.model]), lag: ms(m.lagMs) })}
        <DeviceTag snapshot={snapshot} source={row.source} model={m.model} />
      </button>)}
    </div>}
    {row.visionError !== null && row.state !== 'down' && <p className="dms-card__line vn-warn">{t('dms.visionError', { why: row.visionError })}</p>}
    {info !== null && <TargetLine info={info} compact />}
    {thumb !== null && <Still base={row.base} model={thumb} className="dms-card__thumb" />}
  </article>;
}

export function DetectModelPanel({ onOpen }: { onOpen(base: string, model: string | null): void }) {
  useLang();
  useConnections();
  // 포트 전부를 2초마다 — 상세가 열린 포트는 그쪽이 1초로 붙잡는다.
  useEffect(() => holdAllVisionSources({ slow: true }), []);
  const { rows, totals, infos } = useDetectRows();
  useHoldTargeted(rows);
  // 실행 장치 — 배치표 · 노드 정보를 5초마다(261125).
  useEffect(() => holdPlacement(), []);
  const placement = usePlacement();
  const devices = countDevices(rows.filter((row) => row.state !== 'down')
    .flatMap((row) => row.live.map((m) => placementOf(placement, row.source, m.model))));
  const recorder = useRecorderStatus();
  const replaying = useReplayTarget();
  const history = useDetectHistory();
  const [showHistory, setShowHistory] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);

  // 변경 기록 — 임무 판이 기록되는 동안만 적는다. 다시보기 동안은 지난 판의 기록을 보이므로 부르지 않는다.
  const runFolder = recorder.state === 'recording' ? recorder.folder : null;
  const fingerprint = JSON.stringify(rows.map((row) => [row.base, row.state, row.source, row.busyScanId, row.live.map((m) => [m.model, m.run, m.results])]))
    + JSON.stringify(Object.entries(infos).map(([base, info]) => [base, info?.targets ?? null, info?.profileVersion ?? null]));
  useEffect(() => {
    if (replaying !== null) return;
    noteDetectRows(rows, infos, runFolder, Date.now());
  // 값이 바뀐 때만 — 렌더마다 부르면 같은 장을 두 번 비교할 뿐이지만 쓸데없다.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint, runFolder, replaying]);

  const bases = visionBases();
  const lastAt = rows.reduce<number | null>((latest, row) => (row.receivedAtMs === null ? latest : latest === null ? row.receivedAtMs : Math.max(latest, row.receivedAtMs)), null);
  const host = bases[0] === undefined ? null : new URL(bases[0]).hostname;

  return <aside className="detect-status-panel">
    <header className="dms-head">
      <h2>{t('dms.title', { n: totals.models })}</h2>
      <span className="dms-badge" title={t('dms.badgeWhy')}>{t('dms.badge')}</span>
    </header>
    <p className="dms-hint"><Rich id="dms.hint" vars={{ connected: totals.connected, down: totals.down, targeted: totals.targeted, devices }} /></p>
    {bases.length === 0 && <p className="hardware-panel__none">{t('dms.noPorts')}</p>}
    <div className="dms-list">
      {rows.map((row) => <SourceCard key={row.base} row={row} info={infos[row.base] ?? null} onOpen={onOpen} snapshot={placement} />)}
    </div>
    {showHistory && <DetectHistoryList history={history} base={null} />}
    <footer className="dms-foot">
      <span>{t('dms.foot', { host: host ?? '—', ports: bases.length, ago: lastAt === null ? '—' : Math.max(0, Math.round((now - lastAt) / 1000)) })}</span>
      <button type="button" onClick={() => setShowHistory((value) => !value)} aria-expanded={showHistory}>
        {t('dms.historyButton', { n: history.events.length })}
      </button>
    </footer>
  </aside>;
}
