/**
 * src/physical/GroundDash.tsx (261110 신설 — 드론이 아닌 장비(Go1 등)의 상태판)
 *
 * **드론 상태판과 같은 모양으로.** 드론은 상태 줄(칩) · 계기 · 패널로 한눈에 읽는데, Go1 은 상세를 열어도 이름 · 값 표가
 * 전부라 같은 화면에서 둘을 나란히 놓으면 읽는 법이 갈렸다. 그래서 같은 부품(`Chip` · `Panel` · `Row` · `Compass` —
 * `dronedash/DroneDash.tsx`)으로 그린다.
 *
 * 세 자리에 쓴다.
 *   GroundDashLine   하드웨어 카드 한 줄 — 핵심 지표 타일 넷(연결 · 로봇 링크 · 배터리 · 마지막 수신)
 *   GroundDash       카드 상세(더블클릭)의 상태 — 상태 줄 · 위치/방위 · 동작 · 장비 · 보고 항목
 *   GroundDash compact  전체 장치 확인의 장치 상태 칸 — 상태 줄 · 나침반 · 핵심 값
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
import { isStale, useDeviceStates, type DeviceState } from './deviceState.ts';
import { useRobotSession } from './robotSession.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';
import { isTelemetryStale, useDeviceTelemetry, type DeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { mqttFilled, sdkWords, telemetryValue } from './DeviceFacts.tsx';
import { Compass, Panel, Row, Stat, StatGrid, type Level } from '../dronedash/DroneDash.tsx';
import { useTick } from '../sar/useTick.ts';
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

const ago = (ms: number) => Math.max(0, Math.round((Date.now() - ms) / 1000));

function batteryLevel(pct: number): Level {
  return pct < 20 ? 'bad' : pct < 40 ? 'warn' : 'good';
}

function okLevel(ok: boolean | null): Level {
  return ok === true ? 'good' : ok === false ? 'bad' : 'unknown';
}

type Size = 'full' | 'compact' | 'card';

/**
 * 상태 줄 — 드론 상태판의 `StatusBar` 와 같은 **지표 타일**(261110 A안). `card` 는 하드웨어 카드 한 줄이라 핵심 넷만
 * (연결 · 로봇 링크 · 배터리 · 마지막 수신), `compact` 는 전체 장치 확인 칸, `full` 은 카드 상세.
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
    {!card && <Stat level={device.health === null ? 'unknown' : device.health === 'ok' ? 'good' : device.health === 'degraded' ? 'warn' : 'bad'} label={t('df.6')} value={device.health ?? '—'} />}
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

/** 하드웨어 카드 한 줄 — 핵심 지표 타일 넷. */
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
 * **상태판.** `compact` 면 전체 장치 확인의 4분의 1 칸에 맞춘 축약판 — 상태 줄 · 나침반 · 위치/속도/모드만.
 */
export function GroundDash({ entityId, compact = false }: { entityId: string; compact?: boolean }) {
  useLang();
  useTick(1000);
  const source = useGroundSource(entityId);
  if (source.kind === 'none') return <div className="ground-dash">
    <GroundStatusBar source={source} size={compact ? 'compact' : 'full'} />
    <p className="sar-empty">{t('df.1')}</p>
  </div>;
  if (source.kind === 'report') return <div className={`ground-dash${compact ? ' ground-dash--compact' : ''}`}>
    <GroundStatusBar source={source} size={compact ? 'compact' : 'full'} />
    {source.report !== null && <Panel title={t('gdash.reported')}><ReportRows report={source.report} /></Panel>}
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
    <GroundStatusBar source={source} size="compact" />
    <div className="ground-dash__mini">
      {compass}
      {motion}
    </div>
  </div>;

  return <div className="sar-zoom dash-zoom ground-dash">
    <GroundStatusBar source={source} size="full" />
    <div className="dash-grid">
      <Panel title={t('gdash.heading')}>{compass}</Panel>
      <Panel title={t('gdash.motion')}>{motion}</Panel>
      <Panel title={t('gdash.device')} wide>
        <dl className="dash-rows">
          <Row k={t('df.2')} v={device.online === null ? '—' : device.online ? t('df.3') : t('df.4')} level={stale ? 'unknown' : okLevel(device.online)} />
          <Row k={t('df.5')} v={device.link ?? '—'} level={device.link === null ? undefined : okLevel(device.link === 'ok')} />
          <Row k={t('df.6')} v={device.health ?? '—'} />
          <Row k={t('df.battery')} v={device.batteryPct === null ? '—' : `${device.batteryPct}%${heldSuffix}`}
            level={device.batteryPct === null ? undefined : held ? 'unknown' : batteryLevel(device.batteryPct)} />
          <Row k={t('df.8')} v={sdkWords(device.sdkReady, device.sdkAutostart)} />
          {device.firmware !== null && <Row k={t('df.12')} v={device.firmware} />}
          {device.simulated && <Row k={t('df.13')} v={t('df.14')} />}
          <Row k={t('df.lastSeen')} v={t('df.secondsAgo', { sec: ago(device.lastSeenMs) }) + (device.timestamp === null ? '' : ` · ${device.timestamp}`)}
            level={stale ? 'bad' : undefined} />
        </dl>
      </Panel>
    </div>
  </div>;
}
