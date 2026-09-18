/**
 * src/physical/DeviceFacts.tsx (260910 신설 — 오는 값만 적는다)
 *
 * 장비 하나의 **실제로 도착한 값**. 안 오는 칸은 자리표시로 채우지 않고 **아예 안 그린다** —
 * 「연결 예정」이 시연 화면에서 연결 전 테스트처럼 보인다는 지적이 있었다.
 *
 * ## 링크가 끊기면 값이 멈춘 채로 계속 온다 (연동 가이드 §3-3)
 *
 * 알려진 문제다 — 로봇 링크가 끊겨도 마지막 배터리·위치가 계속 발행된다. 그대로 그리면
 * **멈춘 값을 살아 있는 값으로 보여 준다.** `link` 가 `ok` 가 아니면 「마지막 수신」을 붙인다.
 *
 * 배터리의 `null` 은 **모른다**는 뜻이고 `0%` 로 그리면 안 된다 — 방전 직전과 구별되지 않는다.
 */

import { t } from '../i18n/dict.ts';
import { hardwareTarget } from './encode.ts';
import { isStale, useDeviceStates } from './deviceState.ts';

export function DeviceFacts({ entityId }: { entityId: string }) {
  const devices = useDeviceStates();
  const device = devices[hardwareTarget(entityId)] ?? null;

  if (device === null) {
    return <p className="device-facts device-facts--none">{t('df.1')}</p>;
  }
  const stale = isStale(device);
  // 링크가 성하지 않거나 값이 낡았으면 **마지막 수신**이다 — 현재가 아니다.
  const held = stale || (device.link !== null && device.link !== 'ok');
  const rows: Array<[string, string]> = [];

  if (device.online !== null) rows.push([t('df.2'), device.online ? t('df.3') : t('df.4')]);
  if (device.link !== null) rows.push([t('df.5'), device.link]);
  if (device.health !== null) rows.push([t('df.6'), device.health]);
  if (device.mode !== null) rows.push([t('df.7'), device.mode]);
  // **null 은 「모른다」다** — 회색으로 두고 꺼짐으로 그리지 않는다 (연동 가이드 §4-3).
  rows.push([t('df.8'), sdkWords(device.sdkReady, device.sdkAutostart)]);
  if (device.inMission !== null) rows.push([t('df.9'), device.inMission ? t('df.10') : t('df.11')]);
  // null 은 「모른다」다 — 0% 로 그리지 않는다.
  if (device.batteryPct !== null) {
    rows.push([t('df.battery'), held ? t('df.lastSeenValue', { value: `${device.batteryPct}%` }) : `${device.batteryPct}%`]);
  }
  if (device.position !== null) {
    rows.push([t('df.position'), t('df.positionValue', { x: device.position.x.toFixed(2), y: device.position.y.toFixed(2), deg: device.position.headingDeg }) + (held ? t('df.heldSuffix') : '')]);
  }
  if (device.speedMps !== null) rows.push([t('df.speed'), `${device.speedMps} m/s`]);
  if (device.firmware !== null) rows.push([t('df.12'), device.firmware]);
  if (device.simulated) rows.push([t('df.13'), t('df.14')]);
  rows.push([t('df.lastSeen'), t('df.secondsAgo', { sec: Math.round((Date.now() - device.lastSeenMs) / 1000) }) + (device.timestamp === null ? '' : ` · ${device.timestamp}`)]);

  return <dl className="device-facts">
    {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
  </dl>;
}

/**
 * 구동 브리지의 상태를 한 줄로. **`null` 을 「꺼짐」으로 그리지 않는다** (연동 가이드 §4-3).
 *
 * 지금 돌고 있는 노드(schema 1.3)는 이 필드를 아예 안 실어 보낸다. 그래서 실제로 계속
 * 「모름」이고, 그것이 사실이다 — 「내려감」이라고 적으면 거짓을 그리는 것이다.
 */
export function sdkWords(ready: boolean | null, autostart: boolean | null): string {
  const state = ready === null ? t('df.15') : ready ? t('df.16') : t('df.17');
  if (autostart === null) return state;
  return t('df.sdkWithAutostart', { state, on: t(autostart ? 'df.on' : 'df.off') });
}

/**
 * 로봇 패널의 한 칸짜리 표시. 브리지가 서 있는지를 **버튼 옆에** 둔다 — 눌러야 할지
 * 말지를 그 자리에서 알아야 한다.
 */
export function SdkState({ entityId }: { entityId: string }) {
  const devices = useDeviceStates();
  const device = devices[hardwareTarget(entityId)] ?? null;
  const ready = device?.sdkReady ?? null;
  return <em
    className={`robot-sdk-dot robot-sdk-dot--${ready === null ? 'unknown' : ready ? 'ok' : 'down'}`}
    title={t('df.sdkTitle')}
  >{sdkWords(ready, device?.sdkAutostart ?? null)}</em>;
}
