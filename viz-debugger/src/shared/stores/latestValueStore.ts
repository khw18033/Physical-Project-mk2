import type { Envelope } from '../../transport/index.ts';

/** 탭②~⑥ 이식 때 사용할 채널별 최신값 저장소. 기록열과 합치지 않는다. */
export class LatestValueStore {
  private readonly values = new Map<string, Envelope>();

  accept(envelope: Envelope) {
    this.values.set(`${envelope.node}/${envelope.entity}/${envelope.channel}`, envelope);
  }

  snapshot() {
    return [...this.values.values()];
  }
}
