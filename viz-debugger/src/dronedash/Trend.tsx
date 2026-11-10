/**
 * src/dronedash/Trend.tsx (261110 신설 · 261111 그래프 타일로 — 실시간 상태 그래프)
 *
 * **상태 하나 = 그래프 타일 하나.** 타일 위에 이름과 **지금 상태 글자**, 그 아래에 최근 2분 그래프다.
 * 글자 타일 줄과 그래프 묶음을 따로 두지 않는다(261111 지적 — 같은 것을 두 번 읽게 했다).
 *
 *   숫자(배터리 · 고도 · 수신 간격 …)   선 그래프 — 끊긴 구간은 회색으로 비우고 잇지 않는다, 최신 점은 맥동
 *   범주(연결 · 링크 · 모드 · 무장 …)    색 띠 — 값이 바뀐 자리가 띠의 경계다, 수신 없음은 회색
 *
 * 값은 `shared/metricHistory.ts` 에서 온다. 쓰는 곳은 카드 상세(더블클릭)와 전체 장치 확인뿐이다 — 하드웨어 목록의
 * 카드 한 줄은 글자 타일 그대로다(261111 지시).
 *
 * 그래프 판은 가로로 늘어나는 판이라(`preserveAspectRatio="none"`) 글자를 판 안에 두지 않는다 — 늘어나면 글자도
 * 찌그러진다. 최신 점도 판 밖(HTML)에 놓는다.
 */

import { type ReactNode } from 'react';
import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { deltaOver, stateSpans, trendRuns, type MetricPoint, type StatePoint } from '../shared/metricHistory.ts';

export const FLOW_WINDOW_MS = 120_000;
export const DELTA_SPAN_MS = 60_000;
/** 다시 그리는 주기. 2분 창에서 한 번에 폭의 0.2% 남짓 밀린다 — 끊기지 않고 흐르는 것처럼 보이는 정도. */
export const TREND_TICK_MS = 250;

type GraphLevel = 'good' | 'warn' | 'bad' | 'unknown';
const MARK: Record<GraphLevel, string> = { good: '✓', warn: '!', bad: '✕', unknown: '?' };

/** 「60초 ▲ 0.8 m」 — 숫자 타일의 툴팁. 모르면 모른다고. */
export function deltaWords(points: readonly MetricPoint[], now: number, digits: number, unit: string): string {
  const delta = deltaOver(points, now, DELTA_SPAN_MS);
  if (delta === null) return t('trend.deltaNone');
  if (Math.abs(delta) < 10 ** -digits / 2) return t('trend.deltaSame');
  return t('trend.delta', { arrow: delta > 0 ? '▲' : '▼', v: Math.abs(delta).toFixed(digits), unit });
}

export type LineGraph = {
  kind: 'line';
  points: readonly MetricPoint[];
  /** 세로축을 이보다 좁히지 않는다 — 센서 잡음이 산처럼 보이면 안 된다. */
  minSpan?: number;
  /** 정수로만 오는 값(배터리 %)은 계단으로. */
  stair?: boolean;
  /** 경고선. 축 범위에 넣는다 — 얼마나 가까운지가 보이게. */
  threshold?: number;
};

export type LaneGraph = {
  kind: 'lane';
  points: readonly StatePoint[];
  /** 띠 조각의 색 — 그 값이 좋은가 나쁜가. 없으면 값마다 차례로 중립색. */
  toneOf?(code: string): GraphLevel;
  /** 띠 조각의 툴팁 글자. */
  labelOf(code: string): string;
};

const GW = 100;
const GH = 60;
/**
 * 선이 쓰는 높이 — 판의 위 40% 는 지금 상태 글자 자리다(글자가 그래프 위에 뜬다). 선은 그 아래에서만 오르내려
 * 글자를 가리지 않는다.
 */
const PLOT_TOP = GH * 0.4;
const PLOT_BOTTOM = GH - 2;

