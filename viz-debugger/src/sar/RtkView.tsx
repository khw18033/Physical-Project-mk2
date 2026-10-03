/**
 * src/sar/RtkView.tsx (261002 신설 — 드론 파트 · RTK)
 *
 * **RTK 상태 노드.** 장비가 보고한 `gps` 묶음을 그대로 읽는다(`shared/deviceTelemetry.ts`).
 * 기종을 묻지 않는다 — `gps` 를 보고한 장비면 누구든 한 줄이 된다.
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { isTelemetryStale, telemetryValue, useDeviceTelemetry, type DeviceTelemetry } from '../shared/deviceTelemetry.ts';
import { RTK_LABEL_KEY, rtkLevel, type RtkLevel } from './rtk.ts';
import { useTick } from './useTick.ts';
import { isRtcmReportStale, useRtcmReports, type RtcmReport } from '../shared/rtcmStatus.ts';
import './sar.css';

type GpsView = {
  entityId: string;
  level: RtkLevel;
  fix: string | null;
  fixType: number | null;
  satellites: number | null;
  ephM: number | null;
  lat: number | null;
  lon: number | null;
  ageS: number | null;
  stale: boolean;
};

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

function gpsOf(report: DeviceTelemetry): GpsView | null {
  const gps = report.values.gps;
  if (gps === null || typeof gps !== 'object' || Array.isArray(gps)) return null;
  const id = report.entityId;
  const fix = telemetryValue(id, 'gps.fix');
  const fixType = num(telemetryValue(id, 'gps.fix_type'));
  return {
    entityId: id,
    level: rtkLevel(fixType, fix),
    fix: typeof fix === 'string' ? fix : null,
    fixType,
    satellites: num(telemetryValue(id, 'gps.satellites')),
    ephM: num(telemetryValue(id, 'gps.eph_m')),
    lat: num(telemetryValue(id, 'gps.lat')),
    lon: num(telemetryValue(id, 'gps.lon')),
    ageS: num(telemetryValue(id, 'gps.age_s')),
    stale: isTelemetryStale(report),
  };
}

export function useGpsDevices(): GpsView[] {
  const all = useDeviceTelemetry();
  return Object.values(all).map(gpsOf).filter((g): g is GpsView => g !== null);
}

/** 보정(RTCM) 전달 상태 한 줄. 전달기 보고가 없으면 「모름」이다 — 끊김이라고 짐작하지 않는다. */
function rtcmState(report: RtcmReport | undefined): 'on' | 'off' | 'never' | 'unknown' {
  if (report === undefined || isRtcmReportStale(report)) return 'unknown';
  if (report.receiving) return 'on';
  return report.ageS === null ? 'never' : 'off';
}

export function RtcmLine({ report }: { report: RtcmReport | undefined }) {
  useLang();
  const state = rtcmState(report);
  const text = state === 'on'
    ? t('rtcm.on', { fps: (report?.framesPerS ?? 0).toFixed(1), age: (report?.ageS ?? 0).toFixed(1) })
    : state === 'off' ? t('rtcm.off', { age: (report?.ageS ?? 0).toFixed(0) })
      : state === 'never' ? t('rtcm.never') : t('rtcm.unknown');
  return <span className={`rtcm-line rtcm-line--${state}`}>{text}</span>;
}

export function RtkBadge({ level }: { level: RtkLevel }) {
  useLang();
  return <span className={`rtk-badge rtk-badge--${level}`}>{t(RTK_LABEL_KEY[level])}</span>;
}

export function RtkCard() {
  useLang();
  useTick(1000);
  const devices = useGpsDevices();
  const rtcm = useRtcmReports();
  if (devices.length === 0) return <p className="sar-empty">{t('rtk.noDevice')}</p>;
  return <ul className="rtk-card">
    {devices.map((g) => <li key={g.entityId} className={g.stale ? 'is-stale' : ''}>
      <b>{g.entityId}</b>
      <RtkBadge level={g.level} />
      <span>{t('rtk.sats', { n: g.satellites ?? '—' })}</span>
      {g.ephM !== null && <span>eph {g.ephM.toFixed(2)}</span>}
      {g.stale && <em>{t('rtk.stale')}</em>}
      <RtcmLine report={rtcm[g.entityId]} />
    </li>)}
  </ul>;
}

