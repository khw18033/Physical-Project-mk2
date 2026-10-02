/**
 * src/vision/views/VisionViews.tsx (261001 신설 — 객체 탐지 추론 스트림)
 *
 * 세 자리.
 *
 *   VisionCam            추론 영상 뷰 노드 — 고른 포트의 모델별 오버레이를 나란히. 접힘은 **2초마다 한 장**,
 *                        확대는 서버 스트림을 **그대로**
 *   VisionCardLine       하드웨어 카드 한 줄 — 묶인 포트 · 돌고 있는 모델 · 속도 · 지연과 작은 한 장
 *   VisionDeviceSection  하드웨어 카드 상세 — 포트 고르기(자동 맞춤을 보여 주고 사람이 바꾼다)와 실시간 영상
 *
 * ## ts 를 맞추는 법 (서버를 고치지 않는 범위)
 *
 * 오버레이는 서버가 **그 원본 프레임 위에 그린 것**이다 — 한 장 안에서는 원본과 결과가 같은 순간이다. 그래서 결과는
 * 오버레이로 보인다. 원본 실시간 칸은 결과보다 `lag_ms` 만큼 앞서므로, 켜면 그 칸이 「앞선다」고 적는다 —
 * 나란히 놓인 두 칸을 같은 순간으로 읽지 않게.
 *
 * **프레임 번호가 짝 키다** (261001 검토). 서버는 원본 한 장마다 번호 `n` 을 하나씩 올려 `frames/<n>.jpg` 로 저장하고,
 * 추론 결과에도 그 `n` 이 그대로 실린다(`vision_infer.py` — 디스크의 `overlay/<n>.jpg` · `results.jsonl` 도 같은 이름).
 * `/health` 의 `frames`(받은 장 수)는 같은 실행 안에서 최신 `n` 과 같다. 그래서 「결과가 원본보다 몇 장 뒤인가」를
 * 시계 없이 번호로 적는다(`frameGap`). 그 번호의 원본 **이미지**는 HTTP 로 꺼낼 길이 없어(서버가 파일을 내주지 않는다)
 * 번호까지만 맞춘다.
 *
 * 검출 하나하나의 JSON 은 서버가 HTTP 로 내주지 않는다(서버 안 Redis 에만 있다). 그래서 칸마다 서버 `/health` 의
 * 요약(마지막 결과 번호 · 검출 수 · 지연 · 속도)만 적고, 그것이 요약이라는 것을 적는다.
 *
 * ## 결과가 없는 스트림은 열지 않는다 (261001 실측)
 *
 * 서버의 `/vision?model=<m>` 은 그 모델 결과가 없어도 200 으로 열어 두고 기다린다(`/stream` 도 원본이 없으면 같다).
 * 쓸 것이 없으니 우리가 끊어도 서버 스레드는 끊긴 줄 모르고 남는다. 그래서 **`/health` 에 결과가 한 번이라도 잡힌 모델과
 * 영상이 한 장이라도 들어온 원본에만** 붙는다 — 아닌 칸은 글로 「결과 없음」을 적는다. 한 번이라도 있었으면 서버가 마지막
 * 한 장을 곧바로 주므로 남는 스레드가 없다(멎은 모델이면 그 한 장이 낡았다고 칸 머리가 적는다).
 *
 * **문 찾기 시연(`src/detect/`) · 장애물 탐지(`src/autodrive/`)와 섞지 않는다.** 클래스 몇 개(`detect-cam` 모양)만 빌린다.
 */

import { useEffect, useState } from 'react';
import { t } from '../../i18n/dict.ts';
import { useLang } from '../../shared/language.ts';
import { useConnections } from '../../shared/connections.ts';
import { useReplayTarget } from '../../record/replayMode.ts';
import {
  frameGap, modelLive, modelStale, overlayStreamUrl, rawStreamUrl, stillUrl, visionBases,
  type VisionModelSummary,
} from '../visionClient.ts';
import { holdAllVisionSources, holdVisionSource, useVisionSources, type VisionSourceState } from '../store.ts';
import {
  deviceBrokerHost, deviceDirectBase, resolveVisionBinding, setVisionBinding, useVisionBindingChoice, VISION_UNBOUND, type VisionBinding,
} from '../binding.ts';
import { setVisionNodeChoice, useVisionNodeChoice } from '../nodeChoice.ts';
import { isFixedCamera } from '../../fixedcam/fixedCamera.ts';

