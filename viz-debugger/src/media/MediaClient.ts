/**
 * src/media/MediaClient.ts (260921 신설 — `/media` 수신 경로)
 *
 * **영상 소켓을 아는 유일한 면.** 주소·경로·토큰이 이 파일 밖으로 나가지 않는다 —
 * `src/capability/CapabilityClient.ts` 와 같은 규칙이고 같은 이유다(`verify:media-port`).
 *
 * ## 왜 전송 계층(`WsTransport`)을 안 쓰나
 *
 * 인계문서가 「VZ 는 **두 번째 소켓**을 연다」고 적었고, 그 소켓은 게이트웨이와 **말이 다르다**:
 *
 *   게이트웨이   구독/봉투 규약 — `{type:'subscribe', selector}` · `{channel, topic, key, message}`
 *   `/media`     **제어 메시지가 없다.** 붙는 것이 켜기, 끊는 것이 끄기다
 *
 * `WsTransport` 에 바이너리 갈래를 내면 구독 규약을 안 쓰는 연결이 그 클래스 안에 얹힌다.
 * 대신 이 파일이 **자기 소켓을 직접** 연다. (전송 계층의 `catch { return }` 에 카운터를
 * 붙이는 것은 별개 문제이고 거기서 따로 한다 — 그쪽은 게이트웨이가 형식을 어겼을 때의
 * 신호다.)
 *
 * ## 받는 순서 넷 (`vz-media-interface.md` §5)
 *
 *   ① `binaryType = 'arraybuffer'`   기본 `blob` 이면 `.arrayBuffer()` 가 비동기다
 *   ② 문자열/바이너리 갈래           지금 전송 계층은 전부 JSON 으로 간주한다
 *   ③ `[4B][JSON][페이로드]` 파서    `parse.ts` — 순수 함수라 검사가 그대로 부른다
 *   ④ 디코드                          JPEG 는 `createImageBitmap`, H.264 는 WebCodecs
 *
 * **버리는 자리마다 센다.** 이 경로의 가장 나쁜 실패는 「연결됨인데 영상만 안 옴」이고,
 * 그것은 아무 신호가 없을 때만 진단이 어렵다.
 *
 * ## 끊김 처리
 *
 * `4401`(토큰 없음·불일치)은 **재시도하지 않는다** — 재시도해도 같은 코드가 온다.
 * `4404`(경로 밖)·`4400`(카메라 키 없음)도 같다. 그 셋은 주소를 고쳐야 풀린다.
 */

import { t } from '../i18n/dict.ts';
import { connectionAddress, registerConnectionDefault } from '../shared/connections.ts';
import { MEDIA_PRESETS } from './presets.ts';
import { parseMediaFrame, type MediaFrame, type MediaParseError } from './parse.ts';

const meta = import.meta as unknown as { env?: { VITE_MEDIA_WS?: string } };

const SERVER = MEDIA_PRESETS.find((preset) => preset.id === 'server')?.url ?? '';
registerConnectionDefault('media', 'ws', meta.env?.VITE_MEDIA_WS ?? SERVER);

/** 다시 붙지 않는 끊김 — 주소를 고쳐야 풀린다. */
export const FATAL_CLOSE_CODES: readonly number[] = [4400, 4401, 4404];

/** 지금 쓰는 소켓 주소. 끝의 `/` 는 뗀다. **이 함수 밖에서 주소 문자열을 만들지 않는다.** */
export function mediaBaseUrl(): string {
  return connectionAddress('media', 'ws').trim().replace(/\/+$/, '');
}

export function mediaSourceId(): string {
  return connectionAddress('media', 'source').trim();
}

/**
 * 붙을 주소 한 줄. **토큰이 주소에 실린다**(`vz-media-interface.md` §7 — URL 쿼리 토큰).
 *
 * 토큰을 화면에서 받는 이유가 그것이다 — 코드·설정 파일·시나리오 JSON 에 넣어 커밋하지
 * 않는다. 값은 연결 관리에만 있고 `localStorage` 에 머문다.
 */
