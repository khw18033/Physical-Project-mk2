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

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { hardwareTarget } from './encode.ts';
import { isStale, useDeviceStates } from './deviceState.ts';
import { isTelemetryStale, useDeviceTelemetry, type DeviceTelemetry, type TelemetryRow } from '../shared/deviceTelemetry.ts';

export function DeviceFacts({ entityId }: { entityId: string }) {
  useLang();
  const devices = useDeviceStates();
  const reports = useDeviceTelemetry();
  const device = devices[hardwareTarget(entityId)] ?? null;

  /**
   * **MQTT 가 비면 `/state` 보고를 그린다** (260922).
   *
   * 드론 상태는 백엔드 `/state` 로만 온다(`verify:drone-via-state` — 경로가 둘이면 어느
   * 쪽이 진짜인지가 생긴다). 그래서 이 칸은 지금까지 드론에 대해 「아직 상태가 오지
   * 않았습니다」라고 적었다 — **값은 오고 있는데** 이쪽 저장소에 안 들어올 뿐이었고,
   * 그 문장은 사실이 아니었다.
   *
   * 차례는 MQTT 가 먼저다. Go1 이 `/state` 로 옮겨 가는 동안 두 길이 겹치고, 그때 지금
   * 화면을 채우고 있는 쪽이 이겨야 카드가 깜빡이지 않는다.
   */
  if (device === null) {
    const report = reports[entityId] ?? null;
    if (report !== null) return <TelemetryFacts report={report} />;
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
 * **장비가 보고한 항목을 그대로 그린다** (260922 — 드론 카드 안).
 *
 * 무엇을 그릴지 **여기서 안 고른다.** 줄은 이미 만들어져서 온다(`tabs/data/stateRows.ts`) —
 * 요구사항이 「화면 코드에 기종별 항목표를 두지 않는다」이고, 여기에 `if (드론)` 이 한 줄
 * 생기면 기종이 늘 때마다 이 파일이 자란다.
 *
 * 그래서 이 부품이 아는 것은 셋뿐이다: 이름은 **키**라 풀어야 한다는 것, 값은 **장비가 보낸
 * 그대로**라 번역하지 않는다는 것, 그리고 **낡았으면 낡았다고 말해야** 한다는 것.
 */
function TelemetryFacts({ report }: { report: DeviceTelemetry }) {
  // **별개 컴포넌트는 자기 훅이 필요하다.** 위 `DeviceFacts` 의 `useLang()` 은 이 부품을
  // 다시 그리게 하지 않는다 — 빼면 언어를 바꿔도 이 판만 옛 언어로 남는다
  // (`verify:i18n-no-frozen` 이 그것을 잡았다).
  useLang();
  const stale = isTelemetryStale(report);
  return <dl className={`device-facts${stale ? ' device-facts--held' : ''}`}>
    {/* **낡았으면 맨 위에서 한 번 말한다.** 줄마다 달면 읽을 수 없고, 안 달면 멈춘 값을
        현재로 읽는다 — `DeviceFacts` 가 링크 끊김을 다루는 방식과 같다. */}
    {stale && <div><dt>{t('df.lastSeen')}</dt>
      <dd>{t('df.secondsAgo', { sec: Math.round((Date.now() - report.receivedAtMs) / 1000) })}</dd></div>}
    {report.rows.map((row, index) => <div key={`${row.labelKey ?? row.rawLabel ?? ''}-${index}`}>
      {/* 사전에 없는 이름은 **그대로** 적는다 — 번역된 척하지 않는다(`stateRows.ts`). */}
      <dt>{row.labelKey === null ? row.rawLabel : t(row.labelKey)}</dt>
      <dd>{telemetryValue(row)}</dd>
    </div>)}
    {/* 장비가 찍은 시각. **우리 시계가 아니다** — 그래서 따로 적는다. */}
    {report.timestamp !== null && <div><dt>{t('dt.reportedAt')}</dt>
      <dd>{report.timestamp}{report.reason === null ? '' : ` · ${report.reason}`}</dd></div>}
  </dl>;
}

/**
 * 줄 하나의 값. **나이는 낡았을 때만 적는다** — 계약이 표본마다 `age_s` 를 주는데
 * 매 줄에 「0.2초 전」을 달면 읽을 수 없고, 안 달면 30초 된 고도를 지금 고도로 읽는다.
 */
export function telemetryValue(row: TelemetryRow): string {
  const shown = row.valueKey === undefined ? row.value : t(row.valueKey);
  const note = row.noteKey === undefined ? '' : ` ${t(row.noteKey)}`;
  const age = row.ageS !== null && row.ageS >= STALE_SAMPLE_S
    ? ` ${t('dt.ageSuffix', { sec: row.ageS.toFixed(1) })}`
    : '';
  return `${shown}${note}${age}`;
}

/**
 * 이 나이를 넘은 표본은 **나이를 같이 적는다**(초).
 *
 * 계약의 `state` 가 1Hz 이므로 성한 표본은 1초 안쪽이다. 2초로 두면 한 건 놓친 것은
 * 조용히 넘어가고, 실제로 멈춘 값은 드러난다.
 */
const STALE_SAMPLE_S = 2;

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
  useLang();
  const devices = useDeviceStates();
  const device = devices[hardwareTarget(entityId)] ?? null;
  const ready = device?.sdkReady ?? null;
  return <em
    className={`robot-sdk-dot robot-sdk-dot--${ready === null ? 'unknown' : ready ? 'ok' : 'down'}`}
    title={t('df.sdkTitle')}
  >{sdkWords(ready, device?.sdkAutostart ?? null)}</em>;
}
