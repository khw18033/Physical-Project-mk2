/**
 * src/physical/GroundDash.tsx (261110 신설 — 드론이 아닌 장비(Go1 등)의 상태판)
 *
 * **드론 상태판과 같은 모양으로.** 드론은 상태 줄(칩) · 계기 · 패널로 한눈에 읽는데, Go1 은 상세를 열어도 이름 · 값 표가
 * 전부라 같은 화면에서 둘을 나란히 놓으면 읽는 법이 갈렸다. 그래서 같은 부품(`Chip` · `Panel` · `Row` · `Compass` —
 * `dronedash/DroneDash.tsx`)으로 그린다.
 *
 * 세 자리에 쓴다.
 *   GroundDashLine   하드웨어 카드 한 줄 — 핵심 지표 글자 타일 넷(연결 · 로봇 링크 · 배터리 · 마지막 수신). 그래프 없음
 *   GroundDash       카드 상세(더블클릭)의 상태 탭 — 그래프 타일(261111) · 방위 · 위치/동작 · 장비
 *   GroundDash compact  전체 장치 확인의 장치 상태 칸 — [글자 | 그래프] · [흐름 | 계기]
 *
 * ## 값의 출처는 `DeviceFacts` 와 같다 — 지어내지 않는다
 *
 * ① MQTT 장비 상태(`deviceState.ts`, Go1 모양의 고정 칸)가 알맹이를 채웠으면 그것을, ② 아니면 장비가 보고한 줄
 * (`deviceTelemetry.ts`)을 그린다(`mqttFilled` — 카드와 상세가 같은 판정). 안 온 값은 칩을 안 세우거나 「—」다.
 * 낡은 값은 낡았다고 적는다 — 칩을 회색(unknown)으로 두고 「마지막 수신」을 붙인다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { hardwareTarget } from './encode.ts';
import { isStale, STALE_AFTER_MS, useDeviceStates, type DeviceState } from './deviceState.ts';
import { useRobotSession } from './robotSession.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';
import { isTelemetryStale, TELEMETRY_STALE_MS, useDeviceTelemetry, type DeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { mqttFilled, sdkWords, telemetryValue } from './DeviceFacts.tsx';
import { Compass, Panel, Row, Stat, StatGrid, type Level } from '../dronedash/DroneDash.tsx';
import { useTick } from '../sar/useTick.ts';
import { RobotModeRows, useRobotModes } from './RobotModeRows.tsx';
import { useState } from 'react';
import { AGE_KEY, metricSeries, rowKey, stateSeries, type MetricPoint } from '../shared/metricHistory.ts';
import { CellToggles, GraphGrid, GraphStat, TREND_TICK_MS, deltaWords } from '../dronedash/Trend.tsx';
import '../dronedash/dronedash.css';

type Source =
  | { kind: 'mqtt'; device: DeviceState }
  | { kind: 'report'; report: DeviceTelemetry | null; lastSeenMs: number }
  | { kind: 'none' };

/** 어느 원천으로 그릴지 — `HardwareLink` · `DeviceFacts` 와 같은 갈래. */
function useGroundSource(entityId: string): Source {
  const devices = useDeviceStates();
  const reports = useDeviceTelemetry();
  useConnectedDevices();
  const device = devices[hardwareTarget(entityId)] ?? null;
  const report = reports[entityId] ?? null;
  const viaState = connectedDevice(entityId);
  if (!mqttFilled(device) && (viaState !== null || report !== null)) {
    return { kind: 'report', report, lastSeenMs: viaState?.lastSeenMs ?? report?.receivedAtMs ?? Date.now() };
  }
  if (device === null) return { kind: 'none' };
  return { kind: 'mqtt', device };
}

/**
 * 그래프 이력의 장비 id — 받은 길의 id 다. MQTT 고정 칸은 하드웨어 id(`go1-001`), 보고 줄은 화면 id 그대로
 * (`deviceState.ts` · `deviceTelemetry.ts` 가 각자 그 id 로 받는다).
 */
function historyIdOf(entityId: string, source: Source): string {
  return source.kind === 'mqtt' ? source.device.entityId : entityId;
}

