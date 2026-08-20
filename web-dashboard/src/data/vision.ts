/**
 * src/data/vision.ts
 *
 * 프레임 버퍼와 **탐지 정합** (VZ-I-06 · VZ-I-07 · VZ-I-09).
 *
 * 이 파일이 이번 작업의 핵심 주장을 코드로 만든다 —
 * *"각 탐지에 되돌아온 프레임 참조값으로 해당 프레임에 정합시켜야 박스가 대상 위에 놓인다."*
 *
 * 정합 on/off를 한 함수 안에서 갈라 두는 이유: 두 경로가 멀리 떨어져 있으면
 * "무엇이 달라서 어긋나는가"가 코드에서 안 보인다. 여기서는 딱 한 줄 차이다 —
 * **어느 프레임의 도형과 비교하느냐.**
 *
 * 영상은 렌더 예산의 예외다. 상태 병합(100ms)과 별개로 프레임 루프가 돌지만,
 * 그 루프는 화면 컴포넌트가 소유하고 이 파일은 **버퍼와 계산만** 한다.
 */

import { getTransport } from '../transport/index.ts';

export type VisionObject = {
  track_id: string;
  label: string;
  confidence: number;
  shape: 'person' | 'robot';
  cx: number;
  cy: number;
  w: number;
  h: number;
};

export type VideoFrame = {
  frame_seq: number;
  captured_at: string;
  fps: number;
  display: { width: number; height: number };
  /** 도형 좌표의 기준 해상도. 탐지의 bbox_space.reference와 같은 값이어야 한다. */
  reference: { width: number; height: number };
  objects: VisionObject[];
};

export type BboxSpace = {
  format: 'normalized' | 'absolute';
  origin: 'top-left';
  reference: { width: number; height: number };
};

export type Detection = {
  track_id: string;
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
  trail: Array<[number, number]>;
};

export type DetectionResult = {
  frame_ref: number;
  emitted_at: string;
  inference_delay_ms: number;
  bbox_space: BboxSpace;
  detections: Detection[];
};

/**
 * 신뢰도 임계 — 이보다 낮으면 화면에서 **다르게 그린다** (VZ-I-09).
 * 확실한 것과 애매한 것이 똑같이 보이면 안 된다.
 * ※ 미결: 임계값은 AI와 합의해야 한다. 여기 0.6은 시연용 잠정값이다.
 */
export const CONFIDENCE_THRESHOLD = 0.6;

/**
 * 프레임 버퍼 길이.
 * 정합을 하려면 **지나간 프레임을 들고 있어야** 한다 — 추론 결과가 도착할 때
 * 그 프레임은 이미 화면에서 지나갔기 때문이다. 추론 지연 0.5초 × 15fps ≈ 8프레임이므로
 * 여유를 두고 잡는다. 이 버퍼가 곧 "프레임 참조를 쓸 수 있는 최대 지연"이다.
 */
export const FRAME_BUFFER_SIZE = 48;

/** 표시 좌표계로 환산된 박스. */
export type ResolvedBox = {
  trackId: string;
  label: string;
  confidence: number;
  /** 표시 해상도 기준 픽셀. */
  x: number;
  y: number;
  w: number;
  h: number;
  trail: Array<[number, number]>;
  /** 신뢰도가 임계 미만인가. */
  uncertain: boolean;
  /**
   * 이 박스가 **대상에서 얼마나 뒤처졌는가** (표시 픽셀).
   * 정합 on이면 0에 가깝고, off면 추론 지연만큼 벌어진다.
   */
  lagPx: number;
};

export type AlignmentReport = {
  /** 지금 그리는 프레임 번호. */
  displayFrame: number;
  /** 탐지 결과가 가리키는 프레임 번호. */
  detectionFrame: number;
  /** 두 프레임의 차이. 추론 지연 ÷ 프레임 간격. */
  frameLag: number;
  /** 대상별 뒤처짐의 최댓값(표시 픽셀). 화면에 숫자로 띄운다. */
  maxLagPx: number;
  /** 평균 뒤처짐(표시 픽셀). */
  avgLagPx: number;
  inferenceDelayMs: number;
  bboxFormat: BboxSpace['format'];
  /** 추론 해상도 → 표시 해상도 환산 배율. */
  scale: { x: number; y: number };
  boxes: ResolvedBox[];
};

/**
 * 프레임 버퍼.
 * 지나간 프레임을 들고 있어야 `frame_ref`가 가리키는 프레임을 되찾을 수 있다.
 */
export class FrameBuffer {
  private frames: VideoFrame[] = [];
  private latestDetection: DetectionResult | null = null;

  pushFrame(frame: VideoFrame): void {
    this.frames.push(frame);
    if (this.frames.length > FRAME_BUFFER_SIZE) this.frames.shift();
  }

  pushDetection(result: DetectionResult): void {
    this.latestDetection = result;
  }

  get latestFrame(): VideoFrame | null {
    return this.frames.length === 0 ? null : this.frames[this.frames.length - 1];
  }

  get detection(): DetectionResult | null {
    return this.latestDetection;
  }

  frameAt(seq: number): VideoFrame | null {
    return this.frames.find((f) => f.frame_seq === seq) ?? null;
  }

