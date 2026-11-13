/**
 * src/fixedcam/CameraStateView.tsx (261111 신설 — 360 카메라 장비 상태)
 *
 * `/frame` 헤더로 온 GPS · 배터리 · 온도를 그린다(`cameraState.ts`). 부품은 드론 · Go1 상태판과 같다(`DroneDash`).
 *
 *   CameraStateDash   카드 상세 — 타일 줄 + GPS · 온도 · 프레임 표 + 받은 JSON
 *   CameraStateDash compact  전체 장치 확인의 장치 상태 칸 — 타일 줄만
 *   CameraStateDots   하드웨어 카드 한 줄 — 배터리 · 온도 · GPS 점
 *
 * 보는 동안 2초마다 묻는다(`holdCameraState`). 안 왔으면 「아직 안 옴」이고, 낡았으면 낡았다고 적는다.
 */

import { useEffect } from 'react';
import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import { useTick } from '../sar/useTick.ts';
import { Panel, Row, Stat, StatGrid, fmt, type Level } from '../dronedash/DroneDash.tsx';
import '../dronedash/dronedash.css';
import { holdCameraState, isCameraStateStale, useCameraState, type CameraState } from './cameraState.ts';

const ago = (ms: number) => Math.max(0, Math.round((Date.now() - ms) / 1000));

function batteryLevel(pct: number | null): Level {
  if (pct === null) return 'unknown';
  return pct > 30 ? 'good' : pct > 15 ? 'warn' : 'bad';
}

/** fix_type — 0·1 없음, 2 2D, 3 3D, 4 이상 DGPS/RTK (MAVLink `GPS_FIX_TYPE` 와 같은 번호). */
function fixLevel(fixType: number | null): Level {
  if (fixType === null) return 'unknown';
  return fixType >= 3 ? 'good' : fixType === 2 ? 'warn' : 'bad';
}

function fixWords(fixType: number | null): string {
  if (fixType === null) return '—';
  if (fixType <= 1) return t('ccs.fixNone');
  if (fixType === 2) return '2D';
  if (fixType === 3) return '3D';
  return `fix ${fixType}`;
}

function coordWords(state: CameraState): string {
  const gps = state.gps;
  if (gps === null || gps.lat === null || gps.lon === null) return t('ccs.noCoord');
  return `${gps.lat.toFixed(6)}, ${gps.lon.toFixed(6)}`;
}

/** 서버가 준 부위 이름 — 아는 것만 옮기고 모르는 것은 그대로 적는다. */
const KNOWN_TEMP_PARTS = new Set(['battery', 'board', 'module']);
const tempLabel = (part: string) => (KNOWN_TEMP_PARTS.has(part) ? t(`ccs.temp.${part}`) : part);

function Tiles({ state, size }: { state: CameraState; size: 'full' | 'compact' | 'card' }) {
  const stale = isCameraStateStale(state);
  const gps = state.gps;
  const hottest = state.temperatures.reduce<[string, number] | null>((top, [k, v]) => (top === null || v > top[1] ? [k, v] : top), null);
  return <StatGrid size={size}>
    <Stat level={stale ? 'unknown' : batteryLevel(state.batteryPct)} label={t('ccs.battery')}
      value={state.batteryPct === null ? '—' : `${fmt(state.batteryPct, 0)}%`}
      sub={state.charging === null ? undefined : state.charging ? t('ccs.charging') : t('ccs.discharging')}
      bar={state.batteryPct} />
    <Stat level={stale ? 'unknown' : fixLevel(gps?.fixType ?? null)} label="GPS"
      value={fixWords(gps?.fixType ?? null)}
      sub={t('ccs.satsLine', { sats: gps?.satellites ?? '—', snr: fmt(gps?.snrMax ?? null, 0) })} />
    {size === 'full'
      ? state.temperatures.map(([part, c]) => <Stat key={part} level={stale ? 'unknown' : 'good'} label={tempLabel(part)} value={`${fmt(c, 1)}°C`} />)
      : <Stat level={stale ? 'unknown' : hottest === null ? 'unknown' : 'good'} label={t('ccs.tempMax')}
          value={hottest === null ? '—' : `${fmt(hottest[1], 1)}°C`} sub={hottest === null ? undefined : tempLabel(hottest[0])} />}
    <Stat level={stale ? 'warn' : 'good'} label={t('ccs.received')} value={t('hl.secondsAgo', { sec: ago(state.receivedAtMs) })} />
  </StatGrid>;
}

