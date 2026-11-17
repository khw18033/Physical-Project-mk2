/**
 * src/physical/ArmDash.tsx (261117 신설 — 로봇팔 MT4 상태판)
 *
 * **상태 탭이 「마지막 수신」만 그리던 자리.** 상태판(`GroundDash`)은 보고 줄 가운데 카드 몫(`onCard`)만 타일로 그리는데,
 * MT4 의 값(`arm_state` · 관절 · 끝점 · 펌프 …)은 그 줄 목록(`stateRows.ts`)에 없다 — 드론 · Go1 모양만 안다.
 * 그래서 로봇팔이면 이 판이 대신 그린다. 값은 장비가 보낸 그대로(`deviceTelemetry`)이고, 안 온 칸은 「—」다.
 *
 *   낱말 타일   팔 상태 · 원점 · 장비 상태 · 시리얼 · 제어 잠금
 *   숫자 그래프 j1~j4 · 끝점 x·y·z · 펌프 PWM · 마지막 수신
 *   장비 칸     펌웨어 · 포트 · 링크 길이 · 관절 범위 · 가동 시간 · 발행 실패 · 버퍼 (`status` 요약 · 10초)
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { isTelemetryStale, TELEMETRY_STALE_MS, telemetryValue, type DeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { AGE_KEY, metricSeries, stateSeries } from '../shared/metricHistory.ts';
import { GraphGrid, GraphStat, TREND_TICK_MS } from '../dronedash/Trend.tsx';
import { Panel, Row, type Level } from '../dronedash/DroneDash.tsx';
import { useTick } from '../sar/useTick.ts';
import { armView, isAlarm, isHold, JOINTS, CART_AXES } from './armControl.ts';

const fmt = (value: number | undefined | null, digits = 1) => (value === undefined || value === null ? '—' : value.toFixed(digits));
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** GRBL 상태 → 색. Idle 초록, Run 진행(노랑), Hold 노랑, Alarm 빨강, 모름 회색. */
export function armStateLevel(state: string | null): Level {
  if (state === null) return 'unknown';
  if (state === 'Idle') return 'good';
  if (isAlarm(state)) return 'bad';
  if (isHold(state) || state === 'Run' || state === 'Home' || state === 'Jog') return 'warn';
  return 'unknown';
}

const boolCode = (yes: Level, no: Level) => (code: string): Level => (code === 'true' ? yes : code === 'false' ? no : 'unknown');

/** 상태 탭의 그래프 타일 — `GroundStatusGraphs` 자리. */
export function ArmStatusGraphs({ entityId, report, lastSeenMs, compact }: {
  entityId: string; report: DeviceTelemetry | null; lastSeenMs: number; compact: boolean;
}) {
  useLang();
  const now = useTick(TREND_TICK_MS);
  const stale = report !== null && isTelemetryStale(report);
  const view = armView(entityId);
  const deviceStatus = telemetryValue(entityId, 'device_status');
  const health = typeof deviceStatus === 'string' ? deviceStatus : null;
  const held = (level: Level): Level => (stale ? 'unknown' : level);
  const lane = (key: string, labelOf: (code: string) => string, toneOf?: (code: string) => Level) =>
    ({ kind: 'lane' as const, points: stateSeries(entityId, key), labelOf, toneOf });
  const line = (key: string, minSpan: number, threshold?: number) =>
    ({ kind: 'line' as const, points: metricSeries(entityId, key), minSpan, ...(threshold === undefined ? {} : { threshold }) });
  const ago = Math.max(0, Math.round((Date.now() - lastSeenMs) / 1000));

  return <GraphGrid compact={compact}>
    <GraphStat now={now} level={held(armStateLevel(view.armState))} label={t('arm.dash.state')} value={view.armState ?? '—'}
      graph={lane('arm_state', (code) => code, armStateLevel)} />
    <GraphStat now={now} level={held(view.homed === true ? 'good' : view.homed === false ? 'bad' : 'unknown')} label={t('arm.dash.homed')}
      value={t(view.homed === true ? 'arm.homed.yes' : view.homed === false ? 'arm.homed.no' : 'arm.homed.unknown')}
      graph={lane('homed', (code) => t(code === 'true' ? 'arm.homed.yes' : 'arm.homed.no'), boolCode('good', 'bad'))} />
    <GraphStat now={now} level={held(health === null ? 'unknown' : health === 'ok' ? 'good' : health === 'degraded' ? 'warn' : 'bad')}
      label={t('dt.deviceStatus')} value={health ?? '—'}
      graph={lane('device_status', (code) => code, (code) => (code === 'ok' ? 'good' : code === 'degraded' ? 'warn' : 'bad'))} />
    {!compact && <GraphStat now={now} level={held(view.serialOk === true ? 'good' : view.serialOk === false ? 'bad' : 'unknown')} label={t('arm.dash.serial')}
      value={view.serialOk === null ? '—' : t(view.serialOk ? 'arm.dash.ok' : 'arm.serial.lost')}
      graph={lane('serial_ok', (code) => t(code === 'true' ? 'arm.dash.ok' : 'arm.serial.lost'), boolCode('good', 'bad'))} />}
    {!compact && <GraphStat now={now} level={held(view.locked ? 'warn' : 'good')} label={t('arm.dash.lock')}
      value={view.locked ? (view.lockReason ?? t('arm.dash.locked')) : t('arm.dash.unlocked')}
      graph={lane('control_locked', (code) => t(code === 'true' ? 'arm.dash.locked' : 'arm.dash.unlocked'), boolCode('warn', 'good'))} />}
    {JOINTS.map((j) => <GraphStat key={`j${j}`} now={now} level={held(view.joints?.[`j${j}`] === undefined ? 'unknown' : 'good')}
      label={`j${j}`} value={`${fmt(view.joints?.[`j${j}`])} °`} graph={line(`joints_deg.j${j}`, 2)} />)}
    {CART_AXES.map((axis) => <GraphStat key={axis} now={now} level={held(view.tcp?.[axis] === undefined ? 'unknown' : 'good')}
      label={t('arm.dash.tcp', { axis })} value={`${fmt(view.tcp?.[axis])} mm`} graph={line(`tcp.${axis}`, 2)} />)}
    {!compact && <GraphStat now={now} level={held(view.pumpPwm === null ? 'unknown' : 'good')} label={t('arm.dash.pump')}
      value={fmt(view.pumpPwm, 0)} graph={line('pump_pwm', 1)} />}
    <GraphStat now={now} level={stale ? 'bad' : 'good'} label={t('df.lastSeen')} value={`${ago} s`}
      graph={line(AGE_KEY, 2, TELEMETRY_STALE_MS / 1000)} />
  </GraphGrid>;
}