/** 접힌 카드가 새 한 장을 받는 주기 — 탐지 영상 노드와 같다. */
export const VISION_STILL_MS = 2000;

const sec = (value: number | null) => (value === null ? '—' : `${value.toFixed(1)}s`);
const ms = (value: number | null) => (value === null ? '—' : `${Math.round(value)}ms`);

/** 포트 이름 — 서버가 밝힌 소스 이름, 아직 모르면 주소. */
function sourceName(base: string, sources: Readonly<Record<string, VisionSourceState>>): string {
  return sources[base]?.health?.source ?? base;
}

/** 장비 하나의 포트 묶음. 포트 전부를 붙잡는다 — 주소를 맞대 보려면 다 받아 봐야 한다. */
export function useVisionBinding(entityId: string | null): VisionBinding {
  useConnections();
  const sources = useVisionSources();
  const chosen = useVisionBindingChoice(entityId ?? '');
  useEffect(() => (entityId === null ? undefined : holdAllVisionSources()), [entityId]);
  if (entityId === null || entityId === '') return { base: null, how: 'none', candidates: [] };
  return resolveVisionBinding(chosen, deviceBrokerHost(entityId), sources, visionBases(), deviceDirectBase(entityId));
}

/** 2초마다 한 장. 창구가 그 스트림의 첫 JPEG 를 잘라 준다. */
function Still({ base, model, className }: { base: string; model: string | null; className?: string }) {
  useLang();
  const [nonce, setNonce] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => setNonce((value) => value + 1), VISION_STILL_MS);
    return () => clearInterval(timer);
  }, []);
  return <>
    <img className={className} src={stillUrl(base, model, nonce)} alt={model ?? t('vis.raw')}
      onLoad={() => setFailed(false)} onError={() => setFailed(true)} />
    {failed && <small className="vn-warn">{t('vis.stillFailed')}</small>}
  </>;
}

/** 모델 칸 하나의 요약 한 줄. */
function SummaryLine({ summary, rate, framesNow }: { summary: VisionModelSummary | null; rate: number | undefined; framesNow: number | null }) {
  useLang();
  if (summary === null) return <span className="vn-dim">{t('vis.noResultYet')}</span>;
  return <span className={modelStale(summary) ? 'vn-warn' : undefined}>
    {t('vis.summary', {
      n: summary.n ?? '—',
      det: summary.detections ?? '—',
      lag: ms(summary.lagMs),
      infer: ms(summary.inferMs),
      rate: rate === undefined ? '—' : rate.toFixed(1),
      age: sec(summary.ageS),
    })}
    {frameGap(framesNow, summary) === null ? '' : t('vis.behindFrames', { gap: frameGap(framesNow, summary) ?? 0 })}
    {modelStale(summary) ? t('vis.stale') : ''}
  </span>;
}

