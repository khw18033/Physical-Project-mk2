/**
 * src/media/parse.ts (260921 신설 — `/media` 수신 경로)
 *
 * **방식 B 프레임 한 건을 뜯는다.** 순수 함수만 있다 — 검사가 그대로 부른다.
 *
 * ```
 * [4바이트 big-endian: 헤더 길이][JSON 헤더(UTF-8)][페이로드 바이트]
 * ```
 *
 * ## 던지지 않는다
 *
 * 형식이 틀린 것은 **결과**이지 예외가 아니다. 던지면 부르는 쪽이 `try` 로 감싸고, 그러면
 * 지금 전송 계층이 그러듯 **조용히 버리는** 자리가 또 생긴다. 사유를 값으로 돌려준다.
 *
 * ## 헤더를 다시 판정하지 않는다
 *
 * `encoding` 값 어휘를 여기서 거르지 않는다 — 서버도 안 본다(값을 검증하지 않고 페이로드를
 * 열지도 않는다). 모르는 값은 그대로 들고 가고, **디코드하지 않고 상태로 표시**하는 것은
 * 화면의 몫이다. 여기서 화이트리스트로 막으면 상대가 코덱을 하나 늘릴 때마다 조용히 빈다.
 *
 * ## `frame_ref` 는 객체다
 *
 * 정수 하나가 아니다(`frame-reference.schema.json`). 버퍼 키는 `(source_id, sequence_id)`
 * 쌍이고, 재접속하면 `sequence_id` 가 0부터 다시 시작한다 — 그 리셋은 순번 역전으로만
 * 감지할 수 있다(헤더에 세션 식별자가 없다).
 */

/** 프레임 참조 — 엣지가 부여하고 서버는 바이트 그대로 전파한다. */
export type MediaFrameRef = {
  sourceId: string;
  /** **엣지가 프레임 경계를 확정한 시각.** 촬영 시각이 아니고 보정되지 않았다. */
  captureTimestamp: string;
  sequenceId: number;
};

export type MediaHeader = {
  frameRef: MediaFrameRef;
  /** 페이로드 코덱 **선언**. 값 어휘를 우리가 거르지 않는다. */
  encoding: string;
  /** 이 프레임만으로 디코드를 시작할 수 있는가(IDR). JPEG 는 항상 true. */
  keyframe: boolean;
  width: number;
  height: number;
  /** RFC 6381 — WebCodecs `VideoDecoderConfig.codec`. **상수로 박지 않는다**(실물이 정한다). */
  codec: string | null;
  correlationId: string | null;
};

export type MediaFrame = { header: MediaHeader; payload: Uint8Array };

/** 왜 못 뜯었는가. 화면이 세고 표시한다 — 조용히 버리는 자리를 만들지 않는다. */
export type MediaParseError =
  | 'too_short'
  | 'bad_header_length'
  | 'header_not_json'
  | 'header_shape';

export type MediaParseResult =
  | { ok: true; frame: MediaFrame }
  | { ok: false; reason: MediaParseError };

const num = (value: unknown): number | null =>
  (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null =>
  (typeof value === 'string' && value !== '' ? value : null);

function frameRef(value: unknown): MediaFrameRef | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const sourceId = str(raw.source_id);
  const captureTimestamp = str(raw.capture_timestamp);
  const sequenceId = num(raw.sequence_id);
  if (sourceId === null || captureTimestamp === null || sequenceId === null) return null;
  return { sourceId, captureTimestamp, sequenceId };
}

/**
 * 바이너리 메시지 한 건 → 헤더와 페이로드.
 *
 * 길이 칸이 **남은 바이트보다 크면** 거기서 멈춘다. 안 막으면 `subarray` 가 조용히 짧은
 * 배열을 돌려주고, 디코더가 「깨진 프레임」으로 실패해 원인이 두 단계 뒤에서 나타난다.
 */
export function parseMediaFrame(buffer: ArrayBuffer): MediaParseResult {
  if (buffer.byteLength < 4) return { ok: false, reason: 'too_short' };

  const view = new DataView(buffer);
  const headerLength = view.getUint32(0, false); // big-endian
  if (headerLength === 0 || 4 + headerLength > buffer.byteLength) {
    return { ok: false, reason: 'bad_header_length' };
  }

  const bytes = new Uint8Array(buffer);
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes.subarray(4, 4 + headerLength)));
  } catch {
    return { ok: false, reason: 'header_not_json' };
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, reason: 'header_shape' };
  }

  const raw = parsed as Record<string, unknown>;
  const ref = frameRef(raw.frame_ref);
  const encoding = str(raw.encoding);
  const width = num(raw.width);
  const height = num(raw.height);
  // `keyframe` 은 **필수**이고 불리언이다. 없는 것을 false 로 읽으면 첫 프레임을 디코더에
  // 안 넣고 영영 기다리게 된다 — 그 화면은 「연결됨인데 영상 없음」과 구분이 안 된다.
  if (ref === null || encoding === null || typeof raw.keyframe !== 'boolean'
    || width === null || height === null) {
    return { ok: false, reason: 'header_shape' };
  }

  return {
    ok: true,
    frame: {
      header: {
        frameRef: ref,
        encoding,
        keyframe: raw.keyframe,
        width,
        height,
        codec: str(raw.codec),
        correlationId: str(raw.correlation_id),
      },
      // **복사하지 않는다.** 프레임은 30fps 로 오고 한 건이 수 KB~수백 KB 다.
      payload: bytes.subarray(4 + headerLength),
    },
  };
}

/**
 * **새 세션인가.** 엣지가 다시 붙으면 `sequence_id` 가 0부터 시작한다 — 헤더에 세션
 * 식별자가 없으므로 **순번이 줄어든 것**으로만 안다. 그때 버퍼를 비우지 않으면 지연 계산이
 * 음수·거대값이 된다.
 *
 * 소스가 바뀐 것도 새 세션으로 본다 — 다른 카메라의 순번과 견줄 이유가 없다.
 */
export function isNewSession(prev: MediaFrameRef | null, next: MediaFrameRef): boolean {
  if (prev === null) return true;
  if (prev.sourceId !== next.sourceId) return true;
  return next.sequenceId < prev.sequenceId;
}