/** 장비 칸 — 자주 안 바뀌는 것(`status` 요약). 온 것만 적는다. */
export function ArmInfoPanel({ entityId }: { entityId: string }) {
  useLang();
  const v = (path: string) => telemetryValue(entityId, path);
  const str = (path: string) => { const value = v(path); return typeof value === 'string' && value !== '' ? value : null; };
  const links = v('arm_info.links_mm');
  const ranges = armView(entityId).jointRanges;
  const uptime = num(v('uptime_s'));
  const failures = num(v('publish_failures'));
  const pending = num(v('buffer.pending'));
  const dropped = num(v('buffer.dropped'));
  const age = num(v('state_age_s'));
  const linkText = links !== null && typeof links === 'object' && !Array.isArray(links)
    ? Object.entries(links as Record<string, unknown>).filter(([, value]) => num(value) !== null).map(([key, value]) => `${key} ${value}`).join(' · ')
    : null;
  return <Panel title={t('gdash.device')}>
    <dl className="dash-rows">
      {str('registration.device_type') !== null && <Row k={t('arm.dash.model')} v={str('registration.device_type')} />}
      {str('arm_info.firmware') !== null && <Row k={t('df.12')} v={str('arm_info.firmware')} />}
      {str('arm_info.port') !== null && <Row k={t('arm.dash.port')} v={str('arm_info.port')} />}
      {linkText !== null && linkText !== '' && <Row k={t('arm.dash.links')} v={linkText} />}
      {ranges !== null && <Row k={t('arm.dash.ranges')} v={Object.entries(ranges).map(([key, range]) => `${key} ${range?.[0]}~${range?.[1]}°`).join(' · ')} />}
      {age !== null && <Row k={t('arm.dash.stateAge')} v={`${Math.round(age * 1000)} ms`} level={age > 1 ? 'warn' : undefined} />}
      {uptime !== null && <Row k={t('arm.dash.uptime')} v={`${Math.round(uptime)} s`} />}
      {failures !== null && <Row k={t('arm.dash.publishFailures')} v={String(failures)} level={failures > 0 ? 'warn' : undefined} />}
      {(pending !== null || dropped !== null) && <Row k={t('arm.dash.buffer')} v={t('arm.dash.bufferValue', { pending: pending ?? '—', dropped: dropped ?? '—' })}
        level={(dropped ?? 0) > 0 ? 'warn' : undefined} />}
    </dl>
  </Panel>;
}