export function mediaUrl(): { ok: true; url: string } | { ok: false; reason: string } {
  const base = mediaBaseUrl();
  const source = mediaSourceId();
  const token = connectionAddress('media', 'token').trim();
  if (base === '') return { ok: false, reason: t('media.noAddress') };
  if (source === '') return { ok: false, reason: t('media.noSource') };
  const query = new URLSearchParams({ source_id: source });
  // 토큰이 비어 있으면 안 싣는다 — 서버가 4401 로 끊고, 그 사유가 화면에 그대로 뜬다.
  if (token !== '') query.set('token', token);
  return { ok: true, url: `${base}/media?${query.toString()}` };
}

/** 소켓이 화면에 알리는 것. 값이 아니라 **사건**이다. */
export type MediaEvents = {
  onOpen(): void;
  onFrame(frame: MediaFrame): void;
  /** 뜯지 못한 프레임. **센다** — 조용히 버리지 않는다. */
  onParseError(reason: MediaParseError): void;
  /** 바이너리가 아닌 메시지. `/media` 에는 원래 없다 — 오면 그 사실을 적는다. */
  onTextMessage(text: string): void;
  onClose(code: number, retrying: boolean): void;
  onError(reason: string): void;
};

export type MediaSocket = { close(): void };

/** 소켓 하나를 만드는 자리. 검사가 가짜로 갈아 끼운다. */
export type SocketFactory = (url: string) => WebSocket;

const RETRY_MS = 2000;

/**
 * 붙는다. **붙는 것이 켜기**이므로 여는 것 말고 보낼 제어 메시지가 없다.
 *
 * 돌려주는 것으로 끊는다 — 그것이 끄기다.
 */
export function openMedia(events: MediaEvents, factory?: SocketFactory): MediaSocket {
  let closedByUs = false;
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const connect = (): void => {
    const target = mediaUrl();
    if (!target.ok) { events.onError(target.reason); return; }

    let ws: WebSocket;
    try {
      ws = (factory ?? ((url: string) => new WebSocket(url)))(target.url);
    } catch (error) {
      events.onError(error instanceof Error ? error.message : String(error));
      return;
    }
    socket = ws;

    // ① **동기 계약을 지키려면 이것이 먼저다.** 기본값 `blob` 이면 `.arrayBuffer()` 가
    //    비동기라 프레임 순서가 뒤집힐 수 있다.
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => events.onOpen();

    ws.onmessage = (event: MessageEvent) => {
      // ② 문자열인지 바이너리인지 **먼저 가른다.** 지금 전송 계층은 전부 JSON 으로 간주해
      //    바이너리를 조용히 버린다 — 그 실패를 여기서 반복하지 않는다.
      if (typeof event.data === 'string') { events.onTextMessage(event.data); return; }
      if (!(event.data instanceof ArrayBuffer)) { events.onParseError('too_short'); return; }

      // ③ 뜯는다. 던지지 않고 사유를 돌려주므로 버리는 자리가 안 생긴다.
      const parsed = parseMediaFrame(event.data);
      if (!parsed.ok) { events.onParseError(parsed.reason); return; }
      events.onFrame(parsed.frame);
    };

    ws.onerror = () => events.onError(t('media.socketError'));

    ws.onclose = (event: CloseEvent) => {
      socket = null;
      if (closedByUs) return;
      // **주소를 고쳐야 풀리는 끊김은 다시 안 붙는다.** 재시도해도 같은 코드가 온다.
      const retrying = !FATAL_CLOSE_CODES.includes(event.code);
      events.onClose(event.code, retrying);
      if (retrying) timer = setTimeout(connect, RETRY_MS);
    };
  };

  connect();

  return {
    close(): void {
      closedByUs = true;
      if (timer !== null) { clearTimeout(timer); timer = null; }
      socket?.close();
      socket = null;
    },
  };
}