function range(values: number[], minSpan: number, extra: number[]): [number, number] {
  const all = [...values, ...extra];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
  }
  const pad = (hi - lo) * 0.12;
  return [lo - pad, hi + pad];
}

/** 판 공통 — 창 길이 · 세로 표시선(조작 기록의 명령 시각) · 살아 있는 판인가(최신 점 맥동). */
type Frame = { now: number; windowMs: number; marks: readonly number[]; live: boolean };

function Marks({ frame }: { frame: Frame }) {
  return <>{frame.marks.filter((ms) => ms >= frame.now - frame.windowMs && ms <= frame.now).map((ms, i) =>
    <span key={i} className="graph-mark" style={{ left: `${((ms - (frame.now - frame.windowMs)) / frame.windowMs) * 100}%` }} />)}</>;
}

function LinePlot({ graph, frame }: { graph: LineGraph; frame: Frame }) {
  useLang();
  const { now, windowMs } = frame;
  const { runs, gaps, fresh, last } = trendRuns(graph.points, now, windowMs);
  const values = runs.flat().map((p) => p.v);
  if (values.length === 0) return <span className="graph-empty">{t('dash.noData')}</span>;
  const [lo, hi] = range(values, graph.minSpan ?? 1, graph.threshold === undefined ? [] : [graph.threshold]);
  const x = (ms: number) => Math.max(0, ((ms - (now - windowMs)) / windowMs) * GW);
  const y = (v: number) => PLOT_BOTTOM - ((v - lo) / (hi - lo)) * (PLOT_BOTTOM - PLOT_TOP);
  const pathOf = (run: readonly MetricPoint[]) => run.map((p, i) =>
    (i === 0 ? `M${x(p.atMs).toFixed(2)},${y(p.v).toFixed(2)}`
      : `${graph.stair ? `L${x(p.atMs).toFixed(2)},${y(run[i - 1]!.v).toFixed(2)}` : ''}L${x(p.atMs).toFixed(2)},${y(p.v).toFixed(2)}`)).join('');
  return <>
    <svg viewBox={`0 0 ${GW} ${GH}`} preserveAspectRatio="none" aria-hidden>
      {gaps.map(([a, b], i) => <rect key={i} className="trend-gap" x={x(a)} y={0} width={Math.max(0, x(b) - x(a))} height={GH} />)}
      {graph.threshold !== undefined && <line className="trend-threshold" x1={0} x2={GW} y1={y(graph.threshold)} y2={y(graph.threshold)} vectorEffect="non-scaling-stroke" />}
      {runs.map((run, i) => {
        const d = pathOf(run);
        return <g key={i}>
          <path className="trend-area" d={`${d}L${x(run.at(-1)!.atMs).toFixed(2)},${GH}L${x(run[0]!.atMs).toFixed(2)},${GH}Z`} />
          <path className="trend-line" d={d} vectorEffect="non-scaling-stroke" />
        </g>;
      })}
    </svg>
    <Marks frame={frame} />
    {frame.live && fresh && last !== null && <span className="graph-dot" style={{ left: `${x(last.atMs)}%`, top: `${(y(last.v) / GH) * 100}%` }} />}
  </>;
}

function LanePlot({ graph, frame }: { graph: LaneGraph; frame: Frame }) {
  useLang();
  const { now, windowMs } = frame;
  const spans = stateSpans(graph.points, now, windowMs);
  if (spans.length === 0) return <span className="graph-empty">{t('dash.noData')}</span>;
  const order = new Map<string, number>();
  for (const span of spans) if (span.code !== null && !order.has(span.code)) order.set(span.code, order.size % 4);
  return <div className="graph-lane">
    {spans.map((span) => {
      const left = ((span.from - (now - windowMs)) / windowMs) * 100;
      const width = ((span.to - span.from) / windowMs) * 100;
      const tone = span.code === null ? 'none' : graph.toneOf ? graph.toneOf(span.code) : `n${order.get(span.code)}`;
      return <span key={`${span.from}-${span.code ?? ''}`} className={`graph-lane__seg graph-lane__seg--${tone}`}
        style={{ left: `${left}%`, width: `${width}%` }} title={span.code === null ? t('trend.noSignal') : graph.labelOf(span.code)} />;
    })}
    <Marks frame={frame} />
  </div>;
}