function VisionCell({ base, model, summary, rate, zoom, lagMs, framesNow, gapFrames, available }: {
  base: string;
  /** null 이면 원본 칸. */
  model: string | null;
  summary: VisionModelSummary | null;
  rate: number | undefined;
  zoom: boolean;
  /** 원본 칸이 결과보다 얼마나 앞서는가 — 결과 모델 중 가장 작은 지연. */
  lagMs: number | null;
  /** 원본 최신 번호(`/health` 의 `frames`). */
  framesNow: number | null;
  /** 원본 칸이 결과보다 몇 장 앞서는가 — 결과 모델 중 가장 작은 차이. */
  gapFrames: number | null;
  /** 지금 열어도 되는가 — 결과(원본)가 온다고 서버가 말했는가. 파일 머리 §결과가 없는 스트림. */
  available: boolean;
}) {
  useLang();
  const [failed, setFailed] = useState<string | null>(null);
  const url = model === null ? rawStreamUrl(base) : overlayStreamUrl(base, model);
  return <figure className="vision-cell">
    <figcaption>
      <b>{model ?? t('vis.raw')}</b>
      {model === null
        ? <small>{gapFrames !== null && framesNow !== null
            ? t('vis.rawAheadFrames', { frames: framesNow, gap: gapFrames, lag: ms(lagMs) })
            : lagMs === null ? t('vis.rawAhead') : t('vis.rawAheadBy', { lag: ms(lagMs) })}</small>
        : <small><SummaryLine summary={summary} rate={rate} framesNow={framesNow} /></small>}
    </figcaption>
    {!available
      ? <p className="vn-line vn-dim">{t(model === null ? 'vis.rawNotYet' : 'vis.modelNotLive')}</p>
      : zoom
      // 확대는 주소가 안 바뀌어야 스트림이 안 끊긴다. 닫으면 `<img>` 가 사라지고 연결이 닫힌다.
      ? <img src={url} alt={model ?? t('vis.raw')}
          onLoad={() => setFailed(null)}
          onError={() => setFailed(t('vis.streamFailed', { url }))} />
      : <Still base={base} model={model} />}
    {failed !== null && <small className="vn-warn">{failed}</small>}
  </figure>;
}

/** 포트 고르기 — 확대에서만. 목록에서 빠진 포트를 골라 두었으면 그 포트를 그대로 보이고 「목록에 없음」을 붙인다. */
function SourcePicker({ nodeId, autoBase, autoWhy }: { nodeId: string; autoBase: string | null; autoWhy: string }) {
  useLang();
  useConnections();
  const sources = useVisionSources();
  const choice = useVisionNodeChoice(nodeId);
  const bases = visionBases();
  const chosen = choice.base ?? null;
  const missing = chosen !== null && !bases.includes(chosen);
  return <label className="ai-source">
    <span>{t('vis.sourcePick')}</span>
    <select value={chosen ?? ''} onChange={(event) => setVisionNodeChoice(nodeId, { base: event.target.value === '' ? undefined : event.target.value })}>
      <option value="">{t('vis.sourceAuto', { name: autoBase === null ? t('vis.sourceNone') : sourceName(autoBase, sources), why: autoWhy })}</option>
      {bases.map((base) => <option key={base} value={base}>{`${sourceName(base, sources)} · ${base}`}</option>)}
      {missing && <option value={chosen}>{t('vis.sourceMissing', { url: chosen })}</option>}
    </select>
  </label>;
}

/** 모델 고르기 — 여럿을 고르면 나란히 선다. 아무것도 안 고르면 결과가 오는 모델 전부. */
function ModelPicker({ nodeId, models }: { nodeId: string; models: readonly VisionModelSummary[] }) {
  useLang();
  const choice = useVisionNodeChoice(nodeId);
  const chosen = choice.models ?? null;
  const names = [...new Set([...models.map((m) => m.model), ...(chosen ?? [])])];
  const toggle = (name: string, on: boolean) => {
    const base = chosen ?? models.filter(modelLive).map((m) => m.model);
    const next = on ? [...new Set([...base, name])] : base.filter((m) => m !== name);
    setVisionNodeChoice(nodeId, { models: next });
  };
  return <div className="vision-pick">
    <span>{t('vis.modelPick')}</span>
    {names.length === 0 && <small className="vn-dim">{t('vis.noModel')}</small>}
    {names.map((name) => {
      const summary = models.find((m) => m.model === name) ?? null;
      const on = chosen === null ? (summary !== null && modelLive(summary)) : chosen.includes(name);
      return <label key={name} className={summary !== null && modelLive(summary) ? undefined : 'vn-dim'}>
        <input type="checkbox" checked={on} onChange={(event) => toggle(name, event.target.checked)} />{name}
      </label>;
    })}
    <label>
      <input type="checkbox" checked={choice.raw === true} onChange={(event) => setVisionNodeChoice(nodeId, { raw: event.target.checked ? true : undefined })} />
      {t('vis.rawToggle')}
    </label>
    {chosen !== null && <button type="button" className="detect-cam__back" onClick={() => setVisionNodeChoice(nodeId, { models: undefined })}>{t('vis.modelAuto')}</button>}
  </div>;
}