/** 보고 줄 가운데 숫자 선으로 그릴 것 — 줄 이름(키) → 이력 지표. 나머지 줄은 값 띠로 그린다. */
const ROW_LINE: Record<string, { key: string; minSpan: number; stair?: boolean }> = {
  'dt.battery': { key: 'battery.remaining_pct', minSpan: 5, stair: true },
};

/** 배터리 이력 — Go1 모양(`battery_pct`)이 있으면 그것, 아니면 보고 줄 모양. */
function batterySeries(historyId: string): readonly MetricPoint[] {
  const go1 = metricSeries(historyId, 'battery_pct');
  return go1.length > 0 ? go1 : metricSeries(historyId, 'battery.remaining_pct');
}

const ago = (ms: number) => Math.max(0, Math.round((Date.now() - ms) / 1000));

/** Go1 배터리 경고선 — 상태 타일이 빨강이 되는 값(`batteryLevel`)과 같다. */
const GO1_BATTERY_LOW_PCT = 20;

function batteryLevel(pct: number): Level {
  return pct < GO1_BATTERY_LOW_PCT ? 'bad' : pct < 40 ? 'warn' : 'good';
}

function okLevel(ok: boolean | null): Level {
  return ok === true ? 'good' : ok === false ? 'bad' : 'unknown';
}

function healthLevel(health: string | null): Level {
  return health === null ? 'unknown' : health === 'ok' ? 'good' : health === 'degraded' ? 'warn' : 'bad';
}

/** 보고 줄의 값 띠 글자 — 값 낱말 키면 풀고, 장비가 보낸 규약 문자열이면 그대로. */
const rowWords = (code: string) => (code.startsWith('dt.') ? t(code) : code);

type Size = 'full' | 'compact' | 'card';

/**
 * 상태 줄 — 드론 상태판의 `StatusBar` 와 같은 **글자 타일**(261110 A안). `card` 는 하드웨어 카드 한 줄이라 핵심 넷만
 * (연결 · 로봇 링크 · 배터리 · 마지막 수신), `compact` 는 전체 장치 확인 칸의 「글자」 보기. 카드 상세는 그래프 타일이다
 * (`GroundStatusGraphs`).
 */
function GroundStatusBar({ source, size }: { source: Source; size: Size }) {
  useLang();
  const session = useRobotSession();
  const card = size === 'card';
  if (source.kind === 'none') {
    return <StatGrid size={size}>
      <Stat level="unknown" label={t('df.2')} value={session.connection.state === 'open' ? t('hl.1') : t('hl.2')} />
    </StatGrid>;
  }
  if (source.kind === 'report') {
    const stale = source.report !== null && isTelemetryStale(source.report);
    // 카드 몫(`onCard`)만 타일로 — 어느 줄이 카드 몫인지는 줄이 들고 온다(`stateRows.ts`).
    const rows = (source.report?.rows ?? []).filter((row) => row.onCard === true);
    return <StatGrid size={size}>
      <Stat level={stale ? 'unknown' : 'good'} label={t('df.2')} value={t('hl.connected')} />
      {rows.map((row, index) => <Stat key={`${row.labelKey ?? row.rawLabel ?? ''}-${index}`} level={stale ? 'unknown' : 'good'}
        label={row.labelKey === null ? (row.rawLabel ?? '') : t(row.labelKey)} value={telemetryValue(row)} />)}
      <Stat level={stale ? 'bad' : 'good'} label={t('df.lastSeen')} value={`${ago(source.lastSeenMs)} s`} />
    </StatGrid>;
  }
  const device = source.device;
  const stale = isStale(device);
  // 링크가 성하지 않으면 값이 멈춘 채로 계속 온다 — 그때의 값은 현재가 아니다(연동 가이드 §3-3).
  const held = stale || (device.link !== null && device.link !== 'ok');
  return <StatGrid size={size}>
    <Stat level={stale ? 'unknown' : okLevel(device.online)} label={t('df.2')}
      value={device.online === true ? t('hl.3') : device.online === false ? t('hl.4') : t('hl.5')} />
    <Stat level={device.link === null ? 'unknown' : stale ? 'unknown' : okLevel(device.link === 'ok')} label={t('df.5')} value={device.link ?? '—'} title={t('hl.linkTitle')} />
    {!card && <Stat level={healthLevel(device.health)} label={t('df.6')} value={device.health ?? '—'} />}
    {/* null 은 「모른다」다 — 0% 로 그리지 않는다. 멈춘 값은 회색 + 「마지막 수신」. */}
    <Stat level={device.batteryPct === null || held ? 'unknown' : batteryLevel(device.batteryPct)} label={t('df.battery')}
      value={device.batteryPct === null ? '—' : `${device.batteryPct} %`} sub={held && device.batteryPct !== null ? t('gdash.held') : undefined}
      bar={device.batteryPct} />
    {!card && <Stat level={device.mode === null ? 'unknown' : held ? 'unknown' : 'good'} label={t('df.7')} value={device.mode ?? '—'} />}
    {/* 구동 브리지는 평시에 내려가 있다 — 내려감을 빨강으로 그리지 않는다. 모름은 회색. */}
    {size === 'full' && <Stat level={device.sdkReady === true ? 'good' : 'unknown'} label={t('df.8')} value={sdkWords(device.sdkReady, device.sdkAutostart)} title={t('df.sdkTitle')} />}
    {size === 'full' && <Stat level={device.inMission === null ? 'unknown' : device.inMission ? 'warn' : 'good'} label={t('df.9')} value={device.inMission === null ? '—' : device.inMission ? t('df.10') : t('df.11')} />}
    <Stat level={stale ? 'bad' : 'good'} label={t('df.lastSeen')} value={`${ago(device.lastSeenMs)} s`}
      sub={device.simulated ? t('hl.7') : stale ? t('gdash.silent') : undefined} title={device.simulated ? t('hl.mockTitle') : undefined} />
  </StatGrid>;
}

