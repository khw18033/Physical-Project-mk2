import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { displayMission } from '../data/scenario.ts';
import type { Hardware } from '../model/types.ts';
import { connectionAddress, subscribeConnections } from './connections.ts';

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

/** 이 목록이 어디서 왔는가. 화면이 목임을 감추지 않기 위해 표시한다. */
export function hardwareSourceLabel(): string {
  const { view } = displayMission();
  return view.world === 'registry'
    ? t('sr.1')
    : t('sr.missionScenario', { id: view.missionId });
}