/** 확대 아래의 요약 표 — 모델마다 한 줄. 서버가 준 값 그대로다. */
function SummaryTable({ state }: { state: VisionSourceState }) {
  useLang();
  const health = state.health;
  if (health === null) return null;
  return <>
    <dl className="device-facts">
      <div><dt>{t('vis.factSource')}</dt><dd>{health.source}{health.port === null ? '' : ` :${health.port}`}{health.host === null ? '' : ` · ${health.host}`}</dd></div>
      <div><dt>{t('vis.factFrames')}</dt><dd>{t('vis.framesLine', { frames: health.frames ?? '—', states: health.states ?? '—' })}</dd></div>
      {health.video !== null && <div><dt>{t('vis.factVideo')}</dt><dd>{health.video}</dd></div>}
      {health.state !== null && <div><dt>{t('vis.factState')}</dt><dd>{health.state}</dd></div>}
      {health.visionError !== null && <div><dt>{t('vis.factVisionError')}</dt><dd className="vn-warn">{health.visionError}</dd></div>}
    </dl>
    {health.models.length > 0 && <table className="obstacle-table">
      <thead><tr><th>{t('vis.colModel')}</th><th>{t('vis.colN')}</th><th>{t('vis.colGap')}</th><th>{t('vis.colDet')}</th><th>lag_ms</th><th>infer_ms</th><th>{t('vis.colRate')}</th><th>{t('vis.colAge')}</th><th>{t('vis.colResults')}</th></tr></thead>
      <tbody>{health.models.map((m) => <tr key={m.model} className={modelStale(m) ? 'is-near' : undefined}>
        <td><b>{m.model}</b>{m.run === null ? null : <small>{m.run}</small>}</td>
        <td>{m.n ?? '—'}</td>
        <td>{frameGap(health.frames, m) ?? '—'}</td>
        <td>{m.detections ?? '—'}</td>
        <td>{ms(m.lagMs)}</td>
        <td>{ms(m.inferMs)}</td>
        <td>{state.rate[m.model] === undefined ? '—' : state.rate[m.model].toFixed(1)}</td>
        <td>{sec(m.ageS)}</td>
        <td>{m.results ?? '—'}</td>
      </tr>)}</tbody>
    </table>}
    <p className="vn-line vn-dim">{t('vis.summaryOnly')}</p>
    <details className="obstacle-raw">
      <summary>{t('vis.rawHealth')}</summary>
      <pre>{JSON.stringify(health.raw, null, 2)}</pre>
    </details>
  </>;
}

/**
 * **추론 영상 노드.** `taskDeviceId` 는 노드를 붙인 태스크의 장비 — 그 장비에 묶인 포트가 기본이다.
 * `lockSource` 면 포트 고르기를 안 그린다(하드웨어 카드 상세 — 포트는 그 위의 묶음 칸이 정한다).
 */