/**
 * **상태 줄의 그래프판** (261111). 글자 타일 하나하나가 그래프 타일이 된다 — 위에 지금 상태 글자, 아래에 최근 2분.
 * 생사 · 링크 · 장비 상태 · 모드처럼 낱말인 것은 색 띠, 배터리 · 속도 · 수신 간격은 선. `compact` 는 전체 장치 확인 칸.
 */
function GroundStatusGraphs({ source, historyId, compact }: { source: Source; historyId: string; compact: boolean }) {
  useLang();
  const now = useTick(TREND_TICK_MS);
  const line = (points: readonly MetricPoint[], extra: { minSpan?: number; stair?: boolean; threshold?: number } = {}) =>
    ({ kind: 'line' as const, points, ...extra });
  const lane = (key: string, labelOf: (code: string) => string, toneOf?: (code: string) => Level) =>
    ({ kind: 'lane' as const, points: stateSeries(historyId, key), labelOf, toneOf });
  const ages = metricSeries(historyId, AGE_KEY);
  if (source.kind === 'none') return <GroundStatusBar source={source} size={compact ? 'compact' : 'full'} />;
  if (source.kind === 'report') {
    const stale = source.report !== null && isTelemetryStale(source.report);
    const rows = (source.report?.rows ?? []).filter((row) => row.onCard === true);
    return <GraphGrid compact={compact}>
      <GraphStat now={now} level={stale ? 'bad' : 'good'} label={t('df.lastSeen')} value={`${ago(source.lastSeenMs)} s`}
        graph={line(ages, { minSpan: 2, threshold: TELEMETRY_STALE_MS / 1000 })} />
      {rows.map((row, index) => {
        const spec = row.labelKey === null ? undefined : ROW_LINE[row.labelKey];
        return <GraphStat key={`${row.labelKey ?? row.rawLabel ?? ''}-${index}`} now={now} level={stale ? 'unknown' : 'good'}
          label={row.labelKey === null ? (row.rawLabel ?? '') : t(row.labelKey)} value={telemetryValue(row)}
          graph={spec === undefined ? lane(rowKey(row), rowWords)
            : line(metricSeries(historyId, spec.key), { minSpan: spec.minSpan, stair: spec.stair })} />;
      })}
    </GraphGrid>;
  }
  const device = source.device;
  const stale = isStale(device);
  const held = stale || (device.link !== null && device.link !== 'ok');
  const battery = batterySeries(historyId);
  return <GraphGrid compact={compact}>
    <GraphStat now={now} level={stale ? 'unknown' : okLevel(device.online)} label={t('df.2')}
      value={device.online === true ? t('hl.3') : device.online === false ? t('hl.4') : t('hl.5')}
      graph={lane('status', (code) => (code === 'online' ? t('hl.3') : code === 'offline' ? t('hl.4') : code),
        (code) => (code === 'online' ? 'good' : code === 'offline' ? 'bad' : 'unknown'))} />
    <GraphStat now={now} level={device.link === null || stale ? 'unknown' : okLevel(device.link === 'ok')} label={t('df.5')}
      value={device.link ?? '—'} title={t('hl.linkTitle')} graph={lane('link', (code) => code, (code) => (code === 'ok' ? 'good' : 'bad'))} />
    <GraphStat now={now} level={healthLevel(device.health)} label={t('df.6')} value={device.health ?? '—'}
      graph={lane('device_status', (code) => code, (code) => healthLevel(code))} />
    <GraphStat now={now} level={device.batteryPct === null || held ? 'unknown' : batteryLevel(device.batteryPct)} label={t('df.battery')}
      value={device.batteryPct === null ? '—' : `${device.batteryPct} %${held ? t('df.heldSuffix') : ''}`} title={deltaWords(battery, now, 0, '%')}
      graph={line(battery, { minSpan: 5, stair: true, threshold: GO1_BATTERY_LOW_PCT })} />
    <GraphStat now={now} level={device.mode === null || held ? 'unknown' : 'good'} label={t('df.7')} value={device.mode ?? '—'}
      graph={lane('robot_mode', (code) => code)} />
    <GraphStat now={now} level={device.speedMps === null || held ? 'unknown' : 'good'} label={t('df.speed')}
      value={device.speedMps === null ? '—' : `${device.speedMps} m/s`} graph={line(metricSeries(historyId, 'speed_mps'), { minSpan: 0.5 })} />
    {!compact && <>
      <GraphStat now={now} level={device.sdkReady === true ? 'good' : 'unknown'} label={t('df.8')} value={sdkWords(device.sdkReady, device.sdkAutostart)}
        title={t('df.sdkTitle')} graph={lane('sdk.ready', (code) => (code === 'true' ? t('df.16') : t('df.17')), (code) => (code === 'true' ? 'good' : 'unknown'))} />
      <GraphStat now={now} level={device.inMission === null ? 'unknown' : device.inMission ? 'warn' : 'good'} label={t('df.9')}
        value={device.inMission === null ? '—' : device.inMission ? t('df.10') : t('df.11')}
        graph={lane('in_mission', (code) => (code === 'true' ? t('df.10') : t('df.11')), (code) => (code === 'true' ? 'warn' : 'good'))} />
    </>}
    <GraphStat now={now} level={stale ? 'bad' : 'good'} label={t('df.lastSeen')} value={`${ago(device.lastSeenMs)} s`}
      title={device.simulated ? t('hl.mockTitle') : undefined}
      graph={line(ages, { minSpan: 2, threshold: STALE_AFTER_MS / 1000 })} />
  </GraphGrid>;
}