/** 상세 · 전체 장치 확인의 장비 상태. */
export function CameraStateDash({ entityId, compact = false }: { entityId: string; compact?: boolean }) {
  useLang();
  useTick(1000);
  useEffect(() => holdCameraState(entityId), [entityId]);
  const state = useCameraState(entityId);
  if (state === null) return <p className="vn-line vn-dim">{t('ccs.none')}</p>;
  const gps = state.gps;
  return <div className="camera-state">
    <Tiles state={state} size={compact ? 'compact' : 'full'} />
    {isCameraStateStale(state) && <p className="vn-line vn-warn">{t('ccs.stale', { sec: ago(state.receivedAtMs) })}</p>}
    {!compact && <div className="dash-grid">
      <Panel title="GPS">
        <dl className="dash-rows">
          <Row k={t('ccs.coord')} v={coordWords(state)} />
          <Row k={t('ccs.alt')} v={gps?.altM === null || gps?.altM === undefined ? '—' : `${fmt(gps.altM, 1)} m`} />
          <Row k={t('ccs.fix')} v={`${fixWords(gps?.fixType ?? null)} (fix_type ${gps?.fixType ?? '—'})`} level={fixLevel(gps?.fixType ?? null)} />
          <Row k={t('ccs.sats')} v={gps?.satellites ?? '—'} />
          <Row k="SNR max" v={fmt(gps?.snrMax ?? null, 0)} />
        </dl>
      </Panel>
      <Panel title={t('ccs.tempTitle')}>
        <dl className="dash-rows">
          {state.temperatures.length === 0
            ? <Row k="—" v={t('ccs.noTemp')} />
            : state.temperatures.map(([part, c]) => <Row key={part} k={tempLabel(part)} v={`${fmt(c, 1)} °C`} />)}
        </dl>
      </Panel>
      <Panel title={t('ccs.frameTitle')}>
        <dl className="dash-rows">
          <Row k={t('ccs.frameN')} v={state.frameN ?? '—'} />
          <Row k={t('ccs.frameSize')} v={state.frameWidth === null || state.frameHeight === null ? '—' : `${state.frameWidth}×${state.frameHeight}`} />
          <Row k={t('ccs.frameAt')} v={state.frameTimestamp ?? '—'} />
          <Row k={t('ccs.stateAt')} v={state.timestamp ?? '—'} />
          <Row k="camera_state" v={state.cameraState ?? '—'} />
          {state.sourceId !== null && <Row k="source_id" v={state.sourceId} />}
        </dl>
      </Panel>
    </div>}
    {!compact && <details className="obstacle-raw">
      <summary>{t('ccs.raw')}</summary>
      <pre>{JSON.stringify(state.raw, null, 2)}</pre>
    </details>}
  </div>;
}

/** 하드웨어 카드 한 줄의 점 — 배터리 · 가장 뜨거운 곳 · GPS. 안 왔으면 아무것도 안 그린다. */
export function CameraStateDots({ entityId }: { entityId: string }) {
  useLang();
  const state = useCameraState(entityId);
  if (state === null) return null;
  const stale = isCameraStateStale(state);
  const hottest = state.temperatures.reduce<[string, number] | null>((top, [k, v]) => (top === null || v > top[1] ? [k, v] : top), null);
  const dot = (level: Level) => `hw-dot hw-dot--${stale ? 'unknown' : level === 'good' ? 'ok' : level === 'unknown' ? 'unknown' : level}`;
  return <span className="hw-link">
    {state.batteryPct !== null && <em className={dot(batteryLevel(state.batteryPct))}>
      {t('hl.battery', { pct: Math.round(state.batteryPct) })}{state.charging === true ? ' ⚡' : ''}
    </em>}
    {hottest !== null && <em className="hw-dot hw-dot--plain" title={state.temperatures.map(([k, v]) => `${tempLabel(k)} ${v}°C`).join(' · ')}>
      {`${fmt(hottest[1], 0)}°C`}
    </em>}
    {state.gps !== null && <em className={dot(fixLevel(state.gps.fixType))} title={coordWords(state)}>
      {`GPS ${fixWords(state.gps.fixType)} · ${state.gps.satellites ?? '—'}`}
    </em>}
  </span>;
}
