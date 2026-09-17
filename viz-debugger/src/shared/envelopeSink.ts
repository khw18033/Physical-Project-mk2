/**
 * src/shared/envelopeSink.ts (260916 — 단독 빌드 정합 §3)
 *
 * 임무 다리가 받은 봉투를 **또 누가 보고 싶어 하는가.**
 *
 * `canvas/registry.ts` 의 `registerViewNodes()` 와 **같은 꼴이다** — 셋째 패턴이 아니다.
 *
 * ## 왜 필요했나
 *
 * `shell/missionBridge.ts` 가 게이트웨이의 임무 축을 구독해 봉투를 받는다. 그 봉투를
 * 대시보드 저장소에도 넣어야 했고(`store.apply(envelope)` 한 줄), 그 한 줄 때문에
 * **임무 다리가 `tabs/data/` 를 import 했다.** 다리는 셸에 있으므로 셸 전체가 `tabs/` 에
 * 닿는 것으로 잡혔고, 그래서 셸이 통째로 단독 빌드에서 빠져 있었다.
 *
 * 한 줄을 끊으면 `missionBridge` 의 `tabs/` 도달이 16개에서 0개가 된다.
 *
 * ## 등록이 없으면 조용히 지나간다
 *
 * **그것이 단독 빌드의 정상 상태다.** 단독에는 대시보드 저장소가 없으니 봉투를 넣을 곳도
 * 없다. 임무 축의 계획·기록·명령 결과는 다리가 **직접** 임무 저장소에 반영하므로
 * (`data/scenario.ts`), 여기로 못 흘러가도 화면은 그대로 돈다.
 *
 * 그래서 「등록이 없으면 던진다」로 짜지 않았다. 없는 것이 사고가 아니라 한쪽 빌드의 정상이다.
 */

import type { Envelope } from '../transport/index.ts';

type EnvelopeSink = (envelope: Envelope) => void;

/** 함수 참조로 모은다 — 같은 것을 두 번 등록해도 한 번이다 (HMR 방어, `appServices.ts` 와 같다). */
const sinks = new Set<EnvelopeSink>();

/**
 * 봉투 수신처 주입. 통합 진입점이 **렌더 전에** 부른다.
 * 단독 진입점은 안 부른다 — 부르면 `tabs/data/` 가 단독 번들에 딸려 들어간다.
 */
export function registerEnvelopeSink(sink: EnvelopeSink): void {
  sinks.add(sink);
}

/**
 * 받은 봉투를 등록된 곳 전부에 흘린다.
 *
 * **한 곳이 던져도 나머지는 받아야 한다.** 여기서 터뜨리면 임무 다리의 구독 콜백이 통째로
 * 죽고, 그러면 대시보드 하나 때문에 임무 기록이 멈춘다 — 화면은 멀쩡해 보이는데 값이 안 온다.
 * 이 저장소가 가장 피하고 싶어 하는 실패 모양이다.
 */
export function fanOutEnvelope(envelope: Envelope): void {
  for (const sink of sinks) {
    try {
      sink(envelope);
    } catch (error) {
      console.error('봉투 수신처 하나가 던졌다 — 나머지는 계속 받는다', error);
    }
  }
}