/** 하드웨어 카드 한 줄 — 핵심 지표 글자 타일 넷. 그래프는 없다(261111 — 그래프는 상세와 전체 장치 확인에서만). */
export function GroundDashLine({ entityId }: { entityId: string }) {
  useLang();
  useTick(1000);
  const source = useGroundSource(entityId);
  return <div className="ground-dash-line"><GroundStatusBar source={source} size="card" /></div>;
}

/** 장비가 보고한 줄 전부 — 이름은 키라 풀고, 값은 보낸 그대로(`DeviceFacts` 의 `TelemetryFacts` 와 같은 규칙). */
function ReportRows({ report }: { report: DeviceTelemetry }) {
  useLang();
  return <dl className="dash-rows">
    {report.rows.map((row, index) => <Row key={`${row.labelKey ?? row.rawLabel ?? ''}-${index}`}
      k={row.labelKey === null ? (row.rawLabel ?? '') : t(row.labelKey)} v={telemetryValue(row)} />)}
    {report.timestamp !== null && <Row k={t('dt.reportedAt')} v={`${report.timestamp}${report.reason === null ? '' : ` · ${report.reason}`}`} />}
  </dl>;
}

/**
 * **상태판.** 카드 상세는 그래프 타일 + 방위 · 위치 · 장비 정보. `compact` 는 전체 장치 확인의 칸 —
 * [글자 | 그래프] 로 상태를 어떻게 볼지, [흐름 | 계기] 로 나침반 · 위치 표까지 볼지 고른다(261111).
 */