export function VisionCam({ nodeId, taskDeviceId = null, zoom = false, lockSource = false, compact = false }: {
  nodeId: string;
  taskDeviceId?: string | null;
  zoom?: boolean;
  lockSource?: boolean;
  /** 요약 표를 뺀다 — 장비 여럿을 나란히 보는 화면(전체 카메라, 261002). 고르는 칸과 영상은 그대로다. */
  compact?: boolean;
}) {
  useLang();
  useConnections();
  const choice = useVisionNodeChoice(nodeId);
  const binding = useVisionBinding(taskDeviceId);
  const sources = useVisionSources();
  const replaying = useReplayTarget();
  const firstBase = visionBases()[0] ?? null;
  const autoBase = binding.base ?? (taskDeviceId === null ? firstBase : null);
  const autoWhy = binding.base !== null
    ? t('vis.whyDevice', { device: taskDeviceId ?? '' })
    : taskDeviceId === null ? t('vis.whyFirst') : t('vis.whyNoBinding', { device: taskDeviceId });
  const base = lockSource ? binding.base : (choice.base ?? autoBase);
  useEffect(() => holdVisionSource(base), [base]);

  // **다시보기에서는 영상을 띄우지 않는다** — 지금 영상을 지난 판 자리에 띄우면 그때 본 것으로 읽는다.
  if (replaying !== null) return <p className="vn-line vn-dim">{t('vis.replay')}</p>;

  const state = base === null ? null : (sources[base] ?? null);
  const models = state?.health?.models ?? [];
  const shown = choice.models ?? models.filter(modelLive).map((m) => m.model);
  const framesNow = state?.health?.frames ?? null;
  const minGap = models.filter(modelLive).reduce<number | null>((low, m) => {
    const gap = frameGap(framesNow, m);
    return gap === null ? low : low === null ? gap : Math.min(low, gap);
  }, null);
  const minLag = models.filter(modelLive).reduce<number | null>((low, m) => (m.lagMs === null ? low : low === null ? m.lagMs : Math.min(low, m.lagMs)), null);
  const cells: (string | null)[] = [...shown, ...(choice.raw === true ? [null] : [])];

  return <div className={`detect-cam vision-cam${zoom ? ' detect-cam--zoom' : ''}`}>
    {zoom && !lockSource && <SourcePicker nodeId={nodeId} autoBase={autoBase} autoWhy={autoWhy} />}
    {zoom && base !== null && <ModelPicker nodeId={nodeId} models={models} />}
    {base === null
      ? <p className="vn-line vn-dim">{taskDeviceId === null ? t('vis.noAddressNode') : t('vis.noBindingNode', { device: taskDeviceId })}</p>
      : <>
          {state?.error != null && <p className="vn-line vn-warn">{t('vis.healthFailed', { reason: state.error })}</p>}
          {cells.length === 0
            ? <p className="vn-line vn-dim">{state?.health == null ? t('vis.waitingHealth', { url: base }) : t('vis.noLiveModel', { name: sourceName(base, sources) })}</p>
            : <div className={`vision-grid vision-grid--${Math.min(cells.length, 4)}`}>
                {cells.map((model) => <VisionCell
                  key={model ?? '__raw'}
                  base={base}
                  model={model}
                  summary={model === null ? null : (models.find((m) => m.model === model) ?? null)}
                  rate={model === null ? undefined : state?.rate[model]}
                  zoom={zoom}
                  lagMs={minLag}
                  framesNow={framesNow}
                  gapFrames={minGap}
                  available={model === null
                    ? (state?.health?.frames ?? 0) > 0
                    : models.some((m) => m.model === model)}
                />)}
              </div>}
          <p className="detect-cam__at">
            {sourceName(base, sources)}
            {!zoom && <small className="ai-source__at"> · {t('vis.stillMeta', { sec: VISION_STILL_MS / 1000 })}</small>}
            {zoom && <small className="ai-source__at"> · <code>{base}</code></small>}
          </p>
          {zoom && !compact && state !== null && <SummaryTable state={state} />}
        </>}
  </div>;
}

/**
 * **하드웨어 카드 한 줄.** 묶인 포트가 없으면 아무것도 안 그린다 — 추론 스트림이 없는 장비 카드는 그대로다.
 * 작은 한 장은 결과가 오는 첫 모델의 오버레이다. 실시간은 상세(더블클릭)에서 연다.
 */
export function VisionCardLine({ entityId }: { entityId: string }) {
  useLang();
  const binding = useVisionBinding(entityId);
  const sources = useVisionSources();
  if (binding.base === null) {
    if (binding.how !== 'ambiguous') return null;
    return <span className="hw-link"><em className="hw-dot hw-dot--warn">{t('vis.cardAmbiguous', { n: binding.candidates.length })}</em></span>;
  }
  const state = sources[binding.base] ?? null;
  const live = (state?.health?.models ?? []).filter(modelLive);
  const first = live[0] ?? null;
  return <span className="hw-link hw-vision">
    <em className={`hw-dot ${live.length > 0 ? 'hw-dot--ok' : state?.error != null ? 'hw-dot--bad' : 'hw-dot--unknown'}`}
      title={binding.base}>{t('vis.cardSource', { name: sourceName(binding.base, sources) })}</em>
    {live.map((m) => <em key={m.model} className={`hw-dot ${modelStale(m) ? 'hw-dot--warn' : 'hw-dot--plain'}`}>
      {t('vis.cardModel', { model: m.model, rate: state?.rate[m.model] === undefined ? '—' : state.rate[m.model].toFixed(1), lag: ms(m.lagMs) })}
    </em>)}
    {live.length === 0 && <em className="hw-dot hw-dot--plain">{state?.error != null ? t('vis.cardFailed') : t('vis.cardNoResult')}</em>}
    {first !== null && <Still base={binding.base} model={first.model} className="hw-vision__thumb" />}
  </span>;
}

