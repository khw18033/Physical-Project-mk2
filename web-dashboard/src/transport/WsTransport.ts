/**
 * src/transport/WsTransport.ts
 *
 * Transport의 WebSocket 구현체. **여기가 전송 방식을 아는 유일한 파일이다.**
 *
 * 하는 일 넷:
 *  1. 계약 축 {entity, node, channel} 구독을 그대로 서버에 넘긴다(토픽 문자열로 번역하지 않는다).
 *  2. 끊기면 지수 백오프로 재접속하고 **기존 구독을 자동 복원**한다.
 *  3. 복원되면 서버가 현재값을 다시 밀어 주므로(VZ-I-02) 화면에 공백이 남지 않는다.
 *  4. scope(VZ-I-11)를 구독 요청에 실어 보내고, 봉투에 실려 돌아온 값을 그대로 상위로 넘긴다.
 */

import { backoffDelayMs } from './backoff.ts';
import type { Transport, Unsubscribe } from './Transport.ts';
import type {
  ConnectionState,
  ConnectionStatus,
  Envelope,
  RoleInfo,
  ScopeSpec,
  Selector,
} from './types.ts';

export type WsTransportConfig = {
  /** 게이트웨이 WS 주소. **진짜 백엔드가 나오면 여기만 바꾼다.** */
  url: string;
  /** 레지스트리 HTTP base. */
  httpBase: string;
};

type Sub = {
  id: string;
  selector: Selector;
  scope: ScopeSpec;
  handler: (e: Envelope) => void;
};

export class WsTransport implements Transport {
  private readonly config: WsTransportConfig;
  private ws: WebSocket | null = null;
  private readonly subs = new Map<string, Sub>();
  private readonly statusHandlers = new Set<(s: ConnectionStatus) => void>();
  private roleWaiters: Array<(r: RoleInfo) => void> = [];

  private subSeq = 0;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private manualClose = false;

  private status: ConnectionStatus = {
    state: 'closed',
    attempt: 0,
    nextRetryInMs: null,
    serverTime: null,
    staleThresholdMs: null,
    lastError: null,
  };

  constructor(config: WsTransportConfig) {
    this.config = config;
  }

  // ── 연결 ───────────────────────────────────────────────────────────────────

  connect(): void {
    this.manualClose = false;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.setStatus({ state: this.attempt > 0 ? 'reconnecting' : 'connecting', nextRetryInMs: null });

    const ws = new WebSocket(this.config.url);
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.setStatus({ state: 'open', attempt: 0, nextRetryInMs: null, lastError: null });
      // **구독 자동 복원.** 호출자는 아무것도 하지 않는다.
      // 복원 즉시 서버가 현재값을 1회 푸시하므로(VZ-I-02) 화면 공백이 생기지 않는다.
      for (const sub of this.subs.values()) this.sendSubscribe(sub);
    };

    ws.onmessage = (ev) => this.onMessage(ev);

    ws.onerror = () => {
      this.setStatus({ lastError: '게이트웨이 연결 오류' });
    };

    ws.onclose = () => {
      this.ws = null;
      if (this.manualClose) {
        this.setStatus({ state: 'closed', nextRetryInMs: null });
        return;
      }
      this.scheduleReconnect();
    };
  }

  close(): void {
    this.manualClose = true;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.setStatus({ state: 'closed', attempt: 0, nextRetryInMs: null });
  }

  private scheduleReconnect(): void {
    this.attempt += 1;
    const delay = backoffDelayMs(this.attempt);
    this.setStatus({ state: 'reconnecting', attempt: this.attempt, nextRetryInMs: delay });
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  // ── 구독 ───────────────────────────────────────────────────────────────────

  subscribe(selector: Selector, handler: (e: Envelope) => void, scope: ScopeSpec = 'all'): Unsubscribe {
    this.subSeq += 1;
    const id = 'sub-' + this.subSeq;
    const sub: Sub = { id, selector, scope, handler };
    this.subs.set(id, sub);

    if (this.ws?.readyState === WebSocket.OPEN) this.sendSubscribe(sub);

    return () => {
      this.subs.delete(id);
      this.send({ type: 'unsubscribe', id });
    };
  }

  private sendSubscribe(sub: Sub): void {
    this.send({
      type: 'subscribe',
      id: sub.id,
      // 토픽 문자열로 번역하지 않는다. 계약 축을 그대로 보낸다.
      selector: sub.selector,
      // VZ-I-11 — 현 단계 'all' 고정이지만 요청에 실제로 실려 나간다.
      scope: sub.scope,
    });
  }

  private send(msg: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  // ── 수신 ───────────────────────────────────────────────────────────────────

  private onMessage(ev: MessageEvent): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(String(ev.data)) as Record<string, unknown>;
    } catch {
      return;
    }

    switch (msg.type) {
      case 'hello':
        this.setStatus({
          serverTime: msg.server_time as string,
          // 표시용으로만 받는다. stale 판정은 서버가 이미 끝냈다.
          staleThresholdMs: msg.stale_threshold_ms as number,
        });
        return;

      case 'data': {
        const sub = this.subs.get(msg.sub as string);
        if (!sub) return;
        sub.handler(msg.envelope as Envelope);
        return;
      }

      case 'role': {
        const info: RoleInfo = { role: msg.role as string, scope: msg.scope as string[] };
        const waiters = this.roleWaiters;
        this.roleWaiters = [];
        for (const w of waiters) w(info);
        return;
      }

      case 'error':
        this.setStatus({ lastError: String(msg.message) });
        return;

      default:
        return;
    }
  }

  // ── 상태 ───────────────────────────────────────────────────────────────────

  private setStatus(patch: Partial<ConnectionStatus> & { state?: ConnectionState }): void {
    this.status = { ...this.status, ...patch };
    for (const h of this.statusHandlers) h(this.status);
  }

  onStatus(handler: (s: ConnectionStatus) => void): Unsubscribe {
    this.statusHandlers.add(handler);
    handler(this.status);
    return () => this.statusHandlers.delete(handler);
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  fetchRole(): Promise<RoleInfo> {
    return new Promise((resolve) => {
      this.roleWaiters.push(resolve);
      this.send({ type: 'role' });
    });
  }

  /** 목 게이트웨이 전용. 실제 게이트웨이 구현에는 이 메서드가 없다. */
  playScenario(name: string): void {
    this.send({ type: 'scenario', name });
  }
}