/** `deviceId` 를 주면 그 장비 한 대만 그린다 — 하드웨어 카드의 상세보기(261003). 안 주면 보고한 장비 전부(뷰 노드). */
export function RtkZoom({ deviceId }: { deviceId?: string } = {}) {
  useLang();
  useTick(1000);
  const devices = useGpsDevices().filter((g) => deviceId === undefined || g.entityId === deviceId);
  const rtcm = useRtcmReports();
  const relayOnly = Object.values(rtcm).filter((r) => (deviceId === undefined || r.deviceId === deviceId)
    && !devices.some((g) => g.entityId === r.deviceId));
  return <div className="sar-zoom">
    <p className="sar-lead">{t('rtk.lead')}</p>
    {devices.length === 0 && <p className="sar-empty">{t('rtk.noDevice')}</p>}
    {devices.map((g) => <section key={g.entityId} className="sar-section">
      <header className="sar-section__head">
        <h3>{g.entityId}</h3>
        <RtkBadge level={g.level} />
        {g.stale && <em className="sar-warn">{t('rtk.stale')}</em>}
      </header>
      <dl className="device-facts">
        <div><dt>{t('rtk.fixRaw')}</dt><dd>{g.fix ?? '—'}{g.fixType === null ? '' : ` (fix_type ${g.fixType})`}</dd></div>
        <div><dt>{t('dt.satellites')}</dt><dd>{g.satellites ?? '—'}</dd></div>
        <div><dt>{t('dt.eph')}</dt><dd>{g.ephM === null ? '—' : g.ephM.toFixed(2)}</dd></div>
        <div><dt>{t('dt.lat')}</dt><dd>{g.lat === null ? '—' : g.lat.toFixed(7)}</dd></div>
        <div><dt>{t('dt.lon')}</dt><dd>{g.lon === null ? '—' : g.lon.toFixed(7)}</dd></div>
        {g.ageS !== null && <div><dt>{t('rtk.age')}</dt><dd>{t('dt.ageSuffix', { sec: g.ageS.toFixed(1) })}</dd></div>}
        <div><dt>{t('rtcm.title')}</dt><dd><RtcmLine report={rtcm[g.entityId]} /></dd></div>
        <div><dt>{t('rtk.sarReady')}</dt>
          <dd className={g.level === 'fixed' ? 'sar-ok' : 'sar-bad'}>
            {g.level === 'fixed' ? t('rtk.sarReady.yes') : t('rtk.sarReady.no')}
          </dd></div>
      </dl>
      <RtcmDetail report={rtcm[g.entityId]} />
    </section>)}
    {relayOnly.map((r) => <section key={`relay-${r.deviceId}`} className="sar-section">
      <header className="sar-section__head"><h3>{r.deviceId}</h3><RtcmLine report={r} /></header>
      <RtcmDetail report={r} />
    </section>)}
    <section className="sar-section">
      <h3>{t('rtk.legendTitle')}</h3>
      <ul className="rtk-legend">
        {(['none', 'gps', 'dgps', 'float', 'fixed'] as const).map((level) => <li key={level}>
          <RtkBadge level={level} /> <span>{t(`rtk.legend.${level}`)}</span>
        </li>)}
      </ul>
      <p className="sar-hint">{t('rtk.rtcmHint')}</p>
    </section>
  </div>;
}

function RtcmDetail({ report }: { report: RtcmReport | undefined }) {
  useLang();
  if (report === undefined) return <p className="sar-hint">{t('rtcm.noRelay')}</p>;
  const base = report.base;
  return <dl className="device-facts">
    <div><dt>{t('rtcm.rate')}</dt><dd>{report.framesPerS?.toFixed(2) ?? '—'} /s · {report.rateBps?.toFixed(0) ?? '—'} B/s</dd></div>
    <div><dt>{t('rtcm.types')}</dt><dd>{report.types.join(', ') || '—'}</dd></div>
    <div><dt>{t('rtcm.base')}</dt><dd>{base === null ? t('rtcm.baseUnknown')
      : `#${base.stationId ?? '?'} · ${base.lat?.toFixed(7) ?? '—'}, ${base.lon?.toFixed(7) ?? '—'} · ${base.altM?.toFixed(2) ?? '—'} m`}</dd></div>
    <div><dt>{t('rtcm.sender')}</dt><dd>{report.sender ?? '—'}</dd></div>
    <div><dt>{t('rtcm.injected')}</dt><dd>{report.injectedMessages ?? '—'}{report.badCrc ? ` · CRC ${report.badCrc}` : ''}</dd></div>
  </dl>;
}