export function GroundDash({ entityId, compact = false }: { entityId: string; compact?: boolean }) {
  useLang();
  useTick(1000);
  const source = useGroundSource(entityId);
  const historyId = historyIdOf(entityId, source);
  const hasModes = useRobotModes(hardwareTarget(entityId)) !== null;
  const [flow, setFlow] = useState(true);
  const [graph, setGraph] = useState(true);
  if (source.kind === 'none') return <div className="ground-dash">
    <GroundStatusBar source={source} size={compact ? 'compact' : 'full'} />
    <p className="sar-empty">{t('df.1')}</p>
  </div>;
  const toggles = compact ? <div className="dash-mini__head"><CellToggles graph={graph} onGraph={setGraph} flow={flow} onFlow={setFlow} /></div> : null;
  const status = !compact || graph
    ? <GroundStatusGraphs source={source} historyId={historyId} compact={compact} />
    : <GroundStatusBar source={source} size="compact" />;
  if (source.kind === 'report') return <div className={`ground-dash${compact ? ' ground-dash--compact' : ' sar-zoom dash-zoom'}`}>
    {toggles}
    {status}
    {(!compact || !flow) && source.report !== null && <Panel title={t('gdash.reported')}><ReportRows report={source.report} /></Panel>}
  </div>;

  const device = source.device;
  const stale = isStale(device);
  const held = stale || (device.link !== null && device.link !== 'ok');
  const heldSuffix = held ? t('df.heldSuffix') : '';
  const position = device.position === null ? '—'
    : t('df.positionValue', { x: device.position.x.toFixed(2), y: device.position.y.toFixed(2), deg: device.position.headingDeg }) + heldSuffix;
  const compass = <div className="dash-instruments ground-dash__compass">
    <Compass yaw={device.position?.headingDeg ?? null} homeBearing={null} />
  </div>;
  const motion = <dl className="dash-rows">
    <Row k={t('df.position')} v={position} level={device.position === null ? undefined : held ? 'unknown' : undefined} />
    <Row k={t('df.speed')} v={device.speedMps === null ? '—' : `${device.speedMps} m/s`} />
    <Row k={t('df.7')} v={device.mode ?? '—'} />
    <Row k={t('df.9')} v={device.inMission === null ? '—' : device.inMission ? t('df.10') : t('df.11')} />
  </dl>;

  if (compact) return <div className="ground-dash ground-dash--compact">
    {toggles}
    {status}
    {!flow && <div className="ground-dash__mini">
      {compass}
      {motion}
    </div>}
  </div>;

  // 상태 칸(생사 · 링크 · 배터리 …)은 위 그래프 타일이 말한다 — 장비 칸에는 거기 없는 것만 남긴다.
  return <div className="sar-zoom dash-zoom ground-dash">
    {status}
    <div className="dash-grid">
      <Panel title={t('gdash.heading')}>{compass}</Panel>
      <Panel title={t('gdash.motion')}>{motion}</Panel>
      {hasModes && <Panel title={t('rmode.title')}><RobotModeRows entityId={hardwareTarget(entityId)} /></Panel>}
      <Panel title={t('gdash.device')}>
        <dl className="dash-rows">
          {device.firmware !== null && <Row k={t('df.12')} v={device.firmware} />}
          {device.simulated && <Row k={t('df.13')} v={t('df.14')} />}
          <Row k={t('df.lastSeen')} v={t('df.secondsAgo', { sec: ago(device.lastSeenMs) }) + (device.timestamp === null ? '' : ` · ${device.timestamp}`)}
            level={stale ? 'bad' : undefined} />
        </dl>
      </Panel>
    </div>
  </div>;
}
