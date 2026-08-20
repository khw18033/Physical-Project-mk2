/**
 * src/transport/Transport.ts
 *
 * 상위 코드가 보는 **유일한 면**. 이 인터페이스에는 WebSocket·토픽·프레임이 없다.
 * 백엔드가 논리 구독 대신 토픽 문자열을 고르면 이 인터페이스의 구현만 바뀐다.
 */

import type { ConnectionStatus, Envelope, RoleInfo, ScopeSpec, Selector } from './types.ts';

export type Unsubscribe = () => void;

export interface Transport {
  /** 연결 시작. 이미 열려 있으면 무시. */
  connect(): void;
  /** 연결 종료. 자동 재연결도 멈춘다. */
  close(): void;

  /**
   * 계약 축으로 구독한다. 반환된 함수를 부르면 해제된다.
   *
   * 구현체가 반드시 지켜야 하는 것 둘:
   *  - 재연결 시 **기존 구독을 자동 복원**한다. 호출자는 다시 구독하지 않는다.
   *  - 서버가 구독 즉시 보내는 현재값(VZ-I-02)을 그대로 흘려보낸다. 걸러내지 않는다.
   */
  subscribe(selector: Selector, handler: (envelope: Envelope) => void, scope?: ScopeSpec): Unsubscribe;

  /** 연결 상태 구독. 화면 상단 배너용. */
  onStatus(handler: (status: ConnectionStatus) => void): Unsubscribe;
  getStatus(): ConnectionStatus;

  /** VZ-C-01/C-04 — 현재 역할과 그 적용 범위. */
  fetchRole(): Promise<RoleInfo>;

  /**
   * 시나리오 재생 트리거. **목 게이트웨이 전용 개발 기능**이며 실제 게이트웨이에는 없다.
   * 제어 명령 발행 경로가 아니다 — 명령은 목 서버 안에서만 왕복한다.
   */
  playScenario?(name: string): void;
}
