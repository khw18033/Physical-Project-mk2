// 이식: web-dashboard/src/views/MetricsView.tsx @ 700ed91 — 대본 재생(260831): 도메인 지표 3종 + 위험 수위 선
/**
 * src/views/MetricsView.tsx
 *
 * VZ-I-04 지표 질의 · VZ-C-03 집약 계층 표기.
 *
 * 이 화면이 존재하는 이유는 하나다 — **지금 보는 값이 요약인지 원본인지가 보여야 한다.**
 *
 * 평시에 올라오는 지표는 이미 구역 요약이다(BE-S-03). 그걸 모르고 보면 "원본을 보고 있다"고
 * 착각하게 되고, 그 착각 위에서 평균을 한 번 더 내면 틀린 숫자가 조용히 만들어진다.
 * 그래서 값 옆에 **계층과 창 크기**를 붙이고, 원본이 필요하면 다른 경로로 가야 한다는 것을
 * 화면이 말한다.
 *
 * 차트 라이브러리를 새로 들이지 않았다 — 필요한 것은 점 몇 개를 잇는 선 하나이고,
 * 그건 인라인 SVG로 충분하다.
 */

import { Rich } from '../../i18n/RichText.tsx';
import { t } from '../../i18n/dict.ts';
import { useEffect, useState } from 'react';
import {
  METRICS_AUTO_REFRESH_MS,
  METRICS_MODE_LABEL_KEY,
  RANGE_OPTIONS,
  BLOCK_REASON_LABEL_KEY,
  aggregationBadge,
  guardedMean,
  heavyQueryNotice,
  playScenario,
  seriesExtent,
  type MetricPoint,
  type MetricsMode,
  type MetricsSeries,
} from '../data/index.ts';
import { getBlockLog } from '../data/index.ts';
import { useEntities, useMetricsQuery, useReaggregationBlocks } from '../data/hooks.ts';
import { useMission } from '../../data/scenario.ts';
import { PendingSource } from '../../shared/PendingSource.tsx';
import { PanelGate } from '../ScenarioGate.tsx';
import { useScenarioCast, useScenarioRender } from '../../shared/renderMode.ts';
import { Explain } from '../../shared/Explain.tsx';

/** 관측 지표를 내는 대상. 구역 요약의 출처다. */
const METRIC_ENTITY = 'edge-node-a';

/**
 * `source` 는 이 지표의 **원천 장비** — scenario 모드에서 그 장비가 대본 cast 에 있을 때만
 * 그래프가 그려진다(자리표시 분기). 도메인 지표 3종(260831)은 관측 지표와 **같은 질의
 * 경로**(/metrics/query · BE-Q-01)로 온다 — 별도 경로를 만들지 않는다.
 */
export const METRICS = [
  { id: 'cpu_pct', labelKey: 'mv.1', unit: '%', source: 'edge-node-a' },
  { id: 'publish_latency_ms', labelKey: 'mv.2', unit: 'ms', source: 'edge-node-a' },
  { id: 'water_level_m', labelKey: 'mv.3', unit: 'm', source: 'sensor-01' },
  { id: 'coverage_pct', labelKey: 'mv.4', unit: '%', source: 'camera-02' },
  { id: 'robot_speed_mps', labelKey: 'mv.5', unit: 'm/s', source: 'robot-01' },
] as const;

