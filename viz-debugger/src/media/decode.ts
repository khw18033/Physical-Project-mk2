/**
 * src/media/decode.ts (260921 신설 — `/media` 수신 경로)
 *
 * **바이트 → 그릴 수 있는 것.** 4단계의 넷째다.
 *
 *   `jpeg`   `createImageBitmap(new Blob([payload]))`
 *   `h264`   WebCodecs `VideoDecoder`
 *   그 밖    **디코드하지 않는다.** 상태로 표시한다 — 모르는 코덱을 억지로 넣으면
 *            디코더가 실패하고, 그 실패가 「영상이 안 나온다」로만 보인다
 *
 * ## 최신 프레임만 들고 있는다
 *
 * HW 가 실기에서 겪은 것이다 — **디코더 출력을 전부 그리면 밀린다.** 여기서는 그리지 않고
 * 마지막 것만 들고 있다가 화면의 rAF 가 가져간다. 앞의 것은 버린다: 30fps 영상에서
 * 한 프레임 늦게 그린 그림은 쓸모가 없고, 쌓이면 지연이 무한정 는다.
 *
 * ## 서버가 못 지켜 주는 자리가 여기다
 *
 * 링크는 빠른데 브라우저가 디코드를 못 따라가면 초과분이 브라우저·OS 버퍼에 쌓이고
 * **서버 drop-old 가 발동하지 않는다**(Phase 4 실측: 뷰어를 5초 정지시켜도 서버 드롭 0).
 * 그래서 `decodeQueueSize` 가 임계를 넘으면 **버린다** — 우리가 우리 큐를 관리한다.
 *
 * ## 첫 키프레임까지는 디코더에 안 넣는다
 *
 * 서버가 첫 전송·드롭 뒤 재개를 항상 키프레임으로 보장하지만, **재연결 직후 방어는
 * 뷰어 몫**이다(`vz-media-interface.md` §1).
 */

import type { MediaFrame } from './parse.ts';

/** 디코더가 못 따라갈 때 버리기 시작하는 지점. HW 가 실기에서 쓴 값과 같은 자리다. */
const DECODE_QUEUE_LIMIT = 6;

export type DecodeStats = {
  /** 디코드까지 마친 프레임 수. */
  decoded: number;
  /** 큐가 밀려 우리가 버린 수. **서버 드롭과 다른 축이다** — 이쪽은 뷰어 안의 일이다. */
  droppedBusy: number;
  /** 첫 키프레임을 기다리느라 넘긴 수. */
  waitingKeyframe: number;
  /** 디코더가 낸 오류 수. */
  errors: number;
  /** 디코드하지 않은 코덱 이름들 — 화면이 「무엇을 모르는지」 적을 수 있게. */
  unsupported: readonly string[];
};

export const EMPTY_DECODE_STATS: DecodeStats = {
  decoded: 0, droppedBusy: 0, waitingKeyframe: 0, errors: 0, unsupported: [],
};

/** 그릴 수 있는 한 장. `close()` 가 있는 자원이라 **쓰고 닫는다.** */
export type Painted = { bitmap: ImageBitmap | VideoFrame; width: number; height: number };

export type Decoder = {
  push(frame: MediaFrame): void;
  /** 마지막으로 디코드된 것. 가져가면 비우지 않는다 — rAF 가 같은 것을 다시 그려도 된다. */
  latest(): Painted | null;
  stats(): DecodeStats;
  /** 새 세션 — 들고 있던 것과 디코더를 버린다. */
  reset(): void;
  close(): void;
};

const isJpeg = (encoding: string): boolean => encoding === 'jpeg' || encoding === 'mjpeg';
const isH264 = (encoding: string): boolean => encoding === 'h264' || encoding === 'avc1';

/**
 * 디코더 하나. **화면 한 칸당 하나**다.
 *
 * `onPaint` 는 없다 — 여기서 콜백을 부르면 그 콜백이 곧 React 상태 갱신이 되고,
 * 매 프레임 상태를 바꾸면 병합의 의미가 사라진다(`VideoOverlayView` 머리말과 같은 규칙).
 * 화면이 rAF 로 **가져간다.**
 */
