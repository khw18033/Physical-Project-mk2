import type { ScenarioEvent } from '../../model/types.ts';

/**
 * 탭①의 되감기용 기록 열.
 *
 * ## 상태 모델이 둘인 이유 — 합치지 않는다
 *
 * 통합 앱에는 상태 저장소가 둘 있고, 맡는 것이 다르다.
 *
 * | | 무엇을 담는가 | 누가 쓰는가 | 지우는가 |
 * |---|---|---|---|
 * | `TraceStore` (여기) | **일어난 일의 열.** seq 순서로 덧붙이기만 한다 | 탭① | 안 지운다. 실패해도 남는다 |
 * | `DataStore` (`tabs/data/store.ts`) | **채널별 최신값.** 같은 키가 오면 덮어쓴다 | 탭②~⑥ | 덮어쓴다 |
 *
 * 되감기는 "그 시점의 값"이 아니라 **"그때까지 일어난 일을 접은 결과"**라서 최신값
 * 저장소로는 만들 수 없다. 반대로 구역 현황판은 지난 일이 아니라 **지금 값**만 필요하고,
 * 열을 매번 접으면 20 Hz 수신에서 렌더 예산을 넘긴다.
 *
 * 하나로 합치면 둘 중 하나가 반드시 손해를 본다. **transport 는 하나를 공유하고
 * 저장소만 둘**이라는 것이 지금의 경계다 (기술스택 §10 "두 상태 모델의 공존 방식").
 *
 * 통합 전 이 자리에 있던 `LatestValueStore` 스텁은 지웠다 — 탭이 없을 때 추측으로 만든
 * 자리였고, 실물인 `DataStore`(264줄)가 들어왔으므로 두 벌로 둘 이유가 없다.
 */
export class TraceStore {
  private readonly events: ScenarioEvent[] = [];

  append(event: ScenarioEvent) {
    this.events.push(event);
  }

  snapshot() {
    return [...this.events];
  }
}
