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
 * ## 260918 — 2단계 범위 목록에 없어서 한국어로 남아 있었다
 *
 * `ActionModal`(범위 안)이 이 부품을 가져다 쓰는데 이 파일은 목록에 없어서 2단계가
 * 안 옮겼다. `verify:i18n-scope-leak` 도 못 봤다 — 그 검사가 **문자열 리터럴만** 세고
 * JSX 텍스트를 안 봤기 때문이다(「배터리」는 리터럴이 아니다).
 *
 * ### 어디서 보이는가 — **문 찾기 시연 경로가 아니다**
 *
 * 처음에 「시연의 액션 아이템에 뜬다」고 적었는데 **틀렸다.** 확인해 보니 관문이 둘이다.
 *
 * ```
 *   ActionModal:   device && <PendingSource …><DeviceStrip/></PendingSource>
 *                  ①                          ②
 * ```
 *
 * ① `scriptToView()` 가 `hardware: null` 이라 registry 세계 대본(문 찾기 포함)에는
 *    `device` 가 아예 안 온다. ② `PendingSource` 는 목·개발 모드에서만 `children` 을
 *    그리고 평시에는 자리표시 카드를 대신 띄운다.
 *
 * 실제로 보이는 자리는 **옛 편(`MSN-260826-01`, 하드웨어 7대)의 하드웨어 카드**다 —
 * 그 길(`DeviceStatusOverlay`)은 `PendingSource` 로 안 감싸므로 평시 모드에서도 뜬다.
 * 액션 아이템 쪽은 목·개발 모드에서만 나온다.
 *
 * 옮긴 것 자체는 그대로 맞다(화면에 뜨는 글자다). 다만 **「시연 경로라서 급하다」는
 * 근거는 사실이 아니었다** — 보지 않고 적었고, 사람이 「액션 아이템에 그런 줄이 없다」고
 * 짚어 줘서 알았다.
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