/**
 * 그래프 칸 (261111 두 번째 — 글상자 없이). **그래프가 칸 전체**이고 지금 상태 글자가 그 위쪽에 떠 있다 — 지금 값과
 * 지나온 변화를 한눈에. 글자 색과 표시(✓ ! ✕ ?)가 지금 상태이고, 나쁠 때는 판 바탕도 붉어진다.
 */
export function GraphStat({ level, label, value, graph, now, title, windowMs = FLOW_WINDOW_MS, marks = [], live = true }: {
  level: GraphLevel; label: string; value: ReactNode; graph: LineGraph | LaneGraph; now: number; title?: string;
  /** 창 길이 — 기본은 최근 2분. 조작 기록은 판 전체(시작 ~ 끝)를 준다. */
  windowMs?: number;
  /** 세로 표시선 시각들 — 조작 기록의 명령. */
  marks?: readonly number[];
  /** 지금 흐르는 판인가. 아니면(기록) 최신 점이 맥동하지 않는다. */
  live?: boolean;
}) {
  const frame: Frame = { now, windowMs, marks, live };
  return <figure className={`graph-stat graph-stat--${level} graph-stat--${graph.kind}`} title={title}>
    {graph.kind === 'line' ? <LinePlot graph={graph} frame={frame} /> : <LanePlot graph={graph} frame={frame} />}
    <figcaption className="graph-stat__head">
      <span className="graph-stat__label">{label}</span>
      <b className="graph-stat__value"><i aria-hidden>{MARK[level]}</i>{value}</b>
    </figcaption>
  </figure>;
}

/** 그래프 타일 줄 + 공통 시간축 한 줄(−120 s … 지금). `compact` 는 전체 장치 확인 칸. */
export function GraphGrid({ compact = false, axis, children }: { compact?: boolean; axis?: readonly [string, string]; children: ReactNode }) {
  useLang();
  const [from, to] = axis ?? [t('trend.ago', { s: FLOW_WINDOW_MS / 1000 }), t('trend.now')];
  return <div className="graph-grid-wrap">
    <div className={`graph-grid${compact ? ' graph-grid--compact' : ''}`}>{children}</div>
    <div className="graph-axis" aria-hidden><span>{from}</span><span>{to}</span></div>
  </div>;
}

/**
 * 전체 장치 확인 칸의 머리 (261111).
 *   [글자 | 그래프]  상태를 글자 타일로 볼지 그래프 타일로 볼지 — 둘을 함께 띄우지 않는다
 *   [흐름 | 계기]    상태만 볼지, 상태 아래에 지도 · 자세계 · 나침반까지 볼지
 */
export function CellToggles({ graph, onGraph, flow, onFlow }: {
  graph: boolean; onGraph(graph: boolean): void; flow: boolean; onFlow(flow: boolean): void;
}) {
  useLang();
  return <div className="trend-toggles">
    <div className="trend-toggle" role="group" aria-label={t('trend.viewAs')}>
      <button type="button" aria-pressed={!graph} onClick={() => onGraph(false)}>{t('trend.text')}</button>
      <button type="button" aria-pressed={graph} onClick={() => onGraph(true)}>{t('trend.graph')}</button>
    </div>
    <div className="trend-toggle" role="group" aria-label={t('trend.body')}>
      <button type="button" aria-pressed={flow} onClick={() => onFlow(true)}>{t('trend.flow')}</button>
      <button type="button" aria-pressed={!flow} onClick={() => onFlow(false)}>{t('trend.instruments')}</button>
    </div>
  </div>;
}
