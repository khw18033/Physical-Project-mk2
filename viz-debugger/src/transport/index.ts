// 이식: web-dashboard/src/transport/index.ts @ 605eb73 — 접속 주소 기본값만 변경
/**
 * src/transport/index.ts
 *
 * 전송 계층의 **유일한 출입구**. 상위 코드는 여기서만 import 한다.
 * (`src/transport/WsTransport.ts`를 직접 import 하는 순간 격리가 깨진다.)
 *
 * 진짜 백엔드 게이트웨이가 나오면 두 경우가 있다.
 *   - 같은 논리 구독 방식 → **화면에서 주소를 바꾼다** (`VZ-C-07` · 260904). 빌드 없음.
 *   - 토픽 문자열 방식   → 이 폴더에 TopicTransport.ts 를 추가하고 아래 팩토리만 바꾼다.
 *                          상위 코드(src/data, src/views)는 한 줄도 건드리지 않는다.
 *
 * ## 주소가 런타임으로 바뀌어도 출입구는 하나다 (260904 — `VZ-C-07`)
 *
 * `GATEWAY` 가 상수에서 **게터**가 됐다. 읽는 쪽(`GATEWAY.http` 여섯 곳)은 한 글자도 안
 * 바뀌었고, 부를 때마다 지금 값을 본다 — 그래서 **URL 을 읽는 새 자리가 생기지 않았다.**
 * 그것이 이 단계에서 `verify:one-gateway` 를 깨뜨리지 않은 방법이다.
 *
 * 주소가 바뀌면 **끊고 다시 붙는다.** 새 인스턴스를 만들지 않는다 — 만들면 그 위에 걸린
 * 구독이 통째로 날아가고, 화면은 「연결됨」인데 값이 안 오는 상태가 된다. 같은 인스턴스를
 * 닫았다 열면 `WsTransport` 가 기존 구독을 자동 복원한다(`verify:transport` 가 보는 성질).
 */

import { connectionAddress, subscribeConnections } from '../shared/connections.ts';
import { getLang, subscribeLang } from '../shared/language.ts';
import { WsTransport } from './WsTransport.ts';
import type { Transport } from './Transport.ts';

export type { Transport, Unsubscribe } from './Transport.ts';
export type {
  ActionSpec,
  ActuatorState,
  AiFailure,
  Channel,
  CommandAck,
  CommandRequest,
  CommandResult,
  ControlLock,
  ConnectionState,
  ConnectionStatus,
  Envelope,
  Quality,
  RoleInfo,
  RiskState,
  RoleScope,
  ScopeSpec,
  Selector,
  StateLayers,
  WireAggregation,
  WireMetricsQuery,
} from './types.ts';

/**
 * 접속 주소. **읽을 때마다 지금 값**이다 — 환경변수는 이제 기본값이고, 화면(`VZ-C-07`)이
 * 덮어쓴 값이 있으면 그것이 이긴다. 원천은 `shared/connections.ts` 하나다.
 *
 * 게터인 이유: 여섯 곳이 `GATEWAY.http` 로 읽고 있었는데, 그 자리를 함수 호출로 바꾸면
 * 「URL 을 아는 곳」이 늘어난 것처럼 보이고 실제로도 갈라지기 쉽다. 모양을 그대로 두고
 * 값만 살아 있게 한다.
 */
export const GATEWAY = {
  get ws(): string { return connectionAddress('gateway', 'ws'); },
  get http(): string { return connectionAddress('gateway', 'http'); },
};

/**
 * 붙을 때 **어느 언어로 말해 달라고** 함께 말한다 (260919 · 5단계).
 *
 * 게이트웨이는 완성된 문장을 보낸다 — 승인 팝업의 검증 문장, 명령 거절 사유, 대상 이름.
 * 그 글자는 **우리 사전에 없다.** 만든 쪽이 그 언어로 말해야 한다.
 *
 * 주소에 얹는 이유: 봉투는 붙어 있는 모두에게 나가므로 **접속마다** 언어를 알아야 한다.
 * 3단계에서 STT 에 `language` 를 실어 보낸 것과 같은 자리다.
 */
function withLang(url: string, lang: string): string {
  if (url === '') return url;
  const joiner = url.includes('?') ? '&' : '?';
  return `${url}${joiner}lang=${encodeURIComponent(lang)}`;
}

let singleton: WsTransport | null = null;

export function getTransport(): Transport {
  if (singleton === null) {
    // 주소를 **붙을 때마다** 다시 읽는다. 생성 시점에 굳히면 바꿔도 옛 주소로 붙는다.
    singleton = new WsTransport(() => ({ url: withLang(GATEWAY.ws, getLang()), httpBase: GATEWAY.http }));
    singleton.connect();
    let applied = `${GATEWAY.ws}|${GATEWAY.http}|${getLang()}`;
    const rebind = () => {
      const next = `${GATEWAY.ws}|${GATEWAY.http}|${getLang()}`;
      // STT 나 자리표시 대상만 바뀐 경우까지 끊지 않는다 — 멀쩡한 연결을 흔들 이유가 없다.
      if (next === applied || singleton === null) return;
      applied = next;
      // **끊고 다시 붙는다.** 새 인스턴스가 아니므로 구독은 그대로 살아 복원된다.
      singleton.close();
      singleton.connect();
    };
    subscribeConnections(rebind);
    /**
     * **언어를 바꾸면 다시 붙는다.**
     *
     * 게이트웨이가 하는 말은 접속 언어로 그려져 나온다. 붙은 채로 언어만 바꾸면 그 접속은
     * 옛 언어로 계속 말한다. 다시 붙으면 구독이 복원되면서 **허브가 갖고 있던 봉투를 새
     * 언어로 다시 보내 주므로**, 화면이 한 번에 따라온다.
     *
     * 이미 받아 **화면이 들고 있는 글자**(승인된 계획의 검증 문장 등)는 안 바뀐다 —
     * 그건 받은 기록이고, 다시 받을 일이 없으면 그대로다.
     */
    subscribeLang(rebind);
  }
  return singleton;
}
