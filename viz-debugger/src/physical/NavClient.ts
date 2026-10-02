/**
 * src/physical/NavClient.ts (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * **pi1 브로커에 붙어 중계를 받기만 하는 클라이언트.** `PhysicalClient`(pi7 · 문 찾기 시연)와
 * **다른 연결**이다. 시연 연결을 갈아 끼우거나 주소를 바꾸지 않는다 — 둘은 기계도 브로커도 다르다.
 *
 * ## 보내지 않는다
 *
 * 자율주행 편의 로봇은 **유니티가 몬다.** 이 클라이언트에는 발행 함수가 없고 명령 토픽도
 * 모른다. 머리줄의 ■ 정지는 pi7 로 가는 것이라 **pi1 의 로봇을 세우지 않는다** — 세우는 것은
 * 유니티(PATH_CANCEL · estop)나 조종기다.
 *
 * ## 채널 (계약 — `문서/보관/작업프롬프트_pi1_가시화중계_260915.md` §3)
 *
 *   브로커   pi1 의 mosquitto · WebSocket 9001 · 인증 없음 (pi7 과 같은 설정)
 *   수신     +/robot/+/nav_state (QoS 0) · +/robot/+/nav_event (QoS 1)
 *   페이로드 JSON — 뜯는 것은 `navFeed.ts`
 */

import { t } from '../i18n/dict.ts';
import type { NavProbe } from '../shared/connectionCheck.ts';
import { connectionAddress, registerConnectionDefault } from '../shared/connections.ts';
import { navFeedState, receiveNavMessage } from './navFeed.ts';
import { resolveConnect, type PhysicalStatus } from './PhysicalClient.ts';

const meta = import.meta as unknown as { env?: { VITE_AUTODRIVE_WS?: string } };

/**
 * **기본 주소 — pi1 이 보고한 Tailscale 이름** (260915 `pi1_조사결과.md` · 100.83.132.16).
 *
 * 처음엔 비워 뒀다 — 짐작한 주소가 들어 있으면 「왜 안 붙지」로 시간을 쓴다. 이름은 이제 확인됐다.
 * ⚠ 보고 시점에 pi1 에는 **브로커(mosquitto)가 아직 없다.** 설치 전에는 이 주소로 확인을 누르면 브로커 줄이 빨갛다.
 */
registerConnectionDefault('autodrive', 'ws', meta.env?.VITE_AUTODRIVE_WS ?? 'ws://pi1.tailcb6bfb.ts.net:9001/mqtt');

export function navWsUrl(): string {
  return connectionAddress('autodrive', 'ws');
}

const NAV_TOPICS: ReadonlyArray<{ topic: string; qos: number }> = [
  { topic: '+/robot/+/nav_state', qos: 0 },
  { topic: '+/robot/+/nav_event', qos: 1 },
];

type MqttLike = {
  on(event: string, handler: (...args: never[]) => void): void;
  subscribe(topic: string, opts: { qos: number }, done?: () => void): void;
  end(force?: boolean): void;
};

export class NavClient {
  private client: MqttLike | null = null;
  private connectedUrl = '';
  private status: PhysicalStatus = { state: 'idle' };
  private readonly statusListeners = new Set<(status: PhysicalStatus) => void>();

  getStatus(): PhysicalStatus {
    return this.status;
  }

  onStatus(listener: (status: PhysicalStatus) => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private setStatus(status: PhysicalStatus): void {
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }

  /** 붙는다. **던지지 않는다** — 실패는 상태로 돌려준다. 구독이 서야 「붙었다」고 말한다. */
  async connect(timeoutMs = 6000): Promise<PhysicalStatus> {
    const url = navWsUrl().trim();
    if (this.status.state === 'connecting') return this.status;
    if (this.status.state === 'open') {
      if (url === this.connectedUrl) return this.status;
      // 연결 관리에서 주소를 바꿨다 — 옛 주소에 붙은 채로 「붙었다」고 말하지 않는다.
      this.disconnect();
    }
    if (url === '') {
      this.setStatus({ state: 'closed', reason: t('nc.1') });
      return this.status;
    }
    this.setStatus({ state: 'connecting' });
    try {
      const mod = await import('mqtt');
      const client = resolveConnect(mod)(url, { protocolVersion: 5, reconnectPeriod: 0 }) as MqttLike;
      this.client = client;
      this.connectedUrl = url;
      let settle: ((status: PhysicalStatus) => void) | null = null;
      const settled = new Promise<PhysicalStatus>((resolve) => { settle = resolve; });
      const finish = (status: PhysicalStatus) => {
        // 버린 옛 연결의 뒤늦은 close 가 새 연결의 상태를 덮으면 안 된다.
        if (this.client !== client) return;
        this.setStatus(status);
        if (settle !== null) { settle(status); settle = null; }
      };
      const timer = setTimeout(() => finish({ state: 'closed', reason: t('nc.noAnswer', { ms: timeoutMs }) }), timeoutMs);
      client.on('connect', (() => {
        let pending = NAV_TOPICS.length;
        for (const { topic, qos } of NAV_TOPICS) {
          client.subscribe(topic, { qos }, () => {
            pending -= 1;
            if (pending === 0) { clearTimeout(timer); finish({ state: 'open' }); }
          });
        }
      }) as () => void);
      client.on('message', ((topic: string, payload: Uint8Array) => {
        if (this.client !== client) return;
        let body: unknown;
        try { body = JSON.parse(new TextDecoder().decode(payload)); } catch { return; }
        if (typeof body !== 'object' || body === null || Array.isArray(body)) return;
        receiveNavMessage(topic, body as Record<string, unknown>);
      }) as never);
      client.on('error', ((error: Error) => {
        clearTimeout(timer);
        finish({ state: 'closed', reason: error.message });
      }) as never);
      client.on('close', (() => {
        clearTimeout(timer);
        finish({ state: 'closed', reason: t('nc.2') });
      }) as () => void);
      return await settled;
    } catch (error) {
      this.setStatus({ state: 'closed', reason: error instanceof Error ? error.message : String(error) });
      return this.status;
    }
  }

  disconnect(): void {
    const client = this.client;
    this.client = null;
    this.connectedUrl = '';
    client?.end(true);
    this.setStatus({ state: 'idle' });
  }
}

let singleton: NavClient | null = null;

/** 화면이 쓰는 클라이언트 하나. 만들기만 하고 붙지는 않는다 — 붙는 것은 연결 관리의 「확인」이다. */
export function navClient(): NavClient {
  if (singleton === null) singleton = new NavClient();
  return singleton;
}

/** 연결 관리가 쓰는 얇은 면. 주소·토픽은 여기서도 안 샌다. */
export function navProbe(): NavProbe {
  const client = navClient();
  return {
    connect: () => client.connect(),
    getStatus: () => client.getStatus(),
    latest: () => navFeedState().telemetry,
  };
}