export function MetricsView() {
  const [metric, setMetric] = useState<string>(METRICS[0].id);
  const [mode, setMode] = useState<MetricsMode>('summary');
  const [rangeMin, setRangeMin] = useState<number>(RANGE_OPTIONS[0].min);

  // 시나리오 진입 시 **기본 지표를 대본 지표로 자동 전환** (260831 요구 2).
  // 기본 cpu_pct 의 원천(edge-node-a)은 어느 대본 cast 에도 없어, 그대로 두면
  // 시나리오로 들어가도 탭④ 첫 화면이 자리표시다. 축에서 유도한다:
  // 2편(coverage) → 커버리지, 3편(water) → 수위, 1편(speed) → 로봇 속도.
  const scenarioRender = useScenarioRender();
  const scenarioCast = useScenarioCast();
  useEffect(() => {
    if (scenarioCast === null || scenarioRender === null) return;
    const preferred = scenarioRender.axes.has('coverage')
      ? 'coverage_pct'
      : scenarioRender.axes.has('water')
        ? 'water_level_m'
        : scenarioRender.axes.has('speed')
          ? 'robot_speed_mps'
          : null;
    if (preferred !== null) setMetric(preferred);
  }, [scenarioRender?.missionId, scenarioCast === null]);

  const { series, loading, error, reload } = useMetricsQuery({
    entity: METRIC_ENTITY,
    metric,
    mode,
    rangeMin,
  });

  const unit = METRICS.find((m) => m.id === metric)?.unit ?? '';
  const source = METRICS.find((m) => m.id === metric)?.source ?? METRIC_ENTITY;
  const notice = heavyQueryNotice(mode, rangeMin);
  // 위험 수위 선 — 대본 params 에서 읽는다 (3편 danger_level_m · 지어내지 않는다).
  const mission = useMission();
  const dangerLevel = metric === 'water_level_m'
    ? ((mission.current.params.danger_level_m as number | undefined) ?? null)
    : null;

  return (
    <main className="board">
      <header className="board__head">
        <div>
          <h1 className="board__title">{t('mv.6')}</h1>
          <Explain id="met-1" className="board__sub">
            <Rich id="mv.sub" />
          </Explain>
        </div>
        <div className="board__meta">
          <span>VZ-I-04 · VZ-C-03</span>
        </div>
      </header>

      {/* 관측 지표(observability)는 어느 대본도 몰지 않는다 — 시나리오 모드에서는 패널째 접힌다
          (260901 층 2). 8/31까지는 안쪽 칸만 「해당 없음」이고 제목·표기 각주는 남아 있었다. */}
      <PanelGate id="metrics-push"><LiveSummaryCard /></PanelGate>

      <PanelGate id="metrics-query">
      <section className="panel panel--wide">
        <header className="panel__head">
          <h2 className="panel__title">
            {t(METRICS.find((m) => m.id === metric)?.labelKey ?? '')} · {METRIC_ENTITY}
          </h2>
          <span className="panel__tag">VZ-I-04</span>
        </header>

        <div className="qbar">
          <span className="qbar__group">
            {METRICS.map((m) => {
              // 대본과 무관한 지표(원천이 cast 밖)는 흐리게 — 누르면 자리표시가 뜰 자리다.
              const dimmed = scenarioCast !== null && !scenarioCast.has(m.source);
              return (
                <button
                  key={m.id}
                  type="button"
                  className={'btn btn--small' + (metric === m.id ? ' btn--on' : '') + (dimmed ? ' btn--dim' : '')}
                  title={dimmed ? t('mv.notDriven', { source: m.source }) : undefined}
                  onClick={() => setMetric(m.id)}
                >
                  {t(m.labelKey)}
                </button>
              );
            })}
          </span>

          <span className="qbar__group">
            {RANGE_OPTIONS.map((r) => (
              <button
                key={r.min}
                type="button"
                className={'btn btn--small' + (rangeMin === r.min ? ' btn--on' : '')}
                onClick={() => setRangeMin(r.min)}
              >
                {t(r.labelKey)}
              </button>
            ))}
          </span>

          {/* **원본 보기 전환.** 누르면 다른 경로로 다시 질의한다. */}
          <span className="qbar__group qbar__group--mode">
            {(['summary', 'raw'] as MetricsMode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={'btn btn--small' + (mode === m ? ' btn--on' : '') + (m === 'raw' ? ' btn--raw' : '')}
                onClick={() => setMode(m)}
              >
                {m === 'raw' ? t('mv.9') : t('mv.10')}
              </button>
            ))}
            <button type="button" className="btn btn--tiny" onClick={reload}>
              {t('mv.reload')}
            </button>
          </span>
        </div>

        {notice !== null && <p className="notice notice--warn">{notice}</p>}

        {/* **가져오는 중임이 반드시 보여야 한다** — 원본은 엣지 중계라 0.5~1초 걸린다. */}
        {loading && (
          <p className="notice notice--busy">
            <span className="spinner" aria-hidden="true" />
            {mode === 'raw'
              ? t('mv.11')
              : t('mv.12')}
          </p>
        )}

        {error !== null && <p className="notice notice--warn">{error}</p>}

        <PendingSource id="metrics-query" minHeight={260} entity={source} axis={source === METRIC_ENTITY ? 'observability' : undefined}>
          {series !== null && (
            <>
              <SeriesChart series={series} unit={unit} loading={loading} dangerLevel={dangerLevel} />
              <SeriesMeta series={series} unit={unit} />
            </>
          )}

          {series === null && !loading && error === null && <p className="muted">{t('mv.13')}</p>}
        </PendingSource>

        <Explain id="met-2" className="note">
          <Rich id="mv.federationNote" vars={{ sec: METRICS_AUTO_REFRESH_MS / 1000 }} />
        </Explain>
      </section>
      </PanelGate>

      <BlindspotAges />

      <ReaggregationPanel />
    </main>
  );
}

