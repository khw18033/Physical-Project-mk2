/**
 * src/media/h264Socket.ts (261124 신설 — RoboMaster EP 카메라 중계)
 *
 * **장비가 WebSocket 으로 직접 내는 H.264 한 건을 뜯는다.** 순수 함수만 있다 — 검사가 그대로 부른다.
 *
 * HW `pi/robot/ep_camera.py`(bfec5dd)의 와이어 포맷이다. `bench/go1_cam_view.py` 와 같게 뒀다고 적혀 있다.
 *
 * ```
 * 텍스트  {"t": "hello", "codec": "avc1.4d6029", "cam": "ep-001"}     붙은 뒤 첫 키프레임 직전에 한 번
 * 바이너리 [1바이트 키프레임 0/1][8바이트 big-endian float64 시각(ms)][Annex-B 액세스 유닛]
 * ```
 *
 * - 중계는 **첫 키프레임까지 아무것도 안 보낸다**(GOP 중간 방지). 그래도 재접속 직후 방어는 디코더가 한 번 더 한다.
 * - 코덱 문자열은 SPS 에서 매번 읽어 `hello` 에 싣는다 — 여기서도 상수로 박지 않는다.
 * - 제어 메시지는 없다. **붙는 것이 켜기이고 끊는 것이 끄기다.** 보는 사람이 없으면 20초 뒤 상류를 끈다.
 *
 * `/media`(방식 B, `parse.ts`)와 다른 포맷이라 따로 뜯는다. 뜯은 것은 **같은 디코더**(`decode.ts`)에 넣으려고
 * `MediaFrame` 모양으로 바꾼다 — 디코더를 둘로 만들면 「최신 프레임만 · 큐 넘치면 버림」 규칙이 한쪽만 고쳐진다.
 *
 * ## 던지지 않는다
 *
 * `parse.ts` 와 같은 규칙이다. 틀린 것은 사유를 값으로 돌려준다.
 */

import type { MediaFrame } from './parse.ts';

/** 헤더 = 키프레임 1 + 시각 8. */
export const H264_SOCKET_HEADER_BYTES = 9;

export type H264SocketHello = { codec: string; cam: string | null };

export type H264SocketFrame = { keyframe: boolean; timestampMs: number; data: Uint8Array };

export type H264SocketError = 'too_short' | 'bad_flag' | 'empty_payload' | 'not_hello';

/** 텍스트 한 건. `hello` 가 아니면 사유. 모르는 텍스트는 오류로 세고 넘어간다 — 연결을 끊지 않는다. */
export function parseH264Hello(text: string): { ok: true; hello: H264SocketHello } | { ok: false; reason: H264SocketError } {
  let body: unknown;
  try { body = JSON.parse(text); } catch { return { ok: false, reason: 'not_hello' }; }
  if (typeof body !== 'object' || body === null) return { ok: false, reason: 'not_hello' };
  const record = body as Record<string, unknown>;
  if (record.t !== 'hello' || typeof record.codec !== 'string' || record.codec === '') return { ok: false, reason: 'not_hello' };
  return { ok: true, hello: { codec: record.codec, cam: typeof record.cam === 'string' && record.cam !== '' ? record.cam : null } };
}

/** 바이너리 한 건. */
export function parseH264Frame(buffer: ArrayBuffer): { ok: true; frame: H264SocketFrame } | { ok: false; reason: H264SocketError } {
  if (buffer.byteLength < H264_SOCKET_HEADER_BYTES) return { ok: false, reason: 'too_short' };
  const view = new DataView(buffer);
  const flag = view.getUint8(0);
  if (flag !== 0 && flag !== 1) return { ok: false, reason: 'bad_flag' };
  if (buffer.byteLength === H264_SOCKET_HEADER_BYTES) return { ok: false, reason: 'empty_payload' };
  return {
    ok: true,
    frame: {
      keyframe: flag === 1,
      timestampMs: view.getFloat64(1, false),
      data: new Uint8Array(buffer, H264_SOCKET_HEADER_BYTES),
    },
  };
}

/**
 * 디코더가 먹는 모양으로. 순번은 **받는 쪽이 센다** — 와이어에 순번이 없고, 디코더는 순번을 청크 시각으로만 쓴다.
 * 크기는 0 이다 — H.264 는 디코더가 낸 `VideoFrame` 의 크기를 쓴다(`decode.ts`).
 */
export function toMediaFrame(frame: H264SocketFrame, hello: H264SocketHello, sequenceId: number): MediaFrame {
  return {
    header: {
      frameRef: {
        cameraId: hello.cam ?? 'h264-socket',
        timestamp: Number.isFinite(frame.timestampMs) ? new Date(frame.timestampMs).toISOString() : '',
        sequenceId,
        sessionId: null,
      },
      encoding: 'h264',
      keyframe: frame.keyframe,
      legacy: false,
      width: 0,
      height: 0,
      codec: hello.codec,
      correlationId: null,
    },
    payload: frame.data,
  };
}

/** 장비가 직접 내는 H.264 소켓 주소인가. `<img>` 로는 못 받는 주소라 받는 부품이 여기서 갈린다. */
export function isH264SocketUrl(url: string): boolean {
  return /^wss?:\/\//i.test(url);
}