/** 묶음이 어떻게 정해졌는가 — 한 줄. */
/** 고정 카메라(261002)는 브로커가 아니라 이미지 주소로 맞춘다 — 같은 갈래라도 「브로커 주소」라고 적지 않는다. */
function bindingWhy(binding: VisionBinding, host: string | null, sources: Readonly<Record<string, VisionSourceState>>, camera = false): string {
  switch (binding.how) {
    case 'chosen': return t('vis.bindChosen');
    case 'unbound': return t('vis.bindUnbound');
    case 'same': return t('vis.bindSame', { name: sourceName(binding.base ?? '', sources), base: binding.base ?? '' });
    case 'matched': return t(camera ? 'vis.bindMatchedCamera' : 'vis.bindMatched', { host: host ?? '', name: sourceName(binding.base ?? '', sources) });
    case 'ambiguous': return t(camera ? 'vis.bindAmbiguousCamera' : 'vis.bindAmbiguous', { host: host ?? '', list: binding.candidates.map((b) => sourceName(b, sources)).join(', ') });
    default: return host === null ? t(camera ? 'vis.bindNoHostCamera' : 'vis.bindNoHost') : t(camera ? 'vis.bindNoMatchCamera' : 'vis.bindNoMatch', { host });
  }
}

/**
 * **하드웨어 카드 상세의 추론 스트림 칸.** 포트를 고르고(자동 맞춤이 기본) 그 포트의 실시간 영상을 연다.
 * 전체 카메라 화면(261002)도 이것을 `compact` 로 그린다 — 고름의 저장 키가 같아서(`hw:<장비 id>` · 장비별 포트) 두 화면이
 * 같은 고름을 본다. 한쪽에서 모델을 바꾸면 다른 쪽도 바뀐다.
 */
export function VisionDeviceSection({ entityId, compact = false }: { entityId: string; compact?: boolean }) {
  useLang();
  useConnections();
  const binding = useVisionBinding(entityId);
  const chosen = useVisionBindingChoice(entityId);
  const sources = useVisionSources();
  const host = deviceBrokerHost(entityId);
  const bases = visionBases();
  const missing = chosen !== null && chosen !== VISION_UNBOUND && !bases.includes(chosen);
  return <section className="media-section vision-section">
    <header className="media-section__head">
      <h3>{t('vis.sectionTitle')}</h3>
      <label className="ai-source">
        <span>{t('vis.bindPick')}</span>
        <select value={chosen ?? ''} onChange={(event) => setVisionBinding(entityId, event.target.value === '' ? null : event.target.value)}>
          <option value="">{t('vis.bindAuto')}</option>
          {bases.map((base) => {
            const health = sources[base]?.health ?? null;
            const models = (health?.models ?? []).filter(modelLive).map((m) => m.model);
            return <option key={base} value={base}>
              {`${sourceName(base, sources)} · ${base}${health === null ? '' : ` · ${health.upstreamHosts.join(', ') || '—'}`}${models.length === 0 ? '' : ` · ${models.join(', ')}`}`}
            </option>;
          })}
          {missing && <option value={chosen}>{t('vis.sourceMissing', { url: chosen })}</option>}
          <option value={VISION_UNBOUND}>{t('vis.bindNone')}</option>
        </select>
      </label>
    </header>
    <p className="vn-line vn-dim">{bindingWhy(binding, host, sources, isFixedCamera(entityId))}</p>
    {binding.base !== null && <VisionCam nodeId={`hw:${entityId}`} taskDeviceId={entityId} zoom lockSource compact={compact} />}
  </section>;
}
