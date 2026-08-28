import type { ScenarioEvent } from '../../model/types.ts';

/** 탭①의 되감기용 기록 열. 최신값 저장소와 생명주기를 공유하지 않는다. */
export class TraceStore {
  private readonly events: ScenarioEvent[] = [];

  append(event: ScenarioEvent) {
    this.events.push(event);
  }

  snapshot() {
    return [...this.events];
  }
}
