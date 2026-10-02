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

export function RtkBadge({ level }: { level: RtkLevel }) {
  useLang();
  return <span className={`rtk-badge rtk-badge--${level}`}>{t(RTK_LABEL_KEY[level])}</span>;
}

export function RtkCard() {
  useLang();
  useTick(1000);
  const devices = useGpsDevices();
  if (devices.length === 0) return <p className="sar-empty">{t('rtk.noDevice')}</p>;
  return <ul className="rtk-card">
    {devices.map((g) => <li key={g.entityId} className={g.stale ? 'is-stale' : ''}>
      <b>{g.entityId}</b>
      <RtkBadge level={g.level} />
      <span>{t('rtk.sats', { n: g.satellites ?? '—' })}</span>
      {g.ephM !== null && <span>eph {g.ephM.toFixed(2)}</span>}
      {g.stale && <em>{t('rtk.stale')}</em>}
    </li>)}
  </ul>;
}

export function RtkZoom() {
  useLang();
  useTick(1000);
  const devices = useGpsDevices();
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
        <div><dt>{t('rtk.sarReady')}</dt>
          <dd className={g.level === 'fixed' ? 'sar-ok' : 'sar-bad'}>
            {g.level === 'fixed' ? t('rtk.sarReady.yes') : t('rtk.sarReady.no')}
          </dd></div>
      </dl>
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