/**
 * 사각지대별 「마지막 탐지 이후 경과」 (260831 · 2편 탭④ 요구 — 8/31 점검에서 채움).
 *
 * 커버리지 % 시계열과 같은 원천(coverage 채널)의 **현재 경과 판독**이다 — 지금이
 * 대본 시각으로 언제이고, 각 칸이 마지막으로 탐지된 지 얼마나 됐는지. 재탐색 임계
 * (600초)를 넘은 칸은 「경과 초과」로 갈린다. 대본이 커버리지를 몰 때만 그린다 —
 * 평소의 자리(A · 백엔드 DT-05 시의성)는 위 조회 자리표시가 이미 말하고 있다.
 */
function BlindspotAges() {
  const mission = useMission();
  const entities = useEntities();
  const scenarioActive = mission.current.map !== null;
  const camera = mission.current.map?.camera.entity ?? null;
  const coverage = camera !== null
    ? ((entities.get(camera)?.coverage?.payload ?? null) as {
        rescan_threshold_sec?: number | null;
        cells?: Array<{ cell: string; last_scan_at_sec: number | null }>;
      } | null)
    : null;

  if (!scenarioActive || coverage?.cells === undefined || coverage.cells.length === 0) return null;

  const threshold = coverage.rescan_threshold_sec ?? null;
  const nowSec = mission.headSec; // 대본 시각 — 재생 머리. 트윈 시의성(DT-05)의 축과 같다.

  return (
    <section className="panel panel--wide">
      <header className="panel__head">
        <h2 className="panel__title">{t('mv.agesTitle', { id: mission.current.missionId })}</h2>
        <span className="panel__tag">{t('mv.15')}</span>
      </header>
      <table className="agestable">
        <thead>
          <tr><th>{t('mv.colCell')}</th><th>{t('mv.colLastScan')}</th><th>{t('mv.colAge', { sec: Math.round(nowSec) })}</th><th>{t('mv.colVerdict')}</th></tr>
        </thead>
        <tbody>
          {coverage.cells.map((cell) => {
            const age = cell.last_scan_at_sec === null ? null : Math.max(0, Math.round(nowSec - cell.last_scan_at_sec));
            const over = age !== null && threshold !== null && age > threshold;
            return (
              <tr key={cell.cell} className={over ? 'agestable__row--over' : undefined}>
                <td><code>{cell.cell}</code></td>
                <td>{cell.last_scan_at_sec === null ? t('mv.neverScanned') : `T+${cell.last_scan_at_sec}s`}</td>
                <td>{age === null ? '—' : `${age}s`}</td>
                <td>{cell.last_scan_at_sec === null
                  ? t('mv.beforeScan')
                  : over ? t('mv.overThreshold', { sec: threshold }) : t('mv.fresh')}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <Explain id="met-3" className="note note--dim">
        {t('mv.agesNote', { sec: threshold ?? 600 })}
      </Explain>
    </section>
  );
}

/**
 * 푸시로 들어오는 평시 지표. **여기 붙은 표기가 이번 수정의 요점이다** —
 * 이 값은 원본이 아니라 15초 창의 구역 요약이다.
 */
function LiveSummaryCard() {
  const entities = useEntities();
  const slot = entities.get(METRIC_ENTITY)?.metrics ?? null;

  if (slot === null) {
    return (
      <section className="panel">
        <p className="muted">
          {t('mv.noEnvelopeYet', { sec: METRICS_AUTO_REFRESH_MS / 1000 })}
        </p>
      </section>
    );
  }

  const payload = slot.payload as {
    cpu_pct?: { value: number };
    publish_latency_ms?: { value: number };
    sample_count?: number;
  };
  // 표기 해석은 데이터 레이어가 이미 끝냈다. 컴포넌트는 표시용 형태만 받는다.
  const badge = aggregationBadge(slot.aggregation);

  return (
    <section className="panel panel--wide">
      <header className="panel__head">
        <h2 className="panel__title">{t('mv.pushTitle', { entity: METRIC_ENTITY })}</h2>
        <span className="panel__tag">VZ-C-03</span>
      </header>

      {/* 관측 지표는 어느 대본도 몰지 않는다 — 평시 ObservabilityEmitter 의 몫 (260831 요구 2). */}
      <PendingSource id="metrics-push" minHeight={110} entity={METRIC_ENTITY} axis="observability">
      <div className="statrow">
        <div className="stat">
          <span className="stat__value">{payload.cpu_pct?.value.toFixed(1) ?? '—'}</span>
          <span className="stat__unit">%</span>
          <span className="stat__label">{t('mv.1')}</span>
          <span className={'aggbadge aggbadge--' + badge.state} title={badge.title}>
            {badge.short}
          </span>
        </div>
        <div className="stat">
          <span className="stat__value">{payload.publish_latency_ms?.value.toFixed(1) ?? '—'}</span>
          <span className="stat__unit">ms</span>
          <span className="stat__label">{t('mv.2')}</span>
          <span className={'aggbadge aggbadge--' + badge.state} title={badge.title}>
            {badge.short}
          </span>
        </div>
      </div>
      </PendingSource>

      {/* 세 갈래로 갈라 쓴다. 'unknown'을 원본 쪽에 묶으면 화면이 "원본 측정값이다"라고
          거짓을 말하게 된다 — 실은 원본인지 아닌지 모르는 상태다. */}
      <p className={'note' + (badge.state === 'unknown' ? ' note--unknown' : '')}>
        {badge.state === 'aggregated' && (
          <>
            <Rich id="mv.aggNote" />
            {payload.sample_count !== undefined && <> {t('mv.sampleCount', { n: payload.sample_count })}</>}
          </>
        )}
        {badge.state === 'raw' && <>{t('mv.17')}</>}
        {badge.state === 'unknown' && (
          <>
            <Rich id="mv.unknownNote" />
          </>
        )}
      </p>
    </section>
  );
}

/** 인라인 SVG 선 하나. 라이브러리를 들일 만한 그림이 아니다. */
function SeriesChart({ series, unit, loading, dangerLevel = null }: { series: MetricsSeries; unit: string; loading: boolean; dangerLevel?: number | null }) {
  const W = 900;
  const H = 200;
  const PAD = 8;

  const points: MetricPoint[] = series.points;
  const extent = seriesExtent(points);
  // 위험 수위 선(260831 · 3편)이 화면 밖으로 나가지 않게 축에 포함한다.
  const min = dangerLevel === null ? extent.min : Math.min(extent.min, dangerLevel);
  const max = dangerLevel === null ? extent.max : Math.max(extent.max, dangerLevel);

  const yOf = (value: number) => H - PAD - ((value - min) / Math.max(1e-9, max - min)) * (H - PAD * 2);
  const path = points
    .map((p, i) => {
      const x = PAD + (i / Math.max(1, points.length - 1)) * (W - PAD * 2);
      return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + yOf(p.value).toFixed(1);
    })
    .join(' ');

  return (
    <div className={'chart' + (loading ? ' chart--loading' : '')}>
      <div className="chart__head">
        <span className={'aggbadge aggbadge--' + series.badge.state} title={series.badge.title}>
          {series.badge.short}
        </span>
        <span className="chart__scale">
          {t('mv.scale', { min: min.toFixed(1), max: max.toFixed(1), unit, n: points.length, interval: series.pointIntervalSec })}
          {dangerLevel !== null && <>{t('mv.dangerLevel', { level: dangerLevel, unit })}</>}
        </span>
      </div>
      <svg className="chart__svg" viewBox={'0 0 ' + W + ' ' + H} preserveAspectRatio="none" role="img">
        {/* 위험 수위 선 — 상승 30초·유지 10초·하락 3분 구간이 이 선 기준으로 읽힌다 (3편). */}
        {dangerLevel !== null && (
          <line className="chart__danger" x1={PAD} x2={W - PAD} y1={yOf(dangerLevel)} y2={yOf(dangerLevel)} />
        )}
        <path className={'chart__line chart__line--' + series.badge.state} d={path} />
      </svg>
    </div>
  );
}

/** 이 시계열이 **어디서 어떻게** 왔는지. 요약과 원본을 가르는 근거를 화면에 남긴다. */
function SeriesMeta({ series, unit }: { series: MetricsSeries; unit: string }) {
  const extent = seriesExtent(series.points);
  return (
    <>
      <dl className="kv kv--wide">
        <dt>{t('mv.19')}</dt>
        <dd>{series.via}</dd>
        <dt>{t('mv.20')}</dt>
        <dd>
          <strong>{t(METRICS_MODE_LABEL_KEY[series.mode])}</strong>
          {/* 원본은 계층·창이 없으므로 뱃지를 덧붙이면 같은 말이 두 번 나온다. */}
          {series.badge.state === 'aggregated' && <>{t('mv.aggLayer', { layer: series.badge.short.replace(t('mv.21'), '') })}</>}
          {series.badge.state === 'unknown' && <> · <strong>{t('mv.22')}</strong></>}
        </dd>
        <dt>{t('mv.23')}</dt>
        <dd>
          {series.relayMs === 0 ? (
            <span className="muted">{t('mv.24')}</span>
          ) : (
            <strong>{series.relayMs} ms</strong>
          )}
        </dd>
        <dt>{t('mv.25')}</dt>
        <dd>
          {extent.last === null ? '—' : extent.last.toFixed(1) + ' ' + unit}
        </dd>
      </dl>

      {series.heavy && series.heavyReason !== null && (
        <p className="notice notice--warn">{t('mv.heavyQuery', { reason: series.heavyReason })}</p>
      )}
    </>
  );
}

/**
 * VZ-C-03 검증 — 집약값에 평균을 적용해 본다.
 *
 * **경고가 아니라 차단이다.** 누르면 계산이 수행되지 않고, 그 사실이 콘솔이 아니라
 * 화면에 남는다. 재집약 오류는 화면상으로 드러나지 않아 발견이 늦으므로,
 * 차단됐다는 것 자체가 보여야 검증이 성립한다.
 */
function ReaggregationPanel() {
  const entities = useEntities();
  const blocks = useReaggregationBlocks();
  const [lastResult, setLastResult] = useState<string | null>(null);

  const slot = entities.get(METRIC_ENTITY)?.metrics ?? null;

  const probe = () => {
    if (slot === null) {
      setLastResult(t('mv.26'));
      return;
    }
    const payload = slot.payload as { cpu_pct?: { value: number } };
    const value = payload.cpu_pct?.value ?? 0;
    const result = guardedMean(
      [{ value, aggregation: slot.aggregation }],
      METRIC_ENTITY + '/metrics.cpu_pct',
    );
    // 차단 사유는 데이터 레이어가 판정한다. 화면은 방금 남은 이력에서 읽어 표시만 한다.
    const reason = getBlockLog()[0]?.reason ?? null;
    setLastResult(
      result === null
        ? t('mv.blocked', { reason: reason === null ? t('mv.27') : t(BLOCK_REASON_LABEL_KEY[reason]) })
        : t('mv.allowed', { mean: result.toFixed(2) }),
    );
  };

  return (
    <section className="panel panel--wide">
      <header className="panel__head">
        <h2 className="panel__title">{t('mv.28')}</h2>
        <span className="panel__tag">VZ-C-03</span>
      </header>

      <button type="button" className="btn btn--probe" onClick={probe}>
        {t('mv.tryMean')}
      </button>

      {lastResult !== null && (
        <p className={'notice' + (lastResult.includes(t('mv.29')) ? ' notice--blocked' : '')}>{lastResult}</p>
      )}

      {blocks.length > 0 && (
        <>
          <h3 className="devpanel__title">{t('mv.blockLog', { n: blocks.length })}</h3>
          <ul className="blocklist">
            {/* 두 사유가 눈으로 갈려야 한다 — 통합 때 대응이 다르다.
                'aggregated'는 원본 질의로 우회하면 되고, 'unknown'은 계약을 맞춰야 한다. */}
            {blocks.slice(0, 5).map((b, i) => (
              <li key={i} className={'blocklist__item blocklist__item--' + b.reason}>
                <span className={'blockreason blockreason--' + b.reason}>{t(BLOCK_REASON_LABEL_KEY[b.reason])}</span>
                <code>{b.operation}</code> · {b.context}
                <div className="muted">{b.message}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="devpanel devpanel--inline">
        <h3 className="devpanel__title">{t('mv.30')}</h3>
        <div className="devpanel__row">
          <button type="button" className="btn btn--small" onClick={() => playScenario('agg-unlabeled')}>
            {t('mv.btn.noKind')}
          </button>
          <button type="button" className="btn btn--small" onClick={() => playScenario('agg-odd-string')}>
            {t('mv.btn.oddString')}
          </button>
          <button type="button" className="btn btn--small" onClick={() => playScenario('agg-normal')}>
            {t('mv.btn.normal')}
          </button>
        </div>
        <Explain id="met-4" className="note note--dim">
          <Rich id="mv.devNote" />
        </Explain>
      </div>

      <Explain id="met-5" className="note">
        <Rich id="mv.guardNote" />
      </Explain>
    </section>
  );
}
