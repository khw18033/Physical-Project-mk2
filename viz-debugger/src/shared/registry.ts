import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { displayMission } from '../data/scenario.ts';
import type { Hardware } from '../model/types.ts';
import { connectionAddress, subscribeConnections } from './connections.ts';
import { connectedDevices, useConnectedDevices } from './connectedDevices.ts';

/**
 * 모든 탭이 같은 배정 원천을 보도록 하는 레지스트리 경계.
 *
 * **탭①의 원천은 현재 임무 저장소이고, 탭②~⑤의 원천은 게이트웨이가 내려주는 레지스트리다.**
 * 화면이 임무의 hardware/cast 를 직접 읽으면 그 사실이 코드에서 보이지 않으므로
 * 탭①의 접근을 이 파일 하나로 모은다.
 *
 * 7.8 「두 세계」는 대본 재생(260831)에서 **registry.json 세계로 대본을 쓰는 방향**으로
 * 해소됐다 — 대본(world: 'registry')의 cast 는 registry.json 의 ID 그대로다
 * (실재 여부는 verify:script-library 가 대조한다 — 탭①이 registry.json 을 직접 읽으면
 * 단독 빌드에 대시보드 계층이 딸려 들어간다). 옛 편(MSN-260826-01)은 HCI 전달본이라
 * 손대지 않고 구판 세계의 예외로 남는다.
 */

/**
 * 현재 구역 (`VZ-I-03` · `VZ-C-05` — 설계 전제는 구역 1개).
 *
 * 뷰 노드의 `ViewScope.zoneId` 가 이 값을 쓴다 (260903). 탭②~⑤가 각자 `'zone-503'` 을
 * 손으로 적고 있었는데, 캔버스까지 넷째로 적으면 「두 곳이 갈라진다」가 그대로 난다 —
 * 레지스트리 경계인 이 파일 하나로 모은다.
 *
 * ## 260921 — 상수에서 **연결 설정을 읽는 함수**로 바뀌었다
 *
 * 붙는 게이트웨이마다 구역 값이 다르다: 목(8790)은 `zone-503`, 백엔드 `/state` 는 `zoneA`.
 * 상수로 두면 한쪽에 붙을 때 반드시 다른 쪽이 **연결은 되고 화면만 비는** 상태가 된다.
 * 그래서 값의 원천이 `connections.ts` 의 `gateway.zone` 칸이 됐다 — 주소와 한 묶음이다.
 *
 * **모듈 최상위에서 한 번 읽어 상수에 담지 않는다**(`const ZONE_ID = currentZoneId()`).
 * 그러면 `import` 시점에 굳어 연결을 바꿔도 안 따라간다 — `GATEWAY.ws` 를 게터로 둔 것과
 * 같은 이유다(`transport/index.ts`). 화면은 `useZoneId()` 로 구독한다.
 */
export function currentZoneId(): string {
  return connectionAddress('gateway', 'zone');
}

/**
 * 구독하는 구역 값. 연결 설정이 바뀌면 **부품이 다시 그려진다.**
 *
 * `useConnections()` 를 그대로 쓰지 않는 이유는 그것이 주소 묶음 전체를 돌려주기 때문이다 —
 * STT 주소만 바뀌어도 구역을 보는 부품이 전부 다시 그려진다. 여기서 값 하나로 좁힌다.
 */
export function useZoneId(): string {
  return useSyncExternalStore(subscribeConnections, currentZoneId, currentZoneId);
}

/**
 * 옛 편의 하드웨어 목록(실측값 7행). **대본에는 없다** — registry 세계 장비의 실측값은
 * 남이 줄 데이터라 지어내지 않고, 카드 3행은 자리표시다(8/31 결정 · VZ-D-07).
 */
export function listRegisteredHardware(): readonly Hardware[] {
  return displayMission().view.hardware ?? [];
}

/** 대본 등장 장비 id 목록. 옛 편이면 hardware 목록의 id 들과 같다. */
export function listCastIds(): readonly string[] {
  return displayMission().view.cast;
}