export function createDecoder(): Decoder {
  let painted: Painted | null = null;
  let decoder: VideoDecoder | null = null;
  let configuredCodec: string | null = null;
  let sawKeyframe = false;
  let stats: DecodeStats = { ...EMPTY_DECODE_STATS };
  const unsupported = new Set<string>();

  const setPainted = (next: Painted): void => {
    // 들고 있던 것을 **닫는다.** `ImageBitmap`·`VideoFrame` 은 GC 로 안 풀리는 자원이라
    // 안 닫으면 30fps 로 새고, 탭이 몇 분 만에 무거워진다.
    painted?.bitmap.close();
    painted = next;
    stats = { ...stats, decoded: stats.decoded + 1 };
  };

  const dropDecoder = (): void => {
    try { decoder?.close(); } catch { /* 이미 닫혔다 — 닫는 것이 목적이라 사유가 필요 없다 */ }
    decoder = null;
    configuredCodec = null;
    sawKeyframe = false;
  };

  const pushJpeg = (frame: MediaFrame): void => {
    // `createImageBitmap` 은 비동기다. 늦게 온 것이 더 새 프레임을 덮지 않게 순번을 본다.
    const mySeq = frame.header.frameRef.sequenceId;
    const bytes = frame.payload.slice();
    void createImageBitmap(new Blob([bytes as BlobPart])).then((bitmap) => {
      setPainted({ bitmap, width: frame.header.width, height: frame.header.height });
      void mySeq;
    }).catch(() => { stats = { ...stats, errors: stats.errors + 1 }; });
  };

  const pushH264 = (frame: MediaFrame): void => {
    if (typeof VideoDecoder === 'undefined') {
      unsupported.add(frame.header.encoding);
      stats = { ...stats, unsupported: [...unsupported] };
      return;
    }
    // **첫 키프레임까지 디코더에 안 넣는다.** 재연결 직후 방어는 뷰어 몫이다.
    if (!sawKeyframe && !frame.header.keyframe) {
      stats = { ...stats, waitingKeyframe: stats.waitingKeyframe + 1 };
      return;
    }
    // **코덱 문자열은 헤더가 정한다.** 상수로 박으면 실물에서 디코더 설정이 실패한다.
    const codec = frame.header.codec ?? 'avc1.42E01E';
    if (decoder === null || configuredCodec !== codec) {
      dropDecoder();
      decoder = new VideoDecoder({
        output: (video) => setPainted({ bitmap: video, width: video.displayWidth, height: video.displayHeight }),
        error: () => { stats = { ...stats, errors: stats.errors + 1 }; dropDecoder(); },
      });
      // `hardwareAcceleration: 'prefer-software'` — HW 실기에서 이 해상도는 소프트웨어
      // 디코드가 밀리초대이고 **하드웨어 경로가 오히려 늦다**. `description` 은 없다(Annex-B).
      decoder.configure({ codec, hardwareAcceleration: 'prefer-software' });
      configuredCodec = codec;
      if (!frame.header.keyframe) { stats = { ...stats, waitingKeyframe: stats.waitingKeyframe + 1 }; return; }
    }
    // **우리가 우리 큐를 관리한다.** 서버는 여기까지 못 지켜 준다.
    if (decoder.decodeQueueSize > DECODE_QUEUE_LIMIT) {
      stats = { ...stats, droppedBusy: stats.droppedBusy + 1 };
      return;
    }
    sawKeyframe = sawKeyframe || frame.header.keyframe;
    try {
      decoder.decode(new EncodedVideoChunk({
        type: frame.header.keyframe ? 'key' : 'delta',
        timestamp: frame.header.frameRef.sequenceId * 1000,
        data: frame.payload.slice() as BufferSource,
      }));
    } catch {
      stats = { ...stats, errors: stats.errors + 1 };
      dropDecoder();
    }
  };

  return {
    push(frame: MediaFrame): void {
      const { encoding } = frame.header;
      if (isJpeg(encoding)) { pushJpeg(frame); return; }
      if (isH264(encoding)) { pushH264(frame); return; }
      // **모르는 형식은 디코드하지 않는다.** 화면이 그 사실을 적는다.
      unsupported.add(encoding);
      stats = { ...stats, unsupported: [...unsupported] };
    },
    latest: () => painted,
    stats: () => stats,
    reset(): void {
      dropDecoder();
      painted?.bitmap.close();
      painted = null;
    },
    close(): void {
      dropDecoder();
      painted?.bitmap.close();
      painted = null;
    },
  };
}
