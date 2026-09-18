/**
 * src/views/DeviceStrip.tsx (260904 — 추가 개선 2)
 *
 * **배정 장비 실측 상태 일곱 칸.** `ActionModal` 안에 인라인으로 있던 것을 그대로 꺼냈다 —
 * 하드웨어 카드 더블클릭(`VZ-D-07` 의 미구현분)이 같은 것을 보여야 하기 때문이다.
 * 두 곳에 다른 상태 화면을 만들면 **어휘가 갈린다**: 한쪽은 「관절 온도」, 다른 쪽은 「온도」가
 * 되고, 한쪽에만 하트비트가 있는 식으로 벌어진다.
 *
 * 일곱 칸의 값은 여전히 **남이 줄 데이터**다 — 이 부품은 감싸지 않는다. 부르는 쪽이
 * `<PendingSource id="robot-status-strip">` 로 감싸고, 기본 모드에서는 이 부품이 아예 그려지지
 * 않는다(자리표시 카드가 대신 뜬다). 그것이 8/31 결정이다.
 *
 * ## 260918 — 2단계 범위 목록에 없었는데 시연 경로에 떠 있었다
 *
 * `ActionModal`(범위 안)이 이 부품을 그린다. 그런데 이 파일은 목록에 없어서 2단계가
 * 안 옮겼고, **영문 화면의 액션 아이템에 칸 이름 다섯이 한국어로 남아 있었다.**
 *
 * `verify:i18n-scope-leak` 도 못 봤다 — 그 검사가 **문자열 리터럴만** 세고 JSX 텍스트를
 * 안 봤기 때문이다(「배터리」는 리터럴이 아니다). 사람이 화면을 보고 알려 줘서 찾았고,
 * 검사의 그 사각도 같이 막았다.
 */

import { t } from '../i18n/dict.ts';
import { useLang } from '../shared/language.ts';
import type { Hardware } from '../model/types.ts';

export function DeviceStrip({ device }: { device: Hardware }) {
  // `t()` 는 값을 줄 뿐 리렌더를 안 일으킨다 — 빼면 언어를 바꿔도 이 일곱 칸만 옛 언어로 남는다.
  useLang();
  return <div className="device-strip">
    <b>{device.id}<small>{device.kind} · {device.connection}</small></b>
    <span>{t('strip.battery')}<strong>{device.battery}%</strong></span>
    <span>{t('strip.network')}<strong>{device.rssi} dBm · {device.latency} ms</strong></span>
    <span>{t('strip.ip')}<strong>{device.ip}</strong></span>
    <span>{t('strip.firmware')}<strong>{device.firmware}</strong></span>
    <span>{t('strip.jointTemp')}<strong>{device.temperature} °C</strong></span>
    <span>{t('strip.heartbeat')}<strong>{device.heartbeat}</strong></span>
  </div>;
}