/**
 * **하드웨어 카드에 뜨는 장비** — 지금 값이 흐르는 것만 (260922 지시).
 *
 * ## 260921 → 260922: 대본 배역을 뺐다
 *
 * 260921 에는 **대본 배역 ∪ 붙어 있는 장비**였다. 카드의 뜻이 둘이라고 보았기 때문이다 —
 * 「이번 편에 나오는 것」과 「지금 붙어 있는 것」.
 *
 * **무대에서 그 둘을 못 가린다.** 아무것도 안 붙은 상태에서 카드가 일곱 장 떠 있었다
 * (옛 편 `MSN-260826-01` 의 `go1-02`·`arm-03`·`cam-4f`…). 그 카드들의 배터리·RSSI 는
 * 자리표시 숫자이고 끌어다 배정해도 아무 일이 안 일어난다. 사람이 그것을 보고 **「이건
 * 더미 카드인가」**라고 물었다 — 물어야 알 수 있으면 화면이 말한 것이 아니다.
 *
 * 카드에 「대본 등장 장비」라고 적어 두기는 했다. 그래도 **없는 장비를 그려 둔 자리**는
 * 남고, 붙어 있는 드론 한 대가 그 일곱 장 사이에 섞인다. 자리표시를 지우는 다른 결정들과
 * 같은 규칙이다(8/31 · 260910 — 「연결 예정」 문구를 걷어낸 그 자리).
 *
 * 그래서 **카드는 하나만 뜻한다: 지금 붙어 있다.** 아무것도 안 붙었으면 한 장도 안 뜬다.
 *
 * 대본이 무엇을 쓰는지는 사라지지 않는다 — 마일스톤 칸의 `assignedTargets` 가 그대로
 * 적고, `listCastIds()` 도 그대로 있다. 없어진 것은 **카드로 그리던 것**뿐이다.
 *
 * ## 그런데 목 함대가 남았다 (260922 두 번째)
 *
 * 배역을 걷어냈는데도 카드가 아홉 장 떠 있었다 — `robot-01`·`robot-02`·`sensor-04`·
 * `edge-node-a` … **목 게이트웨이(`gateway/devices.ts`)의 가짜 함대**다. 그쪽이 1Hz 로
 * 봉투를 흘리고, 받는 자리가 그것을 「붙어 있다」로 적고 있었다.
 *
 * 값이 흐르는 것은 사실이다. 다만 **그 값은 우리가 만든 것**이고, 이 저장소의 「붙어 있다」는
 * 무대에서 「저 장비가 저기 있다」로 읽힌다. 아홉 장 사이에 드론 한 대가 섞이면 앞서
 * 걷어낸 자리표시와 똑같은 문제가 된다.
 *
 * **들어온 길로 가른다.** 카드가 되는 것은 `mqtt` — 연결 관리에서 주소를 넣고 「확인」을
 * 눌러 붙은 브로커(pi3·pi7)에서 온 것이다. 사람이 그 장비를 지목했고, 그래서 화면이
 * 「붙어 있다」라고 말할 근거가 있다.
 *
 * 게이트웨이가 흘리는 `state` 는 카드가 아니다. 저장소는 **그대로 기록한다** — 무엇이
 * 흘렀는지는 남고, 대시보드 탭이 그것을 그대로 그린다(「레지스트리에 없는 개체」).
 * 가리는 것은 이 목록 하나다.
 *
 * 렌더 모드로 가르지 않았다. 목 렌더를 읽는 자리는 `PendingSource` 하나여야 하고
 * (`verify:placeholder-default` — 「자리표시를 우회하는 길이 생긴다」), 여기서 읽으면
 * 그 규칙에 구멍이 난다. 실제로 그렇게 짰다가 검사에 걸렸다.
 *
 * > ⚠ **백엔드가 실물 `/state` 를 주기 시작하면 이 줄을 다시 봐야 한다.** 지금 그 길로
 * > 오는 것은 목 함대뿐이라 이 가름이 맞지만, 그때는 「목이냐」와 「게이트웨이냐」가
 * > 갈린다. 그 구분은 **주소로 하지 않는다** — 봉투가 스스로 밝히게 하는 편이 맞다
 * > (`deviceIdentity.ts` 가 장비 종류에 대해 한 것과 같은 규칙).
 */
export function listDeviceCardIds(): readonly string[] {
  return connectedDevices()
    .filter((device) => device.source === 'mqtt')
    .map((device) => device.entityId);
}

/** 위와 같은 목록을 **구독해서** 본다 — 장비가 붙거나 조용해지면 다시 그린다. */
export function useDeviceCardIds(): readonly string[] {
  useConnectedDevices();
  return listDeviceCardIds();
}

/**
 * 이 카드가 **대본 배역인가, 지금 붙어 있어서 뜬 것인가.**
 *
 * 260922 부터 카드는 붙어 있는 것만이라 대부분 `connected` 다. 그래도 남긴다 — 붙어 있는
 * 장비가 **마침 이번 편의 배역이기도 한** 경우가 있고(문 찾기 시연의 로봇), 화면이 그
 * 사실을 적을 수 있어야 한다. 「연결됨」과 「이번 편 등장」은 여전히 다른 말이다.
 */
export function deviceCardOrigin(entityId: string): 'cast' | 'connected' {
  return displayMission().view.cast.includes(entityId) ? 'cast' : 'connected';
}

/** 이 목록이 어디서 왔는가. 화면이 목임을 감추지 않기 위해 표시한다. */
export function hardwareSourceLabel(): string {
  const { view } = displayMission();
  return view.world === 'registry'
    ? t('sr.1')
    : t('sr.missionScenario', { id: view.missionId });
}
