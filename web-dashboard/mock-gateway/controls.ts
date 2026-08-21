/**
 * mock-gateway/controls.ts
 *
 * 시나리오가 건드리는 **런타임 주입 상태**. server.ts와 scenarios.ts가 둘 다 읽으므로
 * 어느 한쪽에 두면 순환 참조가 된다. 그래서 이 둘만 따로 모아 둔다.
 *
 * 여기 있는 값은 전부 **계약이 아니라 검증 수단**이다. 실제 백엔드에는 없다.
 */

import { DEFAULT_ROLE_KEY } from './config.ts';

/**
 * ACK 타이밍 주입.
 *
 * 실제 백엔드는 ACK를 결과보다 먼저 보내겠지만, **순서를 신뢰하는 코드는 실제 백엔드에서
 * 깨진다.** 목 서버가 일부러 순서를 깨뜨리거나 ACK를 아예 보내지 않을 수 있어야
 * 데이터 레이어의 보류·흡수(ack-late)와 만료 정리(ack-drop)를 검증할 수 있다.
 */
export const ackControl = {
  /** 다음 1건의 ACK를 아예 보내지 않는다 → 화면이 client_request_id만으로 만료 정리해야 한다. */
  dropNext: false,
  /** 다음 1건의 ACK를 이만큼 늦게 보낸다 → 진행 이벤트가 매핑보다 먼저 도착한다. */
  delayNextMs: 0,
};

/**
 * 현재 역할 키 (VZ-C-04 / BE-Q-04).
 * 역할은 세션 중 거의 바뀌지 않으므로 실제로는 로그인·토큰 갱신 시점에만 조회된다.
 * 시연에서 범위 제한을 보려면 그 시점을 인위적으로 만들어야 해서 시나리오로 바꾼다.
 */
export const roleState = { key: DEFAULT_ROLE_KEY };
