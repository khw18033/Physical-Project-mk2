/**
 * src/physical/RobotModeRows.tsx (261112 신설 — A2-W 로봇 모드 표시)
 *
 * **로봇이 지금 어느 모드인가** — 자세(잠금 · 엎드림 …) · 걸음(기본 · 고속 · 오르기) · 속도 단계 · 자동 뒤집기 복구 · 몸 높이.
 * 장비가 상태 본문에 `robot_modes` 묶음을 실어 보낼 때만 그린다(지금은 `a2-bridge`). 하드웨어 상세(`GroundDash`)와
 * 수동 제어 탭이 같이 쓴다.
 *
 * 값의 출처가 둘이라 줄마다 적는다.
 *   - **로봇 보고** — `fsm_name` · `speed_level` · `auto_recovery` 는 로봇의 GetState 가 준 값이다. 조종기로 바꿔도 따라온다.
 *   - **마지막 명령** — `posture` · `gait` · `height_offset_m` · 토글은 브리지가 성공한 명령으로 기억한 값이다. 조종기로
 *     바꾸면 어긋날 수 있다. A2-W 의 GetState 이름표(`fsm_name`)가 모드마다 무엇인지 아직 다 모른다(261112).
 *
 * 모르는 값(규약 밖의 문자열)은 번역하지 않고 그대로 적는다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { telemetryValue as rawValue, useDeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { Row } from '../dronedash/DroneDash.tsx';

type Modes = {
  fsm_name?: unknown; posture?: unknown; gait?: unknown; speed_level?: unknown; auto_recovery?: unknown;
  height_offset_m?: unknown; handstand?: unknown; erect?: unknown;
};

const POSTURES = new Set(['locked', 'unlocked', 'prone', 'damped', 'recovering']);
const GAITS = new Set(['default', 'high_speed', 'climb']);

function word(prefix: string, known: ReadonlySet<string>, value: unknown): string {
  if (typeof value !== 'string' || value === '') return '—';
  return known.has(value) ? t(`${prefix}.${value}`) : value;
}

function onOff(value: unknown): string {
  if (value === true || value === 'true') return t('rmode.on');
  if (value === false || value === 'false') return t('rmode.off');
  return '—';
}

/** 그 장비의 `robot_modes`. 없으면 null — 이 부품을 안 그린다. */
export function useRobotModes(entityId: string): Modes | null {
  useDeviceTelemetry();
  const value = rawValue(entityId, 'robot_modes');
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Modes : null;
}

export function RobotModeRows({ entityId }: { entityId: string }) {
  useLang();
  const modes = useRobotModes(entityId);
  if (modes === null) return null;
  const level = typeof modes.speed_level === 'number' || typeof modes.speed_level === 'string' ? String(modes.speed_level) : '—';
  const height = typeof modes.height_offset_m === 'number' ? `${modes.height_offset_m >= 0 ? '+' : ''}${modes.height_offset_m.toFixed(2)} m` : '—';
  const by = (key: 'rmode.byRobot' | 'rmode.byCommand') => <small className="rmode-src">{t(key)}</small>;
  return <dl className="dash-rows rmode">
    <Row k={t('rmode.fsm')} v={<>{typeof modes.fsm_name === 'string' && modes.fsm_name !== '' ? modes.fsm_name : '—'} {by('rmode.byRobot')}</>} />
    <Row k={t('rmode.posture')} v={<>{word('rmode.posture', POSTURES, modes.posture)} {by('rmode.byCommand')}</>} />
    <Row k={t('rmode.gait')} v={<>{word('rmode.gait', GAITS, modes.gait)} {by('rmode.byCommand')}</>} />
    <Row k={t('rmode.speedLevel')} v={<>{level} {by('rmode.byRobot')}</>} />
    <Row k={t('rmode.autoRecovery')} v={<>{onOff(modes.auto_recovery)} {by('rmode.byRobot')}</>} />
    <Row k={t('rmode.height')} v={<>{height} {by('rmode.byCommand')}</>} />
    {modes.handstand === true && <Row k={t('rmode.handstand')} v={t('rmode.on')} />}
    {modes.erect === true && <Row k={t('rmode.erect')} v={t('rmode.on')} />}
  </dl>;
}
