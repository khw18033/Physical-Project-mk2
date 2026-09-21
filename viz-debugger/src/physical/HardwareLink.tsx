/**
 * src/physical/HardwareLink.tsx (260910 신설 · 같은 날 장비 상태 구독으로 채움)
 *
 * **하드웨어 카드가 아는 만큼만 말한다.**
 *
 * 8/31 결정(`VZ-D-07`)은 registry 장비의 실측값을 지어내지 않는다는 것이었다. 그건 값을 줄
 * 채널이 없었기 때문이고, 이제 있다 — `zoneA/<type>/<id>/{status,state,heartbeat}`.
 * **지어내지 않는 것은 그대로**이고, 온 값만 적는다. 안 온 필드는 여전히 자리표시다.
 *
 * ## 세 층을 뭉치지 않는다
 *
 *   브로커  우리가 붙었는가              — 주소·포트·망
 *   장비    파이가 그 장비를 보고 있는가 — `status.status`(끊기면 LWT 가 offline)
 *   로봇    로봇 자신이 붙어 있는가      — **`status.link`** (로봇 ↔ 파이 내부 링크)
 *
 * `ping` 은 단말까지만 증명한다고 적어 둔 자리의 답이 `link` 다.
 *
 * ## 낡은 값은 낡았다고 말한다
 *
 * 상태는 5초 주기다. 그 세 배가 지나도록 아무것도 안 오면 **마지막 값을 현재처럼 보이면
 * 안 된다** — 캐시된 봉투를 현재로 그리지 않는 것과 같은 규칙이다(`CACHE_POLICY`).
 */

import { useLang } from '../shared/language.ts';
import { t } from '../i18n/dict.ts';
import { hardwareTarget } from './encode.ts';
import { isStale, useDeviceStates, type DeviceState } from './deviceState.ts';
import { useRobotSession } from './robotSession.ts';
import { connectedDevice, useConnectedDevices } from '../shared/connectedDevices.ts';

export function HardwareLink({ entityId }: { entityId: string }) {
  useLang();
  const devices = useDeviceStates();
  const session = useRobotSession();
  // `/state` 로 오는 장비도 이 줄이 말해야 한다 — 구독해야 붙거나 조용해질 때 다시 그린다.
  useConnectedDevices();
  // 화면 id(`robot-01`) → 하드웨어 id(`go1-001`). 표는 경계 안에 있다.
  const device: DeviceState | null = devices[hardwareTarget(entityId)] ?? null;

  /**
   * MQTT 장비 상태가 없다. 두 경우가 섞여 있어 가른다 (260921).
   *
   * **값이 `/state` 로 오는 장비**(드론·앞으로의 Go1)는 이 카드가 보는 MQTT 저장소에
   * 애초에 안 들어온다. 그런데 「아직 아무것도 안 왔습니다」로 그리면 **붙어 있는 장비를
   * 조용한 장비로 적는 거짓말**이 된다 — 카드가 뜬 이유가 값이 흐르기 때문인데.
   *
   * 자세한 항목은 상세 보기(현황판의 그 개체)가 그린다. 여기서는 살아 있다는 것과
   * 언제 마지막으로 왔는지만 적는다 — 카드 한 줄에 들어갈 만큼이다.
   */
  const viaState = connectedDevice(entityId);
  if (device === null && viaState !== null) {
    const ago = Math.round((Date.now() - viaState.lastSeenMs) / 1000);
    return <span className="hw-link">
      <em className="hw-dot hw-dot--ok">{t('hl.connected')}</em>
      <em className="hw-dot hw-dot--plain">{t('hl.secondsAgo', { sec: ago })}</em>
    </span>;
  }
  // 아직 아무것도 안 왔다 — 브로커에 안 붙었거나 그 장비가 조용하다.
  if (device === null) {
    return <span className="hw-link">
      <em className="hw-dot hw-dot--unknown">
        {session.connection.state === 'open' ? t('hl.1') : t('hl.2')}
      </em>
    </span>;
  }

  const stale = isStale(device);
  // 링크가 성하지 않으면 값이 멈춘 채로 계속 온다 — 그때의 값은 현재가 아니다.
  const held = stale || (device.link !== null && device.link !== 'ok');
  return <span className="hw-link">
    {/* 파이가 보는 생사. 끊기면 LWT 가 offline 을 넣는다. */}
    <em className={`hw-dot hw-dot--${stale ? 'unknown' : mark(device.online)}`}>
      {device.online === true ? t('hl.3') : device.online === false ? t('hl.4') : t('hl.5')}
    </em>
    {/* **로봇 자신.** ping 이 증명하지 못하던 자리다. */}
    {device.link !== null && <em
      className={`hw-dot hw-dot--${stale ? 'unknown' : mark(device.link === 'ok')}`}
      title={t('hl.linkTitle')}
    >{t('hl.link', { link: device.link })}</em>}
    {device.health !== null && device.health !== 'ok' && <em className="hw-dot hw-dot--bad">{device.health}</em>}
    {/* 링크가 끊겨도 마지막 배터리가 계속 온다(연동 가이드 §3-3) — 멈춘 값을 살아 있는
        값으로 보이면 안 된다. `null` 은 「모른다」이지 0% 가 아니다. */}
    {device.batteryPct !== null && <em className={`hw-dot hw-dot--${held ? 'unknown' : battery(device.batteryPct)}`}>
      {t('hl.battery', { pct: device.batteryPct })}{held ? t('hl.6') : ''}
    </em>}
    {device.mode !== null && <em className="hw-dot hw-dot--plain">{device.mode}</em>}
    {device.simulated && <em className="hw-dot hw-dot--plain" title={t('hl.mockTitle')}>{t('hl.7')}</em>}
    {/* **낡았으면 낡았다고 말한다.** 마지막 값을 현재처럼 보이면 안 된다. */}
    {stale && <em className="hw-dot hw-dot--unknown">
      {t('hl.silentFor', { sec: Math.round((Date.now() - device.lastSeenMs) / 1000) })}
    </em>}
  </span>;
}

function mark(ok: boolean | null): string {
  return ok === true ? 'ok' : ok === false ? 'bad' : 'unknown';
}

/** 배터리는 숫자가 뜻을 갖는다 — 20% 아래는 빨갛게, 40% 아래는 노랗게. */
function battery(pct: number): string {
  if (pct < 20) return 'bad';
  if (pct < 40) return 'warn';
  return 'ok';
}
