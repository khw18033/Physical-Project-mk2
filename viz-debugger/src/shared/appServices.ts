/**
 * src/shared/appServices.ts (260916 — 단독 빌드 정합 §2)
 *
 * **앱 수명과 같은 배경 작업의 주입구.** 셸은 「기동해 달라」고만 하고 무엇이 기동되는지 모른다.
 *
 * `canvas/registry.ts` 의 `registerViewNodes()` 와 **같은 꼴이다** — 셋째 패턴이 아니다.
 * 주입은 명시적 호출이고, 통합 진입점만 부르고, 단독 진입점은 안 부른다.
 *
 * ## 무엇이 여기 실리나
 *
 * 지금은 `tabs/` 의 둘이다 — 구역 축 구독(`startDataLayer`)과 외부 AI 실패 알림
 * (`aiFailureBridge`). 둘 다 대시보드 데이터 계층이라 단독 번들에 들어가면 **논문 측정축 D
 * 가 오염된다**(`verify:standalone` · `verify:build-parity`).
 *
 * 전에는 셸이 `useTabsDataLayer()` 로 그 둘을 직접 불렀다. 그래서 셸이 `tabs/` 를 알게 됐고
 * 셸 전체가 단독 빌드에서 빠졌다. 이 파일이 그 고리를 끊는다.
 *
 * ## 등록이 하나도 없으면 아무 일도 안 일어난다
 *
 * **그것이 단독 빌드의 정상 상태다.** 구역 축 구독이 없으니 장비 격자가 안 차는 것이 맞고,
 * 화면은 자리표시로 뜬다(`shared/renderMode.ts` 의 기본값). 조용히 비는 것이 아니라
 * 「누가 줄 데이터인지」가 적힌 채로 뜬다.
 */

import { useEffect } from 'react';

/** 기동 함수. 되돌리는 함수를 주면 언마운트 때 부른다 — 안 줘도 된다. */
type AppService = () => (() => void) | void;

/**
 * **함수 참조로 모은다.** 같은 함수를 두 번 등록해도 한 번만 남는다 — 개발 중 HMR 로 진입점
 * 모듈이 다시 돌아도 구독이 두 배가 되지 않아야 한다. 그래서 진입점은 **이름 있는 모듈 수준
 * 함수**를 넘긴다(`registerAppService(startTabsServices)`). 익명 화살표를 넘기면 매번 다른
 * 참조라 이 방어가 무력해진다.
 */
const services = new Set<AppService>();

/**
 * 배경 작업 주입. 통합 진입점이 **렌더 전에** 부른다.
 *
 * 렌더 전이어야 하는 이유는 `useAppServices()` 가 마운트 때 한 번만 훑기 때문이다.
 * 늦게 등록하면 이번 세션에는 안 돈다 — `registerViewNodes()` 가 팔레트에 대해 갖는
 * 제약과 같다.
 */
export function registerAppService(start: AppService): void {
  services.add(start);
}

/**
 * 등록된 것을 전부 기동한다. **셸이 최상위에서 한 번 부른다.**
 *
 * React 훅이 아니라 평범한 부수효과 등록이므로 셸 밖에서 부르지 마라 — 두 곳에서 부르면
 * 구독이 두 벌이 된다. 각 작업의 중복 기동 방어는 작업 자신에게 있다(`startDataLayer` 의
 * `started` 플래그).
 */
export function useAppServices(): void {
  useEffect(() => {
    const stops: (() => void)[] = [];
    for (const start of services) {
      const stop = start();
      if (typeof stop === 'function') stops.push(stop);
    }
    return () => { for (const stop of stops) stop(); };
  }, []);
}