  get bufferedCount(): number {
    return this.frames.length;
  }

  clear(): void {
    this.frames = [];
    this.latestDetection = null;
  }
}

/**
 * **정합 계산.**
 *
 * `aligned = true`  — `frame_ref`가 가리키는 프레임의 도형과 비교한다. 박스가 대상 위에 온다.
 * `aligned = false` — 도착 순서대로 **현재 프레임**의 도형과 비교한다.
 *                     박스는 몇 프레임 전 위치에 그려지므로 대상 뒤에 남는다.
 *
 * 두 경우 모두 **박스 좌표 자체는 같다.** 달라지는 것은 "무엇과 비교하는가"뿐이고,
 * 그 차이가 곧 화면에서 보이는 어긋남이다. 뒤처진 거리는 그 비교 대상의 중심 간 거리로 잰다.
 */
export function resolveAlignment(
  buffer: FrameBuffer,
  aligned: boolean,
  displayFrame: VideoFrame | null,
): AlignmentReport | null {
  const detection = buffer.detection;
  if (detection === null || displayFrame === null) return null;

  const space = detection.bbox_space;
  const display = displayFrame.display;

  // bbox 좌표계 환산 (VZ-I-07).
  // normalized면 표시 해상도를 곱하고, absolute면 기준 해상도 대비 배율을 곱한다.
  // **이 선언이 계약에 없으면 여기서 무엇을 곱할지 정할 수 없다.**
  const scaleX = space.format === 'normalized' ? display.width : display.width / space.reference.width;
  const scaleY = space.format === 'normalized' ? display.height : display.height / space.reference.height;

  // 정합 on이면 결과가 가리키는 프레임을, off면 지금 그리는 프레임을 기준으로 삼는다.
  const referenceFrame = aligned ? (buffer.frameAt(detection.frame_ref) ?? displayFrame) : displayFrame;

  const boxes: ResolvedBox[] = detection.detections.map((d) => {
    const [bx, by, bw, bh] = d.bbox;
    const x = bx * scaleX;
    const y = by * scaleY;
    const w = bw * scaleX;
    const h = bh * scaleY;

    // 박스 중심과, 비교 기준 프레임에서의 같은 대상 중심 사이 거리.
    const boxCx = x + w / 2;
    const boxCy = y + h / 2;
    const obj = referenceFrame.objects.find((o) => o.track_id === d.track_id);
    // 도형은 프레임이 선언한 기준 해상도로, 박스는 탐지가 선언한 기준으로 환산한다.
    // 둘이 다르면 그 자체가 계약 위반이며, 여기서 어긋남으로 드러난다.
    const objScaleX = display.width / referenceFrame.reference.width;
    const objScaleY = display.height / referenceFrame.reference.height;
    const lagPx =
      obj === undefined
        ? 0
        : Math.hypot(boxCx - obj.cx * objScaleX, boxCy - obj.cy * objScaleY);

    return {
      trackId: d.track_id,
      label: d.label,
      confidence: d.confidence,
      x,
      y,
      w,
      h,
      trail: d.trail.map(([tx, ty]) => [tx * scaleX, ty * scaleY] as [number, number]),
      uncertain: d.confidence < CONFIDENCE_THRESHOLD,
      lagPx,
    };
  });

  const lags = boxes.map((b) => b.lagPx);

  return {
    displayFrame: displayFrame.frame_seq,
    detectionFrame: detection.frame_ref,
    frameLag: displayFrame.frame_seq - detection.frame_ref,
    maxLagPx: lags.length === 0 ? 0 : Math.max(...lags),
    avgLagPx: lags.length === 0 ? 0 : lags.reduce((a, b) => a + b, 0) / lags.length,
    inferenceDelayMs: detection.inference_delay_ms,
    bboxFormat: space.format,
    scale: { x: scaleX, y: scaleY },
    boxes,
  };
}

/**
 * 영상 구독 + 패널 열기를 한 번에 처리한다.
 *
 * 화면이 transport를 직접 부르지 않게 하려고 여기서 감싼다. 반환된 함수를 부르면
 * 구독 해제와 **패널 닫기**가 함께 일어나므로, 패널을 떠나면 서버가 프레임 발행을 멈춘다
 * (VZ-I-06 — 열린 패널만 받는다).
 *
 * 프레임은 store를 거치지 않고 버퍼로 직접 들어간다. 15fps × 프레임마다 store 스냅샷을
 * 갈면 100ms 병합 창의 의미가 사라지고 상태 화면까지 같이 리렌더되기 때문이다.
 */
export function subscribeVision(entity: string, buffer: FrameBuffer): () => void {
  const transport = getTransport();

  const unsubscribe = transport.subscribe(
    { entity, node: '*', channel: '*' },
    (envelope) => {
      if (envelope.channel === 'video_frame') buffer.pushFrame(envelope.payload as VideoFrame);
      else if (envelope.channel === 'detections') buffer.pushDetection(envelope.payload as DetectionResult);
    },
    'all',
  );

  transport.setVideoPanel(entity, true);

  return () => {
    transport.setVideoPanel(entity, false);
    unsubscribe();
    buffer.clear();
  };
}
