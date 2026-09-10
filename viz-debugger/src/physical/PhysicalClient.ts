/**
 * src/physical/PhysicalClient.ts (260910 신설 — 하드웨어 연동 §2)
 *
 * **가시화 코드가 로봇을 보는 유일한 면이다.** 이 파일 밖에서 MQTT 클라이언트를 만들거나
 * 토픽 문자열을 적지 않는다 (`verify:physical-port`). `SttClient` · `LlmClient` 와 같은
 * 패턴이고 같은 이유다 — 브로커가 프로세스든 워커든, 나중에 중앙 서버 경유로 바뀌든
 * 갈아끼우는 곳이 여기 하나가 되게 하기 위한 제약이다.
 *
 * **브로커가 꺼져 있어도 화면은 뜬다.** 로봇 명령만 꺼지고 대본 재생·되감기·캔버스는
 * 그대로 돈다 (`verify:no-physical`). 그래서 이 모듈은 실패를 **상태로 돌려주고**
 * 무엇을 비활성화할지는 화면이 정한다.
 *
 * ## 채널 (하드웨어가 실제로 쏴 보고 확인한 값)
 *
 *   브로커   ws://pi7.local:9001 (WebSocket) · MQTT 5 · 인증 없음
 *   발행     terminal/go1-001/downlink  QoS 1
 *   수신     terminal/go1-001/uplink    QoS 1
 *   페이로드 protobuf 바이너리 — JSON 문자열이 아니다
 *
 * 응답 세 종(Acceptance · CommandStatus · CommandResult)이 **모두 uplink 하나로** 온다.
 * 종류는 봉투의 `oneof body` 가 구분한다.
 */

import { connectionAddress, registerConnectionDefault } from '../shared/connections.ts';
import { encodeCommand, hardwareTarget, nextCommandId, type CommandInput, type PhysicalAction } from './encode.ts';
import { physical } from './protocol.js';
import { decodeUplink, type UplinkMessage } from './uplink.ts';

const meta = import.meta as unknown as { env?: { VITE_PHYSICAL_WS?: string } };

/**
 * 기본 주소. **환경변수는 기본값일 뿐이고** 화면의 「연결 관리」가 덮어쓸 수 있다
 * (260904 · `VZ-C-07`). 다만 주소를 아는 면은 여기 하나여야 하므로 환경변수는 이 파일에서만
 * 읽고 연결 저장소에는 기본값만 심는다 — `SttClient` 와 같은 규칙이다.
 */
registerConnectionDefault('physical', 'ws', meta.env?.VITE_PHYSICAL_WS ?? 'ws://pi7.local:9001');

/** 지금 쓰는 브로커 주소. 상수가 아니라 **읽을 때마다 지금 값**이다. */
export function physicalWsUrl(): string {
  return connectionAddress('physical', 'ws');
}

/** 토픽. 장비 id 가 토픽에 들어가므로 **이 파일 밖에 적지 않는다.** */
function topics(target: string) {
  return {
    downlink: `terminal/${target}/downlink`,
    uplink: `terminal/${target}/uplink`,
  };
}

export type PhysicalStatus =
  | { state: 'idle' }
  | { state: 'connecting' }
  | { state: 'open' }
  | { state: 'closed'; reason: string };

export type PhysicalListener = (message: UplinkMessage) => void;
export type StatusListener = (status: PhysicalStatus) => void;

/**
 * 브로커에 붙어 명령을 쏘고 uplink 를 흘려보낸다.
 *
 * **mqtt.js 를 동적으로 불러온다** — 붙지 않는 화면(단독 빌드·브로커 없는 개발)에서는
 * 그 덩치가 번들에 실릴 이유가 없다. `verify:standalone` 이 번들을 보는 저장소라
 * 정적 import 로 두면 로봇을 안 쓰는 빌드까지 무거워진다.
 */
export class PhysicalClient {
  private client: unknown = null;
  private status: PhysicalStatus = { state: 'idle' };
  private readonly listeners = new Set<PhysicalListener>();
  private readonly statusListeners = new Set<StatusListener>();
  /** 붙을 대상. 화면 id 를 받아 하드웨어 id 로 바꿔 둔다. */
  private readonly target: string;

  constructor(vizEntityId = 'robot-01') {
    this.target = hardwareTarget(vizEntityId);
  }

  getStatus(): PhysicalStatus {
    return this.status;
  }

  onMessage(listener: PhysicalListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private setStatus(status: PhysicalStatus): void {
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }

  /**
   * 브로커에 붙는다. **실패해도 던지지 않는다** — 화면이 죽으면 안 된다.
   * 붙었는지는 `getStatus()` 로 묻는다.
   */
  async connect(): Promise<PhysicalStatus> {
    if (this.status.state === 'open' || this.status.state === 'connecting') return this.status;
    this.setStatus({ state: 'connecting' });
    try {
      const mqtt = await import('mqtt');
      const client = mqtt.connect(physicalWsUrl(), { protocolVersion: 5, reconnectPeriod: 0 });
      this.client = client;
      const { uplink } = topics(this.target);
      client.on('connect', () => {
        client.subscribe(uplink, { qos: 1 });
        this.setStatus({ state: 'open' });
      });
      client.on('message', (_topic: string, payload: Uint8Array) => {
        const message = decodeUplink(payload);
        // 형식에 안 맞으면 버린다 — 지어 채우지 않는다.
        if (message === null) return;
        for (const listener of this.listeners) listener(message);
      });
      client.on('error', (error: Error) => this.setStatus({ state: 'closed', reason: error.message }));
      client.on('close', () => this.setStatus({ state: 'closed', reason: '연결이 닫혔습니다' }));
    } catch (error) {
      // mqtt 를 못 불러오거나 주소가 틀렸다 — 로봇 명령만 꺼지고 화면은 그대로 돈다.
      this.setStatus({ state: 'closed', reason: error instanceof Error ? error.message : String(error) });
    }
    return this.status;
  }

  disconnect(): void {
    const client = this.client as { end?: (force?: boolean) => void } | null;
    client?.end?.(true);
    this.client = null;
    this.setStatus({ state: 'idle' });
  }

  /**
   * 명령 하나. **바이트로 바꾸는 것은 `encode.ts`, 쏘는 것은 여기.**
   * 붙어 있지 않으면 쏘지 않고 그 사실을 돌려준다 — 조용히 삼키지 않는다.
   */
  send(action: PhysicalAction, parameters?: Record<string, number>): { sent: boolean; commandId: string; reason?: string } {
    const commandId = nextCommandId();
    if (this.status.state !== 'open') {
      return { sent: false, commandId, reason: '브로커에 붙어 있지 않습니다 — ' + this.status.state };
    }
    const input: CommandInput = { commandId, action, parameters, target: this.target };
    const client = this.client as { publish?: (t: string, p: Uint8Array, o: unknown) => void } | null;
    client?.publish?.(topics(this.target).downlink, encodeCommand(input), { qos: 1 });
    return { sent: true, commandId };
  }
}

/** 스키마의 종료 상태. 화면이 숫자 대신 이름으로 읽게 내보낸다. */
export const TERMINAL_STATUS = physical.TerminalStatus;
