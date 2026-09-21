// 이식: web-dashboard/src/data/index.ts @ 700ed91 — 무수정 (transport 경로만 조정)
/**
 * src/data/index.ts
 *
 * 데이터 레이어의 출입구. 화면은 여기서만 import 한다.
 *
 * 화면은 전송 방식을 모른다 — 아래 startDataLayer()가 transport 폴더의
 * `getTransport()` 하나만 붙잡고, 그 위로는 Envelope과 EntityRecord만 흐른다.
 */

import { subscribeConnections } from '../../shared/connections.ts';
import { currentZoneId } from '../../shared/registry.ts';
import { noteConnectedEntity } from '../../shared/connectedDevices.ts';
import { getTransport } from '../../transport/index.ts';
import { DataStore } from './store.ts';
import { fetchRegistry } from './registry.ts';
import { observeEnvelope, startSelfObservability } from './selfObservability.ts';

export { DataStore } from './store.ts';
export type { ChannelSlot, EntityRecord } from './store.ts';
export * from './statusModel.ts';
export * from './actuatorModel.ts';
export * from '../../shared/commandCenter.ts';
export * from './audit.ts';
export * from './plans.ts';
export * from './vision.ts';
export * from '../../shared/auditFieldMap.ts';
export * from './aggregation.ts';
export * from './metrics.ts';
export * from './permissions.ts';
export * from './constants.ts';
export * from './registry.ts';
export { ZoneSummaryFeed } from './summary.ts';
export type { ZoneSummary } from './summary.ts';

export const store = new DataStore();

let started = false;

/**
 * 데이터 레이어 기동.
 *
 * 순서에 의미가 있다 — **레지스트리를 먼저 심는다.** 존재해야 할 목록이 없으면
 * 미배포 대상은 값을 발행하지 않으므로 화면에 영원히 나타나지 않는다(VZ-I-03).
 *
 * 구독은 계약 축 하나로 끝난다. 전송 계층이 재연결과 구독 복원을 알아서 하므로
 * 여기에는 재시도 코드가 없다.
 *
 * ## 구역이 바뀌면 **다시 건다** (260921)
 *
 * 구역은 인자가 아니라 연결 설정(`gateway.zone`)에서 읽는다 — 붙는 게이트웨이마다 값이
 * 다르기 때문이다(목 8790 은 `zone-503`, 백엔드 `/state` 는 `zoneA`).
 *
 * **재연결로는 안 따라온다.** selector 는 `transport.subscribe()` 하는 순간 전송 계층의
 * `subs` 에 값으로 박히고, 주소가 바뀌어 끊었다 붙으면 **박힌 그 selector 를 그대로 다시
 * 보낸다**(`WsTransport.onopen`). 그래서 여기서는 소켓이 아니라 **구독**을 끊고 다시 건다 —
 * 대상만 한 층 위일 뿐 `transport/index.ts` 의 `rebind` 와 같은 문법이다:
 * 값이 실제로 달라졌을 때만, 끊고, 다시.
 */
export function startDataLayer(): () => void {
  if (started) return () => undefined;
  started = true;

  const transport = getTransport();
  const abort = new AbortController();

  void fetchRegistry(abort.signal).then(({ registry, error }) => {
    store.setRegistry(registry, error);
  });

  // {entity: '*', node: <zone>, channel: '*'} — 계약 축 구독.
  // node 축에 zone 식별자를 주면 그 zone의 모든 node에 매칭된다.
  const subscribeZone = (zoneId: string) => transport.subscribe(
    { entity: '*', node: zoneId, channel: '*' },
    (envelope) => {
      observeEnvelope(envelope);
      store.apply(envelope);
      /**
       * **값이 오면 그 장비는 붙어 있는 것이다** (260921). 하드웨어 카드가 임무와
       * 무관하게 이 목록을 그린다 — 대본에 안 적힌 장비(드론)도 뜬다.
       *
       * 그리는 쪽이 이 저장소를 직접 읽게 하면 단독 빌드에 대시보드 계층이 딸려
       * 들어간다(`verify:standalone`). 그래서 **받는 쪽이 밀어 넣는다.**
       */
      noteConnectedEntity(envelope.entity, 'state');
    },
    // VZ-I-11 — 현 단계 'all' 고정. 대상이 늘면 여기를 좁힌다.
    'all',
  );

  let applied = currentZoneId();
  let unsubscribe = subscribeZone(applied);

  // 주소만 바뀐 경우까지 구독을 흔들지 않는다 — 멀쩡한 구독을 다시 걸 이유가 없다
  // (`transport/index.ts` 의 `applied` 비교와 같은 자리).
  const stopConnections = subscribeConnections(() => {
    const next = currentZoneId();
    if (next === applied) return;
    applied = next;
    unsubscribe();
    unsubscribe = subscribeZone(applied);
  });

  const stopObservability = startSelfObservability();

  return () => {
    abort.abort();
    stopConnections();
    unsubscribe();
    stopObservability();
    started = false;
  };
}

/** 개발용 시나리오 트리거. 실제 게이트웨이에는 없는 경로다. */
export function playScenario(name: string): void {
  getTransport().playScenario?.(name);
}
